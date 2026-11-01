"""Shared terminal hints: wrap complete bindings and distinguish keys from actions."""
import curses
import os
import sys
import termios
import unicodedata


def run_screen(function,*args,**kwargs):
    original=None;fd=None
    try:
        fd=sys.stdin.fileno()
        if os.isatty(fd):original=termios.tcgetattr(fd)
    except (OSError,ValueError,termios.error):pass
    try:return curses.wrapper(function,*args,**kwargs)
    finally:
        # Nested curses screens can alter the saved shell mode. Restore the actual
        # entry settings as well, so the next shell prompt behaves normally.
        if original is not None:
            try:
                termios.tcsetattr(fd,termios.TCSADRAIN,original)
            except (OSError,termios.error):pass


def terminal_theme():
    """Use explicit UI colors so a green shell foreground cannot tint the whole desk."""
    theme={name:curses.A_NORMAL for name in ('body','muted','header','inactive','navigation','selected','selection','key','clips','normal','insert','visual','command')}
    theme.update(header=curses.A_BOLD,selected=curses.A_REVERSE,selection=curses.A_REVERSE,key=curses.A_BOLD)
    try:
        if curses.has_colors():
            curses.start_color()
            # All pairs specify both colors for consistent contrast in light and dark terminals.
            if curses.COLORS>=256:
                colors=[('body',253,234),('muted',246,234),('header',231,24),('inactive',250,238),
                        ('navigation',223,236),('selected',16,221),('selection',16,153),('key',75,234)]
            else:
                colors=[('body',curses.COLOR_WHITE,curses.COLOR_BLACK),('muted',curses.COLOR_WHITE,curses.COLOR_BLACK),
                        ('header',curses.COLOR_WHITE,curses.COLOR_BLUE),('inactive',curses.COLOR_WHITE,curses.COLOR_BLACK),
                        ('navigation',curses.COLOR_YELLOW,curses.COLOR_BLACK),('selected',curses.COLOR_BLACK,curses.COLOR_YELLOW),
                        ('selection',curses.COLOR_BLACK,curses.COLOR_CYAN),('key',curses.COLOR_BLUE,curses.COLOR_BLACK)]
            for pair,(name,foreground,background) in enumerate(colors,1):
                if pair>=curses.COLOR_PAIRS:break
                curses.init_pair(pair,foreground,background);theme[name]=curses.color_pair(pair)
    except curses.error:pass
    for name in ('header','key','clips','normal','insert','visual','command'):theme[name]|=curses.A_BOLD
    for name in ('clips','normal','insert','visual','command'):theme[name]=theme['key']
    return theme


def screen_background(window,theme):
    try:window.bkgd(' ',theme['body'])
    except (AttributeError,curses.error):pass


def resume_screen(window):
    # An inner curses.wrapper ends cbreak mode; refresh alone does not restore it.
    for action in (curses.reset_prog_mode,curses.noecho,curses.cbreak,lambda:curses.curs_set(0)):
        try:action()
        except curses.error:pass
    window.keypad(True)
    window.clearok(True);window.touchwin();window.refresh()


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def binding_rows(bindings,width):
    width=max(1,width);rows=[[]];column=0
    for key,label in bindings:
        size=cells(key+' '+label)
        if column and column+2+size>width:rows.append([]);column=0
        if column:rows[-1].append(('  ',False));column+=2
        for text,highlight in [(key,True),(' '+label,False)]:
            for char in text:
                size=cells(char)
                if column+size>width:rows.append([]);column=0
                if not column and char==' ':continue
                if rows[-1] and rows[-1][-1][1]==highlight:
                    prior,_=rows[-1].pop();rows[-1].append((prior+char,highlight))
                else:rows[-1].append((char,highlight))
                column+=size
    return rows


def hint_styles(theme=None):
    theme=theme or terminal_theme()
    return theme['key'],theme['muted']


def paint_bindings(window,start,rows,styles):
    for line,runs in enumerate(rows):
        column=0
        for text,highlight in runs:
            style=styles[0 if highlight else 1]
            try:window.addnstr(start+line,column,text,len(text),style)
            except curses.error:pass
            column+=cells(text)


def mini_bindings(state):
    common=[('Ctrl-S','save'),('Ctrl-Q','quit'),('Ctrl-B','clips'),('Ctrl-W','split'),('Tab','tree')]
    if state.get('tree'):mode=[('↑↓','choose'),('Enter','open scene')]
    elif state['mode']=='INSERT':mode=[('Esc','normal'),('Shift+arrows','select')]
    elif state['mode']=='VISUAL':
        mode=[('Esc','normal'),('Ctrl-C/X','copy/cut'),('Ctrl-V','paste')]
        mode+=[('Type','replace selection')] if state.get('shift_selection') else [('y/d','copy/cut')]
    elif state['mode']=='COMMAND':mode=[('Enter','run'),('Esc','cancel')]
    else:mode=[('Ctrl-J','pane'),('i','insert'),('v','select'),('u','undo')]
    return common+mode+[('F1','help')]+([] if state['mode']=='INSERT' else [('?','help')] if state['mode']=='NORMAL' else [])


def mini_help():
    return [
        ('Mini writing desk', [('F1 / Esc','close help'),('↑↓ / PgUp/PgDn','scroll help')]),
        ('Control means Ctrl alone; Command is not required.',[]),
        ('Every mode', [('Ctrl-S','save'),('Ctrl-Q','quit'),('Ctrl-W','toggle split; return to normal'),('Tab','toggle manuscript tree; return to normal'),('Ctrl-B','open LOOK clips; insert a numbered clip'),('F1','open help without changing mode')]),
        ('Normal mode', [('i / a / o','enter insert mode'),('v','enter Vim visual selection'),('hjkl / arrows','move'),('Ctrl-J / Enter','switch writing pane'),('u / Ctrl-R','undo / redo'),('x','delete character'),('p','paste internal register'),('P','open LOOK clips'),('0 / $ / G','line start / line end / scene end'),(':','enter command'),('?','open help')]),
        ('Insert mode', [('Type','insert text'),('Enter / Ctrl-J','new line'),('Backspace / Delete','delete text'),('Esc','return to normal'),('?','insert a question mark; use F1 for help')]),
        ('Visual selection', [('v then arrows / hjkl','extend Vim selection'),('y / d','copy / cut Vim selection'),('Shift+arrows','start or extend standard selection'),('Type','replace a standard Shift selection'),('Backspace / Delete','remove a standard Shift selection'),('Esc','cancel selection; return to normal')]),
        ('All writing modes', [('Arrows','move cursor'),('PgUp / PgDn','move a screen; retain screen row and preferred column'),('Home / End','line start / end'),('Ctrl-Home / Ctrl-End','scene start / end'),('Shift + navigation','extend selection'),('Ctrl-A','select entire scene'),('Ctrl-C / Ctrl-X / Ctrl-V','copy / cut / paste system clipboard')]),
        ('Manuscript tree', [('↑↓ / j k','select scene'),('Enter','open scene in this pane'),('Tab','return to writing')]),
        ('Commands', [(':w / :wq','save / save and quit'),(':q','exit; local recovery files retained'),(':split / :only','two writing panes / one pane')]),
        ('LOOK clips stay on this computer. Capture records local copies; it does not sync history across the Fabric. Mini copies/cuts explicitly join this local shelf even with capture off.',[]),
    ]
