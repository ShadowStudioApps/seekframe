"""The 3.28 window layout: sidebar + pages (Queue / Settings / About). No real dialog opens (no_dialogs).
  S1 the window opens on the Queue page; the old widgets are all there (tree, Render, status, update button, setup bar)
  S2 show_page switches pages and marks the sidebar row; Settings holds the options, the setup and the language
  S3 the menu button hides / shows the sidebar and the choice is saved (setting 'sidebar'); a saved False starts it hidden
  S4 sidebar rows run their actions (Assistant toggles the panel and is marked while open)
  S5 About shows the version and the links point to the app's GitHub home
  S6 the render options are on the Queue page (3.30); Save to / Folder in Settings
  S11 (3.31) a new version shows a bar + one Windows notification per version; S12 storage places (This PC, clouds, NAS)
  S8 (3.32) AI connections (a row per AI app, tick = connect, notifications) and the AI for the AI jobs; S9 Check access for local / NAS / cloud folders; S10 AI account (subscription default, own API key
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
app.load_cfg = lambda: {}   # never the owner's own settings (his AI choice, theme, ...)
app.App.start_update_check = lambda *a, **k: None
w = app.App()
try:
    w.update()
    check('S1 opens on the Queue page', w.page == 'queue' and w.page_title.cget('text') == 'Queue')
    check('S1 the old widgets are all still there', all(hasattr(w, n) for n in ('tree', 'go', 'stop', 'stop_cur', 'status', 'bar', 'eta_lbl', 'yt_btn',
          'check_btn', 'narr_btn', 'update_btn', 'selftest_btn', 'env_lbls', 'folder_box', 'lang_box', 'theme_btn', 'ai_btn', 'proj_btn')))
    check('S1 Check for updates lives on the About page only (3.31: not in the sidebar)', w.update_btn.winfo_manager() == 'pack'
          and str(w.update_btn).startswith(str(w.pages['about'])) and not [c for c in w.side.winfo_children() if c.winfo_class() == 'TButton'])
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
    w.geometry('+0+0'); w.update()
    need = w.winfo_reqwidth() + w.ai_frame.winfo_reqwidth() + 14; scr = w.winfo_screenwidth() - 8
    w.geometry(f'{min(scr, max(need + 40, w.winfo_reqwidth()))}x900'); w.update(); w0 = w.winfo_width()
    w.nav['assistant'].invoke(); w.update()
    check('S4 opening the Assistant in a wide enough window does not resize it (3.31: no squeezed table)',
          w.winfo_width() == w0 if w0 >= need else w.winfo_width() <= w.winfo_screenwidth(), f'{w0} -> {w.winfo_width()} (needs {need}, screen {scr + 8})')
    check('S4 the Assistant row opens the panel and is marked', w.ai_open and w._nav_selected('assistant') and w.ai_frame.winfo_manager() == 'pack')
    w.nav['assistant'].invoke(); w.update()
    check('S4 and closes it again, same window width', not w.ai_open and not w._nav_selected('assistant') and w.winfo_width() == w0, w.winfo_width())
    w.geometry(f'{w.winfo_reqwidth()}x900'); w.update(); n0 = w.winfo_width()
    w.toggle_assistant(); w.update()
    fits = need <= scr
    check('S4 a narrow window grows once to fit the panel (pages keep their width when the screen is wide enough), never past the screen',
          w.winfo_width() > n0 and w.winfo_width() <= w.winfo_screenwidth() and (not fits or w.body.winfo_width() >= w.body.winfo_reqwidth() - 2),
          f'{n0} -> {w.winfo_width()}, body {w.body.winfo_width()}/{w.body.winfo_reqwidth()}, screen {scr + 8}')
    w.toggle_assistant(); w.update()
    check('S4 and gives the room back on close', abs(w.winfo_width() - n0) <= 2, f'{n0} -> {w.winfo_width()}')
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
    opened.clear(); w.studio_lbl.event_generate('<Button-1>'); w.update()
    check('S5 the Shadow Studio mark sits at the bottom of the sidebar and opens the studio page', w.studio_logo is not None
          and w.studio_box.winfo_manager() == 'pack' and opened == ['https://github.com/' + updater.REPO.split('/')[0]], opened)
    # S6 (3.30): the render options are on the Queue page again
    combos = [c for c in w.pages['queue'].winfo_children() if c.winfo_class() == 'TLabelframe' and c.cget('text') == 'Options']
    names = [x.cget('text') for x in combos[0].winfo_children() if x.winfo_class() == 'TLabel'] if combos else []
    check('S6 Quality, Format, Sound, Capture and Blender are on the Queue page', combos and all(n in names for n in ('Quality', 'Format', 'Sound', 'Capture', 'Blender')), names)
    check('S6 Save to and Folder stay in Settings', str(w.folder_box).startswith(str(w.pages['settings'])))
    # S11 (3.31) a new version: a bar under the header + one Windows notification per version
    toasts = []; real_notify = app.notify; app.notify = lambda *a, **k: toasts.append(a)
    try:
        check('S11 no update bar without an update', not w.update_bar.winfo_manager())
        rel = dict(version='99.0', notes='x', page='https://example.invalid/r')
        w.show_update(rel); w.update()
        check('S11 the update bar shows the new version', w.update_bar.winfo_manager() == 'pack' and '99.0' in w.update_lbl.cget('text'))
        check('S11 a Windows notification once, remembered in settings', len(toasts) == 1 and saved.get('update_seen') == '99.0', (toasts, saved.get('update_seen')))
        w.hide_update_bar(); w.show_update(rel); w.update()
        check('S11 the same version again: bar back, no second notification', w.update_bar.winfo_manager() == 'pack' and len(toasts) == 1)
        w.hide_update_bar(); w.update(); check('S11 Later hides the bar', not w.update_bar.winfo_manager())
        check('S11 the About button says Update to v99.0', w.update_btn.cget('text') == 'Update to v99.0')
    finally:
        app.notify = real_notify; w.update_rel = None
    # S12 storage places: This PC + NAS (3.34: no cloud-app buttons)
    home = os.path.join(TMP, 'home'); os.makedirs(os.path.join(home, 'Dropbox')); os.makedirs(os.path.join(home, 'Box'))
    pl = app.storage_places({'USERPROFILE': home})
    names = [l for l, _ in pl]
    check('S12 only This PC (the Videos folder), no cloud-app buttons', pl == [('This PC', os.path.join(home, 'Videos'))], pl)
    check('S12 the Settings page has This PC + NAS + Check access', [b.cget('text') for b in w.cloud_btns] == ['This PC', 'Network drive (NAS)...']
          and w.storage_btn.winfo_manager() == 'grid')
    picked = os.path.join(TMP, 'nas share'); os.makedirs(picked)
    r = w.use_storage('nas', pick=lambda **k: picked)
    check('S12 NAS asks for the folder and uses it as is', w.out_dir.get() == os.path.normpath(picked) and r and r['ok'], (w.out_dir.get(), r))
    check('S12 a cloud app not found: Cancel changes nothing', w.use_storage(None, 'Google Drive', pick=lambda **k: '') is None and w.out_dir.get() == os.path.normpath(picked))
    w.use_storage(os.path.join(home, 'Dropbox')); check('S12 a found cloud saves in the Seekframe folder of the cloud', w.out_dir.get() == os.path.join(home, 'Dropbox', 'Seekframe'))
    # S8 (3.32) AI connections: a row per AI app on this PC, tick = connected, a notification when one connects / starts using it
    toasts = []; T = lambda *a, **k: toasts.append(a)
    mk = lambda key, inst, conn, use: dict(key=key, name=app.ai_clients.BY_KEY[key].name, installed=inst, connected=conn, using=use)
    w._using_prev = None
    st = [mk('claude_code', True, True, 2), mk('claude_desktop', True, False, 0), mk('cursor', False, False, 0), mk('vscode', False, False, 0),
          mk('windsurf', False, False, 0), mk('gemini', True, False, 0), mk('codex', True, False, 0)]
    w.show_mcp(st, toast=T); w.update()
    r = w.cli_rows
    check('S8 Claude Code: ticked, green, "In use now (2)"', r['claude_code']['var'].get() and str(r['claude_code']['dot'].cget('foreground')) == '#3fb950'
          and r['claude_code']['st'].cget('text') == 'In use now (2)')
    check('S8 Claude Desktop / Gemini / Codex shown, not ticked', all(r[k]['cb'].winfo_manager() == 'grid' and not r[k]['var'].get() for k in ('claude_desktop', 'gemini', 'codex')))
    check('S8 apps not on this PC (3.34): their row stays, tick box off, "Not installed" + Copy install command',
          r['cursor']['cb'].winfo_manager() == 'grid' and r['cursor']['cb'].instate(['disabled']) and r['cursor']['st'].cget('text') == 'Not installed'
          and r['cursor']['inst'].winfo_manager() == 'grid' and not r['claude_code']['inst'].winfo_manager())
    clip = []; w.clipboard_clear = lambda: clip.clear(); w.clipboard_append = lambda x: clip.append(x)   # never the owner's real clipboard
    cmd = w.copy_install('cursor'); w.update()
    check('S8 Copy install command puts the winget command on the clipboard and says what to do', cmd == 'winget install -e --id Anysphere.Cursor'
          and clip == [cmd] and cmd in r['cursor']['st'].cget('text'))
    w.show_mcp(st, toast=T); check('S8 a re-check keeps the "copied" hint', cmd in r['cursor']['st'].cget('text'))
    check('S8 no notification on the first check', toasts == [])
    st[1] = mk('claude_desktop', True, True, 1); w.show_mcp(st, toast=T); w.update()
    check('S8 an app that starts using Seekframe: one notification', len(toasts) == 1 and 'Claude Desktop is now using Seekframe.' in toasts[0], toasts)
    w.show_mcp(st, toast=T); check('S8 still in use: no second notification', len(toasts) == 1)
    home = os.path.join(TMP, 'aihome')
    r['cursor']['var'].set(True); w.on_client('cursor', wait=True, toast=T, home=home); w.update()
    w.update(); import time as _t; _t.sleep(0.3); w.update()
    cfg = os.path.join(home, '.cursor', 'mcp.json')
    check('S8 ticking an app writes its config and notifies', os.path.isfile(cfg) and 'shadow' in open(cfg).read() and r['cursor']['var'].get()
          and any('Cursor can use Seekframe now' in x[1] for x in toasts), (os.path.isfile(cfg), toasts))
    r['cursor']['var'].set(False); w.on_client('cursor', wait=True, toast=T, home=home); w.update(); _t.sleep(0.3); w.update()
    check('S8 un-ticking removes it again', 'shadow' not in open(cfg).read() and not r['cursor']['var'].get())
    # which AI does Seekframe's own AI buttons
    check('S8 Claude Code does the AI jobs by default', w.engine.get() == 'claude' and app.ai_tasks.ENGINE == 'claude', (w.engine.get(), app.ai_tasks.ENGINE, w.cfg_ai))
    n0 = len(toasts)
    w.engine.set('gemini'); ok = w.on_engine(ready=lambda c: (False, 'not signed in'), toast=T)
    check('S8 an AI that is not ready is refused, the choice stays', ok is False and w.engine.get() == 'claude' and app.ai_tasks.ENGINE == 'claude'
          and 'not signed in' in w.engine_lbl.cget('text') and len(toasts) == n0)
    try:
        w.engine.set('gemini'); ok = w.on_engine(ready=lambda c: (True, 'ok'), toast=T)
        check('S8 switching to Gemini: saved, used by the AI jobs, notified', ok and app.ai_tasks.ENGINE == 'gemini' and saved['ai'].get('engine') == 'gemini'
              and len(toasts) == n0 + 1 and 'Gemini CLI' in toasts[-1][1] and 'Gemini CLI' in w.engine_lbl.cget('text'))
    finally:
        w.engine.set('claude'); w.on_engine(ready=lambda c: (True, 'ok'), toast=T)
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
        w.key_var.set('not a key'); check('S10 a wrong key is refused', w.save_key(ask=lambda *a: False) is False and not os.path.exists(assistant.KEY_FILE))
        key = 'sk-ant-api03-' + 'k' * 40 + 'WXYZ'; w.key_var.set(key)
        check('S10 a key is saved encrypted and cleared from the screen', w.save_key(ask=lambda *a: False) and w.key_var.get() == ''
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
        # S10 (3.34) the sign-in row follows the AI chosen above: Gemini gets its own account / API key choice
        real_gk = app.ai_tasks.GEMINI_KEY_FILE; app.ai_tasks.GEMINI_KEY_FILE = os.path.join(TMP, 'gkey.bin')
        try:
            w.engine.set('gemini'); w.on_engine(ready=lambda c: (True, 'ok'), toast=lambda *a: None)
            check('S10 Gemini chosen: the row says how Gemini signs in, its own account by default', 'Gemini CLI' in w.auth_title.cget('text')
                  and w.ai_auth.get() == 'subscription' and app.ai_tasks.GEMINI_AUTH == 'account')
            os.remove(assistant.KEY_FILE) if os.path.exists(assistant.KEY_FILE) else None
            ak = 'sk-ant-api03-' + 'a' * 40 + 'ANTH'; w.key_var.set(ak)
            check('S10 (3.34) an Anthropic key typed while Gemini is chosen is recognised and kept for Claude Code',
                  w.save_key(ask=lambda *a: False) and assistant.load_api_key() == ak and not os.path.exists(app.ai_tasks.GEMINI_KEY_FILE)
                  and 'Anthropic' in w.key_lbl.cget('text') and 'Claude Code' in w.key_lbl.cget('text'), w.key_lbl.cget('text'))
            w.key_var.set('sk-proj-' + 'o' * 40); check('S10 an OpenAI key is refused with the reason', w.save_key(ask=lambda *a: False) is False and 'OpenAI' in w.key_lbl.cget('text'))
            w.key_var.set('hello'); check('S10 an unknown key is refused, saying what keys look like', w.save_key(ask=lambda *a: False) is False and 'sk-ant-' in w.key_lbl.cget('text') and 'AIza' in w.key_lbl.cget('text'))
            gk = 'AIza' + 'g' * 35; w.key_var.set(gk)
            check('S10 a Google AI Studio key is saved encrypted', w.save_key(ask=lambda *a: False) and gk.encode() not in open(app.ai_tasks.GEMINI_KEY_FILE, 'rb').read()
                  and app.ai_tasks.load_gemini_key() == gk and w.key_var.get() == '')
            w.ai_auth.set('api_key'); w.on_ai_auth(ask=lambda *a: True)
            check('S10 Gemini API key mode saved apart from Claude\'s', app.ai_tasks.GEMINI_AUTH == 'api_key' and saved['ai'].get('gemini_auth') == 'api_key'
                  and assistant.AUTH_MODE == 'subscription')
            w.show_account('gemini', (True, 'signed in with Google')); w.ai_auth.set('subscription'); w.on_ai_auth()
            check('S10 sign-in mode shows the AI\'s own sign-in state', 'signed in with Google' in w.key_lbl.cget('text'))
            ran = []
            check('S10 Sign in... opens the AI\'s own sign-in in a console window', w.ai_login(popen=lambda c, **k: ran.append((c, k))) and ran
                  and ran[0][1].get('creationflags') == getattr(app.subprocess, 'CREATE_NEW_CONSOLE', 0) and 'Re-check' in w.key_lbl.cget('text'))
            w.ai_auth.set('api_key'); w.on_ai_auth(ask=lambda *a: True)
            w.remove_key()
            check('S10 Remove key (Gemini): file gone, back to its own sign-in', not os.path.exists(app.ai_tasks.GEMINI_KEY_FILE) and app.ai_tasks.GEMINI_AUTH == 'account')
            w.engine.set('claude'); w.on_engine(ready=lambda c: (True, 'ok'), toast=lambda *a: None)
            check('S10 back to Claude Code: the row shows Claude\'s choice again', 'Claude Code' in w.auth_title.cget('text') and w.ai_auth.get() == 'subscription')
            ran = []; real_cmd = app.ai_tasks.login_command
            app.ai_tasks.login_command = lambda e: ['claude', 'auth', 'login'] if e == 'claude' else None
            try: w.ai_login(popen=lambda c, **k: ran.append(c))
            finally: app.ai_tasks.login_command = real_cmd
            check('S10 Sign in... for Claude Code runs claude auth login', ran == [['claude', 'auth', 'login']], ran)
        finally:
            app.ai_tasks.GEMINI_KEY_FILE = real_gk; app.ai_tasks.GEMINI_AUTH = 'account'; app.ai_tasks.ENGINE = 'claude'
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
