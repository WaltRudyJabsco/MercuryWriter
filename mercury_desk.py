"""Small, dependency-free terminal writing desk with a deliberately bounded modal set."""
import curses
import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import textwrap
import unicodedata
from mercury_terminal import binding_rows,hint_styles,paint_bindings,mini_bindings,mini_help,terminal_theme,screen_background,run_screen

UNDO_LIMIT = 100
CHECKPOINT_SECONDS = 2
NAV_WIDTH = 24
INPUT_TIMEOUT_MS = 500
ESCAPE_TIMEOUT_MS = 25
CLIPBOARD_TIMEOUT_SECONDS = 2


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


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def row_at(rows, position):
    # At a soft wrap, the offset belongs to the following display row.
    return next((i for i in range(len(rows)-1,-1,-1) if rows[i][0] <= position),0)


def at_column(text, row, column):
    start,end=row;cells=0;position=start
    for char in text[start:end]:
        size=cell_width(char)
        if cells+size>column:break
        cells+=size;position+=1
    return position


def move_vertical(text, position, direction, width, column=None):
    rows = wrapped(text, width)
    row = row_at(rows,position)
    target = max(0, min(len(rows)-1, row + direction))
    if column is None:column=cell_width(text[rows[row][0]:position])
    return at_column(text,rows[target],column)


def move_page(text,position,scroll,direction,width,height,column=None):
    rows=wrapped(text,width)
    cursor=move_vertical(text,position,direction*height,width,column)
    scroll=max(0,min(max(0,len(rows)-height),scroll+direction*height))
    return cursor,scroll


def clipboard_command(copy):
    if sys.platform=='darwin':candidates=[['pbcopy'] if copy else ['pbpaste']]
    elif os.environ.get('WAYLAND_DISPLAY'):candidates=[['wl-copy'] if copy else ['wl-paste','--no-newline']]
    elif os.environ.get('DISPLAY'):
        candidates=[['xclip','-selection','clipboard']+([] if copy else ['-o']),['xsel','--clipboard','--input' if copy else '--output']]
    else:candidates=[]
    return next((command for command in candidates if shutil.which(command[0])),None)


def look_clipboard():
    look=Path.home()/'.local/share/look'
    if not (look/'clipboard_shelf.py').is_file():return None
    if str(look) not in sys.path:sys.path.append(str(look))
    try:return importlib.import_module('clipboard_shelf')
    except ImportError:return None


def clipboard_copy(text):
    look=look_clipboard();recorded=False;copied=False
    if look:
        try:
            copied=look.copy_clipboard(text)
            shelf=look.Shelf()
            try:recorded=shelf.observe(text) or any(row[1]==text for row in shelf.rows())
            finally:shelf.close()
        except (OSError,ValueError,sqlite3.Error):pass
        return copied,recorded
    command=clipboard_command(True)
    if command:
        try:return subprocess.run(command,input=text,text=True,capture_output=True,timeout=CLIPBOARD_TIMEOUT_SECONDS).returncode==0,False
        except (OSError,subprocess.SubprocessError,UnicodeError):pass
    return False,False


def clipboard_paste():
    look=look_clipboard()
    if look:return look.read_clipboard()
    command=clipboard_command(False)
    if command:
        try:
            result=subprocess.run(command,text=True,capture_output=True,timeout=CLIPBOARD_TIMEOUT_SECONDS)
            if result.returncode==0:return result.stdout
        except (OSError,subprocess.SubprocessError,UnicodeError):pass
    return None


def clipboard_history(window):
    look=look_clipboard()
    if not look:return None
    curses.def_prog_mode();curses.endwin()
    try:return look.show(insert=True)
    finally:
        curses.reset_prog_mode();curses.raw();window.keypad(True);window.timeout(INPUT_TIMEOUT_MS)


def selection_bounds(state,cursor,length):
    if state['mode']!='VISUAL':return None
    lo,hi=sorted((state['anchor'],cursor))
    if not state.get('shift_selection'):hi+=1
    hi=min(length,hi)
    return (lo,hi) if lo<hi else None


def read_key(window):
    key=window.get_wch()
    if key!='\x1b':return key
    # Terminfo handles most modified keys. Decode xterm CSI variants when it does not.
    sequence=key;window.timeout(ESCAPE_TIMEOUT_MS)
    try:
        following=window.get_wch()
        if following in ('W','\x17'):return key+following
        if following not in ('[','O'):
            if isinstance(following,int):curses.ungetch(following)
            else:curses.unget_wch(following)
            return key
        sequence+=following
        for _ in range(24):
            char=window.get_wch()
            if not isinstance(char,str):curses.ungetch(char);break
            sequence+=char
            if char.isalpha() or char=='~':break
    except curses.error:pass
    finally:window.timeout(INPUT_TIMEOUT_MS)
    return sequence


def pane_action(key):
    # Kitty/CSI-u and xterm modifyOtherKeys preserve modifiers that plain Ctrl-W loses.
    if key=='\x17':return 'toggle'
    if key in ('\x1bW','\x1b[119;4u','\x1b[87;4u','\x1b[27;4;87~','\x1b[27;4;119~'):return 'focus'
    if key in ('\x1b\x17','\x1b[119;6u','\x1b[87;6u','\x1b[119;7u','\x1b[27;6;119~','\x1b[27;6;87~','\x1b[27;7;119~'):return 'close'
    return None


def change_panes(state,panes,action):
    state.update(mode='NORMAL',command='',shift_selection=False)
    if action=='focus':
        if state['split']:state['pane']=1-state['pane']
    elif action=='split':state['split']=True
    elif action=='only':
        panes[0],panes[state['pane']]=panes[state['pane']],panes[0]
        state.update(split=False,pane=0)
    elif action=='close' or action=='toggle' and state['split']:
        if state['split']:
            # Close the focused view, keeping the other view's scene and cursor.
            other=1-state['pane'];panes[0],panes[other]=panes[other],panes[0]
        state.update(split=False,pane=0)
    elif action=='toggle':state['split']=True


def mini_terminal_scope(enabled):
    if os.environ.get('KITTY_WINDOW_ID') and sys.stdout.isatty():
        # LOOK's Kitty config routes only this editor's pane keys into Mini.
        sys.stdout.write('\x1b]1337;SetUserVar=mercury_mini'+('=MQ==' if enabled else '')+'\x07')
        sys.stdout.flush()


def navigation_key(key):
    names={'LEFT':'left','RIGHT':'right','UP':'up','DOWN':'down','HOME':'home','END':'end',
           'PPAGE':'pageup','NPAGE':'pagedown','SLEFT':'shift-left','SRIGHT':'shift-right',
           'SR':'shift-up','SF':'shift-down','SHOME':'shift-home','SEND':'shift-end',
           'SPREVIOUS':'shift-pageup','SNEXT':'shift-pagedown'}
    if isinstance(key,int):
        for suffix,name in names.items():
            if key==getattr(curses,'KEY_'+suffix,None):return name
        try:name=curses.keyname(key).decode()
        except (curses.error,UnicodeError):return None
        for prefix,name_base in [('kUP','up'),('kDN','down'),('kLFT','left'),('kRIT','right'),('kHOM','home'),('kEND','end'),('kPRV','pageup'),('kNXT','pagedown')]:
            if name==prefix:return 'shift-'+name_base
            if name==prefix+'5':return 'ctrl-'+name_base
            if name==prefix+'6':return 'ctrl-shift-'+name_base
        return None
    codes={'A':'up','B':'down','C':'right','D':'left','H':'home','F':'end',
           '1~':'home','4~':'end','7~':'home','8~':'end','5~':'pageup','6~':'pagedown'}
    if key.startswith(('\x1b[','\x1bO')):
        suffix=key[2:]
        if suffix in codes:return codes[suffix]
        for modifier,prefix in [('2','shift-'),('5','ctrl-'),('6','ctrl-shift-')]:
            for code,name in codes.items():
                expected=(code[:-1]+';'+modifier+'~') if code.endswith('~') else '1;'+modifier+code
                if suffix==expected:return prefix+name
    return None


def run(scenes, checkpoint, save, split=False,initial=0,add=None,rename=None):
    """checkpoint writes recoverable local files; save also commits through Mercury."""
    buffers = [Buffer(scene['text']) for scene in scenes]
    if not buffers:
        raise ValueError('This manuscript has no scenes')
    panes = [dict(scene=initial, cursor=0, scroll=0, nav=initial,column=None), dict(scene=initial, cursor=0, scroll=0, nav=initial,column=None)]
    state = dict(pane=0, split=split, mode='NORMAL', tree=False, anchor=0,
                 shift_selection=False,return_mode='NORMAL',register='', message='', command='', dirty=False, checkpoint=0,help=False,help_scroll=0)

    def values():
        return [dict(scene, text=buffer.text) for scene, buffer in zip(scenes, buffers)]

    def persist():
        checkpoint(values()); state['checkpoint'] = time.monotonic()

    def create(kind,title=''):
        if add is None:
            state['message']='Manuscript creation requires a Mercury session';return
        persist()
        old_buffers={scene['scene_id']:buffer for scene,buffer in zip(scenes,buffers)}
        locations=[(scenes[pane['scene']]['scene_id'],scenes[pane['nav']]['scene_id']) for pane in panes]
        active=panes[state['pane']]
        try:new=add(kind,scenes[active['nav'] if state['tree'] else active['scene']]['scene_id'],title)
        except Exception as error:state['message']=str(error);return
        buffers[:]=[old_buffers.get(scene['scene_id']) or Buffer(scene['text']) for scene in scenes]
        indices={scene['scene_id']:i for i,scene in enumerate(scenes)}
        for pane,(scene_id,nav_id) in zip(panes,locations):pane.update(scene=indices[scene_id],nav=indices[nav_id])
        index=indices[new['scene_id']]
        active.update(scene=index,nav=index,cursor=0,scroll=0,column=None)
        state.update(tree=False,mode='INSERT',shift_selection=False,command='',dirty=True)
        try:
            persist();message=save();state['dirty']=False
            state['message']='Added '+('chapter · ' if kind=='chapter' else '')+new['scene_title']+' · '+message
        except Exception as error:state['message']='Created locally · '+str(error)

    def paint(window, row, col, text, width, style=0):
        safe = ''.join(char if char.isprintable() else ' ' for char in str(text))
        try: window.addnstr(row, col, safe, max(0, width), style)
        except curses.error: pass

    def interface(window):
        curses.raw(); window.keypad(True); window.timeout(INPUT_TIMEOUT_MS)
        theme=terminal_theme();styles=hint_styles(theme);screen_background(window,theme)
        while True:
            height, width = window.getmaxyx(); window.erase()
            if height < 10 or width < 48:
                paint(window, 0, 0, 'Mercury needs at least 48 columns × 10 rows', width-1)
                window.refresh()
                key = read_key(window)
                if key in ('q', '\x11'): persist(); return
                continue
            if state['help']:
                lines=[]
                for title,bindings in mini_help():
                    lines.extend([[(line,True)] for line in textwrap.wrap(title,width-1)])
                    lines.extend(binding_rows(bindings,width-3) if bindings else [])
                    lines.append([])
                help_footer=binding_rows([('F1/Esc','back'),('↑↓','scroll'),('PgUp/PgDn','page')],width-1)
                page=height-len(help_footer)-2;state['help_scroll']=max(0,min(state['help_scroll'],max(0,len(lines)-page)))
                paint(window,0,0,'MINI HELP · '+state['mode']+' · Ctrl means Control, not Command',width-1,theme['header'])
                paint_bindings(window,1,lines[state['help_scroll']:state['help_scroll']+page],styles)
                paint_bindings(window,height-len(help_footer),help_footer,styles)
                window.refresh()
                try:key=read_key(window)
                except curses.error:continue
                if key in ('\x1b','q',curses.KEY_F1):state['help']=False
                elif key=='\x11':persist();return
                elif key=='\x13':
                    persist()
                    try:state['message']=save();state['dirty']=False
                    except Exception as error:state['message']=str(error)
                elif key in (curses.KEY_DOWN,'j'):state['help_scroll']+=1
                elif key in (curses.KEY_UP,'k'):state['help_scroll']-=1
                elif key==curses.KEY_NPAGE:state['help_scroll']+=page
                elif key==curses.KEY_PPAGE:state['help_scroll']-=page
                continue
            footer=binding_rows(mini_bindings(state),width-1)
            footer_top=height-len(footer)-2
            count = 2 if state['split'] else 1
            pane_height = footer_top//count
            if pane_height<3:
                paint(window,0,0,'Increase terminal height for two panes or press Ctrl-Shift-W to close',width-1)
                window.refresh()
                try:key=read_key(window)
                except curses.error:continue
                if pane_action(key) in ('toggle','close'):change_panes(state,panes,'close')
                elif key=='\x11':persist();return
                continue
            nav_width = min(NAV_WIDTH, width//3)
            edit_width = width-nav_width-3
            active = panes[state['pane']]; buffer = buffers[active['scene']]
            active['cursor'] = min(active['cursor'], len(buffer.text))
            for number in range(count):
                pane = panes[number]; text = buffers[pane['scene']].text
                top = number*pane_height
                current = scenes[pane['scene']]
                chapter_number = f"Chapter {current['chapter_index']+1}"
                chapter_title = current['chapter_title']
                chapter = chapter_number if chapter_title == chapter_number else f"{chapter_number} — {chapter_title}"
                title = f"{chapter} / {current['scene_title']}"
                paint(window, top, 0, (('▶ ' if number == state['pane'] else '  ')+title).ljust(width-1), width-1, theme['header'] if number==state['pane'] else theme['inactive'])
                body_height = pane_height-2
                for row in range(body_height):
                    paint(window,top+1+row,0,' '*nav_width,nav_width,theme['navigation'])
                    paint(window,top+1+row,nav_width,'│',1,theme['muted'])
                nav_start = max(0, pane['nav']-body_height+1)
                for row, index in enumerate(range(nav_start, min(len(scenes), nav_start+body_height))):
                    scene = scenes[index]
                    label = f"{scene['chapter_index']+1}.{scene['scene_index']+1} {scene['scene_title']}"
                    paint(window, top+1+row, 0, label.ljust(nav_width-1), nav_width-1,
                          theme['selected'] if index == pane['nav'] and number == state['pane'] and state['tree'] else theme['navigation']|curses.A_BOLD if index == pane['scene'] else theme['navigation'])
                rows = wrapped(text, edit_width)
                pane['cursor']=min(pane['cursor'],len(text))
                cursor_row = row_at(rows,pane['cursor'])
                if cursor_row < pane['scroll']: pane['scroll'] = cursor_row
                if cursor_row >= pane['scroll']+body_height: pane['scroll'] = cursor_row-body_height+1
                for line in range(body_height):
                    index = pane['scroll']+line
                    if index >= len(rows): break
                    start, end = rows[index]
                    paint(window, top+1+line, nav_width+1, text[start:end], edit_width,theme['body'])
                    if number == state['pane'] and state['mode'] == 'VISUAL':
                        selected=selection_bounds(state,pane['cursor'],len(text))
                        lo,hi=selected or (0,0)
                        a,b = max(start,lo),min(end,hi)
                        if a < b:
                            prefix = cell_width(text[start:a])
                            paint(window,top+1+line,nav_width+1+prefix,text[a:b],edit_width-prefix,theme['selection'])
                if number == state['pane'] and not state['tree']:
                    start = rows[cursor_row][0]
                    offset = cell_width(text[start:pane['cursor']])
                    cursor = (top+1+cursor_row-pane['scroll'], min(width-2, nav_width+1+offset))
            paint_bindings(window,footer_top,footer,styles)
            badge=' '+state['mode']+' '
            paint(window,height-2,0,badge,len(badge),theme[state['mode'].lower()])
            paint(window,height-2,len(badge),f" · {'Manuscript' if state['tree'] else 'Writing'} · {len(buffer.text.split())} words · {state['message']}",width-len(badge)-1,theme['body'])
            paint(window,height-1,0,(':'+state['command']) if state['mode']=='COMMAND' else '',width-1,theme['command'])
            try:
                curses.curs_set(0 if state['tree'] and state['mode']!='COMMAND' else 1)
                if state['mode']=='COMMAND':
                    window.move(height-1,min(width-2,1+cell_width(state['command'])))
                elif not state['tree']: window.move(*cursor)
            except curses.error: pass
            window.refresh()
            if state['dirty'] and time.monotonic()-state['checkpoint'] >= CHECKPOINT_SECONDS:
                persist()
            try: key = read_key(window)
            except curses.error: continue
            if key==curses.KEY_F1 or key=='?' and state['mode']=='NORMAL':
                persist();state['help']=True;state['help_scroll']=0;continue
            if key == '\x13':
                persist()
                try: state['message']=save(); state['dirty']=False
                except Exception as error: state['message']=str(error)
                continue
            if key == '\x11': persist(); return
            action='split' if key=='W' and state['mode']=='NORMAL' else pane_action(key)
            if action:
                change_panes(state,panes,action);continue
            if key in ('\n','\r',curses.KEY_ENTER) and state['mode'] == 'NORMAL' and not state['tree']:
                change_panes(state,panes,'focus');continue
            if key == '\t': state['tree']=not state['tree']; state['mode']='NORMAL'; continue
            if key == '\x1b': state['mode']='NORMAL'; state['command']=''; continue
            if key=='\x02' and (state['tree'] or state['mode']=='COMMAND'):
                state['tree']=False;state['mode']='NORMAL';state['command']=''
            if state['tree'] and state['mode']!='COMMAND':
                if key in ('r','R'):
                    state.update(mode='COMMAND',command='rename-scene ' if key=='r' else 'rename-chapter ')
                elif key in ('s','c'):create('scene' if key=='s' else 'chapter')
                elif key in ('j',curses.KEY_DOWN): active['nav']=min(len(scenes)-1,active['nav']+1)
                elif key in ('k',curses.KEY_UP): active['nav']=max(0,active['nav']-1)
                elif key in ('\n','\r',curses.KEY_ENTER):
                    active.update(scene=active['nav'],cursor=0,scroll=0,column=None);state['tree']=False
                continue
            if state['mode']=='COMMAND':
                if key in ('\n','\r'):
                    command=state['command'];state['command']='';state['mode']='NORMAL'
                    if command in ('w','wq'):
                        persist()
                        try: state['message']=save();state['dirty']=False
                        except Exception as error: state['message']=str(error);continue
                    if command in ('q','wq'): persist();return
                    elif command in ('split','sp'):change_panes(state,panes,'split')
                    elif command in ('only','close'):change_panes(state,panes,command)
                    elif command.split(' ',1)[0] in ('scene','chapter'):
                        kind,_,title=command.partition(' ');create(kind,title)
                    elif command.split(' ',1)[0] in ('rename-scene','rename-chapter'):
                        action,_,title=command.partition(' ')
                        target=scenes[active['nav'] if state['tree'] else active['scene']]
                        if rename is None:
                            state['message']='Renaming requires a Mercury session';continue
                        try:
                            persist()
                            rename(action.removeprefix('rename-'),target['scene_id'],title)
                        except Exception as error:
                            state['message']=str(error);continue
                        try:state['message']='Renamed · '+save();state['dirty']=False
                        except Exception as error:state['message']='Renamed locally · '+str(error)
                    elif command not in ('w',):state['message']='Commands: :w :q :wq :split :only :close :scene :chapter :rename-scene :rename-chapter'
                elif key in (curses.KEY_BACKSPACE,'\x7f','\b'):state['command']=state['command'][:-1]
                elif isinstance(key,str) and key.isprintable():state['command']+=key
                continue
            pos=active['cursor']; before=buffer.text
            motion=navigation_key(key)
            if state['mode']!='INSERT' and key in ('h','j','k','l') and not (state['mode']=='VISUAL' and state['shift_selection']):
                motion={'h':'left','j':'down','k':'up','l':'right'}[key]
            selected=selection_bounds(state,pos,len(buffer.text))

            def replace_selection(text):
                lo,hi=selected or (pos,pos)
                buffer.replace(lo,hi,text);active['cursor']=lo+len(text)
                state['mode']=state['return_mode'] if state['mode']=='VISUAL' else state['mode']

            def copy_selection(cut=False):
                if not selected:
                    state['message']='Select text with Shift+arrows, Ctrl-A, or v first';return
                lo,hi=selected;state['register']=buffer.text[lo:hi]
                system,shelf=clipboard_copy(state['register'])
                destination='system clipboard' if system else 'Mini clipboard'
                if shelf:destination+=' + LOOK clips'
                state['message']=('Cut to ' if cut else 'Copied to ')+destination
                if not system:state['message']+=' · system clipboard unavailable'
                if cut:replace_selection('')

            if key=='\x01':
                state.update(mode='VISUAL',anchor=0,shift_selection=True,return_mode='INSERT' if state['mode']=='INSERT' else 'NORMAL')
                active['cursor']=len(buffer.text)
            elif key in ('\x03','\x18'):
                copy_selection(key=='\x18')
            elif key in ('\x16','\x02') or key=='P' and state['mode']=='NORMAL':
                if key in ('\x02','P'):
                    try:
                        text=clipboard_history(window)
                        state['message']='LOOK clips closed' if text is None else 'Inserted from LOOK clips'
                        if look_clipboard() is None:state['message']='LOOK clips unavailable; install LOOK or use Ctrl-V'
                    except (OSError,ValueError,RuntimeError,sqlite3.Error,curses.error) as error:
                        text=None;state['message']='LOOK clips unavailable: '+str(error)
                else:
                    text=clipboard_paste()
                    if text is None:text=state['register'];state['message']='Pasted Mini clipboard · system clipboard unavailable'
                    else:state['message']='Pasted system clipboard'
                if text is not None:replace_selection(text)
            elif motion:
                shifted='shift-' in motion
                motion=motion.replace('shift-','')
                collapse=not shifted and state['mode']=='VISUAL' and state['shift_selection'] and selected and motion in ('left','right')
                if shifted and state['mode']!='VISUAL':
                    state.update(anchor=pos,return_mode=state['mode'],mode='VISUAL',shift_selection=True)
                elif not shifted and state['mode']=='VISUAL' and state['shift_selection']:
                    state['mode']=state['return_mode']
                if collapse:
                    active['cursor']=selected[0 if motion=='left' else 1];active['column']=None
                elif motion in ('up','down','pageup','pagedown'):
                    if active['column'] is None:
                        rows=wrapped(buffer.text,edit_width)
                        active['column']=cell_width(buffer.text[rows[row_at(rows,pos)][0]:pos])
                    direction=-1 if motion in ('up','pageup') else 1
                    if motion in ('pageup','pagedown'):
                        active['cursor'],active['scroll']=move_page(buffer.text,pos,active['scroll'],direction,edit_width,pane_height-2,active['column'])
                    else:active['cursor']=move_vertical(buffer.text,pos,direction,edit_width,active['column'])
                else:
                    active['column']=None
                    if motion=='left':active['cursor']=max(0,pos-1)
                    elif motion=='right':active['cursor']=min(len(buffer.text),pos+1)
                    elif motion=='home':active['cursor']=buffer.text.rfind('\n',0,pos)+1
                    elif motion=='end':
                        end=buffer.text.find('\n',pos);active['cursor']=len(buffer.text) if end<0 else end
                    elif motion=='ctrl-home':active['cursor']=0
                    elif motion=='ctrl-end':active['cursor']=len(buffer.text)
            elif state['mode']=='VISUAL' and state['shift_selection'] and (key in (curses.KEY_BACKSPACE,curses.KEY_DC,'\x7f','\b','\n','\r') or isinstance(key,str) and key.isprintable()):
                text='' if key in (curses.KEY_BACKSPACE,curses.KEY_DC,'\x7f','\b') else '\n' if key in ('\n','\r') else key
                replace_selection(text)
                if text:state['mode']='INSERT'
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
            elif key=='v':state.update(mode='VISUAL',anchor=pos,shift_selection=False,return_mode='NORMAL')
            elif key in ('d','y') and state['mode']=='VISUAL':
                copy_selection(key=='d');state['mode']='NORMAL'
            elif key=='x':buffer.replace(pos,pos+1,'')
            elif key=='p':replace_selection(state['register'])
            elif key=='u':buffer.restore()
            elif key=='\x12':buffer.restore(redo=True)
            elif key=='0':active['cursor']=buffer.text.rfind('\n',0,pos)+1
            elif key=='$':
                end=buffer.text.find('\n',pos);active['cursor']=len(buffer.text) if end<0 else end
            elif key=='G':active['cursor']=len(buffer.text)
            elif key==':':state['mode']='COMMAND';state['command']=''
            if before!=buffer.text:state['dirty']=True;active['column']=None
            elif not motion:active['column']=None
    try:
        mini_terminal_scope(True)
        run_screen(interface)
    finally:
        mini_terminal_scope(False)
        checkpoint(values())
