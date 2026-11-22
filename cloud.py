"""Cloud accounts without the providers' desktop apps (3.33): sign in to Google Drive, OneDrive, Dropbox, Box or pCloud in
the browser, browse and download files (scenes, songs, videos) and upload finished videos. All through rclone (free,
open source, MIT; https://rclone.org), started as a hidden program; Seekframe never sees a password.

- rclone itself: on PATH, or %LOCALAPPDATA%\\Seekframe\\rclone\\rclone.exe (Settings > Cloud accounts > Get rclone puts it
  there: the official GitHub release, SHA-256 checked against the release's SHA256SUMS).
- Seekframe's own rclone config: ~/.shadow_cloud.conf (never rclone's default one, so the owner's own rclone setup is not
  touched), ENCRYPTED by rclone with a random password; that password is kept with Windows DPAPI in
  ~/.shadow_cloud_key.bin (only this Windows account can read it) and handed to rclone in RCLONE_CONFIG_PASS.
- One account per provider; the rclone remote name is the provider key ('drive', 'onedrive', ...).
- Sign in = `rclone config create <key> <type>`: rclone opens the provider's sign-in page in the browser and waits for it
  (its own OAuth app, local redirect to 127.0.0.1:53682). Sign out = `rclone config disconnect` (revokes where the
  provider allows it) + `rclone config delete`.
Measured with rclone 1.76.0: an encrypted config cannot be read without the password ("unable to decrypt
configuration"); `config create` prints the new section (with its token) on stdout, so that output is never logged."""
import json, os, re, secrets, shutil, subprocess, threading

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
HOME = os.path.expanduser('~')
CONF = os.path.join(HOME, '.shadow_cloud.conf')
KEY = os.path.join(HOME, '.shadow_cloud_key.bin')
RCLONE_VERSION = 'v1.76.0'   # what Get rclone downloads (tested)

PROVIDERS = [  # key, label, rclone type, extra config
    ('drive', 'Google Drive', 'drive', ['scope=drive']),
    ('onedrive', 'OneDrive', 'onedrive', []),
    ('dropbox', 'Dropbox', 'dropbox', []),
    ('box', 'Box', 'box', []),
    ('pcloud', 'pCloud', 'pcloud', []),
]
LABEL = {k: l for k, l, _, _ in PROVIDERS}
SCENE_EXT = ('.html', '.htm', '.blend')
MEDIA_EXT = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')


def local_rclone_dir(env=None):
    env = os.environ if env is None else env
    return os.path.join(env.get('LOCALAPPDATA') or os.path.join(HOME, 'AppData', 'Local'), 'Seekframe', 'rclone')


def find_rclone(which=shutil.which, env=None):
    p = os.path.join(local_rclone_dir(env), 'rclone.exe')
    if os.path.isfile(p): return p
    return which('rclone')


# ---------------------------------------------------------------- the config password (DPAPI) and the encrypted config
def _dpapi(data, decrypt=False):
    import assistant
    return assistant._dpapi(data, decrypt)


def password(key_file=None, protect=None):
    """The random password of Seekframe's rclone config; made once, kept DPAPI-encrypted."""
    key_file = key_file or KEY; protect = protect or _dpapi
    if os.path.isfile(key_file):
        with open(key_file, 'rb') as f: return protect(f.read(), True).decode('utf-8')
    pw = secrets.token_urlsafe(32)
    with open(key_file, 'wb') as f: f.write(protect(pw.encode('utf-8')))
    return pw


class Rclone:
    """rclone with Seekframe's own encrypted config. run() for short commands, popen() for long ones (sign-in, copy)."""

    def __init__(self, exe=None, conf=None, key_file=None, protect=None):
        self.exe = exe or find_rclone(); self.conf = conf or CONF; self.key_file = key_file or KEY; self.protect = protect

    def ok(self): return bool(self.exe and os.path.isfile(self.exe))

    def env(self):
        e = dict(os.environ); e['RCLONE_CONFIG_PASS'] = password(self.key_file, self.protect)
        e.pop('RCLONE_CONFIG', None); return e

    def args(self, *a):
        return [self.exe] + list(a) + ['--config', self.conf, '--ask-password=false']

    def run(self, *a, timeout=60):
        self.ensure_encrypted()
        return subprocess.run(self.args(*a), capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=timeout, env=self.env(), creationflags=NOWIN)

    def popen(self, *a, **kw):
        self.ensure_encrypted()
        return subprocess.Popen(self.args(*a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                env=self.env(), creationflags=NOWIN, **kw)

    def ensure_encrypted(self):
        """A new config is made encrypted from the start (rclone reads the new password from its password command, which
        prints it from an environment variable: the password never appears on a command line)."""
        if os.path.isfile(self.conf):
            with open(self.conf, encoding='utf-8', errors='replace') as f:
                if f.read(64).startswith('# Encrypted rclone'): return
        e = self.env(); e['SF_CLOUD_PW'] = e.pop('RCLONE_CONFIG_PASS')
        cmd = 'powershell -NoProfile -NonInteractive -Command [Console]::Out.Write($env:SF_CLOUD_PW)'
        r = subprocess.run([self.exe, 'config', 'encryption', 'set', '--config', self.conf, '--password-command', cmd],
                           capture_output=True, text=True, timeout=60, env=e, creationflags=NOWIN)
        if r.returncode != 0: raise RuntimeError('rclone could not encrypt its settings: ' + (r.stderr or '').strip()[-200:])

    # ------------------------------------------------------------ accounts
    def accounts(self):
        """{provider key: rclone type} of the signed-in accounts."""
        if not os.path.isfile(self.conf): return {}
        r = self.run('listremotes', '--long')
        out = {}
        for line in (r.stdout or '').splitlines():
            m = re.match(r'^([^:]+):\s+(\S+)', line.strip())
            if m: out[m.group(1)] = m.group(2)
        return out

    def who(self, key):
        """The signed-in user's e-mail / name when the provider tells it, else ''."""
        try:
            r = self.run('config', 'userinfo', key + ':', '--json', timeout=30)
            d = json.loads(r.stdout or '{}')
            return d.get('Email') or d.get('Login') or d.get('Name') or ''
        except Exception:
            return ''

    def sign_in(self, key, on_url=lambda url: None, cancel=None):
        """Open the provider's sign-in page and wait (max 10 min). Returns (ok, message). The token never leaves rclone."""
        _, label, typ, extra = next(p for p in PROVIDERS if p[0] == key)
        p = self.popen('config', 'create', key, typ, *extra)
        self._proc = p
        url = []
        def read_err():   # rclone prints the local auth link ("...http://127.0.0.1:53682/auth?state=...") on stderr
            for raw in iter(p.stderr.readline, b''):
                m = re.search(rb'(http://127\.0\.0\.1:\d+/auth\?state=\S+)', raw)
                if m and not url: url.append(m.group(1).decode()); on_url(url[0])
        t = threading.Thread(target=read_err, daemon=True); t.start()
        try:
            for raw in iter(p.stdout.readline, b''):   # the new section incl. its token: read and dropped, never logged
                m = re.search(rb'(http://127\.0\.0\.1:\d+/auth\?state=\S+)', raw)
                if m and not url: url.append(m.group(1).decode()); on_url(url[0])
            code = p.wait(timeout=600)
        except subprocess.TimeoutExpired:
            kill(p); return False, 'the sign-in took longer than 10 minutes'
        finally:
            self._proc = None
        if cancel and cancel.is_set(): self.sign_out(key); return False, 'cancelled'
        if code != 0 or key not in self.accounts(): self.forget(key); return False, f'{label} sign-in did not finish'
        return True, label

    def forget(self, key):
        if os.path.isfile(self.conf): self.run('config', 'delete', key)

    def sign_out(self, key):
        """Revoke (where the provider supports it) and delete the account from Seekframe's config."""
        try: self.run('config', 'disconnect', key + ':', timeout=30)
        except Exception: pass
        self.forget(key)
        return key not in self.accounts()

    # ------------------------------------------------------------ files
    def listdir(self, key, path=''):
        """[dict(Name, IsDir, Size, ModTime, Path)] in one folder, folders first."""
        r = self.run('lsjson', f'{key}:{path}', '--max-depth', '1', timeout=120)
        if r.returncode != 0: raise RuntimeError((r.stderr or '').strip().splitlines()[-1:] or ['rclone lsjson failed'])
        items = json.loads(r.stdout or '[]')
        return sorted(items, key=lambda d: (not d.get('IsDir'), d.get('Name', '').lower()))

    def size(self, key, path):
        r = self.run('size', f'{key}:{path}', '--json', timeout=300)
        d = json.loads(r.stdout or '{}'); return d.get('bytes', 0), d.get('count', 0)

    def copy(self, src, dst, progress=lambda done, total: None, cancel=None, one_file=False):
        """rclone copy (or copyto for one file) with progress from its JSON stats. Returns (ok, message)."""
        p = self.popen('copyto' if one_file else 'copy', src, dst, '--stats', '1s', '--use-json-log', '--stats-log-level', 'NOTICE')
        self._proc = p; last = []
        def watch():
            for raw in iter(p.stderr.readline, b''):
                try: d = json.loads(raw)
                except ValueError: continue
                st = d.get('stats')
                if st: progress(st.get('bytes', 0), st.get('totalBytes', 0))
                elif d.get('level') in ('error', 'critical'): last.append(str(d.get('msg', ''))[:300])
                if cancel is not None and cancel.is_set(): kill(p); return
        t = threading.Thread(target=watch, daemon=True); t.start()
        code = p.wait(); t.join(5); self._proc = None
        if cancel is not None and cancel.is_set(): return False, 'cancelled'
        return code == 0, ('ok' if code == 0 else (last[-1] if last else f'rclone stopped ({code})'))

    def download(self, key, path, dest, **kw):
        return self.copy(f'{key}:{path}', dest, **kw)

    def upload(self, local_file, key, remote_dir, **kw):
        return self.copy(local_file, f'{key}:{remote_dir.strip("/")}/{os.path.basename(local_file)}', one_file=True, **kw)


def kill(p):
    try:
        if p and p.poll() is None:
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True, timeout=15, creationflags=NOWIN)
    except Exception:
        pass


def cache_dir(key, path, root=None):
    """Where a cloud folder is kept on this PC: <Videos>\\Seekframe cloud\\<Provider>\\<path> (Windows-safe names)."""
    root = root or os.path.join(HOME, 'Videos', 'Seekframe cloud')
    parts = [re.sub(r'[<>:"|?*]', '_', x).rstrip(' .') or '_' for x in path.replace('\\', '/').split('/') if x]
    return os.path.join(root, LABEL.get(key, key), *parts)


def upload_dir(out_dir, mp4):
    """The cloud folder for a finished video: Seekframe/<same folders as under Save to> (e.g. Seekframe/Music/song)."""
    try: rel = os.path.relpath(os.path.dirname(mp4), out_dir)
    except ValueError: rel = os.path.basename(os.path.dirname(mp4))
    if rel.startswith('..'): rel = os.path.basename(os.path.dirname(mp4))
    return '/'.join(['Seekframe'] + [p for p in rel.replace('\\', '/').split('/') if p and p != '.'])


def get_rclone(dest_dir=None, gh=None, progress=lambda s: None):
    """Download the official rclone release (RCLONE_VERSION) from GitHub, check its SHA-256 against the release's
    SHA256SUMS, put rclone.exe in %LOCALAPPDATA%\\Seekframe\\rclone. Returns the path. Raises on any mismatch."""
    import hashlib, io, urllib.request, zipfile
    dest_dir = dest_dir or local_rclone_dir()
    name = f'rclone-{RCLONE_VERSION}-windows-amd64.zip'
    base = f'https://github.com/rclone/rclone/releases/download/{RCLONE_VERSION}/'
    fetch = gh or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Seekframe'}), timeout=120).read())
    progress('Downloading rclone...')
    sums = fetch(base + 'SHA256SUMS').decode('utf-8', 'replace')
    m = re.search(r'([0-9a-f]{64})\s+\*?' + re.escape(name), sums)
    if not m: raise RuntimeError('rclone checksum not found')
    data = fetch(base + name)
    if hashlib.sha256(data).hexdigest() != m.group(1): raise RuntimeError('rclone download is damaged (checksum mismatch)')
    progress('Unpacking rclone...')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        inner = next(n for n in z.namelist() if n.endswith('/rclone.exe'))
        os.makedirs(dest_dir, exist_ok=True)
        with z.open(inner) as src, open(os.path.join(dest_dir, 'rclone.exe.part'), 'wb') as out: shutil.copyfileobj(src, out)
    final = os.path.join(dest_dir, 'rclone.exe')
    os.replace(final + '.part', final)
    return final
