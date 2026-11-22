"""Update check (updater.py + the App's update button), against a local http server - never the real GitHub.
Usage: python tests/test_updater.py      exit 0 = every check PASS, 1 = any FAIL
  U1 parse_version / is_newer   U2 latest_release picks the Setup asset, sha256 from 'digest'; draft/prerelease/no asset -> None
  U3 network error -> UpdateError   U4 download: ok, wrong sha256, wrong size (no file / .part left behind)
  U5 the real App (hidden window): newer release -> 'Update to vX' button; Update downloads and hands the file to the installer step
  U6 same version: 'Check for updates'; pressing it says latest / warns when offline / finds a release added later
Settings, log and %TEMP%\\Shadow-update of the real user are not touched (all point into a temp folder)."""
import re, hashlib, http.server, json, os, shutil, sys, tempfile, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import updater

TMP = tempfile.mkdtemp(prefix='shadow_updater_')
PAYLOAD = os.urandom(300_000); SHA = hashlib.sha256(PAYLOAD).hexdigest()
STATE = {'release': None}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == '/latest':
            b = json.dumps(STATE['release']).encode(); ct = 'application/json'
        elif self.path.startswith('/dl/'):
            b = PAYLOAD; ct = 'application/octet-stream'
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Content-Length', str(len(b))); self.end_headers()
        self.wfile.write(b)

srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{srv.server_address[1]}'
os.environ['SHADOW_UPDATE_URL'] = BASE + '/latest'

def release(tag, digest=True, size=None, name=None, **kw):
    n = name or f'Shadow-{tag.lstrip("v")}-Setup.exe'
    a = {'name': n, 'size': len(PAYLOAD) if size is None else size, 'browser_download_url': f'{BASE}/dl/{n}'}
    if digest: a['digest'] = 'sha256:' + (SHA if digest is True else digest)
    return {'tag_name': tag, 'body': 'Fixes and new things.\r\n\r\nDownload Shadow-x-Setup.exe below and run it.', 'html_url': BASE + '/page', 'draft': False, 'prerelease': False,
            'assets': [{'name': 'notes.txt', 'size': 1, 'browser_download_url': BASE + '/dl/x'}, a], **kw}

results = []
def check(name, fn):
    try: fn(); results.append((name, True, '')); print(f'PASS {name}')
    except Exception as e: results.append((name, False, str(e))); print(f'FAIL {name}: {e}\n{traceback.format_exc()}')

def u1():
    pv = updater.parse_version
    assert pv('v3.0') == (3,) and pv('3.0.1') == (3, 0, 1) and pv('2.10') == (2, 10) and pv('x') is None and pv(None) is None
    assert updater.is_newer('v3.0', '2.9') and updater.is_newer('2.10', '2.9') and not updater.is_newer('2.9', '2.9')
    assert not updater.is_newer('3.0', '3') and not updater.is_newer('2.8', '2.9') and not updater.is_newer('junk', '2.9')

def u2():
    STATE['release'] = release('v3.1'); r = updater.latest_release()
    assert r['version'] == '3.1' and r['name'] == 'Shadow-3.1-Setup.exe' and r['sha256'] == SHA and r['size'] == len(PAYLOAD), r
    assert r['notes'].startswith('Fixes and new things.')
    STATE['release'] = release('v3.1', digest=False); assert updater.latest_release()['sha256'] is None
    STATE['release'] = release('v3.1', prerelease=True); assert updater.latest_release() is None
    STATE['release'] = release('v3.1', draft=True); assert updater.latest_release() is None
    STATE['release'] = release('v3.1', name='Shadow.zip'); assert updater.latest_release() is None
    STATE['release'] = release('nightly'); assert updater.latest_release() is None
    # 3.25 rename: a release carries Seekframe-X.Y-Setup.exe plus the same file as Shadow-X.Y-Setup.exe (for copies up to 3.24)
    rel = release('v3.25', name='Shadow-3.25-Setup.exe'); new = dict(rel['assets'][1], name='Seekframe-3.25-Setup.exe',
                                                                       browser_download_url=f'{BASE}/dl/Seekframe-3.25-Setup.exe')
    rel['assets'].append(new); STATE['release'] = rel
    assert updater.latest_release()['name'] == 'Seekframe-3.25-Setup.exe', 'the new name is preferred when both are there'
    STATE['release'] = release('v3.25', name='Seekframe-3.25-Setup.exe'); assert updater.latest_release()['version'] == '3.25'
    assert re.match(r'^Shadow-[\d.]+-Setup\.exe$', 'Shadow-3.25-Setup.exe'), 'what copies up to 3.24 look for (their ASSET_RE)'

def u3():
    old = os.environ['SHADOW_UPDATE_URL']; os.environ['SHADOW_UPDATE_URL'] = 'http://127.0.0.1:1/latest'
    try:
        try: updater.latest_release(timeout=3)
        except updater.UpdateError: pass
        else: raise AssertionError('no UpdateError for an unreachable server')
    finally: os.environ['SHADOW_UPDATE_URL'] = old

def u8():
    env = updater.child_env({'PATH': 'x', '_PYI_APPLICATION_HOME_DIR': 'C:/t/_MEI1', '_PYI_PARENT_PROCESS_LEVEL': '1', '_MEIPASS2': 'y', 'TEMP': 't'})
    assert env == {'PATH': 'x', 'TEMP': 't', 'PYINSTALLER_RESET_ENVIRONMENT': '1'}, env

def u4():
    d = os.path.join(TMP, 'dl')
    STATE['release'] = release('v3.1'); r = updater.latest_release(); seen = []
    p = updater.download(r, d, progress=lambda g, t: seen.append((g, t)))
    assert open(p, 'rb').read() == PAYLOAD and seen[-1] == (len(PAYLOAD), len(PAYLOAD)), seen[-1:]
    for bad in (dict(r, sha256='0' * 64, name='bad1.exe'), dict(r, size=len(PAYLOAD) + 5, name='bad2.exe')):
        try: updater.download(bad, d)
        except updater.UpdateError: pass
        else: raise AssertionError(f'no UpdateError for {bad["name"]}')
        assert not os.path.exists(os.path.join(d, bad['name'])) and not os.path.exists(os.path.join(d, bad['name'] + '.part'))

def gui(newer):
    os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts
    import app, render_core as rc
    app.CFG = os.path.join(TMP, 'cfg.json'); app.LOG = os.path.join(TMP, 'shadow.log'); app.LOG_DIR = os.path.join(TMP, 'logs')
    os.environ['TEMP'] = os.path.join(TMP, 'temp')   # do_update downloads into %TEMP%\Shadow-update
    msgs = []
    for n in ('showwarning', 'showerror', 'showinfo'):
        setattr(app.messagebox, n, (lambda n: lambda title, text, **k: msgs.append((n, text)))(n))
    app.messagebox.askyesno = lambda title, text, **k: (msgs.append(('ask', text)), True)[1]
    ver = f'v{rc.VERSION}' if not newer else 'v99.0'
    STATE['release'] = release(ver)
    toasts = []; app.notify = lambda *x, **k: toasts.append(x)   # 3.31: never a real Windows notification from a test
    a = app.App(); a.withdraw(); ran = []
    a.run_installer = lambda p: ran.append(p)   # never start a setup in a test
    try:
        t0 = time.time()
        while time.time() - t0 < 10 and not a.update_rel: a.update(); time.sleep(0.05)
        assert a.update_btn.winfo_manager() == 'pack', 'the update button is on the About page'
        assert len(toasts) == (1 if newer else 0) and bool(a.update_bar.winfo_manager()) == newer, (toasts, a.update_bar.winfo_manager())
        if not newer:
            assert a.update_rel is None and a.update_btn.cget('text') == 'Check for updates', a.update_btn.cget('text')
            # manual check, up to date -> 'latest version'; unreachable -> a warning (both only for the button, never at start)
            assert not msgs, msgs
            a.on_update_btn(); t0 = time.time()
            while time.time() - t0 < 10 and not msgs: a.update(); time.sleep(0.05)
            assert msgs and msgs[-1][0] == 'showinfo' and 'latest version' in msgs[-1][1], msgs
            assert a.update_btn.cget('text') == 'Check for updates' and str(a.update_btn.cget('state')) == 'normal'
            old = os.environ['SHADOW_UPDATE_URL']; os.environ['SHADOW_UPDATE_URL'] = 'http://127.0.0.1:1/latest'
            try:
                a.on_update_btn(); t0 = time.time()
                while time.time() - t0 < 15 and len(msgs) < 2: a.update(); time.sleep(0.05)
            finally: os.environ['SHADOW_UPDATE_URL'] = old
            assert len(msgs) == 2 and msgs[-1][0] == 'showwarning' and 'Could not check' in msgs[-1][1], msgs
            # a release appears later: the button finds it and goes straight to the update question + download
            STATE['release'] = release('v99.0'); a.on_update_btn(); t0 = time.time()
            while time.time() - t0 < 15 and not ran: a.update(); time.sleep(0.05)
            assert ran and open(ran[0], 'rb').read() == PAYLOAD and any(k == 'ask' and 'v99.0' in t for k, t in msgs), (ran, msgs)
            return
        assert a.update_rel and a.update_btn.cget('text') == 'Update to v99.0', a.update_btn.cget('text')
        assert not msgs, f'the automatic check must not show a message box: {msgs}'
        a.do_update(); t0 = time.time()
        while time.time() - t0 < 15 and not ran: a.update(); time.sleep(0.05)
        assert ran and open(ran[0], 'rb').read() == PAYLOAD, (ran, msgs)
        assert os.path.dirname(ran[0]) == os.path.join(TMP, 'temp', 'Shadow-update'), ran[0]
        assert any(k == 'ask' and 'v99.0' in t for k, t in msgs), msgs
        ask = [t for k, t in msgs if k == 'ask'][0]
        assert 'Fixes and new things.' in ask and 'Download Shadow' not in ask, f'update window shows only what changed: {ask}'
    finally:
        try: a.after_cancel(a._poll_id); a.destroy()
        except Exception: pass

if __name__ == '__main__':
    real_cfg = os.path.join(os.path.expanduser('~'), '.shadow_renderer.json')
    before = os.path.getmtime(real_cfg) if os.path.exists(real_cfg) else None
    check('U1 parse_version / is_newer', u1)
    check('U2 latest_release asset + digest; draft/prerelease/no asset ignored', u2)
    check('U3 unreachable server -> UpdateError', u3)
    check('U8 setup gets an env without PyInstaller onefile variables', u8)
    check('U4 download ok; bad sha256 / size rejected, nothing left', u4)
    check('U5 App: newer release -> button, Update downloads to the installer step', lambda: gui(True))
    check('U6 App: same version -> "Check for updates"; button: latest / offline warning / finds a new release', lambda: gui(False))
    after = os.path.getmtime(real_cfg) if os.path.exists(real_cfg) else None
    check('U7 real settings file untouched', lambda: (_ for _ in ()).throw(AssertionError('changed')) if before != after else None)
    srv.shutdown()
    if 'app' in sys.modules: sys.modules['app'].close_log()   # shadow.log in the temp folder is open: close it first
    shutil.rmtree(TMP, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f'\n{len(results) - len(bad)}/{len(results)} PASS'); sys.exit(1 if bad else 0)
