"""3.33 cloud accounts (cloud.py + Settings > Cloud accounts + Queue > Cloud... + upload after a render), through rclone.
No real cloud and no real sign-in: an rclone 'local' remote in a temp folder stands in for an account, with a temp
config + key file (never ~/.shadow_cloud.conf). Needs rclone (PATH or %LOCALAPPDATA%\\Seekframe\\rclone); without it the
rclone parts are skipped (said so), the rest still runs.
  K1 Seekframe's rclone config is encrypted, the key file is DPAPI-protected, without the key nothing can be read
  K2 accounts / listdir / size / download / upload / sign out
  K3 cache folder (Windows-safe) and the upload folder mirrors Save to (Seekframe/Music/<scene>)
  K4 Get rclone: SHA-256 checked against SHA256SUMS (a damaged download is refused, nothing left)
  K5 Settings: rows per provider, Get rclone when missing, upload choice saved
  K6 Cloud...: a file brings its folder (scene + its song), at the top only the file; a folder adds its scenes
  K7 a finished video (+ .srt) is uploaded to Seekframe/<folders> in the chosen account
Usage: python tests/test_cloud.py     exit 0 = all PASS"""
import hashlib, io, json, os, shutil, sys, tempfile, zipfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'
import cloud

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_cloud_')
T = TMP.replace('\\', '/')
HAVE = bool(cloud.find_rclone())
rc = cloud.Rclone(conf=os.path.join(TMP, 'c.conf'), key_file=os.path.join(TMP, 'k.bin')) if HAVE else None
DATA = f'{T}/remote'   # the stand-in account's files
os.makedirs(f'{DATA}/Songs/moon', exist_ok=True); os.makedirs(f'{DATA}/Batch/a', exist_ok=True)
open(f'{DATA}/Songs/moon/moon.html', 'w').write('<canvas id="c"></canvas>'); open(f'{DATA}/Songs/moon/moon.mp3', 'wb').write(b'ID3' + b'0' * 100)
open(f'{DATA}/Songs/other.txt', 'w').write('x'); open(f'{DATA}/top.html', 'w').write('<canvas id="c"></canvas>')
open(f'{DATA}/Batch/a/a.html', 'w').write('<canvas id="c"></canvas>'); open(f'{DATA}/Batch/b.html', 'w').write('<canvas id="c"></canvas>')
try:
    if not HAVE:
        print('SKIP K1/K2/K6/K7: rclone not found (Settings > Cloud accounts > Get rclone)')
    else:
        # K1
        r = rc.run('config', 'create', 'drive', 'local')   # the stand-in "Google Drive" account
        check('K1 the config is encrypted', r.returncode == 0 and open(rc.conf).read(40).startswith('# Encrypted rclone'))
        pw = rc.env()['RCLONE_CONFIG_PASS']
        check('K1 the key file does not hold the password in clear', pw.encode() not in open(rc.key_file, 'rb').read() and len(pw) >= 32)
        import subprocess
        e = dict(os.environ); e.pop('RCLONE_CONFIG_PASS', None)
        r = subprocess.run([rc.exe, 'listremotes', '--config', rc.conf, '--ask-password=false'], capture_output=True, text=True, env=e, creationflags=cloud.NOWIN)
        check('K1 without the key rclone cannot read it', r.returncode != 0 and 'decrypt' in (r.stderr or '').lower(), r.stderr[-200:])
        # K2
        check('K2 accounts', rc.accounts() == {'drive': 'local'}, rc.accounts())
        ls = rc.listdir('drive', DATA)
        check('K2 listdir: folders first', [d['Name'] for d in ls] == ['Batch', 'Songs', 'top.html'], [d['Name'] for d in ls])
        check('K2 size', rc.size('drive', f'{DATA}/Songs') == (sum(os.path.getsize(os.path.join(r_, f_)) for r_, _, fs in os.walk(f'{DATA}/Songs') for f_ in fs), 3), rc.size('drive', f'{DATA}/Songs'))
        prog = []
        ok, msg = rc.download('drive', f'{DATA}/Songs/moon', os.path.join(TMP, 'dl'), progress=lambda a, b: prog.append((a, b)))
        check('K2 download a folder, progress reported', ok and sorted(os.listdir(os.path.join(TMP, 'dl'))) == ['moon.html', 'moon.mp3'] and prog and prog[-1][0] == prog[-1][1], (ok, msg, prog[-1:]))
        ok, msg = rc.upload(os.path.join(TMP, 'dl', 'moon.mp3'), 'drive', f'{T}/up/Seekframe/Music')
        check('K2 upload one file into a folder that does not exist yet', ok and os.listdir(f'{T}/up/Seekframe/Music') == ['moon.mp3'], msg)
    # K3
    c = cloud.cache_dir('drive', 'My Videos/what?: x', root=os.path.join(TMP, 'cache'))
    check('K3 cache folder per provider, Windows-safe', c == os.path.join(TMP, 'cache', 'Google Drive', 'My Videos', 'what__ x'), c)
    check('K3 upload folder mirrors Save to', cloud.upload_dir(r'D:\Videos', r'D:\Videos\Music\moon\moon.mp4') == 'Seekframe/Music/moon'
          and cloud.upload_dir(r'D:\Videos', r'E:\else\x\x.mp4') == 'Seekframe/x')
    # K4
    exe = b'MZ fake rclone'
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, 'w') as z: z.writestr(f'rclone-{cloud.RCLONE_VERSION}-windows-amd64/rclone.exe', exe)
    zdata = zb.getvalue(); name = f'rclone-{cloud.RCLONE_VERSION}-windows-amd64.zip'
    good = lambda url: (f'{hashlib.sha256(zdata).hexdigest()}  {name}\n'.encode() if url.endswith('SHA256SUMS') else zdata)
    p = cloud.get_rclone(dest_dir=os.path.join(TMP, 'getrc'), gh=good)
    check('K4 Get rclone: checked and unpacked', open(p, 'rb').read() == exe)
    bad = lambda url: (f'{"0" * 64}  {name}\n'.encode() if url.endswith('SHA256SUMS') else zdata)
    try: cloud.get_rclone(dest_dir=os.path.join(TMP, 'getrc2'), gh=bad); refused = False
    except RuntimeError: refused = True
    check('K4 a damaged download is refused and nothing is left', refused and not os.path.exists(os.path.join(TMP, 'getrc2', 'rclone.exe')))
    # K5..K7 in the window
    import app, no_dialogs
    no_dialogs.block(app)
    app.LOG = os.path.join(TMP, 'l.log'); app.close_log()
    saved = {}; app.save_cfg = lambda d: saved.update(d)
    app.App.start_update_check = lambda *a, **k: None
    app.App.refresh_cloud = lambda self, *a, **k: None   # the window never asks the real rclone config in this test
    w = app.App(); w.withdraw()
    try:
        w.update()
        w.show_cloud(None, {}); w.update()
        check('K5 no rclone: Get rclone shown, sign-in buttons off', w.rclone_btn.winfo_manager() == 'pack' and str(w.cloud_rows['drive']['btn'].cget('state')) == 'disabled')
        w.show_cloud(True, {'drive': 'me@example.com'}); w.update()
        check('K5 signed in: e-mail shown, Sign out, the others Sign in', w.cloud_rows['drive']['st'].cget('text') == 'me@example.com'
              and w.cloud_rows['drive']['btn'].cget('text') == 'Sign out' and w.cloud_rows['dropbox']['btn'].cget('text') == 'Sign in' and not w.rclone_btn.winfo_manager())
        check('K5 upload choices: Off + signed-in accounts', list(w.cloud_up_box.cget('values')) == ['Off', 'Google Drive'])
        w.cloud_up_box.set('Google Drive'); w.on_cloud_up()
        check('K5 the upload choice is saved', w.cloud_up == 'drive' and saved.get('cloud_upload') == 'drive')
        w.show_cloud(True, {}); check('K5 signed out: upload goes back to Off', w.cloud_up == '' and w.cloud_up_box.get() == 'Off')
        if HAVE:
            cache = os.path.join(TMP, 'cache'); real_cache = cloud.cache_dir
            cloud.cache_dir = lambda key, path, root=None: real_cache(key, path, root=cache)
            try:
                d = app.CloudDialog(w, rc=rc, accounts={'drive': 'local'}); d.top.withdraw()
                d.open(f'{DATA}/Songs/moon', wait=True)
                check('K6 the dialog lists a folder', [x['Name'] for x in d.items] == ['moon.html', 'moon.mp3'])
                d.tree.selection_set('0'); w.update()
                got = d.add(wait=True)
                local = os.path.join(real_cache('drive', f'{DATA}/Songs/moon', root=cache))
                check('K6 a scene brings its folder (the song next to it) and is added to the queue',
                      sorted(os.listdir(local)) == ['moon.html', 'moon.mp3'] and got == [os.path.normpath(os.path.join(local, 'moon.html'))], (got, os.listdir(local) if os.path.isdir(local) else None))
                d.open(DATA, wait=True); d.tree.selection_set(str([x['Name'] for x in d.items].index('top.html'))); w.update()
                d.path = ''; d.items = [dict(x, Name=x['Name']) for x in d.items]   # the top of an account
                calls = []; real_copy = rc.copy
                rc.copy = lambda src, dst, **k: (calls.append((src, dst, k.get('one_file'))), (True, 'ok'))[1]
                try: d.add(wait=True)
                finally: rc.copy = real_copy
                check('K6 at the top of an account only the file comes (never the whole drive)', len(calls) == 1 and calls[0][2] is True and calls[0][0] == 'drive:top.html', calls)
                d.path = DATA; d.open(DATA, wait=True); d.tree.selection_set(str([x['Name'] for x in d.items].index('Batch'))); w.update()
                got = d.add(wait=True, ask=lambda *a: True)
                check('K6 a folder: downloaded, its scenes (and subfolders, when asked) added', sorted(os.path.basename(g) for g in got) == ['a.html', 'b.html'], got)
                d.close()
            finally:
                cloud.cache_dir = real_cache
            # K7
            out = os.path.join(TMP, 'Save to'); vid = os.path.join(out, 'Music', 'moon'); os.makedirs(vid)
            open(os.path.join(vid, 'moon.mp4'), 'wb').write(b'\x00' * 2000); open(os.path.join(vid, 'moon.srt'), 'w').write('1')
            w.cloud_up = 'drive'
            real_dir = cloud.upload_dir; cloud.upload_dir = lambda od, m: f'{T}/acct/' + real_dir(od, m)
            try: w.cloud_upload(os.path.join(vid, 'moon.mp4'), out, rc=rc, wait=True)
            finally: cloud.upload_dir = real_dir
            dest = f'{T}/acct/Seekframe/Music/moon'
            check('K7 the video and its subtitles go to Seekframe/Music/moon', os.path.isdir(dest) and sorted(os.listdir(dest)) == ['moon.mp4', 'moon.srt'], os.listdir(dest) if os.path.isdir(dest) else None)
            w.update(); w.poll() if hasattr(w, 'poll') else None
        check('K0 no real dialog opened', not [c for c in no_dialogs.CALLS if c.startswith('ask')], no_dialogs.CALLS)
    finally:
        try: w.destroy()
        except Exception: pass
        app.close_log()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAIL: " + ", ".join(fails)}')
sys.exit(1 if fails else 0)
