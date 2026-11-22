"""The 3.28 window layout: sidebar + pages (Queue / Settings / About). No real dialog opens (no_dialogs).
  S1 the window opens on the Queue page; the old widgets are all there (tree, Render, status, update button, setup bar)
  S2 show_page switches pages and marks the sidebar row; Settings holds the options, the setup and the language
  S3 the menu button hides / shows the sidebar and the choice is saved (setting 'sidebar'); a saved False starts it hidden
  S4 sidebar rows run their actions (Assistant toggles the panel and is marked while open)
  S5 About shows the version and the links point to the app's GitHub home
  S6 the options line on the Queue page follows the settings and opens Settings
Usage: python tests/test_sidebar.py     exit 0 = all PASS"""
import os, shutil, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts
import app, no_dialogs, updater, render_core as rc

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_sidebar_'); app.LOG = os.path.join(TMP, 'l.log'); app.close_log()
no_dialogs.block(app)
saved = {}; app.save_cfg = lambda d: saved.update(d)
app.App.start_update_check = lambda *a, **k: None
w = app.App(); w.withdraw()
try:
    w.update()
    check('S1 opens on the Queue page', w.page == 'queue' and w.pages['queue'].winfo_manager() == 'pack'
          and not w.pages['settings'].winfo_manager() and w.page_title.cget('text') == 'Queue')
    check('S1 the old widgets are all still there', all(hasattr(w, n) for n in ('tree', 'go', 'stop', 'stop_cur', 'status', 'bar', 'eta_lbl', 'yt_btn',
          'check_btn', 'narr_btn', 'update_btn', 'selftest_btn', 'env_lbls', 'folder_box', 'lang_box', 'theme_btn', 'ai_btn', 'proj_btn')))
    check('S1 the update button stays in the window (sidebar)', w.update_btn.winfo_manager() == 'pack' and str(w.update_btn.master) == str(w.side))
    w.show_page('settings'); w.update()
    check('S2 Settings page shown, Queue hidden, row marked', w.page == 'settings' and w.pages['settings'].winfo_manager() == 'pack'
          and not w.pages['queue'].winfo_manager() and w._nav_selected('settings') and not w._nav_selected('queue'))
    inside = lambda wid, page: str(wid).startswith(str(w.pages[page]))
    check('S2 Settings holds the options, the setup and the language', inside(w.folder_box, 'settings') and inside(w.selftest_btn, 'settings')
          and inside(w.lang_box, 'settings') and inside(w.go, 'queue') and inside(w.tree, 'queue'))
    w.show_page('nonsense'); check('S2 an unknown page is ignored', w.page == 'settings')
    w.toggle_sidebar(); w.update()
    check('S3 the menu button hides the sidebar and saves it', not w.side.winfo_manager() and saved.get('sidebar') is False)
    w.toggle_sidebar(); w.update()
    check('S3 and shows it again, left of the pages', w.side.winfo_manager() == 'pack' and saved.get('sidebar') is True
          and w.pack_slaves().index(w.side) < w.pack_slaves().index(w.body))
    called = []
    real = w.toggle_assistant
    w.nav['assistant'].invoke(); w.update()
    check('S4 the Assistant row opens the panel and is marked', w.ai_open and w._nav_selected('assistant') and w.ai_frame.winfo_manager() == 'pack')
    w.nav['assistant'].invoke(); w.update()
    check('S4 and closes it again', not w.ai_open and not w._nav_selected('assistant'))
    w.nav['queue'].invoke(); w.update(); check('S4 the Queue row opens the Queue page', w.page == 'queue')
    w.show_page('about'); w.update()
    texts = []
    def walk(x):
        try: texts.append(str(x.cget('text')))
        except Exception: pass
        for c in x.winfo_children(): walk(c)
    walk(w.pages['about'])
    check('S5 About shows the name, version and studio', 'Seekframe' in texts and f'Version {rc.VERSION}' in texts and 'by Shadow Studio' in texts, texts[:8])
    check('S5 the links are there', all(t in texts for t in ('GitHub page', 'User guide', "What's new", 'Report a problem', 'Privacy policy', 'Shadow Studio')))
    opened = []; app.webbrowser.open = lambda u: opened.append(u)
    for b in w.pages['about'].winfo_children()[0].winfo_children():
        for c in b.winfo_children():
            if getattr(c, 'cget', None) and c.winfo_class() == 'TButton' and c.cget('text') == 'GitHub page': c.invoke()
    check('S5 GitHub page opens the app home', opened == [f'https://github.com/{updater.REPO}'], opened)
    w.show_page('queue'); w.preset.set('Draft (fast, 720p)'); w.update()
    check('S6 the options line follows the settings', w.opt_line.cget('text').startswith('Draft (fast, 720p)'), w.opt_line.cget('text'))
    w.opt_line.event_generate('<Button-1>'); w.update()
    check('S6 a click on it opens Settings', w.page == 'settings')
finally:
    w.destroy()
# S3: a saved hidden sidebar starts hidden
app.load_cfg = lambda: {'sidebar': False}
w2 = app.App(); w2.withdraw()
try:
    w2.update(); check('S3 a saved hidden sidebar starts hidden', not w2.side.winfo_manager() and w2.side_open is False)
finally:
    w2.destroy(); app.close_log(); shutil.rmtree(TMP, ignore_errors=True)
check('S0 no real dialog opened', not [c for c in no_dialogs.CALLS if c.startswith('ask')], no_dialogs.CALLS)
print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAIL: " + ", ".join(fails)}')
sys.exit(1 if fails else 0)
