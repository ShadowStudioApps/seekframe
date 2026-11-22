"""3.35 text fields: where you type must look like it, and typing / pasting must work on any keyboard layout.
  F1 New video (AI): the idea box is a field (border, field colour, focus colour), the progress log below is flat
  F2 an empty idea box shows a grey hint, gone as soon as there is text; the cursor starts in the idea box
  F3 key events typed into the idea box land in it (Tk key events, whatever the Windows layout is)
  F4 Ctrl+V by the key: <<Paste>> fires exactly once, also when the layout gives a non-Latin keysym (Arabic)
  F5 right-click menu: Cut / Copy / Paste / Select all, Cut and Paste off in a read-only box
  F6 the Assistant's message box and the AI window's note box are fields too
No real clipboard, no real menu pops up (tk_popup is stubbed), no dialog (no_dialogs).
Usage: python tests/test_text_fields.py     exit 0 = all PASS"""
import os, shutil, sys, tempfile, types
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'
import tkinter as tk
import app, no_dialogs, shadow_util as su

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_fields_'); app.LOG = os.path.join(TMP, 'l.log'); app.close_log()
no_dialogs.block(app)
app.save_cfg = lambda d: None; app.load_cfg = lambda: {}   # never the owner's own settings
app.App.start_update_check = lambda *a, **k: None
popped = []
tk.Menu.tk_popup = lambda self, x, y, entry='': popped.append(self)   # never a real menu on the owner's screen
w = app.App()
try:
    w.ai_voice = ''   # no voice search thread
    w.update()
    d = w.open_new_video(); d.top.update()
    idea, out = d.idea, d.out
    check('F1 the idea box has a visible border and a focus colour', int(idea.cget('highlightthickness')) == 2
          and str(idea.cget('highlightcolor')) != str(idea.cget('highlightbackground')))
    check('F1 the progress log is flat and looks different from the idea box', int(out.cget('highlightthickness')) == 0
          and str(out.cget('background')) != str(idea.cget('background')))
    d.top.after(10); w.focus_set(); w.update(); idea.hint_update()
    check('F2 an empty idea box shows a grey hint', getattr(idea, 'hint_lbl', None) is not None and idea.hint_lbl.winfo_manager() == 'place'
          and 'idea' in idea.hint_lbl.cget('text'))
    idea.insert('1.0', 'volcanoes'); w.update()
    check('F2 the hint goes away when there is text', not idea.hint_lbl.winfo_manager())
    idea.delete('1.0', 'end'); w.update()
    check('F2 ...and comes back when it is empty again', idea.hint_lbl.winfo_manager() == 'place')

    d.top.focus_force(); idea.focus_force(); w.update()
    # two letters the current Windows layout has (Tk refuses a keysym the layout has no key for)
    keys = []
    for ks in ('h', 'i', 'Arabic_heh', 'Arabic_alef', '1', '2'):
        try: idea.event_generate('<KeyPress>', keysym=ks); keys.append(ks)
        except tk.TclError: continue
        if len(keys) == 2: break
    w.update()
    typed = idea.get('1.0', 'end-1c')
    check('F3 two key presses typed into the idea box give two letters', len(keys) == 2 and len(typed) == 2, (keys, typed))
    check('F3 the hint is hidden while the box has the cursor', not idea.hint_lbl.winfo_manager())

    pastes = []
    idea.bind('<<Paste>>', lambda e: (pastes.append(1), 'break')[1])   # count, never read the real clipboard
    idea.event_generate('<Control-KeyPress>', keycode=86); w.update()
    check('F4 Ctrl+V (key V, the layout of this PC) pastes once', len(pastes) == 1, pastes)
    pastes.clear()
    ev = types.SimpleNamespace(widget=idea, keysym='Arabic_ra', keycode=86)
    check('F4 Ctrl+V with an Arabic layout (keysym Arabic_ra) still pastes', su._ctrl_key(ev) == 'break' and w.update() is None and len(pastes) == 1, pastes)
    pastes.clear()
    ev = types.SimpleNamespace(widget=idea, keysym='v', keycode=86)
    check('F4 a Latin layout is left to Tk (no double paste)', su._ctrl_key(ev) is None and len(pastes) == 0)
    idea.unbind('<<Paste>>')
    idea.delete('1.0', 'end'); idea.insert('1.0', 'abc')
    su._ctrl_key(types.SimpleNamespace(widget=idea, keysym='Arabic_sheen', keycode=65)); w.update()
    check('F4 Ctrl+A with an Arabic layout selects all', idea.tag_ranges('sel') != () and idea.get('sel.first', 'sel.last').strip() == 'abc', idea.tag_ranges('sel'))

    me = types.SimpleNamespace(widget=idea, x_root=10, y_root=10)
    su._menu(me, app.tr); m = idea.edit_menu
    labels = [m.entrycget(i, 'label') for i in (0, 1, 2, 4)]
    check('F5 right-click menu: Cut / Copy / Paste / Select all', popped and labels == ['Cut', 'Copy', 'Paste', 'Select all'], labels)
    check('F5 with a selection everything is on', all(m.entrycget(i, 'state') == 'normal' for i in (0, 1, 2)))
    d.write('log line')
    su._menu(types.SimpleNamespace(widget=out, x_root=10, y_root=10), app.tr); m = out.edit_menu
    check('F5 in the read-only log Cut and Paste are off', m.entrycget(0, 'state') == 'disabled' and m.entrycget(2, 'state') == 'disabled')
    m.invoke(4); w.update()
    check('F5 Select all works in the read-only log', out.tag_ranges('sel') != ())
    d.close()

    check('F6 the Assistant message box is a field with a hint', int(w.ai_in.cget('highlightthickness')) == 2
          and 'Claude' in w.ai_in.hint_lbl.cget('text') and str(w.ai_in.cget('background')) != str(w.ai_text.cget('background')))
    import dialogs
    p = os.path.join(TMP, 'x.html'); open(p, 'w').write('<canvas id="c"></canvas>')
    aw = dialogs.AIWindow(w, p, problems=[]) if 'problems' in dialogs.AIWindow.__init__.__code__.co_varnames else None
    if aw is not None:
        aw.top.update()
        check('F6 the AI window note box is a field, its log is flat', int(aw.note.cget('highlightthickness')) == 2 and int(aw.out.cget('highlightthickness')) == 0)
        aw.close()
    old = w.theme; w.toggle_theme(); w.update()
    check('F6 switching the theme restyles the Assistant box', str(w.ai_in.cget('background')) == su.FIELD[w.theme == 'dark']['bg'])
    w.theme = old
finally:
    try: w.destroy()
    except Exception: pass
    app.close_log(); shutil.rmtree(TMP, ignore_errors=True)
print('ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}')
sys.exit(1 if fails else 0)
