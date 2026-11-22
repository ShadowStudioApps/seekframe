"""Small helpers shared by the window and its dialogs (no Shadow state): open a file, the dark Windows title bar, the
narration kit loader. Split out of app.py (3.16); app.py imports these names back."""
import importlib, os, subprocess, sys

def open_path(p):
    os.startfile(p) if hasattr(os, 'startfile') else subprocess.Popen(['xdg-open', p])

def narrate_module():
    """make_narrated_scene, from tools/narrate next to app.py or inside the PyInstaller bundle (_MEIPASS)."""
    base = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'tools', 'narrate')
    if base not in sys.path: sys.path.insert(0, base)
    return importlib.import_module('make_narrated_scene')

def dark_titlebar(win, dark):
    """Windows 10 1809+/11: DWMWA_USE_IMMERSIVE_DARK_MODE (20, or 19 on old builds). On Windows 11 the caption colour is also
    set (DWMWA_CAPTION_COLOR / TEXT_COLOR), otherwise "accent colour on title bars" keeps the bar coloured."""
    if os.name != 'nt': return
    try:
        import ctypes
        win.update_idletasks()
        dwm = ctypes.windll.dwmapi; hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        def put(attr, v):
            v = ctypes.c_uint(v); return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        if put(20, 1 if dark else 0) != 0: put(19, 1 if dark else 0)
        DEFAULT = 0xFFFFFFFF  # DWMWA_COLOR_DEFAULT
        put(35, 0x001C1C1C if dark else DEFAULT)   # caption colour, COLORREF 0x00BBGGRR
        put(36, 0x00FFFFFF if dark else DEFAULT)   # caption text
        # repaint the non-client area now (SWP_NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


# ---------------------------------------------------------------- text fields (3.35)
# Where you can type must look like it: an editable tk.Text gets its own field colour, a visible border that turns blue
# while it has the cursor, and a grey hint inside while it is empty. Read-only boxes (logs, results) stay flat.
FIELD = {True: dict(bg='#2d2d2d', fg='#fafafa', border='#7a7a7a', focus='#4cc2ff', hint='#9a9a9a', ro='#232323'),
         False: dict(bg='#ffffff', fg='#1b1b1b', border='#8a8a8a', focus='#005fb8', hint='#707070', ro='#f3f3f3')}


def style_input(w, dark, hint=None):
    """An editable tk.Text: field background, 2 px border (blue while focused) and an optional grey hint while empty."""
    c = FIELD[bool(dark)]
    w.configure(background=c['bg'], foreground=c['fg'], insertbackground=c['fg'], insertwidth=2, relief='flat', borderwidth=0,
                highlightthickness=2, highlightbackground=c['border'], highlightcolor=c['focus'], selectbackground='#2f6fb5',
                selectforeground='#ffffff')
    lbl = getattr(w, 'hint_lbl', None)
    if hint and lbl is None:
        import tkinter as tk
        lbl = w.hint_lbl = tk.Label(w, text=hint, anchor='nw', justify='left', font=w.cget('font'), cursor='xterm', borderwidth=0)
        lbl.bind('<Button-1>', lambda e: w.focus_set())
        def update(e=None):
            try:
                empty = not w.get('1.0', 'end-1c')
                if empty and w.focus_get() is not w and str(w.cget('state')) == 'normal':
                    lbl.place(x=int(str(w.cget('padx'))), y=int(str(w.cget('pady'))))
                    lbl.configure(wraplength=max(80, w.winfo_width() - 2 * int(str(w.cget('padx'))) - 8))
                else:
                    lbl.place_forget()
            except Exception:
                pass
        def modified(e=None):
            update()
            try: w.edit_modified(False)
            except Exception: pass
        w.hint_update = update
        for ev in ('<FocusIn>', '<FocusOut>', '<Configure>'): w.bind(ev, update, add='+')
        w.bind('<<Modified>>', modified, add='+')
        w.after_idle(update)
    if lbl is not None:
        lbl.configure(background=c['bg'], foreground=c['hint'])
    return w


def style_output(w, dark):
    """A read-only tk.Text (log / result): flat, slightly different from the window, no border - nothing to type in."""
    c = FIELD[bool(dark)]
    w.configure(background=c['ro'], foreground=c['fg'], relief='flat', borderwidth=0, highlightthickness=0,
                selectbackground='#2f6fb5', selectforeground='#ffffff')
    return w


# Ctrl+C / V / X / A / Z by the KEY, not the letter: with an Arabic (or any non-Latin) keyboard layout Tk sees Arabic
# keysyms, so Tk's own <Control-Key-v> never matches and paste did nothing. Windows key codes stay the same.
EDIT_KEYS = {86: '<<Paste>>', 67: '<<Copy>>', 88: '<<Cut>>', 65: '<<SelectAll>>', 90: '<<Undo>>', 89: '<<Redo>>'}
EDIT_CLASSES = ('Text', 'Entry', 'TEntry', 'TCombobox', 'TSpinbox')


def _ctrl_key(e):
    ks = str(getattr(e, 'keysym', '') or '')
    if len(ks) == 1 and ks.isascii(): return None   # a Latin layout: Tk's own bindings already did it
    ev = EDIT_KEYS.get(getattr(e, 'keycode', None))
    if not ev: return None
    try: e.widget.event_generate(ev)
    except Exception: return None
    return 'break'


def _menu(e, labels):
    import tkinter as tk
    w = e.widget
    try: w.focus_set()
    except Exception: pass
    try: state = str(w.cget('state'))
    except Exception: state = 'normal'
    editable = state not in ('disabled', 'readonly')
    try:
        sel = bool(w.tag_ranges('sel')) if isinstance(w, tk.Text) else bool(w.selection_present())
    except Exception:
        sel = False
    m = tk.Menu(w, tearoff=0)
    def do(ev):
        if isinstance(w, tk.Text) and str(w.cget('state')) == 'disabled' and ev == '<<SelectAll>>':
            w.tag_add('sel', '1.0', 'end-1c'); return
        w.event_generate(ev)
    m.add_command(label=labels('Cut'), command=lambda: do('<<Cut>>'), state='normal' if editable and sel else 'disabled')
    m.add_command(label=labels('Copy'), command=lambda: do('<<Copy>>'), state='normal' if sel else 'disabled')
    m.add_command(label=labels('Paste'), command=lambda: do('<<Paste>>'), state='normal' if editable else 'disabled')
    m.add_separator()
    m.add_command(label=labels('Select all'), command=lambda: do('<<SelectAll>>'))
    w.edit_menu = m
    try: m.tk_popup(e.x_root, e.y_root)
    finally:
        try: m.grab_release()
        except Exception: pass
    return 'break'


def edit_bindings(root, labels=lambda s: s):
    """Once per app: layout-independent Ctrl+C/V/X/A/Z and a right-click Cut / Copy / Paste / Select all menu on every
    text field (Text, Entry, Combobox, Spinbox) of every window."""
    for cls in EDIT_CLASSES:
        root.bind_class(cls, '<Control-KeyPress>', _ctrl_key, add='+')
        root.bind_class(cls, '<Button-3>', lambda e: _menu(e, labels))
