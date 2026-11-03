"""Exercise modified pane keys through real curses input and terminal teardown."""
import errno, fcntl, json, os, pty, select, struct, subprocess, sys, tempfile, termios, time
from pathlib import Path
from textwrap import dedent


def test_modified_pane_keys_preserve_both_scenes_and_restore_terminal():
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        result=Path(directory)/'result.json'
        code=dedent("""\
        import json,sys
        from pathlib import Path
        sys.path.insert(0,sys.argv[1])
        import mercury_desk
        scenes=[dict(scene_id=str(i),chapter_title='Chapter '+name,scene_title='Scene '+name,chapter_index=i,scene_index=0,text='') for i,name in enumerate(('Alpha','Beta'))]
        mercury_desk.run(scenes,lambda rows:Path(sys.argv[2]).write_text(json.dumps(rows)),lambda:'Saved')
        """)
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',36,120,0,0))
        child=subprocess.Popen([sys.executable,'-c',code,str(root),str(result)],stdin=slave,stdout=slave,stderr=slave,env=dict(os.environ,TERM='xterm-256color',KITTY_WINDOW_ID='test'))
        os.close(slave)
        output=bytearray()
        def until(needle):
            start=len(output);deadline=time.monotonic()+5
            while needle not in output[start:]:
                if time.monotonic()>deadline:raise AssertionError('Missing '+repr(needle)+' in '+repr(bytes(output[-1000:])))
                if select.select([master],[],[],.1)[0]:output.extend(os.read(master,65536))
        try:
            until(b'Chapter Alpha')
            os.write(master,b'\x17');until(b'Option/Alt-Shift-W')
            os.write(master,b'\x1b[119;4u\tj\r');until(b'Beta / Scene Beta')
            os.write(master,b'iB\x1b[119;6uiA\x11')
            deadline=time.monotonic()+5
            while child.poll() is None:
                if time.monotonic()>deadline:raise AssertionError('Mini did not exit')
                if select.select([master],[],[],.1)[0]:
                    try:
                        chunk=os.read(master,65536)
                        if not chunk:break
                        output.extend(chunk)
                    except OSError as error:
                        if error.errno!=errno.EIO:raise
            child.wait(timeout=1)
            while select.select([master],[],[],.1)[0]:
                try:
                    chunk=os.read(master,65536)
                    if not chunk:break
                    output.extend(chunk)
                except OSError as error:
                    if error.errno==errno.EIO:break
                    raise
            assert child.returncode==0,bytes(output[-1000:])
            assert [row['text'] for row in json.loads(result.read_text())]==['A','B']
            assert b'\x1b]1337;SetUserVar=mercury_mini=MQ==\x07' in output
            assert b'\x1b]1337;SetUserVar=mercury_mini\x07' in output
        finally:
            if child.poll() is None:child.kill();child.wait()
            os.close(master)
