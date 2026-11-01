"""Small, dependency-free terminal writing desk with a deliberately bounded modal set."""
import curses
import time
import unicodedata

UNDO_LIMIT = 100
CHECKPOINT_SECONDS = 2
NAV_WIDTH = 24


class Buffer:
    def __init__(self, text=""):
        self.text = text
        self.undo = []
        self.redo = []

    def replace(self, start, end, text):
        changed = self.text[:start] + text + self.text[end:]
        if changed == self.text:
            return
        self.undo.append(self.text)
        self.undo = self.undo[-UNDO_LIMIT:]
        self.redo.clear()
        self.text = changed

    def restore(self, redo=False):
        source, target = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if source:
            target.append(self.text)
            self.text = source.pop()


def wrapped(text, width):
    """Keep source offsets so wrapping never changes the manuscript."""
    rows = []; start = 0; cells = 0
    for index, char in enumerate(text):
        size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF' else 1
        if char == '\n':
            rows.append((start, index)); start = index + 1; cells = 0
        else:
            if cells + size > width:
                rows.append((start, index)); start = index; cells = 0
            cells += size
    rows.append((start, len(text)))
    return rows


def move_vertical(text, position, direction, width):
    rows = wrapped(text, width)
    row = next((index for index, (start, end) in enumerate(rows) if start <= position <= end), len(rows)-1)
    target = max(0, min(len(rows)-1, row + direction))
    return min(rows[target][1], rows[target][0] + position - rows[row][0])


def run(scenes, checkpoint, save, split=False,initial=0):
    """checkpoint writes recoverable local files; save also commits through Mercury."""
    buffers = [Buffer(scene['text']) for scene in scenes]
    if not buffers:
        raise ValueError('This manuscript has no scenes')
    panes = [dict(scene=initial, cursor=0, scroll=0, nav=initial), dict(scene=initial, cursor=0, scroll=0, nav=initial)]
    state = dict(pane=0, split=split, mode='NORMAL', tree=False, anchor=0,
                 register='', message='', command='', dirty=False, checkpoint=0)

    def values():
        return [dict(scene, text=buffer.text) for scene, buffer in zip(scenes, buffers)]

    def persist():
        checkpoint(values()); state['checkpoint'] = time.monotonic()

    def paint(window, row, col, text, width, style=0):
        safe = ''.join(char if char.isprintable() else ' ' for char in str(text))
        try: window.addnstr(row, col, safe, max(0, width), style)
        except curses.error: pass

    def interface(window):
        curses.raw(); window.keypad(True); window.timeout(500)
        while True:
            height, width = window.getmaxyx(); window.erase()
            if height < 10 or width < 48:
                paint(window, 0, 0, 'Mercury needs at least 48 columns × 10 rows', width-1)
                window.refresh()
                key = window.get_wch()
                if key in ('q', '\x11'): persist(); return
                continue
            count = 2 if state['split'] else 1
            pane_height = (height-3)//count
            nav_width = min(NAV_WIDTH, width//3)
            edit_width = width-nav_width-3
            active = panes[state['pane']]; buffer = buffers[active['scene']]
            active['cursor'] = min(active['cursor'], len(buffer.text))
            for number in range(count):
                pane = panes[number]; text = buffers[pane['scene']].text
                top = number*pane_height
                title = scenes[pane['scene']]['chapter_title']+' / '+scenes[pane['scene']]['scene_title']
                paint(window, top, 0, ('▶ ' if number == state['pane'] else '  ')+title, width-1, curses.A_REVERSE)
                body_height = pane_height-2
                nav_start = max(0, pane['nav']-body_height+1)
                for row, index in enumerate(range(nav_start, min(len(scenes), nav_start+body_height))):
                    scene = scenes[index]
                    label = f"{scene['chapter_index']+1}.{scene['scene_index']+1} {scene['scene_title']}"
                    paint(window, top+1+row, 0, label, nav_width-1,
                          curses.A_REVERSE if index == pane['nav'] and number == state['pane'] and state['tree'] else curses.A_BOLD if index == pane['scene'] else 0)
                rows = wrapped(text, edit_width)
                cursor_row = next((i for i, (a,b) in enumerate(rows) if a <= pane['cursor'] <= b), len(rows)-1)
                if cursor_row < pane['scroll']: pane['scroll'] = cursor_row
                if cursor_row >= pane['scroll']+body_height: pane['scroll'] = cursor_row-body_height+1
                for line in range(body_height):
                    index = pane['scroll']+line
                    if index >= len(rows): break
                    start, end = rows[index]
                    paint(window, top+1+line, nav_width+1, text[start:end], edit_width)
                    if number == state['pane'] and state['mode'] == 'VISUAL':
                        lo, hi = sorted((state['anchor'],pane['cursor'])); hi += 1
                        a,b = max(start,lo),min(end,hi)
                        if a < b:
                            prefix = sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text[start:a])
                            paint(window,top+1+line,nav_width+1+prefix,text[a:b],edit_width-prefix,curses.A_REVERSE)
                if number == state['pane'] and not state['tree']:
                    start = rows[cursor_row][0]
                    offset = sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text[start:pane['cursor']])
                    cursor = (top+1+cursor_row-pane['scroll'], min(width-2, nav_width+1+offset))
            paint(window,height-3,0,'Ctrl-S save  Ctrl-Q quit  Ctrl-W split  Tab navigator  Ctrl-J other pane  ? help',width-1,curses.A_DIM)
            paint(window,height-2,0,f"{state['mode']} · {'Manuscript' if state['tree'] else 'Writing'} · {len(buffer.text.split())} words · {state['message']}",width-1,curses.A_REVERSE)
            paint(window,height-1,0,(':'+state['command']) if state['mode']=='COMMAND' else '',width-1)
            try:
                curses.curs_set(0 if state['tree'] else 1)
                if not state['tree']: window.move(*cursor)
            except curses.error: pass
            window.refresh()
            if state['dirty'] and time.monotonic()-state['checkpoint'] >= CHECKPOINT_SECONDS:
                persist()
            try: key = window.get_wch()
            except curses.error: continue
            if key == '\x13':
                persist()
                try: state['message']=save(); state['dirty']=False
                except Exception as error: state['message']=str(error)
                continue
            if key == '\x11': persist(); return
            if key == '\x17':
                state['split']=not state['split']; state['pane']=0; continue
            if key == '\n' and state['mode'] != 'INSERT' and state['mode'] != 'COMMAND' and not state['tree']:
                state['pane']=1-state['pane'] if state['split'] else 0; continue
            if key == '\t': state['tree']=not state['tree']; state['mode']='NORMAL'; continue
            if key == '\x1b': state['mode']='NORMAL'; state['command']=''; continue
            if state['tree']:
                if key in ('j',curses.KEY_DOWN): active['nav']=min(len(scenes)-1,active['nav']+1)
                elif key in ('k',curses.KEY_UP): active['nav']=max(0,active['nav']-1)
                elif key in ('\n','\r',curses.KEY_ENTER):
                    active.update(scene=active['nav'],cursor=0,scroll=0);state['tree']=False
                continue
            if state['mode']=='COMMAND':
                if key in ('\n','\r'):
                    command=state['command'];state['command']='';state['mode']='NORMAL'
                    if command in ('w','wq'):
                        persist()
                        try: state['message']=save();state['dirty']=False
                        except Exception as error: state['message']=str(error);continue
                    if command in ('q','wq'): persist();return
                    elif command in ('split','sp'):state['split']=True
                    elif command in ('only','close'):state['split']=False;state['pane']=0
                    elif command not in ('w',):state['message']='Commands: :w :q :wq :split :only'
                elif key in (curses.KEY_BACKSPACE,'\x7f','\b'):state['command']=state['command'][:-1]
                elif isinstance(key,str) and key.isprintable():state['command']+=key
                continue
            pos=active['cursor']; before=buffer.text
            if key in (curses.KEY_LEFT,) or state['mode']!='INSERT' and key=='h': active['cursor']=max(0,pos-1)
            elif key in (curses.KEY_RIGHT,) or state['mode']!='INSERT' and key=='l': active['cursor']=min(len(buffer.text),pos+1)
            elif key in (curses.KEY_UP,) or state['mode']!='INSERT' and key=='k':active['cursor']=move_vertical(buffer.text,pos,-1,edit_width)
            elif key in (curses.KEY_DOWN,) or state['mode']!='INSERT' and key=='j':active['cursor']=move_vertical(buffer.text,pos,1,edit_width)
            elif state['mode']=='INSERT':
                if key in (curses.KEY_BACKSPACE,'\x7f','\b'):
                    buffer.replace(max(0,pos-1),pos,'');active['cursor']=max(0,pos-1)
                elif key == curses.KEY_DC:buffer.replace(pos,pos+1,'')
                elif key in ('\n','\r'):buffer.replace(pos,pos,'\n');active['cursor']+=1
                elif isinstance(key,str) and key.isprintable():buffer.replace(pos,pos,key);active['cursor']+=len(key)
            elif key=='i':state['mode']='INSERT'
            elif key=='a':state['mode']='INSERT';active['cursor']=min(len(buffer.text),pos+1)
            elif key=='o':
                end=buffer.text.find('\n',pos);end=len(buffer.text) if end<0 else end
                buffer.replace(end,end,'\n');active['cursor']=end+1;state['mode']='INSERT'
            elif key=='v':state['mode']='VISUAL';state['anchor']=pos
            elif key in ('d','y') and state['mode']=='VISUAL':
                lo,hi=sorted((state['anchor'],pos));hi=min(len(buffer.text),hi+1);state['register']=buffer.text[lo:hi]
                if key=='d':buffer.replace(lo,hi,'');active['cursor']=lo
                state['mode']='NORMAL'
            elif key=='x':buffer.replace(pos,pos+1,'')
            elif key=='p':buffer.replace(pos,pos,state['register']);active['cursor']+=len(state['register'])
            elif key=='u':buffer.restore()
            elif key=='\x12':buffer.restore(redo=True)
            elif key=='0':active['cursor']=buffer.text.rfind('\n',0,pos)+1
            elif key=='$':
                end=buffer.text.find('\n',pos);active['cursor']=len(buffer.text) if end<0 else end
            elif key=='G':active['cursor']=len(buffer.text)
            elif key==':':state['mode']='COMMAND';state['command']=''
            elif key=='?':state['message']='i/a/o insert · Esc normal · v select, y/d · hjkl · x p u Ctrl-R · 0 $ G · :w :q :split :only'
            if before!=buffer.text:state['dirty']=True
    try: curses.wrapper(interface)
    finally: checkpoint(values())
