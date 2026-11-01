"""Shared terminal hints: wrap complete bindings and distinguish keys from actions."""
import curses
import unicodedata


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


def hint_styles():
    key,label=curses.A_BOLD,curses.A_NORMAL
    try:
        if curses.has_colors():
            curses.start_color();curses.use_default_colors()
            curses.init_pair(1,curses.COLOR_CYAN,-1)
            key|=curses.color_pair(1)
    except curses.error:pass
    return key,label


def paint_bindings(window,start,rows,styles):
    for line,runs in enumerate(rows):
        column=0
        for text,highlight in runs:
            try:window.addnstr(start+line,column,text,len(text),styles[0 if highlight else 1])
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
