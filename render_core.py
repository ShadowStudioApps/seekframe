"""Shadow rendering engine: HTML scene -> frames -> audio -> MP4. No GUI code here."""
VERSION = "3.37"
import base64, collections, functools, urllib.parse, http.server, os, shutil, subprocess, sys, tempfile, threading, time, wave, array

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
FORMATS = {'16:9 (YouTube)': False, '9:16 (Shorts)': True}
PRESETS = {
    'Draft (fast, 720p)': dict(w=1280, samples=8),
    'Good (1080p, 24 samples)': dict(w=1920, samples=24),
    'Best (1080p, 64 samples)': dict(w=1920, samples=64),
    '1440p (QHD, 64 samples)': dict(w=2560, samples=64),   # 3.15: YouTube streams 1440p/4K uploads with its better codec
    '4K (UHD, 64 samples)': dict(w=3840, samples=64),      # (VP9/AV1), also when watched at 1080p
}

# External audio (Sound = External file / Auto song): loudness-match to -15 LUFS, then a true-peak limiter so the track
# never goes over -1 dBTP (ceiling -1.5). The limiter runs 4x oversampled (192 kHz) so it catches inter-sample peaks;
# latency=1 removes its 5 ms look-ahead delay (needs ffmpeg 5.1+). level=0: no auto make-up gain (it would undo the ceiling).
# Loudness target per channel (3.13): songs (Music) -14 LUFS like YouTube's own playback level, everything else -15.
# The caller picks it (app.target_lufs: <meta name="shadow-lufs">, else Music -> -14); render(lufs=None) = DEFAULT_LUFS.
DEFAULT_LUFS, MUSIC_LUFS = -15.0, -14.0
LUFS_RANGE = (-24.0, -9.0)   # a scene's own shadow-lufs must be inside this (QC still checks the result)
TP_CEILING_DB = -1.5
TP_LIMITER = (f'aresample=192000,alimiter=limit={10 ** (TP_CEILING_DB / 20):.4f}:attack=5:release=50:level=0:latency=1,'
              'aresample=48000')

def loudnorm_af(lufs=None):
    return f'loudnorm=I={DEFAULT_LUFS if lufs is None else lufs:g}:TP={TP_CEILING_DB:g}:LRA=11'

def ext_audio_af(lufs=None):
    """External song chain: loudnorm to `lufs`, true-peak limiter, apad (silence after a track shorter than the video)."""
    return f'{loudnorm_af(lufs)},{TP_LIMITER},apad'

LOUDNORM = loudnorm_af()         # -15 (kept for callers that do not choose)
EXT_AUDIO_AF = ext_audio_af()

def x264_args():
    """Video encoder settings (crf 16 = visually lossless for these scenes; preset medium: about 2x faster than slow).
    3.17: the stream is tagged BT.709, limited range - what YouTube and players assume for HD. Before, the frames were
    converted with ffmpeg's default BT.601 matrix and left untagged (measured: pure red came out as Y=81; BT.709 gives 63),
    so reds and greens shifted slightly on YouTube. Pair it with video_filter(), which does the matching conversion."""
    return ['-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p',
            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv']

def video_filter():
    """-vf for captured frames (PNG = RGB, JPEG = full-range BT.601 YUV): even size (yuv420p needs it; an outdated scene can
    give odd sizes), then ONE conversion to BT.709 limited-range yuv420p, so the pixels match x264_args()'s tags."""
    # setparams: ffmpeg 9 takes primaries / transfer from the frames, not from -color_primaries / -color_trc (measured: both
    # came out 'unknown' without it), so the frames carry all four BT.709 values themselves
    # format=rgb24 first: JPEG frames arrive as YUV; converting them to BT.709 straight from YUV moved them away from the PNG
    # result (measured on tests/fixtures/webgl_min.html: JPEG vs PNG mean difference 2.33; through RGB 1.02; 3.16 had 0.71).
    # test_capture.py C2 (limit 2.0) guards this. PNG frames are RGB already, so for them the step costs nothing.
    return ('pad=ceil(iw/2)*2:ceil(ih/2)*2,format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
            'setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv')

# Injected into every render / frame-check page before the scene's own scripts (3.17). The scene is drawn by several copies
# at once (parallel capture), so anything random at setup must come out the same in every copy, or the video flickers
# between copies. Math.random becomes one fixed-seed generator (mulberry32) and Date is frozen at a fixed instant (new Date()
# with no arguments and Date.now(); dates the scene builds itself are untouched). performance.now stays real: loaders use it
# for timeouts, and a scene that uses it inside seek(t) is caught by Check frames' redraw (purity) test.
RENDER_SEED, RENDER_EPOCH_MS = 0x5AD0, 1767225600000   # 2026-01-01T00:00:00Z
RENDER_INIT_JS = '''(() => {
  if (window.__shadowFixed) return; window.__shadowFixed = true;
  let s = %d >>> 0;
  Math.random = function () { s = (s + 0x6D2B79F5) >>> 0; let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const RealDate = Date, FIXED = %d;
  const FixedDate = new Proxy(RealDate, {
    construct(target, args, nt) { return Reflect.construct(target, args.length ? args : [FIXED], nt); },
    apply() { return new RealDate(FIXED).toString(); },
    get(target, key) { return key === 'now' ? () => FIXED : Reflect.get(target, key); },
  });
  window.Date = FixedDate;
})();''' % (RENDER_SEED, RENDER_EPOCH_MS)

def find_ffmpeg():
    return shutil.which('ffmpeg')

BROWSERS = (('chrome', 'Chrome', '\\Google\\Chrome\\Application\\chrome.exe', ('google-chrome', 'chrome')),
            ('msedge', 'Edge', '\\Microsoft\\Edge\\Application\\msedge.exe', ('microsoft-edge', 'msedge')))   # preference order

def find_browser():
    """The Playwright channel of the installed browser to render with: 'chrome' (preferred), else 'msedge' (Edge ships with
    Windows 10/11 and is the same Chromium engine), else None."""
    for channel, _, rel, names in BROWSERS:
        if any(os.path.exists(os.environ.get(k, '') + rel) for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if os.environ.get(k)) \
                or any(shutil.which(n) for n in names):
            return channel
    return None

def browser_name(channel):
    return next((n for c, n, *_ in BROWSERS if c == channel), channel or 'none')

def check_env():
    """Returns a dict of what is available. 'chrome' = a browser to render with (Chrome or, as fallback, Edge); 'browser' names it."""
    out = {'ffmpeg': bool(find_ffmpeg()), 'playwright': False, 'chrome': False}
    try:
        import playwright  # noqa
        out['playwright'] = True
    except Exception:
        pass
    ch = find_browser(); out['chrome'] = bool(ch); out['browser'] = browser_name(ch) if ch else None
    return out

def resolve_channel(channel):
    """render(channel=...): 'auto' -> find_browser() (Chrome, else Edge; 'chrome' when neither is found so the error names
    Chrome); None -> Playwright's own bundled Chromium (tests); anything else as given."""
    return (find_browser() or 'chrome') if channel == 'auto' else channel

class Cancelled(Exception):
    pass

def ffmpeg_message(lines, ret):
    """'ffmpeg failed: <last 3 error lines joined by " | ">' (one line, so the GUI's error box shows all of it); the exit
    code when ffmpeg printed nothing. Pure."""
    lines = [l.strip() for l in lines if l and l.strip()][-3:]
    return 'ffmpeg failed: ' + (' | '.join(lines) if lines else f'exit code {ret}')

def _ff(cmd):
    """Run ffmpeg; on failure raise with ffmpeg's own last 3 error lines instead of the whole command."""
    r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
    if r.returncode != 0:
        raise RuntimeError(ffmpeg_message(r.stderr.decode('utf-8', 'replace').splitlines(), r.returncode))

# What a scene must provide (CLAUDE.md "Scene contract"), with the reason, for messages a person can act on.
CONTRACT = {
    'ready': 'window.__ready is never set: set window.__ready = true when the scene has loaded (Seekframe waits for it)',
    'seek': 'window.seek(t) is missing: Seekframe calls it for every frame to draw the moment t (seconds)',
    'duration': 'window.DURATION is missing: set it to the length of the scene in seconds',
    'canvas': 'no <canvas id="c">: Seekframe takes every frame from the canvas with id "c"',
}

def _scene_sources(html_path, limit=40):
    """The scene's text plus its LOCAL scripts (<script src>, ES module imports; not http/CDN ones), at most `limit` files."""
    import re
    root = os.path.dirname(os.path.abspath(html_path)); seen, out, todo = set(), [], [os.path.abspath(html_path)]
    while todo and len(seen) < limit:
        p = todo.pop()
        if p in seen or not os.path.isfile(p): continue
        seen.add(p)
        try:
            with open(p, encoding='utf-8', errors='replace') as f: s = f.read()
        except OSError: continue
        out.append(s)
        refs = re.findall(r"""<script[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""", s, re.I) + re.findall(r"""(?:\bfrom|\bimport)\s*\(?\s*['"]([^'"]+\.m?js)['"]""", s)
        for r in refs:
            if re.match(r'^(https?:)?//|^data:', r, re.I): continue
            r = urllib.parse.unquote(r.split('?')[0].split('#')[0])
            todo.append(os.path.normpath(os.path.join(root if r.startswith('/') else os.path.dirname(p), r.lstrip('/'))))
    return out

def contract_problems(html_path):
    """Static check BEFORE rendering: CONTRACT messages for what the scene's text (and its local scripts) never mentions.
    Only absences are reported, so a scene that builds things in an unusual way may pass here and still fail at load time
    (that check is exact). [] for a readable scene that mentions everything; never raises."""
    import re
    try: src = '\n'.join(_scene_sources(html_path))
    except Exception: return []
    if not src: return []
    out = []
    if '__ready' not in src: out.append(CONTRACT['ready'])
    if not re.search(r'\bseek\b', src): out.append(CONTRACT['seek'])
    if 'DURATION' not in src: out.append(CONTRACT['duration'])
    if not re.search(r"""\bid\s*=\s*['"]?c['"\s>/]|\.id\s*=\s*['"]c['"]""", src): out.append(CONTRACT['canvas'])
    return out

def runtime_problems(state):
    """CONTRACT messages from what the loaded page reports: state = dict(seek=typeof window.seek, dur=window.DURATION,
    canvas=tag name of #c or None). Pure (tests feed it dicts)."""
    out = []
    if state.get('seek') != 'function': out.append(CONTRACT['seek'])
    d = state.get('dur')
    if not isinstance(d, (int, float)) or isinstance(d, bool) or not d > 0 or d != d or d == float('inf'):
        out.append(CONTRACT['duration'] + f' (it is {d!r})' if d is not None else CONTRACT['duration'])
    if (state.get('canvas') or '').upper() != 'CANVAS':
        out.append(CONTRACT['canvas'] + (f' (#c is a <{state["canvas"].lower()}>)' if state.get('canvas') else ''))
    return out

# Frame capture from the canvas. PNG = lossless (default). JPEG 0.98 = "Fast capture": measured on a 1080p scene
# (RTX 5070 Ti, 2026-11-18) 82 -> 31 ms per frame (whole render about 2x faster), final video SSIM 0.986 -> 0.983, file ~1.7x larger.
CAPTURE_JS = {'png': '"image/png"', 'jpeg': '"image/jpeg", 0.98'}   # toDataURL arguments
CAPTURE_CODEC = {'png': 'png', 'jpeg': 'mjpeg'}                         # ffmpeg decoder for the piped frames

AUDIO_TARGET_LUFS, AUDIO_TP_MAX = -15.0, -1.2   # final mp4 audio: QC allows -17..-13 LUFS and true peak <= -1 dBTP

def _loud(ffmpeg, path):
    """(integrated LUFS, true peak dBTP) of an audio/video file (ffmpeg ebur128, 4x oversampled true peak)."""
    import re
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, creationflags=NOWIN).stderr.decode('utf-8', 'replace')
    i = re.findall(r'I:\s*(-?[\d.]+) LUFS', r); tp = re.search(r'True peak:\s*Peak:\s*(-?[\d.]+|-inf)', r)
    return (float(i[-1]) if i else None), (float(tp.group(1)) if tp and tp.group(1) != '-inf' else None)

def finalize_audio(ffmpeg, wav, tmp, aac=('-c:a', 'aac', '-b:a', '192k'), target=None):
    """Make the mp4's audio land inside the QC limits AFTER the AAC encode: encode a trial AAC, measure it, and turn the
    wav down by exactly what is needed (never up) - loudness to AUDIO_TARGET_LUFS when it is louder, true peak to
    AUDIO_TP_MAX. Measured on a loud song: the limiter gives -1.4 dBTP, but AAC 192k added +1.4 dB (0.0 dBTP) and
    single-pass loudnorm left -13.6 LUFS. Returns the wav to mux (a new file when it was turned down).
    target: the loudness to keep under (default AUDIO_TARGET_LUFS = -15; songs use MUSIC_LUFS)."""
    target = AUDIO_TARGET_LUFS if target is None else target
    cur = wav
    for k in range(3):
        trial = os.path.join(tmp, f'trial{k}.m4a')
        if subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', cur, *aac, trial], capture_output=True, creationflags=NOWIN).returncode: return cur
        lufs, tp = _loud(ffmpeg, trial)
        if lufs is None or tp is None: return cur
        gain = min(0.0, target - lufs if lufs > target + 0.3 else 0.0, AUDIO_TP_MAX - tp if tp > AUDIO_TP_MAX else 0.0)
        if gain > -0.05: return cur
        nxt = os.path.join(tmp, f'final{k}.wav')
        _ff([ffmpeg, '-y', '-i', cur, '-af', f'volume={gain:.2f}dB', '-c:a', 'pcm_s16le', nxt]); cur = nxt
    return cur

# Temp folders of a render (frames never go there; audio wavs do). Removed when a render ends; a crash / power cut / killed
# process leaves them, so clean_stale_temp() (app start, MCP server start) removes the ones whose process is gone.
TEMP_PREFIXES = ('bq_render_', 'shadow_blend_', 'shadow_blendpv_')
OWNER_FILE = 'owner.pid'

def mark_temp_owner(folder):
    try:
        with open(os.path.join(folder, OWNER_FILE), 'w') as f: f.write(str(os.getpid()))
    except OSError: pass

def pid_alive(pid):
    """True while process `pid` runs (Windows: OpenProcess + exit code STILL_ACTIVE; elsewhere signal 0)."""
    if not pid or pid <= 0: return False
    if pid == os.getpid(): return True
    if os.name == 'nt':
        import ctypes
        k = ctypes.windll.kernel32; h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h: return False
        code = ctypes.c_ulong()
        try: return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally: k.CloseHandle(h)
    try: os.kill(pid, 0); return True
    except OSError: return False

def clean_stale_temp(base=None, min_age_s=600, now=None):
    """Remove leftover render temp folders in `base` (default %TEMP%): its owner.pid process is gone, or (older Shadow, no
    owner file) it is over a day old. Folders younger than min_age_s are always kept. -> (folders removed, bytes freed)."""
    base = base or tempfile.gettempdir(); now = time.time() if now is None else now; n = freed = 0
    try: names = os.listdir(base)
    except OSError: return 0, 0
    for name in names:
        p = os.path.join(base, name)
        if not name.startswith(TEMP_PREFIXES) or not os.path.isdir(p): continue
        try:
            age = now - os.path.getmtime(p)
            if age < min_age_s: continue
            try:
                with open(os.path.join(p, OWNER_FILE)) as f: alive = pid_alive(int(f.read().strip() or 0))
            except (OSError, ValueError): alive = age < 86400
            if alive: continue
            size = sum(os.path.getsize(os.path.join(r, x)) for r, _, fs in os.walk(p) for x in fs)
            shutil.rmtree(p)
            n += 1; freed += size
        except OSError: continue
    return n, freed

READY_TIMEOUT_MS = 180000   # how long a scene may take to set window.__ready (big textures / fonts over a slow line)

# ---------------------------------------------------------------- parallel frame capture (3.15)
# Measured on a real Moon Shift three.js scene (RTX 5070 Ti, 16 cores, 2026-11-20), ms per frame, capture side only:
#   one page + toDataURL (old):  1080p PNG 75 | JPEG 25 | 1440p PNG 123 | 4K PNG 260 | JPEG 91
#   4 pages + toBlob + binary POST: 1080p PNG 17 (3 pages) | JPEG 5.6 | 1440p PNG 23 | 4K PNG 50 | JPEG 21
# Encoding (toDataURL) was ~55% and the base64 transfer ~45%; drawing (seek) ~0. PNG frames are byte-identical to the
# old path with 1 page; with several pages a scene that keeps a little state between frames can differ invisibly (real
# Moon Shift scene: PSNR >= 46 dB, 54 dB average; the 1-page path and 3.13 give the same bytes). Chrome keeps blobs until GC: without window.gc() every 30 frames, fetch failed after a few hundred 1080p frames.
CAPTURE_INFLIGHT = 4      # frames per page being encoded / sent at the same time
CAPTURE_STALL_S = 120     # no new frame for this long = stop with an error (never hang a queue)
CAPTURE_LOOP_JS = '''(o) => {
  window.__shadow = {done: false, err: null, stop: false, fails: 0};
  const c = document.getElementById('c'), busy = new Set();
  const send = async (b, i) => {
    for (let t = 0; ; t++) {
      try { const r = await fetch(o.url, {method: 'POST', body: b, headers: {'X-Frame': String(i)}});
            if (r.ok || r.status === 409) return; throw new Error('HTTP ' + r.status); }
      catch (e) { window.__shadow.fails++; if (t >= 5 || window.__shadow.stop) throw e; await new Promise(r => setTimeout(r, 100 * (t + 1))); }
    }
  };
  (async () => {
    let k = 0;
    for (let i = o.start; i < o.n; i += o.step) {
      if (window.__shadow.stop) return;
      if (++k % 30 === 0 && window.gc) window.gc();
      window.seek(i / o.fps);
      const p = new Promise((res, rej) => c.toBlob(b => b ? res(b) : rej(new Error('the canvas gave no image (too large for the GPU?)')), o.mime, o.q === null ? undefined : o.q))
        .then(b => send(b, i));
      busy.add(p); p.then(() => busy.delete(p), () => {});
      if (busy.size >= o.inflight) await Promise.race(busy);
    }
    await Promise.all(busy);
  })().then(() => { window.__shadow.done = true; }, e => { window.__shadow.err = String(e && e.message || e); });
}'''

def capture_workers(workers='auto', n_frames=None):
    """How many pages capture frames. 'auto' = 4 on 8+ cores, 2 on 4+, else 1 (measured: 3-4 pages give 4-5x); an int is
    used as given (0 = the original single-page path). Never more pages than frames."""
    if workers in (None, 'auto') and os.environ.get('SHADOW_CAPTURE_WORKERS', '').strip().isdigit():
        workers = int(os.environ['SHADOW_CAPTURE_WORKERS'])   # 1 = frames byte-identical to 3.13 (one page), 0 = the old path
    if workers in (None, 'auto'):
        c = os.cpu_count() or 2
        workers = 4 if c >= 8 else 2 if c >= 4 else 1
    workers = max(0, int(workers))
    return min(workers, n_frames) if n_frames else workers

class _FrameSink:
    """Receives the POSTed frames (any order, from several pages) and writes them to ffmpeg's stdin in frame order.
    put() blocks while a frame is more than `window` ahead of the next one to write (back-pressure: the pages wait)."""
    def __init__(self):
        self.path = '/__shadow_frame/' + os.urandom(8).hex(); self.url = self.path
        self.cond = threading.Condition(); self.buf = {}; self.written = 0; self.n = 0; self.out = None
        self.window = 8; self.error = None; self.stopped = False
    def open(self, out, n, window=8):
        with self.cond: self.out, self.n, self.window, self.written, self.buf, self.stopped = out, n, max(2, window), 0, {}, False
    def stop(self):
        with self.cond: self.stopped = True; self.cond.notify_all()
    def put(self, i, data):
        """-> HTTP status: 204 stored/written, 409 stopped or not needed, 500 ffmpeg failed."""
        with self.cond:
            if self.out is None or not 0 <= i < self.n: raise ValueError(i)
            while not self.stopped and self.error is None and i >= self.written + self.window: self.cond.wait(0.5)
            if self.stopped: return 409
            if self.error is not None: return 500
            if i < self.written or i in self.buf: return 409
            self.buf[i] = data
            while self.written in self.buf:
                try: self.out.write(self.buf.pop(self.written))
                except OSError as e: self.error = e; self.cond.notify_all(); return 500
                self.written += 1
            self.cond.notify_all(); return 204

def _part_path(out_mp4):
    """The file ffmpeg writes while rendering; renamed to out_mp4 only when everything succeeded."""
    root, ext = os.path.splitext(os.path.abspath(out_mp4))
    return f'{root}.part{ext or ".mp4"}'

def render(html_path, out_mp4, preset, fps=30, progress=lambda *_: None, cancel=None, max_frames=None, channel='auto', extra_args=(), vertical=False, sound='generated', audio_file=None, info=None, capture='png', lufs=None, workers='auto'):
    """progress(stage, done, total[, eta]); stages in order: load, audio, frames, encode, done. cancel: threading.Event.
    sound: 'generated' | 'none' | 'file' (audio_file). capture: 'png' (lossless, default) | 'jpeg' (Fast capture).
    lufs: loudness target of the sound (None = DEFAULT_LUFS -15; songs MUSIC_LUFS -14).
    workers: frame capture pages ('auto' = capture_workers(); 0 = the original single-page path). Each page is its own copy of
    the scene and draws every nw-th frame (seek(t) is pure by the contract), so frames come out identical, just faster.
    info: optional dict, filled with {'sound': the mode actually used, 'scene_duration', 'duration', 'capture', 'lufs'}.
    Frames are piped straight into ffmpeg (no frame files on disk) and encoded while the scene renders; the mp4 is written
    as <name>.part.mp4 and renamed to out_mp4 only on success, so a cancelled or failed render leaves no file behind."""
    from playwright.sync_api import sync_playwright
    if capture not in CAPTURE_JS: raise ValueError(f'capture must be one of {list(CAPTURE_JS)}')
    src = os.path.abspath(html_path); page = os.path.basename(src); d = os.path.dirname(src)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError('ffmpeg not found')
    if CONTRACT['ready'] in contract_problems(src):   # would only time out after 3 minutes: say why now
        raise RuntimeError('The scene cannot render: ' + CONTRACT['ready'] + '.')
    w, samples = preset['w'], preset['samples']
    cw, ch = (round(w * 9 / 16), w) if vertical else (w, round(w * 9 / 16))
    tmp = tempfile.mkdtemp(prefix=TEMP_PREFIXES[0]); mark_temp_owner(tmp)
    part = _part_path(out_mp4); proc = None
    sink = _FrameSink()
    class Q(http.server.SimpleHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'   # keep-alive: a few connections for thousands of frame POSTs (no port exhaustion)
        def log_message(self, *a, **k): pass
        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0); data = self.rfile.read(n)
            if self.path != sink.path: self.send_response(404)
            else:
                try: code = sink.put(int(self.headers.get('X-Frame', '-1')), data)
                except ValueError: code = 400
                self.send_response(code)
            self.send_header('Content-Length', '0'); self.end_headers()
    class S(http.server.ThreadingHTTPServer):
        request_queue_size = 64; daemon_threads = True
        def handle_error(self, request, client_address):   # the browser closing a connection at the end / on cancel is normal
            if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)): super().handle_error(request, client_address)
    srv = S(('127.0.0.1', 0), functools.partial(Q, directory=d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        with sync_playwright() as p:
            kw = dict(args=['--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--js-flags=--expose-gc', *extra_args])
            channel = resolve_channel(channel)
            if channel: kw['channel'] = channel
            if info is not None: info['browser'] = browser_name(channel) if channel else 'bundled Chromium'
            b = p.chromium.launch(**kw)
            pg = b.new_page(viewport={'width': 1280, 'height': 720})
            pg.add_init_script(RENDER_INIT_JS)   # same Math.random / Date in every copy of the scene
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            progress('load', 0, 1)
            pg.goto(f'http://127.0.0.1:{port}/{urllib.parse.quote(page)}?render=1&s={samples}&w={cw}&h={ch}')
            try:
                pg.wait_for_function('window.__ready===true', timeout=READY_TIMEOUT_MS)
            except Exception:
                why = (' Page errors: ' + ' | '.join(errs[:2])) if errs else ' No page errors: check that the scene sets window.__ready = true at the end of loading.'
                raise RuntimeError(f'The scene did not load: window.__ready was not true after {READY_TIMEOUT_MS // 1000} s.' + why)
            bad = runtime_problems(pg.evaluate("""(()=>{const c=document.getElementById('c');
                return {seek: typeof window.seek, dur: window.DURATION === undefined ? null : window.DURATION, canvas: c ? c.tagName : null}})()"""))
            if bad: raise RuntimeError('The scene cannot render: ' + '; '.join(bad) + '.')
            if sound == 'generated' and not pg.evaluate("typeof window.STYLE_SOUND==='function' && typeof window.SOUND==='object' && typeof window.SOUND.renderOffline==='function'"):
                sound = 'none'   # the scene has no generated score: render it silent instead of failing after all the frames
            if info is not None: info['sound'] = sound; info['capture'] = capture; info['lufs'] = None if sound == 'none' else (DEFAULT_LUFS if lufs is None else lufs)
            dur = pg.evaluate('window.DURATION'); n = round(dur * fps)
            if max_frames: n = min(n, max_frames)
            if info is not None:
                info['scene_duration'] = dur; info['duration'] = n / fps   # scene length / length actually rendered
                th = pg.evaluate('typeof window.THUMBNAIL_T === "number" ? window.THUMBNAIL_T : null')   # optional: thumbnail moment (s)
                if th is not None: info['thumbnail_t'] = max(0.0, min(float(th), n / fps - 1 / fps))
            if cancel is not None and cancel.is_set(): raise Cancelled()

            # 1) sound first: ffmpeg needs the finished audio file as its second input before the frames start flowing
            aud = os.path.join(tmp, 'audio.wav')
            if sound == 'generated':
                progress('audio', 0, 1)
                b64 = pg.evaluate('''async()=>{const o=await SOUND.renderOffline((k)=>window.STYLE_SOUND(k), window.DURATION, 48000, {voiceover:false});
                  const u=new Uint8Array(o.inter.buffer); let s=''; for(let i=0;i<u.length;i+=32768) s+=String.fromCharCode.apply(null,u.subarray(i,i+32768)); return btoa(s)}''')
                f32 = array.array('f'); f32.frombytes(base64.b64decode(b64))
                i16 = array.array('h', (int(max(-1.0, min(1.0, v)) * 32767) for v in f32))
                raw = os.path.join(tmp, 'raw.wav')
                with wave.open(raw, 'wb') as wf:
                    wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(48000); wf.writeframes(i16.tobytes())
                _ff([ffmpeg, '-y', '-i', raw, '-af', loudnorm_af(lufs), '-ar', '48000', aud])
            elif sound == 'file':
                if not audio_file or not os.path.exists(audio_file): raise RuntimeError('Audio file not found')
                progress('audio', 0, 1)
                # loudness-match the external track, true-peak limit it, pad with silence if it is shorter than the video
                _ff([ffmpeg, '-y', '-i', audio_file, '-af', ext_audio_af(lufs), '-ar', '48000', '-t', str(n / fps), aud])
            if sound != 'none':   # measured after a trial AAC encode: turn down until the mp4 will pass QC (true peak, loudness)
                aud = finalize_audio(ffmpeg, aud, tmp, target=lufs)

            # 2) frames -> ffmpeg's stdin, encoded while the next frames render. -nostats + a reader thread on stderr:
            # ffmpeg can never block on a full stderr pipe (that would hang a long render).
            cmd = [ffmpeg, '-y', '-hide_banner', '-nostats', '-loglevel', 'error',
                   '-f', 'image2pipe', '-c:v', CAPTURE_CODEC[capture], '-framerate', str(fps), '-i', '-']
            if sound != 'none': cmd += ['-i', aud]
            cmd += ['-vf', video_filter(), *x264_args()]   # even size + BT.709 conversion, tagged to match
            if sound != 'none': cmd += ['-c:a', 'aac', '-b:a', '192k', '-shortest']
            cmd += ['-movflags', '+faststart', '-f', 'mp4', part]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NOWIN)
            err_lines = collections.deque(maxlen=20)
            def drain():
                for line in iter(proc.stderr.readline, b''):
                    t = line.decode('utf-8', 'replace').strip()
                    if t: err_lines.append(t)
            reader = threading.Thread(target=drain, daemon=True); reader.start()
            def ffmpeg_error(ret):
                return RuntimeError(ffmpeg_message(list(err_lines), ret))
            js = CAPTURE_JS[capture]
            t0 = time.time()
            nw = capture_workers(workers, n)
            if info is not None: info['workers'] = nw
            if nw == 0:   # the original one-page path: one evaluate per frame, base64 back to Python
                for i in range(n):
                    if cancel is not None and cancel.is_set(): raise Cancelled()
                    d64 = pg.evaluate(f'(()=>{{window.seek({i}/{fps});return document.getElementById("c").toDataURL({js})}})()')
                    try:
                        proc.stdin.write(base64.b64decode(d64.split(',')[1]))
                    except OSError:   # ffmpeg stopped (bad frame, disk full...): report its own message
                        ret = proc.wait(); reader.join(5); raise ffmpeg_error(ret)
                    progress('frames', i + 1, n, (time.time() - t0) / (i + 1) * (n - i - 1))
            else:   # parallel capture: nw pages draw frames k, k+nw, ... and POST them (binary) to this server, in order to ffmpeg
                sink.open(proc.stdin, n, window=nw * 6)
                pages = [pg]
                for _ in range(nw - 1):   # more copies of the scene, each in its own renderer process (own browser context)
                    px = b.new_context(viewport={'width': 1280, 'height': 720}).new_page()
                    px.add_init_script(RENDER_INIT_JS)
                    px.on('pageerror', lambda e: errs.append(str(e)))
                    px.goto(f'http://127.0.0.1:{port}/{urllib.parse.quote(page)}?render=1&s={samples}&w={cw}&h={ch}')
                    px.wait_for_function('window.__ready===true', timeout=READY_TIMEOUT_MS)
                    pages.append(px)
                mime, q = ('image/png', None) if capture == 'png' else ('image/jpeg', 0.98)
                for k, px in enumerate(pages):
                    px.evaluate(CAPTURE_LOOP_JS, dict(start=k, step=nw, n=n, inflight=CAPTURE_INFLIGHT, url=sink.url, fps=fps, mime=mime, q=q))
                last_poll = 0; last_done = 0; last_change = time.time()
                while True:
                    done = sink.written
                    if done != last_done: last_done, last_change = done, time.time(); progress('frames', done, n, (time.time() - t0) / max(done, 1) * (n - done))
                    if done >= n: break
                    if sink.error is not None: ret = proc.wait(); reader.join(5); raise ffmpeg_error(ret)
                    if cancel is not None and cancel.is_set():
                        sink.stop()
                        for px in pages:
                            try: px.evaluate('window.__shadow && (window.__shadow.stop = true)')
                            except Exception: pass
                        raise Cancelled()
                    if time.time() - last_poll > 0.5:
                        last_poll = time.time()
                        for px in pages:
                            st = px.evaluate('window.__shadow || null')
                            if st and st.get('err'):
                                raise RuntimeError('frame capture failed: ' + st['err'].splitlines()[0] + (f' | page errors: {errs[0]}' if errs else ''))
                    if time.time() - last_change > CAPTURE_STALL_S:
                        raise RuntimeError(f'frame capture stopped: no new frame for {CAPTURE_STALL_S} s at frame {done} of {n}'
                                           + (f' | page errors: {errs[0]}' if errs else ''))
                    time.sleep(0.02)
                sink.stop()
            b.close()
        progress('encode', 0, 1)   # only the last frames are left to encode
        try: proc.stdin.close()
        except OSError: pass   # ffmpeg already stopped: its exit code below says why
        ret = proc.wait(); reader.join(5)
        if ret != 0: raise ffmpeg_error(ret)
        proc = None
        os.replace(part, out_mp4)
        progress('done', 1, 1)
        return out_mp4
    finally:
        if proc is not None:   # cancelled / failed while ffmpeg runs: stop it and wait, so Windows releases the .part file
            try: proc.kill()
            except Exception: pass
            try: proc.wait(10)
            except Exception: pass
        if os.path.exists(part):
            try: os.remove(part)
            except OSError: pass
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
