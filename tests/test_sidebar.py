"""The 3.28 window layout: sidebar + pages (Queue / Settings / About). No real dialog opens (no_dialogs).
  S1 the window opens on the Queue page; the old widgets are all there (tree, Render, status, update button, setup bar)
  S2 show_page switches pages and marks the sidebar row; Settings holds the options, the setup and the language
  S3 the menu button hides / shows the sidebar and the choice is saved (setting 'sidebar'); a saved False starts it hidden
  S4 sidebar rows run their actions (Assistant toggles the panel and is marked while open)
  S5 About shows the version and the links point to the app's GitHub home
  S6 the render options are on the Queue page (3.30); Save to / Folder in Settings
  S8 Claude (MCP) lights; S9 Check access for local / NAS / cloud folders; S10 AI account (subscription default, own API key
     encrypted with DPAPI, asks before paid use, passed to Claude Code only in that mode)
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
w = app.App()
try:
    w.update()
    check('S1 opens on the Queue page', w.page == 'queue' and w.page_title.cget('text') == 'Queue')
    check('S1 the old widgets are all still there', all(hasattr(w, n) for n in ('tree', 'go', 'stop', 'stop_cur', 'status', 'bar', 'eta_lbl', 'yt_btn',
          'check_btn', 'narr_btn', 'update_btn', 'selftest_btn', 'env_lbls', 'folder_box', 'lang_box', 'theme_btn', 'ai_btn', 'proj_btn')))
    check('S1 the update button stays in the window (sidebar)', w.update_btn.winfo_manager() == 'pack' and str(w.update_btn.master) == str(w.side))
    w.show_page('settings'); w.update()
    check('S2 Settings page shown, row marked', w.page == 'settings' and w.page_title.cget('text') == 'Settings'
          and w._nav_selected('settings') and not w._nav_selected('queue'))
    inside = lambda wid, page: str(wid).startswith(str(w.pages[page]))
    check('S2 Settings holds the options, the setup and the language', inside(w.folder_box, 'settings') and inside(w.selftest_btn, 'settings')
          and inside(w.lang_box, 'settings') and inside(w.go, 'queue') and inside(w.tree, 'queue'))
    w.show_page('nonsense'); check('S2 an unknown page is ignored', w.page == 'settings')
    w.toggle_sidebar(); w.update()
    check('S3 the menu button hides the sidebar and saves it', not w.side.winfo_manager() and saved.get('sidebar') is False)
    w.toggle_sidebar(); w.update()
    check('S3 and shows it again, left of the pages', w.side.winfo_manager() == 'pack' and saved.get('sidebar') is True
          and w.pack_slaves().index(w.side) < w.pack_slaves().index(w.body))
    import time as _t
    t0 = _t.perf_counter()
    for i in range(30): w.show_page(('settings', 'about', 'queue')[i % 3]); w.update()
    ms = (_t.perf_counter() - t0) * 1000 / 30
    check('S7 switching pages stays under 150 ms on average (3.30 measured ~95 ms; the theme draws every widget on show)', ms < 150, f'{ms:.1f} ms')
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
    # S6 (3.30): the render options are on the Queue page again
    combos = [c for c in w.pages['queue'].winfo_children() if c.winfo_class() == 'TLabelframe' and c.cget('text') == 'Options']
    names = [x.cget('text') for x in combos[0].winfo_children() if x.winfo_class() == 'TLabel'] if combos else []
    check('S6 Quality, Format, Sound, Capture and Blender are on the Queue page', combos and all(n in names for n in ('Quality', 'Format', 'Sound', 'Capture', 'Blender')), names)
    check('S6 Save to and Folder stay in Settings', str(w.folder_box).startswith(str(w.pages['settings'])))
    # S8 Claude (MCP) lights
    w.show_mcp(dict(claude=True, registered=True, running=2)); w.update()
    check('S8 MCP connected: three green lights, count shown', all(str(w.mcp_lbls[k][0].cget('foreground')) == '#3fb950' for k in ('claude', 'registered', 'running'))
          and w.mcp_lbls['running'][1].cget('text') == 'Connected now (2)')
    w.show_mcp(dict(claude=True, registered=False, running=0)); w.update()
    check('S8 not set up: red light, "Not connected now"', str(w.mcp_lbls['registered'][0].cget('foreground')) == '#f85149'
          and w.mcp_lbls['running'][1].cget('text') == 'Not connected now')
    cj = os.path.join(TMP, 'claude.json'); open(cj, 'w').write('{"mcpServers": {"shadow": {"command": "python"}}}')
    st = app.mcp_status(claude_json=cj, ps=lambda *a, **k: type('R', (), {'stdout': '3' + chr(10)})())
    check('S8 mcp_status reads the setup and counts the server processes', st['registered'] and st['running'] == 3, st)
    # S9 storage: a folder that works, one that cannot be written
    ok = app.storage_check(os.path.join(TMP, 'videos out'))
    check('S9 Check access: a writable folder is OK with free space', ok['ok'] and ok['kind'] == 'local' and ok['free_gb'] > 0, ok)
    bad = app.storage_check(os.path.join(TMP, 'file.txt', 'sub')) if open(os.path.join(TMP, 'file.txt'), 'w').close() is None else None
    check('S9 a path that cannot be a folder is reported, never raised', bad and not bad['ok'] and bad['message'], bad)
    check('S9 a server-share address (two backslashes) is a network drive', app.storage_kind('\\\\NAS\\Videos') == 'network')
    # S10 AI account: subscription by default, the API key asks first, the key is stored encrypted and passed to Claude Code
    import assistant
    real_key = assistant.KEY_FILE; assistant.KEY_FILE = os.path.join(TMP, 'key.bin')   # never the user's real key file
    try:
        check('S10 subscription is the default', w.ai_auth.get() == 'subscription' and assistant.AUTH_MODE == 'subscription')
        w.ai_auth.set('api_key'); w.on_ai_auth(ask=lambda *a: False)
        check('S10 saying No to the cost question keeps the subscription', w.ai_auth.get() == 'subscription' and assistant.AUTH_MODE == 'subscription')
        w.key_var.set('not a key'); check('S10 a wrong key is refused', w.save_key() is False and not os.path.exists(assistant.KEY_FILE))
        key = 'sk-ant-api03-' + 'k' * 40 + 'WXYZ'; w.key_var.set(key)
        check('S10 a key is saved encrypted and cleared from the screen', w.save_key() and w.key_var.get() == ''
              and key.encode() not in open(assistant.KEY_FILE, 'rb').read() and assistant.load_api_key() == key)
        w.ai_auth.set('api_key'); w.on_ai_auth(ask=lambda *a: True)
        env = assistant.clean_env({'PATH': 'x', 'CLAUDE_CODE_USE_BEDROCK': '1'})
        ok_, msg = assistant.check_ready('claude')
        check('S10 API key mode: Claude Code gets the key, cloud switches still removed', env.get('ANTHROPIC_API_KEY') == key
              and 'CLAUDE_CODE_USE_BEDROCK' not in env and ok_ and 'WXYZ' in msg and key not in msg, msg)
        check('S10 the screen shows only a hint of the key', 'WXYZ' in w.key_lbl.cget('text') and key not in w.key_lbl.cget('text'))
        w.remove_key()
        check('S10 Remove key: file gone, back to the subscription, no key passed', not os.path.exists(assistant.KEY_FILE)
              and assistant.AUTH_MODE == 'subscription' and 'ANTHROPIC_API_KEY' not in assistant.clean_env({'ANTHROPIC_API_KEY': 'sk-ant-x'}))
    finally:
        assistant.KEY_FILE = real_key; assistant.AUTH_MODE = 'subscription'
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
