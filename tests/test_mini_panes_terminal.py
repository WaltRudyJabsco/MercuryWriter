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
            os.write(master,b'W');until(b'Option/Alt-Shift-W')
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


def test_real_terminal_sidebar_creates_scene_and_chapter_and_reopens(tmp_path):
    root=Path(__file__).resolve().parents[1]
    result=tmp_path/'project.json'
    code=dedent('''\
        import json,sys
        from pathlib import Path
        sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
        from test_mercury import server_at,manuscript
        from mercury_session import Session
        import mercury_desk
        directory=Path(sys.argv[2]);server=server_at(directory/'server')
        server._lcommit(manuscript())
        Path.home=lambda:directory
        def request(base,path,body,timeout):
            r=server._lapply(body['project_id'],body['base_revision'],body['scenes'],body['source'],body.get('additions'),body.get('renames'))
            return (409 if r.get('conflict') else 200),r
        session=Session('local',server._lbundle('book-1'),request)
        mercury_desk.run(session.scenes,session.checkpoint,session.save,add=session.add,rename=session.rename)
        session.save()
        Path(sys.argv[3]).write_text(json.dumps(server._lbundle('book-1')))
        ''')
    master,slave=pty.openpty()
    fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',36,120,0,0))
    child=subprocess.Popen([sys.executable,'-c',code,str(root),str(tmp_path),str(result)],stdin=slave,stdout=slave,stderr=slave,env=dict(os.environ,TERM='xterm-256color'))
    os.close(slave);output=bytearray()
    def read_until(needle):
        offset=len(output);deadline=time.monotonic()+5
        while needle not in output[offset:]:
            assert time.monotonic()<deadline,repr(bytes(output[-1200:]))
            if select.select([master],[],[],.1)[0]:
                chunk=os.read(master,65536)
                assert chunk,repr(bytes(output[-1200:]))
                output.extend(chunk)
    try:
        read_until(b'Arrival')
        os.write(master,b'\t');read_until(b'new scene')
        os.write(master,b's');read_until(b'Added Scene 3')
        os.write(master,b'A\tc');read_until(b'Added chapter')
        os.write(master,b'BW\x1b\trWind\r')
        read_until(b'Wind')
        os.write(master,b'RFinale\r')
        read_until(b'Finale')
        os.write(master,b'\x13\x11')
        deadline=time.monotonic()+5
        while child.poll() is None:
            assert time.monotonic()<deadline,repr(bytes(output[-1200:]))
            if select.select([master],[],[],.1)[0]:
                try:
                    chunk=os.read(master,65536)
                    if chunk:output.extend(chunk)
                except OSError as error:
                    if error.errno!=errno.EIO:raise
        assert child.returncode==0,repr(bytes(output[-1200:]))
        rows=json.loads(result.read_text())['scenes']
        assert [(row['chapter_index'],row['scene_title'],row['text']) for row in rows][-2:]==[(0,'Scene 3','A'),(1,'Wind','BW')]
        assert rows[-1]['chapter_title']=='Finale'
    finally:
        if child.poll() is None:child.kill();child.wait()
        os.close(master)
