import datetime, glob, importlib, json, logging, os, queue, re, shutil, subprocess, sys, threading, time, traceback, uuid, webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_core as rc
import blender_core as bc
import frame_check
import qc
import subtitles
import updater
import assistant
import ai_clients   # 3.32: AI apps that can use Seekframe (MCP), connect / disconnect
import ai_tasks
import cloud   # 3.33: cloud accounts through rclone (sign in, browse, download, upload)
import video_song as vsong
import i18n
from i18n import t as tr   # 3.20: the UI language (locales/<code>.json); keys and the log stay English
import youtube   # noqa: F401  (YouTubeDialog imports it again; listed here so PyInstaller bundles it)
# 3.16: these parts live in their own modules; their names are imported back so app.<name> works everywhere
from scene_paths import *   # noqa: F401,F403  (names, folders, Format / Sound / Folder)
from scene_paths import _WIN_RESERVED, _META_FOLDER, _META_LUFS   # noqa: F401
from projects import *   # noqa: F401,F403  (.shadow project files)
from projects import _rel   # noqa: F401
from shadow_util import dark_titlebar, edit_bindings, narrate_module, open_path, style_input, style_output   # noqa: F401

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    Root = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    Root = tk.Tk
    HAS_DND = False
try:
    import sv_ttk
except Exception:
    sv_ttk = None
try:
    import darkdetect
except Exception:
    darkdetect = None

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CFG = os.path.join(os.path.expanduser('~'), '.shadow_renderer.json')
LOG = os.path.join(os.path.dirname(CFG), 'shadow.log')
LOG_DIR = os.path.join(os.path.dirname(LOG), 'logs')   # fallback only: a failure log normally goes into the scene's own output folder
LIGHT_TINT = 39   # Light theme = light gray: sv-ttk's near-white (#fafafa) darkened by this much, for the window and its images alike
LIGHT_BG = LIGHT_FIELD = '#%02x%02x%02x' % ((250 - LIGHT_TINT,) * 3)   # #d3d3d3 (owner's choice)
BLENDER_ENGINES = list(bc.ENGINES.values())   # GUI labels: Scene setting / Eevee / Cycles (GPU) / Workbench (fast)
SOUNDS = ['Generated (built into the scene)', 'None (silent)', 'External file...', 'Auto (file next to scene)']
OUTDATED = 'This scene is outdated and does not support 9:16'


SKIPPED_SCENE_CHECK = 'Skipped (scene check)'   # Render: the scene misses window.__ready / seek / DURATION / canvas#c and the user chose No
# Capture: how each frame leaves the browser (render_core.render(capture=...)). PNG = lossless; JPEG = final video very slightly
# softer (measured SSIM 0.986 -> 0.983 on a 1080p scene) and ~1.2x larger file. Speed gap measured again after the 3.15
# parallel capture (end to end, real Moon Shift scene): 1080p 22 -> 18 ms/frame, 4K 73 -> 58 = about 1.2x (it was ~2x).
CAPTURES = {'Best quality (PNG)': 'png', 'Fast (JPEG, ~1.2x faster)': 'jpeg'}
OLD_CAPTURE_LABELS = {'Fast (JPEG, ~2x faster)': 'Fast (JPEG, ~1.2x faster)'}   # settings / projects saved by 3.16 and older

log = logging.getLogger('shadow')
def close_log():
    """Close and drop the log file handlers (tests: so their temp folder with shadow.log can be deleted on Windows)."""
    for h in list(log.handlers):
        try: h.close()
        except Exception: pass
        log.removeHandler(h)
def setup_log():
    if log.handlers: return
    try:
        from logging.handlers import RotatingFileHandler
        h = RotatingFileHandler(LOG, maxBytes=1_000_000, backupCount=1, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(h); log.setLevel(logging.INFO)
    except Exception:
        log.addHandler(logging.NullHandler())

def load_cfg():
    try:
        with open(CFG, encoding='utf-8') as f: return json.load(f)
    except Exception: return {}
def save_cfg(d):
    try:
        with open(CFG, 'w', encoding='utf-8') as f: json.dump(d, f)
    except Exception: pass
def fmt(sec):
    sec = int(sec); return f'{sec // 60}:{sec % 60:02d}'

def system_theme():
    try: return 'dark' if (darkdetect.theme() or '').lower() == 'dark' else 'light'
    except Exception: return 'light'

def blender_engine(label):
    """Blender combobox label -> blender_core engine key ('scene' | 'eevee' | 'cycles' | 'workbench')."""
    return next((k for k, v in bc.ENGINES.items() if v == label), 'scene')


# ---------------------------------------------------------------- folders, up-to-date check, time estimate, notification
SKIPPED_UP_TO_DATE = 'Skipped (up to date)'


def up_to_date(scene_path, out, vertical, deps=(), expect=None, main=None):
    """The existing output mp4 if this scene does not need rendering again, else None: <out>\\<scene>\\<scene>.mp4 (or
    _shorts.mp4) exists, is not empty and is newer than the scene file and every file in deps (the song / narration voice
    / words.json it uses). expect=(w, h): the mp4 must also have that size (a Draft render does not count for Best);
    when the size cannot be read (no ffprobe) the age check alone decides. Good and Best have the same size, so switching
    between them is not detected: untick "Skip already rendered" to force a new render."""
    first = output_mp4(out, scene_path, vertical, main); folder = os.path.dirname(first); stem = os.path.splitext(os.path.basename(first))[0]
    pat = re.compile(re.escape(stem) + r'(_\d+)?\.mp4$', re.I)   # <scene>.mp4, <scene>_2.mp4 ... (a re-render after a change is _2)
    try:
        cands = [os.path.join(folder, n) for n in os.listdir(folder) if pat.match(n)] if os.path.isdir(folder) else []
        if not cands: return None
        mp4 = max(cands, key=os.path.getmtime)   # the newest render decides
        if os.path.getsize(mp4) == 0: return None
        t = os.path.getmtime(mp4)
        for d in (scene_path, *deps):
            if d and os.path.isfile(d) and os.path.getmtime(d) > t: return None
    except OSError:
        return None
    if expect:
        pr = probe(mp4)
        if pr is not None and (pr[0], pr[1]) != tuple(expect): return None
    return mp4

def render_deps(scene_path, opts, narr=None):
    """Files besides the scene whose change means a new render: the audio file it will use and the narration files."""
    deps = []
    mode = opts.get('sound')
    if mode == 'auto' and not narr: deps.append(find_scene_audio(scene_path))
    elif mode == 'file' and not narr: deps.append(opts.get('audio_file'))
    if narr:
        deps.append(narr.get('wav'))
        if isinstance(narr.get('words'), str): deps.append(narr['words'])
    return [d for d in deps if d]

# Speed before the first frame is measured: 1080p Best on the owner's PC (RTX 5070 Ti), seconds per frame for the capture
# mode; other sizes scale with the pixel count. Plus a fixed part per scene (Chrome start, sound, encode tail, QC).
SEC_PER_FRAME = {'png': 0.025, 'jpeg': 0.019}   # 3.15 parallel capture, measured end to end at 1080p (was 0.087 / 0.036)
ITEM_OVERHEAD_S = 15
_DUR_RE = re.compile(r'(?<![\w.])(?:window\.)?DURATION\s*=\s*(\d+(?:\.\d+)?)\s*(?:[;,)\n]|$)')

def media_seconds(path):
    """Length of an audio file in seconds (wav via the wave module, others via ffprobe), or None."""
    try:
        if path.lower().endswith('.wav'):
            import wave
            with wave.open(path) as wf: return wf.getnframes() / float(wf.getframerate())
    except Exception: pass
    ff = rc.find_ffmpeg()
    exe = shutil.which('ffprobe') or (os.path.join(os.path.dirname(ff), 'ffprobe' + ('.exe' if os.name == 'nt' else '')) if ff else None)
    if not exe or not os.path.exists(exe): return None
    try:
        r = subprocess.run([exe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                           capture_output=True, text=True, timeout=15, creationflags=NOWIN)
        return float(r.stdout.strip())
    except Exception: return None

def scene_duration_guess(scene_path, audio_file=None, narr=None):
    """The scene's length in seconds WITHOUT opening it in Chrome, for the time estimate: a literal `DURATION = 12.5` in the
    HTML, else the narration (words.json "duration" / last word, or the voice WAV), else the song it will use. None when it
    cannot be known (a .blend, or DURATION computed in code without an audio file)."""
    if bc.is_blend(scene_path): return None
    try:
        with open(scene_path, encoding='utf-8', errors='replace') as fh: m = _DUR_RE.search(fh.read())
        if m and float(m.group(1)) > 0: return float(m.group(1))
    except OSError: pass
    if narr:
        try:
            wj = narr.get('words')
            if isinstance(wj, str):
                with open(wj, encoding='utf-8') as fh: wj = json.load(fh)
            if isinstance(wj, dict) and wj.get('duration'): return float(wj['duration'])
        except Exception: pass
        if narr.get('wav'):
            s = media_seconds(narr['wav'])
            if s: return s
    if audio_file and os.path.isfile(audio_file):
        return media_seconds(audio_file)
    return None

def estimate_seconds(scene_seconds, preset, capture='png', sec_per_frame=None, fps=30):
    """Render time of one scene: frames x seconds per frame (measured in this batch, else SEC_PER_FRAME scaled from 1080p
    by the pixel count) + ITEM_OVERHEAD_S. None when the length is unknown."""
    if not scene_seconds: return None
    if sec_per_frame is None:
        w = preset.get('w', 1920) if preset else 1920
        sec_per_frame = SEC_PER_FRAME.get(capture, SEC_PER_FRAME['png']) * (w / 1920.0) ** 2
    return round(scene_seconds * fps) * sec_per_frame + ITEM_OVERHEAD_S

def span_text(seconds):
    """'under 1 min' / 'about 12 min' / 'about 1 h 05 min'."""
    m = int(round(seconds / 60.0))
    if seconds < 60: return 'under 1 min'
    return f'about {m // 60} h {m % 60:02d} min' if m >= 60 else f'about {m} min'

def eta_text(seconds, now=None, unknown=0):
    """'about 12 min · done ~15:40' (+ how many scenes could not be estimated). now: a datetime (tests), default now."""
    if seconds is None or seconds <= 0:
        return f'{unknown} scene(s) not estimated yet' if unknown else ''
    end = (now or datetime.datetime.now()) + datetime.timedelta(seconds=seconds)
    return f'{span_text(seconds)} · done ~{end:%H:%M}' + (f' (+ {unknown} not estimated)' if unknown else '')

def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"

def toast_script(title, text, folder=None, show=True):
    """PowerShell (Windows PowerShell 5.1, built into Windows 10/11) that shows a Windows notification through WinRT, with
    no extra package. Clicking it opens `folder` (a file: link; protocol activation). show=False builds everything but does
    not show it (tests). The app id is Windows PowerShell's own, so no shortcut/registration is needed."""
    from xml.sax.saxutils import escape, quoteattr
    launch = ''
    if folder:
        launch = f' activationType="protocol" launch={quoteattr("file:///" + os.path.abspath(folder).replace(os.sep, "/"))}'
    xml = (f'<toast{launch}><visual><binding template="ToastGeneric"><text>{escape(title)}</text><text>{escape(text)}</text>'
           '</binding></visual></toast>')
    return '\n'.join([
        "$ErrorActionPreference = 'Stop'",
        '[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]',
        '[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]',
        '$x = New-Object Windows.Data.Xml.Dom.XmlDocument',
        f'$x.LoadXml({_ps_quote(xml)})',
        '$t = [Windows.UI.Notifications.ToastNotification]::new($x)',
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'",
        '$n = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app)',
        '$n.Show($t)' if show else "Write-Output 'toast ready'"])

def notify(title, text, folder=None, show=True, wait=False):
    """Show a Windows notification (fire and forget, hidden PowerShell, CREATE_NO_WINDOW). Never raises; returns the
    Popen (or the CompletedProcess when wait=True), None when it cannot run (not Windows / no powershell.exe)."""
    if os.name != 'nt': return None
    try:
        import base64
        exe = shutil.which('powershell') or os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        if not os.path.exists(exe): return None
        enc = base64.b64encode(toast_script(title, text, folder, show).encode('utf-16-le')).decode('ascii')
        cmd = [exe, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-EncodedCommand', enc]
        if wait: return subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NOWIN)
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    except Exception:
        log.exception('notification'); return None

def write_srt(mp4, words):
    """<mp4 name>.srt next to the video from the narration's word timings (subtitles.srt). Returns the path or None
    (never raises: a missing subtitle file must not fail the render)."""
    try:
        path = os.path.splitext(mp4)[0] + '.srt'
        with open(path, 'w', encoding='utf-8') as fh: fh.write(subtitles.srt(subtitles.words_list(words)))
        log.info('subtitles %s', path); return path
    except Exception:
        log.error('srt failed for %s\n%s', mp4, traceback.format_exc()); return None

def write_failure_log(scene, out_mp4, preset, opts, exc, tb_text, log_dir=None, when=None):
    """Write <scene name>_<YYYYMMDD-HHMMSS>.log for one failed render and return its path (None if it cannot be written).
    log_dir: the scene's output folder (the queue passes it); without it the fallback LOG_DIR is used.
    ffmpeg's output only reaches us through render_core's error text ('ffmpeg failed: <its last line>'), so that is what is kept."""
    try:
        d = log_dir or LOG_DIR; os.makedirs(d, exist_ok=True)
        stamp = (when or datetime.datetime.now()).strftime('%Y%m%d-%H%M%S')
        path = unique_path(os.path.join(d, f'{os.path.splitext(os.path.basename(scene))[0]}_{stamp}.log'))
        msg = str(exc).strip()
        ff = [l for l in msg.splitlines() if 'ffmpeg' in l.lower()]
        lines = [f'Seekframe v{rc.VERSION} - render failed {stamp}', '',
                 f'scene:   {scene}', f'output:  {out_mp4}', f'preset:  {json.dumps(preset)}',
                 f'options: {json.dumps(opts, ensure_ascii=False)}', '',
                 f'error:   {type(exc).__name__}: {msg.splitlines()[0] if msg else ""}', '',
                 'ffmpeg output (last lines):', *(ff or ['(not available: ffmpeg did not fail, or gave no output)']), '',
                 'traceback:', tb_text.rstrip()]
        with open(path, 'w', encoding='utf-8') as fh: fh.write('\n'.join(lines) + '\n')
        return path
    except Exception:
        log.exception('could not write the failure log')
        return None

# ---------------------------------------------------------------- narration (tools/narrate/make_narrated_scene.py)
NARR_PREFIX = '.shadow_narr_'      # hidden temp scene written next to the original, so its relative files still load
VOICE_MARK = '[voice]'             # shown after the file name of a queue row that has narration
VOICE_EMBEDDED_MARK = '[voice embedded]'   # the scene file itself already contains narration
NARR_STALE_S = 3600               # older leftovers of a crashed run are removed before writing a new one


def remove_with_retries(path, tries=3, delay=0.3):
    """Delete a file, retrying a few times (OneDrive / antivirus can hold it for a moment). Never raises."""
    for i in range(tries):
        try:
            if os.path.exists(path): os.remove(path)
            return True
        except OSError:
            if i < tries - 1: time.sleep(delay)
    log.warning('could not delete %s', path)
    return False

def narrate_for_render(scene_path, narr, info=None):
    """Write the scene with narration embedded as a hidden .shadow_narr_<id>_<scene>.html next to the original and return
    its path (the caller deletes it). narr: {'wav', 'words' (path to words.json or a list), 'style', 'yh', 'gain', 'captions'}.
    Stale .shadow_narr_* files older than NARR_STALE_S in that folder are removed first. info gets the tool's
    narration_duration / words / warnings. Raises ValueError for bad narration input (tool errors included)."""
    d = os.path.dirname(os.path.abspath(scene_path))
    for old in glob.glob(os.path.join(d, NARR_PREFIX + '*')):
        try:
            if time.time() - os.path.getmtime(old) > NARR_STALE_S: remove_with_retries(old)
        except OSError: pass
    words = narr.get('words')
    if isinstance(words, str):
        try:
            with open(words, encoding='utf-8') as fh: words = json.load(fh)
        except (OSError, ValueError) as e:
            raise ValueError(f'words file could not be read: {e}')
    with open(scene_path, encoding='utf-8') as fh: html = fh.read()
    html = narrate_module().build_narrated_html(html, narr.get('wav'), words, style=narr.get('style', 'pop'), yh=narr.get('yh', 0.88),
                                                gain=narr.get('gain', 1.0), captions=narr.get('captions', True), info=info)
    path = os.path.join(d, f'{NARR_PREFIX}{uuid.uuid4().hex[:8]}_{os.path.splitext(os.path.basename(scene_path))[0]}.html')
    with open(path, 'w', encoding='utf-8') as fh: fh.write(html)
    if os.name == 'nt':
        try:
            import ctypes; ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)   # FILE_ATTRIBUTE_HIDDEN
        except Exception: pass
    return path

def render_item(scene, mp4, preset, opts, narr=None, cancel=None, progress=lambda *_: None, info=None, warns=None):
    """Render one queue item. Without narration this is exactly rc.render(scene, ...). With narration: check cancel,
    build the hidden temp scene, force sound='generated' (the voice is mixed inside the page's SOUND kit), render it
    to mp4 (the name comes from the caller, i.e. the original scene) and always delete the temp file."""
    opts = dict(opts); bl = {k: opts.pop(k) for k in ('engine', 'device', 'allow_scripts') if k in opts}   # Blender-only settings
    vo = {k: opts.pop(k) for k in ('video_mode', 'song_start', 'loop_end') if k in opts}   # video + song only (3.18)
    if vsong.is_video(scene):   # a finished video + a song: video_song arranges and joins them (no browser)
        if narr: raise ValueError('narration is for HTML scenes; a video gets a song (put <video>.mp3 next to it)')
        song = opts.get('audio_file') if opts.get('sound') == 'file' else None
        return vsong.render(scene, song, mp4, mode=vo.get('video_mode') or 'auto', song_start=vo.get('song_start'),
                            loop_end=vo.get('loop_end'), progress=progress, cancel=cancel, info=info)
    if opts.get('lufs') is None:   # loudness per channel: songs -14, the rest -15, or the scene's own shadow-lufs
        opts['lufs'] = target_lufs(scene, opts.get('sound', 'generated'), opts.get('audio_file'), narrated=bool(narr))
    if bc.is_blend(scene):   # Blender scene: same contract as rc.render (folders, audio rules, QC all the same)
        if narr: raise ValueError('narration with word captions works for HTML scenes only; for a .blend put the voice in its sound')
        return bc.render(scene, mp4, preset, progress=progress, cancel=cancel, info=info, **opts, **bl)
    if not narr:
        return rc.render(scene, mp4, preset, progress=progress, cancel=cancel, info=info, **opts)
    if cancel is not None and cancel.is_set(): raise rc.Cancelled()
    opts = dict(opts, sound='generated', audio_file=None)
    tmp = None
    try:
        ninfo = {}
        tmp = narrate_for_render(scene, narr, info=ninfo)
        if warns is not None: warns.extend(f'{os.path.basename(scene)}: {w}' for w in ninfo.get('warnings', []))
        if cancel is not None and cancel.is_set(): raise rc.Cancelled()
        return rc.render(tmp, mp4, preset, progress=progress, cancel=cancel, info=info, **opts)
    finally:
        if tmp: remove_with_retries(tmp)

def render_scene(f, preset, out, opts, narr=None, cancel=None, progress=lambda *_: None, used=None, embedded=False,
                 fmt_name=None, warns=None):
    """Render ONE queue item exactly as the GUI queue does (App._run_one and tools/mcp_server.py both call this):
    <out>\\<scene name>\\<scene>.mp4 (or _shorts.mp4), never overwriting; Format Auto and Sound Auto per file; narration
    forces generated sound; ffprobe size/audio check; QC report; thumbnail; failure log in the scene folder; an empty folder
    left by a cancelled item is removed. Never raises (cancel / errors come back in the result).
    f: the ORIGINAL scene; opts: dict(vertical, format, sound, audio_file, capture) like App.opts; used: set of mp4 paths
    already given out in this batch; embedded: the scene already contains narration; warns: list the warnings are added to.
    opts['skip_done'] = True: a scene whose <scene>.mp4 is up to date (up_to_date()) is not rendered again ('skipped').
    A narrated render also gets <video>.srt (from the words.json used) next to the mp4.
    Returns dict(status='done'|'cancelled'|'error'|'skipped', row (the Status column text), mp4, dur, error (one line + log
    path), log, qc (qc result or None), qc_report, thumb, srt, sound (mode actually used), vertical, warns)."""
    warns = [] if warns is None else warns; used = set() if used is None else used
    opts = dict(opts); used_mode = {}; skip_done = bool(opts.pop('skip_done', False))
    fmt_name = fmt_name or opts.get('format') or '16:9 (YouTube)'
    if opts.get('format') == FORMAT_AUTO:   # Format = Auto (by file name): 9:16 for short_*.html, 16:9 for the rest
        opts['vertical'] = format_vertical(f, FORMAT_AUTO)
        fmt_name = '9:16 (Shorts)' if opts['vertical'] else '16:9 (YouTube)'
    opts.pop('format', None)   # render_item / render_core do not take it
    opts['vertical'] = bool(opts.get('vertical'))
    if vsong.is_video(f):   # video + song: its own shape, and a song is needed whatever Sound says (Auto = <video>.mp3 next to it)
        opts['vertical'] = format_vertical(f, FORMAT_AUTO); fmt_name = '9:16 (Shorts)' if opts['vertical'] else '16:9 (YouTube)'
        if opts.get('sound') != 'file': opts['sound'] = 'auto'
        narr = None
    main = category_folder(f, opts.pop('folder', None), opts.get('sound', 'generated'), opts.get('audio_file'), narrated=bool(narr or embedded))
    sub, name = output_place(f, opts['vertical'], main); folder = os.path.join(out, sub)
    if skip_done:   # already rendered and nothing it uses changed since: keep that file, render nothing
        old = up_to_date(f, out, opts['vertical'], render_deps(f, opts, narr),
                         expect=None if vsong.is_video(f) else expected_size(preset, opts['vertical']), main=main)
        if old and os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(f)): old = None   # the source video itself
        if old:
            log.info('skipped %s: %s is up to date', f, old)
            return dict(status='skipped', row=SKIPPED_UP_TO_DATE, mp4=old, dur=None, error=None, log=None, qc=None, qc_report=None,
                        thumb=None, srt=None, sound=None, vertical=opts['vertical'], warns=warns)
    mp4 = unique_path(os.path.join(folder, name + '.mp4'), used)   # never overwrite: not a file on disk, not one from this batch
    used.add(mp4)
    res = dict(status='error', row='Error', mp4=mp4, dur=None, error=None, log=None, qc=None, qc_report=None, thumb=None,
               srt=None, sound=None, vertical=opts['vertical'], warns=warns)
    created = False
    if narr and opts['sound'] not in ('generated', 'auto'):   # the voice lives in the page's own sound: External file / None would drop it
        warns.append(f'{os.path.basename(f)}: narration needs generated sound, used Generated for this file.')
    if narr:
        opts['sound'] = 'generated'; opts['audio_file'] = None
    elif opts['sound'] == 'auto':   # per scene: <scene>.mp3/.wav/... next to it, else the scene's own sound (warned)
        ra = resolve_audio(f, 'auto', narrated=embedded)
        opts['sound'], opts['audio_file'] = ra['sound'], ra['audio_file']
        if ra['warn']: warns.append(ra['warn'])
        log.info('auto audio for %s: %s', f, ra['audio_file'] or ra['label'])
    stopped = lambda: cancel is not None and cancel.is_set()
    try:
        created = not os.path.isdir(folder)
        os.makedirs(folder, exist_ok=True)
        log.info('render %s -> %s%s', f, mp4, ' (with narration)' if narr else '')
        render_item(f, mp4, preset, opts, narr=narr, cancel=cancel, progress=progress, info=used_mode, warns=warns)
        warns.extend(f'{os.path.basename(f)}: {w}' for w in used_mode.get('warnings', []))   # Blender: missing files, no 9:16 camera...
        silent = opts['sound'] == 'generated' and used_mode.get('sound') == 'none'
        if silent: warns.append(f'{os.path.basename(f)}: the scene has no sound, rendered silent.'); opts['sound'] = 'none'
        exp = used_mode.get('size') or expected_size(preset, opts['vertical']); pr = probe(mp4)
        if pr is None:
            warns.append(f'{os.path.basename(mp4)}: could not check the output (ffprobe missing?).'); dur = None
        else:
            dur = fmt(pr[2]) if pr[2] >= 1 else f'{pr[2]:.1f}s'
            if (pr[0], pr[1]) != exp:
                warns.append(f'{os.path.basename(mp4)} is {pr[0]}x{pr[1]}, expected {exp[0]}x{exp[1]} for {fmt_name}.')
            if opts['sound'] != 'none' and not pr[3]:
                warns.append(f'{os.path.basename(mp4)} has no audio track.')
        log.info('done %s %s', mp4, pr)
        row = 'Done (silent)' if silent else 'Done'
        if not stopped():   # QC: only adds information, never changes Done or the file
            try:
                qres, qpath = quality_check(mp4, preset, opts['vertical'], used_mode, opts['sound'])
                res.update(qc=qres, qc_report=qpath)
                if qres:
                    row += f" · QC {qres['status']}"
                    if qres['status'] != qc.OK:
                        warns.append(f"{os.path.basename(mp4)}: QC {qres['status']} - {'; '.join(qres['reasons'])}" + (f' (report: {qpath})' if qpath else ''))
            except Exception:
                log.error('qc hook failed for %s\n%s', mp4, traceback.format_exc())
            if used_mode.get('thumbnail_t') is not None:   # the scene asked for a thumbnail (window.THUMBNAIL_T)
                th = save_thumbnail(mp4, used_mode['thumbnail_t'], opts['vertical'])
                if th: row += ' · thumb'; res['thumb'] = th
            if narr and narr.get('words'):   # subtitles for YouTube from the same word timings the captions use
                res['srt'] = write_srt(mp4, narr['words'])
        res.update(status='done', row=row, dur=dur, sound=opts['sound'])
    except rc.Cancelled:
        log.info('cancelled %s', f); res.update(status='cancelled', row='Cancelled')
    except Exception as e:
        tb = traceback.format_exc()
        log.error('failed %s\n%s', f, tb)
        flog = write_failure_log(f, mp4, preset, opts, e, tb, log_dir=folder if os.path.isdir(folder) else None)
        first = (str(e).strip().splitlines() or [type(e).__name__])[0].replace('Page.evaluate: ', '')
        res.update(status='error', row='Error', log=flog, error=f'{os.path.basename(f)}: {first}' + (f'\nLog: {flog}' if flog else ''))
    finally:
        if created:   # a folder this item made and left empty (cancelled before anything was written) is removed again
            try: os.rmdir(folder)   # only succeeds when empty
            except OSError: pass
    return res

def narration_problem(scene, wav, words, style='pop'):
    """Why this narration cannot be attached to scene (an error string), or None. The checks App.set_narration uses
    (wav and words.json readable and well-formed, style, the scene not narrated already, a Shadow scene with SOUND/seek)."""
    if bc.is_blend(scene): return 'narration with word captions works for HTML scenes only (a .blend uses <scene>.wav as its sound)'
    try:
        if not wav or not os.path.isfile(wav): return f'narration WAV not found: {wav}'
        if not words: return 'no words.json given'
        if isinstance(words, str):
            if not os.path.isfile(words): return f'words file not found: {words}'
            try:
                with open(words, encoding='utf-8') as fh: wj = json.load(fh)
            except (OSError, ValueError) as e: return f'words file could not be read: {e}'
        else:
            wj = words
        wl = wj['words'] if isinstance(wj, dict) and 'words' in wj else wj
        if not isinstance(wl, list) or not wl or not all(isinstance(x, dict) and {'w', 's', 'e'} <= set(x) for x in wl):
            return 'words must be a non-empty list of {"w","s","e"} (or {"words": [...]})'
        mod = narrate_module()
        if style not in mod.STYLES: return f'style must be one of {", ".join(mod.STYLES)}, got {style!r}'
        with open(scene, encoding='utf-8') as fh: html = fh.read()
        if mod.is_narrated(html): return f'{os.path.basename(scene)} already has narration built in'
        if 'SOUND' not in html or 'seek' not in html: return f'{os.path.basename(scene)} is not a Seekframe scene with a SOUND kit'
        return None
    except Exception as e:
        log.exception('narration_problem'); return f'{type(e).__name__}: {e}'

def save_thumbnail(mp4, t, vertical):
    """<name>_thumb.jpg next to the mp4: the frame at t seconds, 1280x720 (720x1280 for 9:16), as YouTube wants.
    Only for scenes that set window.THUMBNAIL_T. Never raises (a failed thumbnail must not fail the render); returns the path or None."""
    try:
        out = unique_path(os.path.splitext(mp4)[0] + '_thumb.jpg'); size = '720:1280' if vertical else '1280:720'
        r = subprocess.run([rc.find_ffmpeg(), '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', mp4, '-frames:v', '1', '-vf', f'scale={size}', '-q:v', '2', out],
                           capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode == 0 and os.path.exists(out): log.info('thumbnail %s at %.2f s', out, t); return out
        log.error('thumbnail failed for %s: %s', mp4, r.stderr.decode('utf-8', 'replace')[-300:])
    except Exception:
        log.error('thumbnail failed for %s\n%s', mp4, traceback.format_exc())
    return None

def quality_check(mp4, preset, vertical, info, sound):
    """Post-render QC (qc.run_qc + qc.write_report) for a finished mp4. Returns (result, report_path), or (None, None) if
    the QC code itself broke - that is only logged. Never raises, never touches the mp4.
    info: render_core's info dict (duration = what was rendered); sound: the mode actually used ('none' = silent by design)."""
    try:
        w, h = (info or {}).get('size') or expected_size(preset, vertical)   # a video + song keeps the video's size
        res = qc.run_qc(mp4, dict(width=w, height=h, duration=(info or {}).get('duration'), silent=(sound == 'none'),
                                      lufs=(info or {}).get('lufs')))
        path = qc.write_report(mp4, res)
        log.info('qc %s %s: %s%s', res['status'], mp4, '; '.join(res['reasons']) or 'no issues', f' (report {path})' if path else '')
        return res, path
    except Exception:
        log.error('qc crashed for %s (render kept as is)\n%s', mp4, traceback.format_exc())
        return None, None

def video_check(video, song):
    """Check frames for a video + song (3.18): Shadow's own look at the video (contact sheet <video>.check.jpg next to it,
    motion, cuts, loop point), the song's beats / chorus and the arrangement it will render, as a frame_check-like result."""
    sheet = os.path.splitext(video)[0] + '.check.jpg'
    v = vsong.look(video, sheet=sheet)
    if not song: return dict(ok=False, sheet=v['sheet'], problems=[f'no song: put {os.path.splitext(os.path.basename(video))[0]}.mp3 next to the video, or choose Sound = External file'],
                             notes=vsong.describe(v, dict(dur=0, bpm=None, chorus=None, source='none'), dict(mode='-', reason='needs a song', song_start=0, out_dur=v['dur'], fade_out=0))[:4])
    s = vsong.song_info(song, clip_len=v['dur']); pl = vsong.plan(v, s)
    return dict(ok=True, sheet=v['sheet'], problems=[], notes=vsong.describe(v, s, pl))

def expected_size(preset, vertical):
    w = preset['w']; return (round(w * 9 / 16), w) if vertical else (w, round(w * 9 / 16))

def probe(mp4):
    """(width, height, seconds, has_audio) of a rendered file, or None."""
    ff = rc.find_ffmpeg()
    exe = shutil.which('ffprobe') or (os.path.join(os.path.dirname(ff), 'ffprobe' + ('.exe' if os.name == 'nt' else '')) if ff else None)
    if not exe or not os.path.exists(exe): return None
    r = subprocess.run([exe, '-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'json', mp4],
                       capture_output=True, text=True, creationflags=NOWIN)
    try: j = json.loads(r.stdout)
    except Exception: return None
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not v: return None
    return v['width'], v['height'], float(j.get('format', {}).get('duration', 0) or 0), any(s.get('codec_type') == 'audio' for s in j['streams'])


def dpi_aware():
    """Sharp text on scaled displays (Tk then scales its fonts itself)."""
    if os.name != 'nt': return
    try:
        import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

class App(Root):
    def __init__(self):
        super().__init__()
        setup_log()
        self.title(tr('Seekframe v{0}', rc.VERSION))
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))   # exe: unpacked bundle; source: project folder
        ico = os.path.join(base, 'assets', 'shadow.ico')
        try:
            if os.path.exists(ico): self.iconbitmap(default=ico)   # default= also covers the message boxes
        except Exception: pass
        # self.cancel = "Stop queue" (the whole batch); self.item_cancel = a fresh Event per file, the one render() watches,
        # so "Cancel current" stops only that file and can never leak into the next one
        self.q = queue.Queue(); self.cancel = threading.Event(); self.item_cancel = threading.Event(); self.worker = None
        cfg = load_cfg(); self.files = []; self.rows = {}
        self.lang = i18n.set_lang(i18n.pick(cfg.get('language'))); self.lang_choice = cfg.get('language', 'auto')   # 3.20
        # the live queue: self.files (order) + self.state[path] = 'queued' | 'running' | 'finished' | 'skipped'.
        # The worker takes the next 'queued' file under self.lock, so files added/removed while rendering are honoured.
        self.state = {}; self.lock = threading.Lock()
        self.project_path = None   # the .shadow file opened / saved last (Project > Save project)
        self.narr = {}   # path -> narration settings for that file (see narrate_for_render); set by the UI later
        self.out_mp4 = {}   # path -> the mp4s this session rendered (or found up to date) for that row: the YouTube dialog uploads them
        self.embedded = set()   # files whose HTML already carries narration (shown as [voice embedded], never narrated again)
        self.theme_choice = cfg.get('theme') if cfg.get('theme') in ('dark', 'light') else None   # None = follow Windows
        self.theme = self.theme_choice or system_theme()
        self.out_dir = tk.StringVar(value=cfg.get('out', os.path.join(os.path.expanduser('~'), 'Videos')))
        q = cfg.get('preset'); self.preset = tk.StringVar(value=q if q in rc.PRESETS else 'Best (1080p, 64 samples)')
        self.open_when_done = tk.BooleanVar(value=cfg.get('open', True))
        self.skip_done = tk.BooleanVar(value=cfg.get('skip_done', True))   # don't render a scene again whose mp4 is up to date
        self.notify = tk.BooleanVar(value=cfg.get('notify', True))         # Windows notification when the queue ends
        self._dur_cache = {}   # path -> (key, seconds or None): scene lengths for the time estimate
        self._spf = {}         # measured seconds per frame in this batch: {'html': s, 'blend': s}
        self._run_t0 = {}      # path -> time its render started (the Time column shows how long it took)
        self._cur_left = None  # (path, seconds left) of the file rendering now
        self.check_thread = None; self.check_results = []; self.check_kw = {}   # Check frames (check_kw: tests pass Chrome options)
        self.cfg_ai = dict(cfg.get('ai') or {})
        assistant.AUTH_MODE = 'api_key' if self.cfg_ai.get('auth') == 'api_key' else 'subscription'
        ai_tasks.ENGINE = self.cfg_ai.get('engine') if self.cfg_ai.get('engine') in ai_tasks.ENGINES else 'claude'   # 3.32
        ai_tasks.GEMINI_AUTH = 'api_key' if self.cfg_ai.get('gemini_auth') == 'api_key' else 'account'   # 3.34
        self.cloud_up = cfg.get('cloud_upload') if cfg.get('cloud_upload') in cloud.LABEL else ''   # 3.33: upload finished videos there
        self.upload_q = None   # 3.33: the cloud upload thread's queue (made on the first upload)
        self._using_prev = None   # 3.32: AI apps using Seekframe at the last check (a new one -> notification)   # 3.30 Settings > AI account   # New video (AI): style, length, voice, dir, voice_python (3.19)
        self.row_problems = {}   # path -> what went wrong last (render error + log, QC, Check frames): the AI window starts from it
        f = cfg.get('format'); self.fmt = tk.StringVar(value=f if f in FORMAT_CHOICES else '16:9 (YouTube)')
        c = OLD_CAPTURE_LABELS.get(cfg.get('capture'), cfg.get('capture')); self.capture = tk.StringVar(value=c if c in CAPTURES else next(iter(CAPTURES)))
        self.folders = [safe_rel_folder(x) for x in cfg.get('folders', DEFAULT_FOLDERS) if safe_rel_folder(x)] or list(DEFAULT_FOLDERS)
        fc = cfg.get('folder', FOLDER_AUTO); self.folder_choice = tk.StringVar(value=fc if fc in self.folder_values() else FOLDER_AUTO)
        e = cfg.get('blender_engine'); self.bl_engine = tk.StringVar(value=e if e in BLENDER_ENGINES else BLENDER_ENGINES[0])
        s = cfg.get('sound'); self.snd = tk.StringVar(value=s if s in SOUNDS else SOUNDS[0]); self.snd_file = tk.StringVar(value=cfg.get('sound_file', ''))
        # Assistant panel (assistant.py: Claude Code CLI headless, the owner's subscription). ai_kw: tests pass a fake CLI
        self.ai = None; self.ai_kw = {}; self.ai_dir_choice = cfg.get('assistant_dir', ''); self.ai_open = bool(cfg.get('assistant_open', False))
        self.ai_pending = None; self.ai_t0 = None; self.ai_last = None
        self.side_open = bool(cfg.get('sidebar', True))   # 3.28: the sidebar, shown or hidden by the menu button
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.apply_theme()
        self.build()
        self.apply_theme(refresh=True)   # sv-ttk set before the widgets exist leaves wrong fonts/colours on the first pass
        self.check()
        self._clients_id = self.after(1500, self._poll_clients)   # 3.32: AI connections, then every 45 s
        self.update_idletasks()   # size the window to its content (fonts scale with the display DPI), the tallest page counts
        rw, rh = self.winfo_reqwidth(), self.winfo_reqheight()
        # (the pages share one grid cell, so the window already asks for the tallest one)
        w, h = max(rw, int(self.winfo_fpixels('8i'))), rh + int(self.winfo_fpixels('0.3i'))
        h = min(h, self.winfo_screenheight() - int(self.winfo_fpixels('0.9i')))   # 3.33: never taller than the screen (taskbar)
        self.minsize(rw, min(rh, h)); self.geometry(f'{w}x{h}')
        self._poll_id = self.after(150, self.poll)
        self.update_rel = None; self.update_busy = False; self.update_checking = False
        self.update_seen = cfg.get('update_seen')   # 3.31: the version the Windows notification was shown for
        self.after(2500, self.start_update_check)

    # ------------------------------------------------------------------ updates (GitHub Releases, see updater.py)
    def start_update_check(self, manual=False):
        # automatic check (at start): only the installed exe, and silent when offline. manual = the 'Check for updates' button
        if not updater.configured():
            if manual: messagebox.showinfo(tr('Update'), tr('Updates are not set up in this build (updater.REPO).'))
            return
        if not manual and not (getattr(sys, 'frozen', False) or os.environ.get('SHADOW_UPDATE_URL')): return
        if self.update_checking: return
        self.update_checking = True
        if manual: self.update_btn.config(text=tr('Checking...'), state='disabled')
        def run():
            try:
                rel = updater.latest_release()
                if rel and updater.is_newer(rel['version'], rc.VERSION): self.q.put(('update', rel, manual))
                else: self.q.put(('update_none', manual, rel['version'] if rel else None))
            except Exception as e:
                log.info('%s', e); self.q.put(('update_none', manual, e))   # offline / rate limited: quiet unless manual
        threading.Thread(target=run, daemon=True).start()
    def on_update_btn(self):
        if self.update_rel: self.do_update()
        else: self.start_update_check(manual=True)
    def show_update(self, rel, manual=False):
        self.update_checking = False; self.update_rel = rel
        self.update_btn.config(text=tr('Update to v{0}', rel['version']), style='Accent.TButton', state='normal')
        # 3.31 notice: a bar in the window, and once per new version a Windows notification
        self.update_lbl.config(text=tr('Seekframe v{0} is available (you have v{1}).', rel['version'], rc.VERSION))
        if not self.update_bar.winfo_manager(): self.update_bar.pack(fill='x', padx=14, pady=(0, 6), before=self.page_box)
        if not manual and self.update_seen != rel['version']:
            self.update_seen = rel['version']; self.save()
            notify(tr('Seekframe update'), tr('Version {0} is ready to install. Open Seekframe and press Update now.', rel['version']))
        if manual: self.do_update()
    def hide_update_bar(self):
        self.update_bar.pack_forget()
    def update_none(self, manual, info):
        self.update_checking = False; self.update_btn.config(text=tr('Check for updates'), state='normal')
        if not manual: return
        if isinstance(info, Exception):
            messagebox.showwarning(tr('Update'), tr('Could not check for updates (no internet?).\n\n{0}', info))
        else:
            messagebox.showinfo(tr('Update'), tr('You have the latest version (v{0}).', rc.VERSION))
    def do_update(self):
        rel = self.update_rel
        if not rel or self.update_busy: return
        if not (getattr(sys, 'frozen', False) or os.environ.get('SHADOW_UPDATE_URL')):
            messagebox.showinfo(tr('Update'), tr('Seekframe v{0} is available. This copy runs from source: update it with git pull.', rel['version'])); return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(tr('Update'), tr('Wait until the render queue has finished, then press Update again.')); return
        # only the first paragraph (what changed); the rest of the release text is download help for the GitHub page
        first = re.split(r'\r?\n\s*\r?\n', rel['notes'].strip(), maxsplit=1)[0]
        notes = first[:1200] + ('...' if len(first) > 1200 else '')
        if not messagebox.askyesno(tr('Update'), f'Seekframe v{rel["version"]} is available (you have v{rc.VERSION}).\n\n'
                                   + (notes + '\n\n' if notes else '') + 'Download and install it now? Seekframe closes and opens again by itself.'):
            return
        self.update_busy = True; self.update_btn.config(state='disabled'); self.update_now.config(state='disabled'); self.go.config(state='disabled')
        dest = os.path.join(os.environ.get('TEMP') or os.path.expanduser('~'), 'Shadow-update')
        for old in glob.glob(os.path.join(dest, '*')):   # setups from earlier updates
            try: os.remove(old)
            except OSError: pass
        def prog(got, total): self.q.put(('update_p', got, total))
        def run():
            try: self.q.put(('update_ready', updater.download(rel, dest, progress=prog)))
            except Exception as e:
                log.error('update download: %s', e); self.q.put(('update_fail', str(e)))
        threading.Thread(target=run, daemon=True).start()
    def run_installer(self, path):
        # /SILENT: progress window only, same folder and shortcuts as before; /relaunch=1 makes the setup start Shadow again
        try:
            subprocess.Popen([path, '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/relaunch=1'], env=updater.child_env())
        except Exception as e:
            self.update_failed(str(e)); return
        self.on_close()
    def update_failed(self, msg):
        self.update_busy = False; self.update_btn.config(state='normal'); self.update_now.config(state='normal'); self.go.config(state='normal')
        self.status.config(text=tr('Update failed')); messagebox.showerror(tr('Update'), tr('{0}\n\nYou can also download the setup from:\n{1}', msg, self.update_rel.get('page') or updater.REPO))

    # ------------------------------------------------------------------ layout (3.28: sidebar + pages)
    # Icons from Windows' own icon font (Segoe Fluent Icons on Windows 11, Segoe MDL2 Assets on 10); text only without them.
    NAV_ICONS = {'menu': '', 'queue': '', 'new': '', 'ai': '', 'youtube': '', 'project': '',
                 'cloud': '', 'assistant': '', 'settings': '', 'about': ''}
    SIDE_COLORS = {'dark': dict(bg='#191b1f', hover='#262a31', sel='#2f3640', fg='#c8ccd4', fg_sel='#ffffff', muted='#7d8491', line='#2a2e35'),
                   'light': dict(bg='#e4e4e2', hover='#d8d8d5', sel='#cdd5e3', fg='#2b2b2b', fg_sel='#101010', muted='#6b6b6b', line='#d0d0cc')}

    def build(self):
        P = 14
        edit_bindings(self, tr)   # 3.35: Ctrl+C/V/X/A/Z on any keyboard layout + right-click Cut/Copy/Paste/Select all, every window
        k = self.winfo_fpixels('1i') / 96
        try:
            import tkinter.font as tkf
            fams = set(tkf.families(self))
            self.icon_font = next((f for f in ('Segoe Fluent Icons', 'Segoe MDL2 Assets') if f in fams), None)
        except Exception:
            self.icon_font = None
        # ---- sidebar (can be hidden: the menu button, setting 'sidebar')
        self.side = tk.Frame(self, width=round(200 * k)); self.side.pack_propagate(False)
        self.body = ttk.Frame(self)
        self.side.pack(side='left', fill='y'); self.body.pack(side='left', fill='both', expand=True)
        self.nav = {}
        brand = tk.Frame(self.side); brand.pack(fill='x', padx=12, pady=(16, 14))
        self.side_title = tk.Label(brand, text='Seekframe', font='SunValleySubtitleFont', anchor='w'); self.side_title.pack(fill='x')
        self.side_ver = tk.Label(brand, text=f'v{rc.VERSION}', anchor='w'); self.side_ver.pack(fill='x')
        for key, text, cmd in (('queue', 'Queue', lambda: self.show_page('queue')), ('new', 'New video', self.open_new_video),
                               ('ai', 'AI tools', self.open_ai), ('youtube', 'YouTube...', self.open_youtube_dialog), ('cloud', 'Cloud...', self.open_cloud),
                               ('project', 'Project', self.project_menu), ('assistant', 'Assistant', self.toggle_assistant)):
            self._nav_item(key, tr(text), cmd)
        self._studio_mark(k)   # 3.31: Shadow Studio at the very bottom
        for key, text in (('about', 'About'), ('settings', 'Settings')):
            self._nav_item(key, tr(text), lambda k_=key: self.show_page(k_), side='bottom')
        self.ai_btn = self.nav['assistant']; self.proj_btn = self.nav['project']; self.new_btn = self.nav['new']; self.cloud_btn = self.nav['cloud']   # 3.33: in the sidebar (the queue row stays narrow)

        # ---- header of the page area: menu button, page title, theme
        hdr = ttk.Frame(self.body); hdr.pack(fill='x', padx=P, pady=(P, 6))
        self.menu_btn = ttk.Button(hdr, text=self.NAV_ICONS['menu'] if self.icon_font else '≡', width=3, command=self.toggle_sidebar)
        if self.icon_font:
            st = ttk.Style(self); st.configure('Icon.TButton', font=(self.icon_font, 11)); self.menu_btn.config(style='Icon.TButton')
        self.menu_btn.pack(side='left')
        self.page_title = ttk.Label(hdr, text='', font='SunValleySubtitleFont'); self.page_title.pack(side='left', padx=(10, 0))
        self.theme_btn = ttk.Button(hdr, width=9, command=self.toggle_theme); self.theme_btn.pack(side='right')
        self._top = hdr
        self._theme_text()
        # 3.31: a new version shows this bar under the header (packed by show_update, hidden by Later)
        self.update_bar = ttk.Frame(self.body, padding=(10, 6), style='Card.TFrame')
        self.update_lbl = ttk.Label(self.update_bar, text=''); self.update_lbl.pack(side='left')
        ttk.Button(self.update_bar, text=tr('Later'), command=self.hide_update_bar).pack(side='right')
        ttk.Button(self.update_bar, text=tr("What's new"), command=lambda: webbrowser.open((self.update_rel or {}).get('page')
                   or f'https://github.com/{updater.REPO}/releases/latest')).pack(side='right', padx=6)
        self.update_now = ttk.Button(self.update_bar, text=tr('Update now'), style='Accent.TButton', command=self.do_update)
        self.update_now.pack(side='right')
        # the pages sit on top of each other in one grid cell; switching only raises one (no re-layout: 117 ms -> ~1 ms)
        self.page_box = ttk.Frame(self.body); self.page_box.pack(fill='both', expand=True)
        self.page_box.rowconfigure(0, weight=1); self.page_box.columnconfigure(0, weight=1)
        self.pages = {n: ttk.Frame(self.page_box) for n in ('queue', 'settings', 'about')}
        for f in self.pages.values(): f.grid(row=0, column=0, sticky='nsew')

        # ==== Queue page: scenes, progress, actions
        qp = self.pages['queue']
        card = ttk.LabelFrame(qp, text=tr('Scenes'), padding=10); card.pack(fill='both', expand=True, padx=P, pady=(4, 10))
        dz = ttk.Frame(card, style='Card.TFrame', padding=14, cursor='hand2'); dz.pack(fill='x')
        self.drop = ttk.Label(dz, anchor='center', cursor='hand2', font='SunValleyBodyLargeFont',
                              text=(tr('⤓   Drop .html or .blend scenes here, or click to browse') if HAS_DND else tr('Click to add .html or .blend scenes')))
        self.drop.pack(fill='x')
        for w in (dz, self.drop): w.bind('<Button-1>', lambda e: self.add())
        self.dz = dz
        tf = ttk.Frame(card); tf.pack(fill='both', expand=True, pady=(8, 8))
        # values: name, status, dur, audio, fmt, time (new columns go last so older code/tests keep their indices)
        # time: the estimate before the render (~3 min), the time left while it renders, how long it took when finished
        self.tree = ttk.Treeview(tf, columns=('name', 'status', 'dur', 'audio', 'fmt', 'time'), displaycolumns=('name', 'status', 'dur', 'time', 'fmt', 'audio'),
                                 show='headings', height=8, selectmode='extended')
        for c, t, w, st in (('name', 'Name', 300, True), ('status', 'Status', 200, True), ('dur', 'Duration', 80, False),
                            ('audio', 'Audio', 170, True), ('fmt', 'Format', 70, False), ('time', 'Time', 90, False)):
            self.tree.heading(c, text=tr(t), anchor='w'); self.tree.column(c, width=round(w * k), minwidth=round(60 * k), stretch=st, anchor='w')
        sb = ttk.Scrollbar(tf, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.bind('<Double-1>', lambda e: self.preview()); self.tree.bind('<Delete>', lambda e: self.remove())
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._update_narr_btn())
        if HAS_DND:
            for w in (self.dz, self.drop, self.tree):
                w.drop_target_register(DND_FILES); w.dnd_bind('<<Drop>>', self.on_drop)
        bt = ttk.Frame(card); bt.pack(fill='x')
        btns = {}
        for i, (t, c) in enumerate((('Add...', self.add), ('Add folder...', self.add_folder), ('Remove', self.remove), ('Clear', self.clear),
                                    ('Preview', self.preview), ('Check frames', self.check_frames), ('Narration...', self.open_narration_dialog),
                                    ('AI...', self.open_ai))):
            b = btns[t] = ttk.Button(bt, text=tr(t), command=c); b.grid(row=0, column=i, sticky='we', padx=(0 if i == 0 else 6, 0))
            bt.columnconfigure(i, weight=1, uniform='b')
        self.check_btn = btns['Check frames']
        self.narr_btn = btns['Narration...']; self.narr_btn.config(state='disabled')   # enabled when one row is selected that can take narration
        # the render options, right on the Queue page (3.30: one click away, not inside Settings)
        op = ttk.LabelFrame(qp, text=tr('Options'), padding=(10, 6)); op.pack(fill='x', padx=P)
        rows = (('Quality', self.preset, list(rc.PRESETS)), ('Format', self.fmt, FORMAT_CHOICES), ('Sound', self.snd, SOUNDS),
                ('Capture', self.capture, list(CAPTURES)), ('Blender', self.bl_engine, BLENDER_ENGINES))
        for i, (lbl, var, vals) in enumerate(rows):
            r, c = i % 3, (i // 3) * 2
            ttk.Label(op, text=tr(lbl)).grid(row=r, column=c, sticky='w', pady=2, padx=(0 if c == 0 else 18, 0))
            i18n.Combo(op, var, vals, width=30).grid(row=r, column=c + 1, sticky='w', padx=8, pady=2)   # shows translations, keeps keys
        ttk.Label(op, textvariable=self.snd_file, foreground='#888').grid(row=2, column=2, columnspan=2, sticky='w', padx=(18, 0))
        self.snd.trace_add('write', self.on_sound)
        self.fmt.trace_add('write', lambda *_: self.refresh_audio())   # the Format column follows the Format setting
        pr = ttk.Frame(qp); pr.pack(fill='x', padx=P, pady=(10, 0))
        self.bar = ttk.Progressbar(pr, maximum=100); self.bar.pack(side='left', fill='x', expand=True)
        self.pct = ttk.Label(pr, text='0%', width=16, anchor='e'); self.pct.pack(side='right', padx=(10, 0))
        sl = ttk.Frame(qp); sl.pack(fill='x', padx=P, pady=(4, 0))
        self.eta_lbl = ttk.Label(sl, text='', foreground='#888'); self.eta_lbl.pack(side='right')   # whole queue: about 12 min · done ~15:40
        self.status = ttk.Label(sl, text=tr('Ready'), foreground='#888'); self.status.pack(side='left')
        act = ttk.Frame(qp); act.pack(fill='x', padx=P, pady=P)
        self.go = ttk.Button(act, text=tr('Render'), style='Accent.TButton', command=self.start)
        self.stop_cur = ttk.Button(act, text=tr('Cancel current'), command=self.do_cancel_current, state='disabled')
        self.stop = ttk.Button(act, text=tr('Stop queue'), command=self.do_cancel, state='disabled')
        self.yt_btn = ttk.Button(act, text=tr('YouTube...'), command=self.open_youtube_dialog)
        for i, w in enumerate((self.go, self.stop_cur, self.stop, ttk.Button(act, text=tr('Open folder'), command=self.open_out), ttk.Button(act, text=tr('Open log'), command=self.open_log), self.yt_btn)):
            w.grid(row=0, column=i, sticky='we', padx=(0 if i == 0 else 6, 0)); act.columnconfigure(i, weight=1, uniform='a')
        chk = ttk.Frame(act); chk.grid(row=1, column=0, columnspan=6, sticky='w', pady=(8, 0))
        for t, v in (('Open folder when done', self.open_when_done), ('Skip scenes already rendered (up to date)', self.skip_done),
                     ('Notify me when the queue ends', self.notify)):
            ttk.Checkbutton(chk, text=tr(t), variable=v).pack(side='left', padx=(0, 18))

        # ==== Settings page: where videos go (PC, NAS, cloud), setup, Claude (MCP), AI account, language
        sp = self._scroll_page(self.pages['settings'])   # 3.33: Settings scrolls (it is taller than a laptop screen)
        op = ttk.LabelFrame(sp, text=tr('Save videos to'), padding=10); op.pack(fill='x', padx=P, pady=(4, 10))
        ttk.Label(op, text=tr('Save to')).grid(row=0, column=0, sticky='w', pady=3)
        ttk.Entry(op, textvariable=self.out_dir).grid(row=0, column=1, columnspan=2, sticky='we', padx=10, pady=3)
        ttk.Button(op, text=tr('Browse...'), command=self.pick_out).grid(row=0, column=3, sticky='e')
        ttk.Label(op, text=tr('Folder')).grid(row=1, column=0, sticky='w', pady=3)
        self.folder_box = i18n.Combo(op, self.folder_choice, self.folder_values(), width=32)
        self.folder_box.grid(row=1, column=1, sticky='w', padx=10, pady=3)
        ttk.Label(op, text=tr('Auto: songs -> Music, the rest -> Video (Short + video share one folder)'), foreground='#888').grid(row=1, column=2, sticky='w')
        ttk.Button(op, text=tr('New folder...'), command=self.add_main_folder).grid(row=1, column=3, sticky='e')
        cl = ttk.Frame(op); cl.grid(row=2, column=1, columnspan=3, sticky='w', padx=10, pady=(6, 0))
        self.cloud_btns = []   # 3.31: every place, found or not (one not found asks for its folder)
        places = storage_places() + [('Network drive (NAS)...', 'nas')]   # 3.34: no cloud-app buttons (the owner uploads himself)
        for i, (label, path) in enumerate(places):
            b = ttk.Button(cl, text=tr(label), command=lambda l=label, p=path: self.use_storage(p, l))
            b.grid(row=i // 4, column=i % 4, sticky='we', padx=(0, 6), pady=(0, 6)); self.cloud_btns.append(b)
        self.storage_btn = ttk.Button(cl, text=tr('Check access'), style='Accent.TButton', command=self.check_storage)
        self.storage_btn.grid(row=len(places) // 4, column=len(places) % 4, sticky='we', padx=(0, 6), pady=(0, 6))
        self.storage_lbl = ttk.Label(op, text=tr('A NAS works too: type its address, for example \\\\NAS\\Videos, or a mapped drive like Z:\\Videos.'),
                                     foreground='#888', wraplength=round(700 * k), justify='left')
        self.storage_lbl.grid(row=3, column=1, columnspan=3, sticky='w', padx=10, pady=(6, 0))
        op.columnconfigure(2, weight=1)
        # 3.33 cloud accounts: sign in in the browser (rclone), no cloud app needed; upload finished videos there
        ca = ttk.LabelFrame(sp, text=tr('Cloud accounts'), padding=10); ca.pack(fill='x', padx=P, pady=(0, 10))
        self.cloud_note = ttk.Label(ca, text='', foreground='#888', wraplength=round(700 * k), justify='left'); self.cloud_note.pack(anchor='w')
        self.rclone_btn = ttk.Button(ca, text=tr('Get rclone (free, about 30 MB)'), command=self.get_rclone)
        cg = ttk.Frame(ca); cg.pack(fill='x', pady=(6, 0))
        self.cloud_rows = {}
        for i, (key_, label, _t, _x) in enumerate(cloud.PROVIDERS):
            ttk.Label(cg, text=label).grid(row=i // 2, column=(i % 2) * 3, sticky='w', pady=2)
            st = ttk.Label(cg, text='', foreground='#888', width=26); st.grid(row=i // 2, column=(i % 2) * 3 + 1, sticky='w', padx=(8, 4))
            b = ttk.Button(cg, text=tr('Sign in'), width=10, command=lambda k_=key_: self.cloud_toggle(k_))
            b.grid(row=i // 2, column=(i % 2) * 3 + 2, sticky='w', padx=(0, 24), pady=2)
            self.cloud_rows[key_] = dict(st=st, btn=b)
        ur = ttk.Frame(ca); ur.pack(fill='x', pady=(8, 0))
        ttk.Label(ur, text=tr('Also upload finished videos to')).pack(side='left')
        self.cloud_up_box = ttk.Combobox(ur, state='readonly', width=18); self.cloud_up_box.pack(side='left', padx=8)
        self.cloud_up_box.bind('<<ComboboxSelected>>', lambda e: self.on_cloud_up())
        ttk.Label(ur, text=tr('(folder Seekframe in that account)'), foreground='#888').pack(side='left')
        self.cloud_accounts = {}
        self.after(800, self.refresh_cloud)
        su = ttk.LabelFrame(sp, text=tr('Setup'), padding=10); su.pack(fill='x', padx=P, pady=(0, 10))
        env = ttk.Frame(su); env.pack(fill='x')
        self.env_lbls = {}
        for key in ('Chrome', 'ffmpeg', 'playwright', 'Blender'):
            dot = ttk.Label(env, text='●'); dot.pack(side='left'); txt = ttk.Label(env, text=key); txt.pack(side='left', padx=(3, 14))
            self.env_lbls[key] = (dot, txt)
        ttk.Button(env, text=tr('Install missing'), command=self.install_missing).pack(side='right')
        self.selftest_btn = ttk.Button(env, text=tr('Self-test'), command=self.run_selftest); self.selftest_btn.pack(side='right')
        ttk.Button(env, text=tr('Re-check'), command=self.check).pack(side='right', padx=6)
        # 3.32 AI connections: every AI app found on this PC with a tick box (connect Seekframe to it, MCP) and a light
        # (green = connected, with "In use now" while it runs Seekframe); then which AI does Seekframe's own AI buttons
        mc = ttk.LabelFrame(sp, text=tr('AI connections'), padding=10); mc.pack(fill='x', padx=P, pady=(0, 10))
        mrow = ttk.Frame(mc); mrow.pack(fill='x')
        ttk.Label(mrow, text=tr('Tick an AI app to let it use Seekframe (render, check, upload).'), foreground='#888').pack(side='left')
        ttk.Button(mrow, text=tr('How to connect'), command=lambda: webbrowser.open(f'https://github.com/{updater.REPO}/blob/main/docs/MCP.md')).pack(side='right')
        ttk.Button(mrow, text=tr('Re-check'), command=lambda: (self.check_mcp(), self.refresh_account())).pack(side='right', padx=6)
        self.cli_box = ttk.Frame(mc); self.cli_box.pack(fill='x', pady=(6, 0))
        self.cli_rows = {}
        for i, c in enumerate(ai_clients.CLIENTS):
            var = tk.BooleanVar(value=False)
            dot = ttk.Label(self.cli_box, text='●', foreground='#888')
            cb = ttk.Checkbutton(self.cli_box, text=c.name, variable=var, command=lambda k=c.key: self.on_client(k))
            st = ttk.Label(self.cli_box, text='', foreground='#888')
            ib = ttk.Button(self.cli_box, text=tr('Copy install command'), command=lambda k_=c.key: self.copy_install(k_))
            dot.grid(row=i, column=0, sticky='w'); cb.grid(row=i, column=1, sticky='w', padx=(4, 18), pady=1); st.grid(row=i, column=2, sticky='w')
            ib.grid(row=i, column=3, sticky='w', padx=(12, 0), pady=1); ib.grid_remove()
            self.cli_rows[c.key] = dict(var=var, dot=dot, cb=cb, st=st, inst=ib)
        self.cli_missing = ttk.Label(mc, text='', foreground='#888', wraplength=round(700 * k), justify='left'); self.cli_missing.pack(anchor='w', pady=(4, 0))
        er = self.engine_row = ttk.Frame(mc); er.pack(fill='x', pady=(8, 0))
        self.cli_missing.pack_forget()   # shown only while another app uses Seekframe
        ttk.Label(er, text=tr("AI for Seekframe's own AI buttons:")).pack(side='left')
        self.engine = tk.StringVar(value=ai_tasks.ENGINE)
        self.engine_btns = {}
        for key_, name in ai_tasks.ENGINES.items():
            b = ttk.Radiobutton(er, text=name, value=key_, variable=self.engine, command=self.on_engine); b.pack(side='left', padx=(12, 0))
            self.engine_btns[key_] = b
        self.engine_lbl = ttk.Label(mc, text='', foreground='#888', wraplength=round(700 * k), justify='left'); self.engine_lbl.pack(anchor='w', pady=(4, 0))
        # 3.34 how that AI signs in: the account / subscription, or an API key of that company (stored encrypted)
        ar = ttk.Frame(mc); ar.pack(fill='x', pady=(8, 0))
        self.auth_title = ttk.Label(ar, text=''); self.auth_title.pack(side='left')
        self.ai_auth = tk.StringVar(value='api_key' if self.cfg_ai.get('auth') == 'api_key' else 'subscription')
        ttk.Radiobutton(ar, text=tr('Sign in with my account'), value='subscription', variable=self.ai_auth, command=self.on_ai_auth).pack(side='left', padx=(12, 0))
        ttk.Radiobutton(ar, text=tr('API key (paid per use)'), value='api_key', variable=self.ai_auth, command=self.on_ai_auth).pack(side='left', padx=(12, 0))
        self.login_btn = ttk.Button(ar, text=tr('Sign in...'), command=self.ai_login); self.login_btn.pack(side='left', padx=(16, 0))
        self.acct_state = {}   # engine -> (signed in?, text) from ai_tasks.account_status (a thread)
        kr = ttk.Frame(mc); kr.pack(fill='x', pady=(6, 0))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(kr, textvariable=self.key_var, show='•', width=46); self.key_entry.pack(side='left')
        ttk.Button(kr, text=tr('Save key'), command=self.save_key).pack(side='left', padx=(6, 0))
        ttk.Button(kr, text=tr('Remove key'), command=self.remove_key).pack(side='left', padx=(6, 0))
        self.key_lbl = ttk.Label(mc, text='', foreground='#888', wraplength=round(700 * k), justify='left'); self.key_lbl.pack(anchor='w', pady=(6, 0))
        self._engine_text()
        lg = ttk.LabelFrame(sp, text=tr('Language'), padding=10); lg.pack(fill='x', padx=P)
        # 3.20 language: 'Auto' = Windows' language when Seekframe has it; a change asks to restart
        self.lang_names = [tr('Auto (Windows)')] + list(i18n.LANGS.values())
        self.lang_var = tk.StringVar(value=self.lang_names[0] if self.lang_choice == 'auto' else i18n.LANGS.get(self.lang_choice, 'English'))
        self.lang_box = ttk.Combobox(lg, textvariable=self.lang_var, values=self.lang_names, state='readonly', width=24)
        self.lang_box.pack(side='left'); self.lang_box.bind('<<ComboboxSelected>>', lambda e: self.on_language())
        self._key_status()

        # ==== About page
        ap = self.pages['about']
        box = ttk.Frame(ap, padding=(P + 10, 20)); box.pack(fill='both', expand=True)
        self.about_logo = None
        try:
            from PIL import Image
            import base64, io
            for b in (getattr(sys, '_MEIPASS', None), os.path.dirname(os.path.abspath(__file__))):
                lp = b and os.path.join(b, 'assets', 'shadow.ico')
                if lp and os.path.isfile(lp):
                    with Image.open(lp) as im0: im = im0.convert('RGBA').resize((round(96 * k), round(96 * k)), Image.LANCZOS)
                    buf = io.BytesIO(); im.save(buf, 'PNG')
                    self.about_logo = tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()).decode('ascii'), format='png'); break
        except Exception:
            log.exception('about logo')
        head = ttk.Frame(box); head.pack(fill='x')
        if self.about_logo: ttk.Label(head, image=self.about_logo).pack(side='left', padx=(0, 16))
        hd2 = ttk.Frame(head); hd2.pack(side='left', fill='x')
        ttk.Label(hd2, text='Seekframe', font='SunValleyTitleLargeFont').pack(anchor='w')
        ttk.Label(hd2, text=tr('Version {0}', rc.VERSION), foreground='#888').pack(anchor='w')
        ttk.Label(hd2, text=tr('by Shadow Studio')).pack(anchor='w')
        wl = round(620 * k)
        ttk.Label(box, text=tr('A free, open-source app that turns code-made scenes (HTML and Blender) into finished videos for YouTube and Shorts, with a quality check on every video.'),
                  wraplength=wl, justify='left').pack(anchor='w', pady=(18, 4))
        ttk.Label(box, text=tr('Seekframe was called Shadow until version 3.24.'), foreground='#888').pack(anchor='w')
        lk = ttk.Frame(box); lk.pack(anchor='w', pady=(16, 0))
        base = f'https://github.com/{updater.REPO}'
        for i, (t, url) in enumerate((('GitHub page', base), ('User guide', base + '/blob/main/docs/GUIDE.md'),
                                      ("What's new", base + '/blob/main/CHANGELOG.md'), ('Report a problem', base + '/issues/new/choose'),
                                      ('Privacy policy', base + '/blob/main/docs/PRIVACY.md'), ('Shadow Studio', 'https://github.com/' + updater.REPO.split('/')[0]))):
            ttk.Button(lk, text=tr(t), command=lambda u=url: webbrowser.open(u)).grid(row=i // 3, column=i % 3, sticky='we', padx=(0, 8), pady=(0, 8))
        self.update_btn = ttk.Button(box, text=tr('Check for updates'), command=self.on_update_btn)   # 3.31: only here (not in the sidebar)
        self.update_btn.pack(anchor='w', pady=(8, 0))
        ttk.Label(box, text=tr('MIT license. Made with Python, Playwright, ffmpeg and sv-ttk; the AI features use your own Claude Code.'),
                  foreground='#888', wraplength=wl, justify='left').pack(anchor='w', pady=(18, 0))

        self.skip_done.trace_add('write', lambda *_: self.update_eta())
        for var in (self.preset, self.capture):
            var.trace_add('write', lambda *_: self.update_eta())
        self.page = None; self.show_page('queue')
        self.side_colors()
        if not self.side_open: self.side.pack_forget()
        self.build_assistant()

    def _nav_item(self, key, text, cmd, side='top'):
        """One row of the sidebar: an icon (Windows' icon font) and its label; the whole row is clickable."""
        row = tk.Frame(self.side, cursor='hand2'); row.pack(side=side, fill='x', padx=8, pady=1)
        ic = tk.Label(row, text=self.NAV_ICONS.get(key, '') if self.icon_font else '', width=2,
                      font=(self.icon_font, 11) if self.icon_font else None, anchor='center')
        ic.pack(side='left', padx=(8, 6), pady=7)
        lb = tk.Label(row, text=text, anchor='w', font='SunValleyBodyFont'); lb.pack(side='left', fill='x', expand=True, pady=7)
        row.parts = (row, ic, lb); row.key = key; row.cget_text = text
        for w in row.parts:
            w.bind('<Button-1>', lambda e: cmd()); w.bind('<Enter>', lambda e, r=row: self._nav_hover(r, True))
            w.bind('<Leave>', lambda e, r=row: self._nav_hover(r, False))
        row.invoke = cmd
        self.nav[key] = row
        return row

    def _nav_selected(self, key):
        return key == self.page or (key == 'assistant' and self.ai_open)

    def _studio_mark(self, k):
        """Bottom of the sidebar: the Shadow Studio logo + name, quiet (muted, small, spaced letters); a click opens the
        studio's GitHub page. A thin line above it separates it from Settings / About."""
        box = tk.Frame(self.side, cursor='hand2'); box.pack(side='bottom', fill='x', padx=14, pady=(4, 14))
        tk.Frame(self.side, height=1).pack(side='bottom', fill='x', padx=14, pady=(8, 6))   # the line (coloured in side_colors)
        self.studio_logo = None
        try:
            from PIL import Image
            import base64, io
            for b in (getattr(sys, '_MEIPASS', None), os.path.dirname(os.path.abspath(__file__))):
                lp = b and os.path.join(b, 'assets', 'shadow_studio.png')
                if lp and os.path.isfile(lp):
                    with Image.open(lp) as im0: im = im0.convert('RGBA').resize((round(26 * k),) * 2, Image.LANCZOS)
                    buf = io.BytesIO(); im.save(buf, 'PNG')
                    self.studio_logo = tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()).decode('ascii'), format='png'); break
        except Exception:
            log.exception('studio logo')
        parts = []
        if self.studio_logo: parts.append(tk.Label(box, image=self.studio_logo, cursor='hand2'))
        txt = tk.Frame(box, cursor='hand2')
        self.studio_lbl = tk.Label(txt, text='S H A D O W', font=('Segoe UI Semibold', 9), anchor='w', cursor='hand2')
        self.studio_sub = tk.Label(txt, text='S T U D I O', font=('Segoe UI', 7), anchor='w', cursor='hand2')
        self.studio_lbl.pack(fill='x'); self.studio_sub.pack(fill='x')
        parts += [txt, self.studio_lbl, self.studio_sub]
        if self.studio_logo: parts[0].pack(side='left', padx=(0, 9))
        txt.pack(side='left')
        url = 'https://github.com/' + updater.REPO.split('/')[0]
        for w in [box] + parts:
            w.bind('<Button-1>', lambda e: webbrowser.open(url))
            w.bind('<Enter>', lambda e: self.studio_lbl.config(foreground=self.SIDE_COLORS['dark' if self.theme == 'dark' else 'light']['fg_sel']))
            w.bind('<Leave>', lambda e: self.side_colors())
        self.studio_box = box

    def _nav_hover(self, row, on):
        c = self.SIDE_COLORS['dark' if self.theme == 'dark' else 'light']
        bg = c['sel'] if self._nav_selected(row.key) else (c['hover'] if on else c['bg'])
        for w in row.parts: w.config(background=bg)

    def _scroll_page(self, outer):
        """A page that scrolls: a Canvas + scrollbar in `outer`, returns the frame to fill. The mouse wheel scrolls it while
        the pointer is over it. Its height never decides the window's height (the Queue page does)."""
        cv = tk.Canvas(outer, highlightthickness=0, bd=0, height=200)
        vs = ttk.Scrollbar(outer, orient='vertical', command=cv.yview); cv.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y'); cv.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(cv); win = cv.create_window(0, 0, window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all'), width=inner.winfo_reqwidth()))
        cv.bind('<Configure>', lambda e: cv.itemconfigure(win, width=e.width))
        def wheel(e):
            if cv.yview() != (0.0, 1.0): cv.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), 'units')
        cv.bind('<Enter>', lambda e: cv.bind_all('<MouseWheel>', wheel)); cv.bind('<Leave>', lambda e: cv.unbind_all('<MouseWheel>'))
        self.scroll_canvases = getattr(self, 'scroll_canvases', []) + [cv]
        self.settings_canvas = cv
        return inner

    def side_colors(self):
        """Paint the sidebar for the current theme (a plain Tk frame: sv-ttk does not colour it)."""
        if not hasattr(self, 'side'): return
        c = self.SIDE_COLORS['dark' if self.theme == 'dark' else 'light']
        self.side.config(background=c['bg'])
        try:
            bg = ttk.Style(self).lookup('TFrame', 'background') or None
            for cv in getattr(self, 'scroll_canvases', []): cv.config(background=bg)
        except tk.TclError: pass
        for w in self.side.winfo_children():
            if isinstance(w, tk.Frame) and not hasattr(w, 'key'):
                w.config(background=c['bg'])
                for x in w.winfo_children(): x.config(background=c['bg'])
        self.side_title.config(foreground=c['fg_sel']); self.side_ver.config(foreground=c['muted'])
        if hasattr(self, 'studio_box'):   # the Shadow Studio mark: line in the theme's line colour, quiet text
            for w in self.side.winfo_children():
                if isinstance(w, tk.Frame) and not hasattr(w, 'key') and int(w.cget('height') or 0) == 1: w.config(background=c['line'])
            self.studio_lbl.config(foreground=c['fg'], background=c['bg']); self.studio_sub.config(foreground=c['muted'], background=c['bg'])
        for row in self.nav.values():
            sel = self._nav_selected(row.key); bg = c['sel'] if sel else c['bg']
            for w in row.parts: w.config(background=bg)
            row.parts[1].config(foreground=c['fg_sel'] if sel else c['muted']); row.parts[2].config(foreground=c['fg_sel'] if sel else c['fg'])

    def show_page(self, name):
        """Queue / Settings / About in the page area; the sidebar marks the open one."""
        if name not in self.pages or self.page == name: return
        self.pages[name].tkraise()
        self.page = name
        self.page_title.config(text=tr({'queue': 'Queue', 'settings': 'Settings', 'about': 'About'}[name]))
        self.side_colors()

    def toggle_sidebar(self):
        """The menu button: hide or show the sidebar (remembered in the settings)."""
        self.side_open = not self.side_open
        if self.side_open: self.side.pack(side='left', fill='y', before=self.body)
        else: self.side.pack_forget()
        self.save()

    # ------------------------------------------------------------------ Settings: storage, Claude (MCP), AI account (3.30)
    def use_storage(self, path, label='', pick=None):
        """A place button: save videos in <place>\\Seekframe (made on the first render), then check it. A cloud app that
        was not found (path None) or the NAS button asks for the folder (pick = a test's stand-in for the folder picker)."""
        if path in (None, 'nas'):
            msg = (tr('Pick the NAS folder (Network in the list, or a mapped drive like Z:).') if path == 'nas'
                   else tr('{0} was not found on this PC. Pick its folder (install its desktop app first if needed).', label))
            self.storage_lbl.config(text=msg, foreground='#d29922')
            got = (pick or filedialog.askdirectory)(title=msg)
            if not got: return None
            self.out_dir.set(os.path.normpath(got)); return self.check_storage()
        self.out_dir.set(os.path.join(path, 'Seekframe')); return self.check_storage()

    def check_storage(self):
        d = self.out_dir.get().strip()
        if not d: self.storage_lbl.config(text=tr('Choose a folder first.'), foreground='#f85149'); return None
        r = storage_check(d)
        kind = {'network': tr('network drive (NAS)'), 'cloud': tr('cloud folder'), 'local': tr('this PC')}[r['kind']]
        if r['ok']:
            self.storage_lbl.config(text=tr('OK: Seekframe can save there ({0}, {1} GB free).', kind, r['free_gb']), foreground='#3fb950')
        else:
            self.storage_lbl.config(text=tr('Seekframe cannot save there: {0}', r['message']), foreground='#f85149')
        return r

    def check_mcp(self, wait=False, status=None):
        """The AI connections lights (3.32): in a thread (the process list takes a second). Runs again every 45 s, so an
        AI app that starts using Seekframe shows up (and gets one Windows notification)."""
        def run():
            try: st = (status or ai_clients.status)()
            except Exception: log.exception('ai clients'); st = []
            self.q.put(('mcp', st))
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def _poll_clients(self):
        self.check_mcp(); self._clients_id = self.after(45000, self._poll_clients)

    def show_mcp(self, st, toast=None):
        """Paint the AI connections rows from ai_clients.status(): green light + ticked = connected, 'In use now (n)' while
        it runs Seekframe; apps not on this PC are listed in one grey line instead of a row."""
        if not hasattr(self, 'cli_rows'): return
        toast = toast or notify
        green, grey = '#3fb950', '#888'
        missing, other = [], 0
        using = {}
        for s in st:
            if s['key'] == 'other': other = s['using']; continue
            row = self.cli_rows.get(s['key'])
            if not row: continue
            using[s['key']] = s['using']
            if not (s['installed'] or s['connected']):   # 3.34: not on this PC: a row with its install command to copy
                row['var'].set(False); row['cb'].state(['disabled']); row['dot'].config(foreground=grey)
                if not row.get('copied'): row['st'].config(text=tr('Not installed'), foreground=grey)
                row['inst'].grid(); missing.append(s['name']); continue
            row['inst'].grid_remove()
            row['var'].set(bool(s['connected'])); row['cb'].state(['!disabled'])
            row['dot'].config(foreground=green if s['connected'] else grey)
            row['st'].config(text=tr('In use now ({0})', s['using']) if s['using'] else (tr('Connected') if s['connected'] else tr('Not connected')),
                             foreground=green if s['using'] else grey)
        self.cli_missing.config(text=tr('Another app is using Seekframe now ({0}).', other) if other else '')
        if other: self.cli_missing.pack(anchor='w', pady=(4, 0), before=self.engine_row)
        else: self.cli_missing.pack_forget()
        if self._using_prev is not None:   # the first check only sets the baseline (no notification at start)
            for key_, n in using.items():
                if n and not self._using_prev.get(key_):
                    toast(tr('Seekframe connected'), tr('{0} is now using Seekframe.', ai_clients.BY_KEY[key_].name))
        self._using_prev = using
        self.mcp_state = st

    def on_client(self, key, wait=False, toast=None, **kw):
        """A tick box: connect Seekframe to that AI app (or remove it), in a thread; then a notification and a re-check."""
        row = self.cli_rows[key]; want = row['var'].get(); name = ai_clients.BY_KEY[key].name
        row['cb'].state(['disabled']); row['st'].config(text=tr('Connecting...') if want else tr('Removing...'), foreground='#888')
        def run():
            try:
                ok, msg = (ai_clients.connect(key, ai_clients.server_command(), **kw) if want else ai_clients.disconnect(key, **kw))
            except Exception as e: ok, msg = False, str(e)
            self.q.put(('client_done', key, want, ok, msg, toast))
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def copy_install(self, key):
        """Copy that app's install command; the owner pastes it in a terminal (Seekframe installs nothing itself)."""
        cmd = ai_clients.INSTALL[key]
        self.clipboard_clear(); self.clipboard_append(cmd); self.update_idletasks()
        row = self.cli_rows[key]; row['copied'] = True
        row['st'].config(text=tr('Copied: {0}. Paste it in a terminal, then press Re-check.', cmd), foreground='#3fb950')
        return cmd

    def client_done(self, key, want, ok, msg, toast=None):
        row = self.cli_rows[key]; name = ai_clients.BY_KEY[key].name
        row['cb'].state(['!disabled'])
        if not ok:
            row['var'].set(not want)
            row['st'].config(text=tr('Could not change {0}: {1}', name, msg), foreground='#f85149'); return
        row['var'].set(want); row['dot'].config(foreground='#3fb950' if want else '#888')
        if want:
            row['st'].config(text=tr('Connected. Restart {0} if it is open.', name), foreground='#3fb950')
            (toast or notify)(tr('Seekframe connected'), tr('{0} can use Seekframe now. Restart {0} if it is open.', name))
        else:
            row['st'].config(text=tr('Not connected'), foreground='#888')
        log.info('ai client %s %s', key, 'connected' if want else 'removed')

    def _engine_text(self):
        name = ai_tasks.ENGINES[ai_tasks.ENGINE]
        self.engine_lbl.config(text=tr('Fix the scene, YouTube text and New video use {0}. The Assistant chat always uses Claude Code.', name), foreground='#888')
        if hasattr(self, 'ai_auth'):   # the sign-in row shows the chosen AI's own choice
            self.auth_title.config(text=tr('How {0} signs in:', name))
            mode = ('api_key' if ai_tasks.GEMINI_AUTH == 'api_key' else 'subscription') if ai_tasks.ENGINE == 'gemini' else assistant.AUTH_MODE
            self.ai_auth.set(mode); self._key_status(); self.refresh_account()

    def on_engine(self, ready=None, toast=None):
        """The AI for Seekframe's own AI buttons: checked first (installed + signed in), then saved, with a notification."""
        want = self.engine.get()
        if want == 'gemini': ok, msg = (ready or ai_tasks.gemini_ready)(ai_tasks.find_gemini())
        else: ok, msg = (ready or assistant.check_ready)(assistant.find_claude())
        if not ok:
            self.engine.set(ai_tasks.ENGINE)
            self.engine_lbl.config(text=tr('{0} is not ready: {1}', ai_tasks.ENGINES[want], msg), foreground='#f85149'); return False
        changed = want != ai_tasks.ENGINE
        ai_tasks.ENGINE = want; self.cfg_ai['engine'] = want; self.save(); self._engine_text()
        self.engine_lbl.config(foreground='#3fb950')
        if changed:
            (toast or notify)(tr('AI connected'), tr("{0} now does Seekframe's AI jobs.", ai_tasks.ENGINES[want]))
        return True

    # ------------------------------------------------------------------ cloud accounts (3.33, cloud.py / rclone)
    def refresh_cloud(self, wait=False, rc=None):
        """Which accounts are signed in (+ the user's e-mail): rclone in a thread, then show_cloud on the Tk thread."""
        rc = rc or cloud.Rclone()
        def run():
            if not rc.ok(): self.q.put(('cloud', None, {})); return
            try:
                acc = rc.accounts(); who = {k: rc.who(k) for k in acc}
            except Exception as e:
                log.warning('cloud accounts: %s', e); acc, who = {}, {}
            self.q.put(('cloud', True, {k: who.get(k, '') for k in acc}))
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def show_cloud(self, have_rclone, accounts):
        if not hasattr(self, 'cloud_rows'): return
        self.cloud_accounts = accounts
        if not have_rclone:
            self.cloud_note.config(text=tr('Sign in to Google Drive, OneDrive, Dropbox, Box or pCloud without their apps. This uses rclone (free, open source), which Seekframe can download for you.'))
            if not self.rclone_btn.winfo_manager(): self.rclone_btn.pack(anchor='w', pady=(6, 0), before=self.cloud_rows['drive']['st'].master)
        else:
            self.rclone_btn.pack_forget()
            self.cloud_note.config(text=tr('Sign in once in your browser; Seekframe never sees your password. Then use Cloud... in the sidebar to add files from there.'))
        for key, row in self.cloud_rows.items():
            on = key in accounts
            row['st'].config(text=(accounts[key] or tr('Signed in')) if on else tr('Not signed in'), foreground='#3fb950' if on else '#888')
            row['btn'].config(text=tr('Sign out') if on else tr('Sign in'), state='normal' if have_rclone else 'disabled')
        names = [tr('Off')] + [cloud.LABEL[k] for k, _, _, _ in cloud.PROVIDERS if k in accounts]
        self.cloud_up_box.config(values=names)
        if self.cloud_up and self.cloud_up not in accounts: self.cloud_up = ''
        self.cloud_up_box.set(cloud.LABEL[self.cloud_up] if self.cloud_up else tr('Off'))

    def on_cloud_up(self):
        lbl = self.cloud_up_box.get()
        self.cloud_up = next((k for k, l in cloud.LABEL.items() if l == lbl), ''); self.save()

    def get_rclone(self, fetch=None, wait=False):
        """Download rclone (official release, SHA-256 checked) into %LOCALAPPDATA%\\Seekframe\\rclone."""
        self.rclone_btn.state(['disabled']); self.cloud_note.config(text=tr('Downloading rclone...'), foreground='#888')
        def run():
            try: cloud.get_rclone(gh=fetch); msg = None
            except Exception as e: msg = str(e)
            self.q.put(('cloud_msg', tr('rclone is ready.') if not msg else tr('Could not get rclone: {0}', msg)))
            self.rclone_btn.state(['!disabled']); self.refresh_cloud()
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def cloud_toggle(self, key, rc=None, wait=False, toast=None):
        """Sign in (opens the browser) or sign out of one provider."""
        rc = rc or cloud.Rclone(); row = self.cloud_rows[key]; label = cloud.LABEL[key]
        if key in self.cloud_accounts:
            row['btn'].state(['disabled'])
            def out():
                rc.sign_out(key); self.q.put(('cloud_msg', tr('Signed out of {0}.', label))); self.refresh_cloud(rc=rc)
            if wait: out()
            else: threading.Thread(target=out, daemon=True).start()
            return
        row['btn'].state(['disabled']); row['st'].config(text=tr('Sign in in your browser...'), foreground='#d29922')
        def run():
            ok, msg = rc.sign_in(key)
            if ok: (toast or notify)(tr('Seekframe connected'), tr('{0} is connected to Seekframe.', label))
            self.q.put(('cloud_msg', tr('{0} is connected to Seekframe.', label) if ok else tr('{0}: {1}', label, msg)))
            self.refresh_cloud(rc=rc)
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def open_cloud(self):
        if not cloud.find_rclone() or not self.cloud_accounts:
            self.show_page('settings'); self.status.config(text=tr('Sign in to a cloud account first (Settings > Cloud accounts).')); return None
        return CloudDialog(self, accounts=self.cloud_accounts)

    def cloud_upload(self, mp4, out_dir, rc=None, wait=False):
        """Queue one finished video (+ its subtitles and thumbnail) for upload to the chosen account, folder
        Seekframe/<same folders as under Save to>. One upload thread, in order; the render queue never waits for it."""
        key = self.cloud_up
        if not key: return
        import queue as _qm
        if self.upload_q is None:
            self.upload_q = _qm.Queue()
            def worker():
                while True:
                    job = self.upload_q.get()
                    if job is None: return
                    m, od, k, r_ = job
                    r_ = r_ or cloud.Rclone()
                    extra = [x for x in (os.path.splitext(m)[0] + '.srt',) + tuple(glob.glob(glob.escape(os.path.splitext(m)[0]) + '_thumb*.jpg')) if os.path.isfile(x)]
                    dest = cloud.upload_dir(od, m)
                    ok, msg = r_.upload(m, k, dest)
                    for x in extra:
                        if ok: r_.upload(x, k, dest)
                    log.info('cloud upload %s -> %s:%s %s', m, k, dest, 'ok' if ok else msg)
                    self.q.put(('cloud_msg', tr('Uploaded {0} to {1}.', os.path.basename(m), cloud.LABEL[k]) if ok
                                else tr('Upload to {0} failed: {1}', cloud.LABEL[k], msg)))
                    self.upload_q.task_done()
            self.upload_thread = threading.Thread(target=worker, daemon=True); self.upload_thread.start()
        self.upload_q.put((mp4, out_dir, key, rc))
        if wait: self.upload_q.join()

    def _key_status(self):
        if ai_tasks.ENGINE == 'gemini':
            key = ai_tasks.load_gemini_key()
            if self.ai_auth.get() == 'api_key':
                self.key_lbl.config(text=tr('Gemini uses your Google AI Studio key {0}. Google may bill requests beyond its free tier.', assistant.key_hint(key)) if key
                                    else tr('Paste your Google AI Studio API key (starts with AIza) and press Save key. It is stored encrypted for your Windows account only.'),
                                    foreground='#d29922' if key else '#888')
            else:
                st = self.acct_state.get('gemini') if hasattr(self, 'acct_state') else None
                self.key_lbl.config(text=(tr('Gemini CLI: {0}.', tr(st[1])) if st else tr('Gemini CLI uses its own sign-in (run gemini once in a terminal to set it up).')) +
                                    ('  ' + tr('A saved API key {0} is kept but not used.', assistant.key_hint(key)) if key else ''),
                                    foreground='#3fb950' if st and st[0] else ('#d29922' if st and st[0] is False else '#888'))
            return
        key = assistant.load_api_key()
        if self.ai_auth.get() == 'api_key':
            self.key_lbl.config(text=tr('The AI features use your API key {0}. Every request is billed by Anthropic.', assistant.key_hint(key)) if key
                                else tr('Paste your Anthropic API key (starts with sk-ant-) and press Save key. It is stored encrypted for your Windows account only.'),
                                foreground='#d29922' if key else '#888')
        else:
            st = self.acct_state.get('claude') if hasattr(self, 'acct_state') else None
            self.key_lbl.config(text=(tr('Claude Code: {0}.', tr(st[1])) if st else tr('The AI features use your Claude subscription through Claude Code.')) +
                                ('  ' + tr('A saved API key {0} is kept but not used.', assistant.key_hint(key)) if key else ''),
                                foreground='#3fb950' if st and st[0] else ('#d29922' if st and st[0] is False else '#888'))

    def on_ai_auth(self, ask=None):
        """Switching to the API key asks once (it costs money per request); the choice is saved in settings 'ai'.
        3.34: for the AI chosen above (Claude Code: 'auth', Gemini CLI: 'gemini_auth')."""
        mode = self.ai_auth.get()
        if ai_tasks.ENGINE == 'gemini':
            if mode == 'api_key' and self.cfg_ai.get('gemini_auth') != 'api_key':
                if not (ask or messagebox.askyesno)(tr('AI connections'), tr('With an API key, Google may bill Gemini requests beyond its free tier. Use your API key?')):
                    self.ai_auth.set('subscription'); mode = 'subscription'
            self.cfg_ai['gemini_auth'] = 'api_key' if mode == 'api_key' else 'account'; ai_tasks.GEMINI_AUTH = self.cfg_ai['gemini_auth']
            self._key_status(); self.save(); return
        if mode == 'api_key' and self.cfg_ai.get('auth') != 'api_key':
            if not (ask or messagebox.askyesno)(tr('AI account'), tr('With an API key every AI request is billed to your Anthropic account. Use your API key?')):
                self.ai_auth.set('subscription'); mode = 'subscription'
        self.cfg_ai['auth'] = mode; assistant.AUTH_MODE = mode
        if self.ai: self.ai.new_chat()   # the next chat starts with the new sign-in
        self._key_status(); self.save()

    def save_key(self, ask=None):
        """3.34: the company is read from the key itself (sk-ant- = Anthropic for Claude Code, AIza = Google AI Studio for
        Gemini CLI) and the key is stored for that AI, whichever AI is chosen above. For the chosen one it offers to switch
        to API-key mode (asks about the cost first)."""
        prov = ai_tasks.key_provider(self.key_var.get())
        if prov == 'openai':
            self.key_lbl.config(text=tr('That is an OpenAI key. Seekframe\'s AI buttons use Claude Code or Gemini CLI, so it is not used.'), foreground='#f85149'); return False
        if prov is None:
            self.key_lbl.config(text=tr('Seekframe does not know this key. Anthropic keys start with sk-ant-, Google AI Studio keys with AIza.'), foreground='#f85149'); return False
        target = 'gemini' if prov == 'google' else 'claude'
        if target != ai_tasks.ENGINE:
            cur = ai_tasks.ENGINE
            try:
                ai_tasks.ENGINE = target; ok = self._save_key_for_engine()
            finally:
                ai_tasks.ENGINE = cur
            if ok:
                self._key_status()
                self.key_lbl.config(text=tr('Saved as your {0} key for {1}. Choose {1} above to use it.', 'Google AI Studio' if prov == 'google' else 'Anthropic',
                                            ai_tasks.ENGINES[target]), foreground='#3fb950')
            return ok
        ok = self._save_key_for_engine()
        if ok and self.ai_auth.get() != 'api_key':
            self.ai_auth.set('api_key'); self.on_ai_auth(ask=ask)
        return ok

    def _save_key_for_engine(self):
        if ai_tasks.ENGINE == 'gemini':
            try: ai_tasks.save_gemini_key(self.key_var.get())
            except ValueError: self.key_lbl.config(text=tr('That does not look like a Google AI Studio API key (it starts with AIza).'), foreground='#f85149'); return False
            except OSError as e: self.key_lbl.config(text=str(e), foreground='#f85149'); return False
            self.key_var.set(''); self._key_status(); return True
        try: assistant.save_api_key(self.key_var.get())
        except ValueError as e: self.key_lbl.config(text=tr('That does not look like an Anthropic API key (it starts with sk-ant-).'), foreground='#f85149'); return False
        except OSError as e: self.key_lbl.config(text=str(e), foreground='#f85149'); return False
        self.key_var.set('')   # never kept on screen
        self._key_status(); return True

    def refresh_account(self, wait=False, status=None):
        """The chosen AI's own sign-in state (thread), shown under the sign-in row."""
        eng = ai_tasks.ENGINE
        def run():
            try: st = (status or ai_tasks.account_status)(eng)
            except Exception: st = (None, 'could not check')
            self.q.put(('acct', eng, st))
        if wait: run(); return None
        threading.Thread(target=run, daemon=True).start()

    def show_account(self, eng, st):
        self.acct_state[eng] = st
        if eng == ai_tasks.ENGINE: self._key_status()

    def ai_login(self, popen=None):
        """Sign the chosen AI in, in its own console window (claude auth login / Gemini CLI's first-start sign-in). The token
        stays with that program; Seekframe only checks afterwards whether it is signed in."""
        cmd = ai_tasks.login_command(ai_tasks.ENGINE)
        name = ai_tasks.ENGINES[ai_tasks.ENGINE]
        if not cmd:
            self.key_lbl.config(text=tr('{0} is not installed. Use Copy install command above, then press Re-check.', name), foreground='#f85149'); return False
        try:
            (popen or subprocess.Popen)(cmd, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0), cwd=os.path.expanduser('~'), env=assistant.clean_env())
        except Exception as e:
            self.key_lbl.config(text=str(e), foreground='#f85149'); return False
        self.key_lbl.config(text=tr('Finish the sign-in in the window that opened, then press Re-check.'), foreground='#d29922')
        return True

    def remove_key(self):
        if ai_tasks.ENGINE == 'gemini':
            ai_tasks.delete_gemini_key()
            if self.ai_auth.get() == 'api_key': self.ai_auth.set('subscription'); self.on_ai_auth()
            self._key_status(); return
        assistant.delete_api_key()
        if self.ai_auth.get() == 'api_key': self.ai_auth.set('subscription'); self.on_ai_auth()
        self._key_status()

    # ------------------------------------------------------------------ theme
    def apply_theme(self, refresh=False):
        if sv_ttk:
            try:
                if refresh: sv_ttk.set_theme('light' if self.theme == 'dark' else 'dark', self)
                sv_ttk.set_theme(self.theme, self)
                if self.theme == 'light': self._light_gray()
                # the root window is a plain Tk widget (not ttk): give it the current theme's background every time,
                # or the light gray stays between the frames after switching back to Dark
                self.configure(background=LIGHT_BG if self.theme == 'light' else (str(ttk.Style(self).lookup('TFrame', 'background')) or '#1c1c1c'))
                self._scale_theme()
                i18n.apply_fonts(self)   # 3.20: a Windows font that has the language's letters (Arabic, Hindi, Chinese, Japanese)
                self.side_colors()
            except Exception: log.exception('theme')
        dark_titlebar(self, self.theme == 'dark')
    def _light_gray(self):
        # the owner's Light theme: light gray instead of sv-ttk's near-white #fafafa (only the 'light' theme is touched;
        # buttons, entries and cards keep sv-ttk's lighter images, so they stand out on the gray)
        st = ttk.Style(self)
        st.configure('.', background=LIGHT_BG)
        for s in ('TFrame', 'TLabel', 'TLabelframe', 'TLabelframe.Label', 'TCheckbutton', 'TRadiobutton'):
            st.configure(s, background=LIGHT_BG)
        st.configure('Treeview', background=LIGHT_FIELD, fieldbackground=LIGHT_FIELD)
        st.configure('Treeview.Heading', background=LIGHT_BG)
        self.configure(background=LIGHT_BG)
        if not getattr(self, '_light_tinted', False):
            self._light_tinted = True
            try: self._tint_light_sprites()
            except Exception: log.exception('light gray sprites')   # keeps sv-ttk's white parts, still usable
    def _tint_light_sprites(self):
        # cards, the table, entries and buttons are images cut from sv-ttk's spritesheet_light.png: darken their near-white
        # pixels by LIGHT_TINT (#fafafa -> LIGHT_BG) and copy them back into the theme's own images (in place, light theme only)
        import base64, io
        from PIL import Image
        sheet = Image.open(os.path.join(os.path.dirname(sv_ttk.__file__), 'theme', 'spritesheet_light.png')).convert('RGBA')
        px = [(r - LIGHT_TINT, g - LIGHT_TINT, b - LIGHT_TINT, a) if a and min(r, g, b) >= 236 else (r, g, b, a) for r, g, b, a in sheet.getdata()]
        sheet.putdata(px); buf = io.BytesIO(); sheet.save(buf, 'PNG')
        tinted = tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()).decode('ascii'), format='png')
        info = self.tk.splitlist(self.tk.eval('set ::spriteinfo'))   # name x y w h ... (same layout for light and dark)
        imgs = dict(zip(*[iter(self.tk.splitlist(self.tk.eval('array get ::ttk::theme::sv_light::I')))] * 2))
        for i in range(0, len(info), 5):
            name, x, y, w, h = info[i], *map(int, info[i + 1:i + 5])
            if name in imgs: self.tk.call(imgs[name], 'copy', str(tinted), '-from', x, y, x + w, y + h)
        self._tinted_sheet = tinted   # keep the Tk image alive
    def _scale_theme(self):
        # sv-ttk sizes its fonts and rows in pixels, so on a 150-225% display they come out tiny next to everything else
        k = self.winfo_fpixels('1i') / 96
        if not getattr(self, '_fonts_scaled', False):
            import tkinter.font as tkfont
            for n in tkfont.names(self):
                if n.startswith('SunValley'):
                    f = tkfont.nametofont(n, self); sz = int(f.cget('size'))
                    if sz < 0: f.configure(size=-round(-sz * k))
            self._fonts_scaled = True
        ttk.Style(self).configure('Treeview', rowheight=round(26 * k))
    def _theme_text(self):
        self.theme_btn.config(text=tr('Light') if self.theme == 'dark' else tr('Dark'))
    def toggle_theme(self):
        self.theme = self.theme_choice = 'light' if self.theme == 'dark' else 'dark'
        self.apply_theme(); self._theme_text(); self.ai_colors(); self.save()

    # ------------------------------------------------------------------ setup
    def check(self):
        e = rc.check_env(); self.env = e; self.blender = bc.find_blender()
        for k, ok in (('Chrome', e['chrome']), ('ffmpeg', e['ffmpeg']), ('playwright', e['playwright']), ('Blender', bool(self.blender))):
            dot, txt = self.env_lbls[k]
            dot.config(foreground='#3fb950' if ok else '#f85149' if k != 'Blender' else '#888'); txt.config(text=k if ok else f'{k} (missing)' if k != 'Blender' else 'Blender (not found, only for .blend)')
        if e['chrome'] and e.get('browser') != 'Chrome': self.env_lbls['Chrome'][1].config(text=tr('{0} (Chrome not found)', e['browser']))
        miss = [n for n, ok in (('Chrome', e['chrome']), ('ffmpeg', e['ffmpeg']), ('playwright', e['playwright'])) if not ok]
        if miss and hasattr(self, 'status'): self.status.config(text=tr('Missing: {0}. Open Settings to install.', ', '.join(miss)))   # the setup moved to Settings
    def run_selftest(self, wait=False, **kw):
        """Self-test button: selftest() in a thread, the result in a message box (tests: wait=True runs here, returns it)."""
        if self.worker is not None and self.worker.is_alive():
            messagebox.showinfo(tr('Self-test'), tr('A render is running. Run the self-test when the queue is done.')); return None
        self.selftest_btn.config(state='disabled'); self.status.config(text=tr('Self-test: rendering a 2-second test scene...'))
        out = {}
        def work():
            out['res'] = selftest(**kw)
            self.q.put(('selftest', out['res']))
        if wait: work(); self.on_selftest(out['res']); return out['res']
        threading.Thread(target=work, daemon=True).start()
    def on_selftest(self, res):
        if not self.selftest_btn.winfo_exists(): return
        self.selftest_btn.config(state='normal')
        self.status.config(text=('Self-test passed' if res['ok'] else 'Self-test FAILED') + f" ({res.get('seconds', 0)} s, {res.get('browser') or 'no browser'})")
        if getattr(self, 'selftest_box_off', False): return   # tests
        (messagebox.showinfo if res['ok'] else messagebox.showwarning)('Self-test', selftest_text(res))
    def install_missing(self):
        cmds = []
        frozen = getattr(sys, 'frozen', False)  # in Shadow.exe the python packages are bundled; sys.executable is the exe
        if not frozen and (not self.env['playwright'] or not HAS_DND or not sv_ttk): cmds.append(f'"{sys.executable}" -m pip install playwright tkinterdnd2 sv-ttk darkdetect')
        if not self.env['ffmpeg']: cmds.append('winget install -e --id Gyan.FFmpeg')
        if not self.env['chrome']: cmds.append('winget install -e --id Google.Chrome')
        if not getattr(self, 'blender', None) and any(bc.is_blend(f) for f in self.files): cmds.append('winget install -e --id BlenderFoundation.Blender')
        if not cmds:
            messagebox.showinfo(tr('Setup'), tr('Everything is installed.')); return
        subprocess.Popen('cmd /c "' + ' && '.join(cmds) + ' && echo. && echo Done. Close this window and restart the app. && pause"', creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        messagebox.showinfo(tr('Setup'), tr('Installing in a new window. When it finishes, close this app and open it again (ffmpeg needs a restart to be found).'))

    # ------------------------------------------------------------------ file list
    def on_drop(self, ev):
        for f in self.tk.splitlist(ev.data):
            if os.path.isdir(f): self.add_folder(f)   # a dropped folder adds its scenes, like "Add folder..."
            elif f.lower().endswith(PROJECT_EXT): self.open_project(f)
            else: self._add(f)

    # ------------------------------------------------------------------ project files (.shadow)
    def project_menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=tr('Open project...'), command=self.open_project)
        m.add_command(label=tr('Save project'), command=lambda: self.save_project(self.project_path))
        m.add_command(label=tr('Save project as...'), command=self.save_project)
        try: m.tk_popup(self.proj_btn.winfo_rootx(), self.proj_btn.winfo_rooty() + self.proj_btn.winfo_height())
        finally: m.grab_release()
    def project_data(self):
        """The queue (scenes in order + each row's narration) and the render options, as saved in a .shadow file."""
        return dict(files=list(self.files), narration={f: dict(v) for f, v in self.narr.items() if f in self.files},
                    options=dict(quality=self.preset.get(), format=self.fmt.get(), sound=self.snd.get(), sound_file=self.snd_file.get(),
                                 capture=self.capture.get(), blender=self.bl_engine.get(), folder=self.folder_choice.get(),
                                 save_to=self.out_dir.get(), skip_done=bool(self.skip_done.get())))
    def save_project(self, path=None):
        """Save project (as): the queue and its options in a .shadow file. Returns the path, or None (cancelled / failed)."""
        if not path:
            path = filedialog.asksaveasfilename(defaultextension=PROJECT_EXT, filetypes=[('Seekframe project', '*' + PROJECT_EXT)],
                                                initialdir=os.path.dirname(self.files[0]) if self.files else None, initialfile='project' + PROJECT_EXT)
            if not path: return None
        try: write_project(path, self.project_data())
        except OSError as e: messagebox.showerror(tr('Project'), tr('Could not save {0}:\n{1}', path, e)); return None
        self.project_path = path; self.title(tr('Seekframe - {0}', os.path.splitext(os.path.basename(path))[0]))
        self.status.config(text=tr('Project saved: {0}', path)); log.info('project saved %s (%d scenes)', path, len(self.files))
        return path
    def open_project(self, path=None, ask=messagebox.askyesnocancel):
        """Open project: scenes (in order) + their narration + the options. With scenes already in the list it asks:
        Yes = replace the list, No = add to it, Cancel. Missing files are listed, the rest is opened. Returns the scenes added."""
        if self.worker is not None and self.worker.is_alive():
            messagebox.showinfo(tr('Project'), tr('A render is running. Open the project when the queue is done.')); return []
        if not path:
            path = filedialog.askopenfilename(filetypes=[('Seekframe project', '*' + PROJECT_EXT)])
            if not path: return []
        try: data = read_project(path)
        except (OSError, ValueError) as e: messagebox.showerror(tr('Project'), tr('Could not open {0}:\n{1}', path, e)); return []
        if self.files:
            a = ask('Project', f'Replace the {len(self.files)} scene(s) in the list with the project?\n\nYes = replace   No = add to the list   Cancel = do nothing')
            if a is None: return []
            if a: self.clear()
        o = data['options']
        if o.get('capture') in OLD_CAPTURE_LABELS: o['capture'] = OLD_CAPTURE_LABELS[o['capture']]   # a project saved by 3.16 or older
        # the song file first, and Sound without its file picker: a project with "External file..." already names its file
        # (3.17 fix: opening such a project popped up the picker)
        if o.get('sound_file') is not None: self.snd_file.set(o['sound_file'])
        self._quiet_sound = True
        try:
            for var, key, ok in ((self.preset, 'quality', rc.PRESETS), (self.fmt, 'format', FORMAT_CHOICES), (self.snd, 'sound', SOUNDS),
                                 (self.capture, 'capture', CAPTURES), (self.bl_engine, 'blender', BLENDER_ENGINES)):
                if o.get(key) in ok: var.set(o[key])
        finally: self._quiet_sound = False
        if o.get('save_to'): self.out_dir.set(o['save_to'])
        if 'skip_done' in o: self.skip_done.set(bool(o['skip_done']))
        fc = o.get('folder')
        if fc and fc not in self.folder_values() and safe_rel_folder(fc): self.folders.append(safe_rel_folder(fc)); self.folder_box.set_values(self.folder_values())
        if fc in self.folder_values(): self.folder_choice.set(fc)
        added, missing, narr_err = [], [f for f in data['files'] if not os.path.isfile(f)], []
        for f in data['files']:
            if f in missing or os.path.normpath(f) in self.files: continue
            self._add(f); added.append(os.path.normpath(f))
            n = data['narration'].get(f)
            if n and os.path.normpath(f) not in self.embedded:
                err = self.set_narration(f, n.get('wav', ''), n.get('words', ''), style=n.get('style', 'pop'), yh=n.get('yh', 0.88),
                                         gain=n.get('gain', 1.0), captions=n.get('captions', True))
                if err: narr_err.append(f'{os.path.basename(f)}: {err}')
        self.refresh_audio(); self.project_path = path; self.title(tr('Seekframe - {0}', os.path.splitext(os.path.basename(path))[0]))
        self.status.config(text=f'Project opened: {len(added)} scene(s)' + (f', {len(missing)} missing' if missing else ''))
        log.info('project opened %s: %d added, %d missing', path, len(added), len(missing))
        if missing or narr_err:
            messagebox.showwarning(tr('Project'), ('Not found (not added):\n' + '\n'.join(missing) if missing else '')
                                   + ('\n\n' if missing and narr_err else '') + ('Narration not attached:\n' + '\n'.join(narr_err) if narr_err else ''))
        return added
    def add_folder(self, d=None, ask=None):
        """Add every .html / .blend scene in a folder (sorted; hidden .shadow_narr_* temp scenes skipped). When its subfolders
        hold scenes too, ask whether to add those as well. Returns the scenes added (tests)."""
        if d is None:
            d = filedialog.askdirectory(initialdir=os.path.dirname(self.files[-1]) if self.files else None)
            if not d: return []
        top, _ = collect_scenes([d]); deep, _ = collect_scenes([d], recursive=True)
        found = top
        if len(deep) > len(top):
            more = len(deep) - len(top)
            if (ask or messagebox.askyesno)('Add folder', f'{os.path.basename(os.path.normpath(d)) or d}: {len(top)} scene(s) in the folder, '
                                            f'{more} more in its subfolders.\n\nAdd the subfolders too?'):
                found = deep
        before = set(self.files)
        for f in found: self._add(f)
        added = [f for f in self.files if f not in before]
        self.status.config(text=f'{len(added)} scene(s) added from {d}' if added else f'No new .html or .blend scenes in {d}')
        return added
    def add(self):
        for f in filedialog.askopenfilenames(filetypes=[('Scene or video', '*.html *.htm *.blend *.mp4 *.mov *.m4v *.webm *.mkv'), ('HTML scene', '*.html *.htm'),
                                                        ('Blender scene', '*.blend'), ('Video + song next to it', '*.mp4 *.mov *.m4v *.webm *.mkv')]): self._add(f)
    def _add(self, f):
        f = os.path.normpath(f)
        if (f.lower().endswith(SCENE_EXTS) or vsong.is_video(f)) and f not in self.files:
            with self.lock:   # while a batch runs, a new file joins it and renders after the ones before it
                self.files.append(f); self.state[f] = 'queued'
            try:   # narration already built into the scene (the tool's own check): marked, never narrated twice
                if bc.is_blend(f) or vsong.is_video(f): raise StopIteration   # binary files: no HTML narration
                with open(f, encoding='utf-8', errors='replace') as fh:
                    if narrate_module().is_narrated(fh.read()): self.embedded.add(f)
            except Exception: pass
            self.rows[f] = self.tree.insert('', 'end', values=(self._row_name(f), i18n.status('Queued'), '—', '', '', ''))
            self._auto_narration(f)
            self._refresh_name(f)
            if sound_mode(self.snd.get()) == 'auto':
                w = self._audio(f)['warn']
                if w: self.status.config(text=w)
            self.update_eta()
    def _auto_narration(self, f):
        """<scene>.wav + <scene>.words.json next to the scene -> attach them (style pop) and say so on the status line."""
        if f in self.embedded: return
        base = os.path.splitext(f)[0]; wav, words = base + '.wav', base + '.words.json'
        if not (os.path.isfile(wav) and os.path.isfile(words)): return
        err = self.set_narration(f, wav, words, style='pop')
        name = os.path.basename(f)
        self.status.config(text=f'{name}: narration found next to it ({os.path.basename(wav)} + {os.path.basename(words)})' if err is None
                           else f'{name}: narration files found but not used: {err}')
    def _row_name(self, f):
        mark = f' {VOICE_EMBEDDED_MARK}' if f in self.embedded else f' {VOICE_MARK}' if f in self.narr else ''
        return os.path.basename(f) + mark
    def _selected_path(self):
        sel = self.tree.selection()
        return next((k for k, v in self.rows.items() if len(sel) == 1 and v == sel[0]), None)
    def _narr_blocked(self, f):
        """Why this row cannot get narration now, or None."""
        if f is None: return 'select one scene first'
        if f in self.embedded: return f'{os.path.basename(f)} already has narration built in'
        with self.lock:
            if self.state.get(f) == 'running': return f"{os.path.basename(f)} is rendering; change its narration after it finishes"
        return None
    def _update_narr_btn(self):
        try: self.narr_btn.config(state='disabled' if self._narr_blocked(self._selected_path()) else 'normal')
        except Exception: pass
    def open_narration_dialog(self):
        """The 'Narration...' button. Returns the dialog (tests drive it), or None with a status-line reason."""
        f = self._selected_path(); why = self._narr_blocked(f)
        if why:
            self.status.config(text=why); return None
        return NarrationDialog(self, f)
    def _audio(self, f):
        """resolve_audio for one queued file with the current Sound setting (what the Audio column shows)."""
        mode = sound_mode(self.snd.get())
        if vsong.is_video(f):   # video + song: External file, else <video>.mp3 next to it
            if mode != 'file': mode = 'auto'
            r = resolve_audio(f, mode, self.snd_file.get() or None)
            return r if r['sound'] == 'file' else dict(r, label=tr('no song next to it'), warn=f'{os.path.basename(f)}: put {os.path.splitext(os.path.basename(f))[0]}.mp3 next to it')
        narrated = f in self.narr or (f in self.embedded and mode in ('auto', 'generated'))
        return resolve_audio(f, mode, self.snd_file.get() or None, narrated=narrated)
    def _refresh_name(self, f):
        iid = self.rows.get(f)
        if iid and self.tree.exists(iid):
            v = list(self.tree.item(iid, 'values')); v += [''] * (6 - len(v))
            v[0] = self._row_name(f); v[3] = tr(self._audio(f)['label']); v[4] = format_label(format_vertical(f, self.fmt.get()))
            self.tree.item(iid, values=v)
    def refresh_audio(self):
        """Update every row's Audio and Format columns; in Auto sound mode the status line names the scenes without an audio file."""
        for f in list(self.files): self._refresh_name(f)
        self.update_eta()
        if sound_mode(self.snd.get()) == 'auto':
            miss = [os.path.basename(f) for f in self.files if self._audio(f)['warn']]
            if miss: self.status.config(text='No audio file next to: ' + ', '.join(miss) + ' (scene sound is used)')
            return miss
        return []

    def set_narration(self, path, wav, words, style='pop', yh=0.88, gain=1.0, captions=True):
        """Attach narration to a queued file. Checks everything that can be checked now (file in the list, wav and
        words.json readable, style, the scene not narrated already, a Shadow scene with SOUND/seek) and returns an error
        string, or None when it was set. Never raises. A file that is rendering right now keeps what it started with."""
        try:
            f = os.path.normpath(path)
            if f not in self.files: return f'not in the list: {os.path.basename(f)}'
            err = narration_problem(f, wav, words, style)
            if err: return err
            with self.lock:
                self.narr[f] = dict(wav=wav, words=words, style=style, yh=yh, gain=gain, captions=captions)
            self._refresh_name(f)
            return None
        except Exception as e:
            log.exception('set_narration'); return f'{type(e).__name__}: {e}'

    def clear_narration(self, path):
        """Remove the narration from a queued file (nothing happens if it had none)."""
        f = os.path.normpath(path)
        with self.lock: self.narr.pop(f, None)
        self._refresh_name(f)

    def set_row(self, f, status=None, dur=None):
        iid = self.rows.get(f)
        if not iid or not self.tree.exists(iid): return
        v = list(self.tree.item(iid, 'values'))
        if status is not None: v[1] = i18n.status(status)   # shown translated; the code keeps the English text
        if dur is not None: v[2] = dur
        self.tree.item(iid, values=v)
    def _drop(self, paths):
        """Take files out of the list, except the one rendering right now. Returns True if that one was asked for."""
        kept = False
        with self.lock:
            for f in paths:
                if self.state.get(f) == 'running': kept = True; continue
                self.files.remove(f); self.state.pop(f, None); self.narr.pop(f, None); self.embedded.discard(f); self.tree.delete(self.rows.pop(f))
        self.update_eta()
        if kept: self.status.config(text=tr("The file that is rendering can't be removed. Press Cancel to stop it."))
        return kept
    def remove(self):
        self._drop([k for iid in self.tree.selection() for k, v in self.rows.items() if v == iid])
    def clear(self):
        self._drop(list(self.files))
    def preview(self):
        sel = self.tree.selection()
        f = next((k for k, v in self.rows.items() if sel and v == sel[0]), self.files[0] if self.files else None)
        if f and bc.is_blend(f) and getattr(self, 'blender', None):   # open a .blend in the Blender Shadow renders with
            subprocess.Popen([self.blender, f], creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)); return
        if f: open_path(f)

    # ------------------------------------------------------------------ options
    def on_sound(self, *_):
        if self.snd.get().startswith('External') and not getattr(self, '_quiet_sound', False):
            f = filedialog.askopenfilename(filetypes=[('Audio', '*.wav *.mp3 *.m4a *.aac *.flac *.ogg')])
            if f: self.snd_file.set(f)
            elif not self.snd_file.get(): self.snd.set(SOUNDS[0])
        self.refresh_audio()
    def pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get())
        if d: self.out_dir.set(d)
    def youtube_items(self):
        """(mp4, scene) pairs for the YouTube dialog: the videos this session made for the selected rows (all rows if none
        is selected), newest render of each output last."""
        sel = set(self.tree.selection())
        rows = [f for f in self.files if not sel or self.rows.get(f) in sel]
        return [(m, f) for f in rows for m in self.out_mp4.get(f, []) if os.path.isfile(m)]
    def open_youtube_dialog(self):
        try: return YouTubeDialog(self, self.youtube_items())
        except Exception as e:
            log.exception('youtube dialog'); messagebox.showerror(tr('YouTube'), str(e)); return None
    def folder_values(self):
        """The Folder combobox: Auto, the main folders (Music, Video, the ones added), None."""
        return [FOLDER_AUTO, *self.folders, FOLDER_NONE]
    def add_main_folder(self, name=None):
        """New folder...: add a main folder name (e.g. 'Kids') to the Folder list and select it. Saved in the settings."""
        from tkinter import simpledialog
        name = safe_rel_folder(name if name is not None else simpledialog.askstring('New folder', 'Folder name (inside Save to), e.g. Kids:', parent=self) or '')
        if not name: return
        if name.lower() not in (x.lower() for x in self.folders): self.folders.append(name)
        self.folder_box.set_values(self.folder_values()); self.folder_choice.set(next(x for x in self.folders if x.lower() == name.lower()))
        self.save()
    def open_out(self):
        d = self.out_dir.get(); os.makedirs(d, exist_ok=True); open_path(d)
    def open_log(self):
        if not os.path.exists(LOG): open(LOG, 'a').close()
        open_path(LOG)
    def save(self):
        save_cfg({'out': self.out_dir.get(), 'preset': self.preset.get(), 'open': self.open_when_done.get(), 'format': self.fmt.get(),
                  'skip_done': self.skip_done.get(), 'notify': self.notify.get(),
                  'folder': self.folder_choice.get(), 'folders': self.folders,
                  'assistant_open': self.ai_open, 'assistant_dir': self.ai_dir_choice, 'sidebar': getattr(self, 'side_open', True), 'ai': getattr(self, 'cfg_ai', {}),
                  'language': getattr(self, 'lang_choice', 'auto'), 'update_seen': getattr(self, 'update_seen', None), 'cloud_upload': getattr(self, 'cloud_up', ''),
                  'capture': self.capture.get(), 'blender_engine': self.bl_engine.get(), 'sound': self.snd.get(), 'sound_file': self.snd_file.get(), **({'theme': self.theme_choice} if self.theme_choice else {})})
    def on_close(self):
        self.do_cancel(); self.save()
        if self.ai: self.ai.close()   # ends the assistant's claude process (and a render it started)
        for i in (self._poll_id, getattr(self, '_clients_id', None)):
            try: self.after_cancel(i)
            except Exception: pass
        self.destroy()

    # ------------------------------------------------------------------ render
    def start(self, ask=messagebox.askyesnocancel):
        if not self.files: messagebox.showwarning(tr('Render'), tr('Add at least one .html or .blend scene.')); return
        self.check()
        need = {'ffmpeg'} | ({'chrome', 'playwright'} if any(not bc.is_blend(f) and not vsong.is_video(f) for f in self.files) else set())   # a .blend-only queue needs no Chrome
        miss = [k for k, v in self.env.items() if not v and k in need]
        if any(bc.is_blend(f) for f in self.files) and not self.blender: miss.append('Blender (for the .blend scenes)')
        if miss: messagebox.showwarning(tr('Setup'), 'Missing: ' + ', '.join(miss) + '. Use "Install missing".'); return
        try: os.makedirs(self.out_dir.get(), exist_ok=True)
        except OSError as e: messagebox.showerror(tr('Save to'), str(e)); return
        mode = sound_mode(self.snd.get())
        if mode == 'file' and not os.path.exists(self.snd_file.get()): messagebox.showwarning(tr('Sound'), tr('Pick an audio file.')); return
        fmt_name = self.fmt.get(); vertical = format_vertical('', fmt_name)   # Auto: decided per file in the worker
        jobs = [(f, scene_info(f)) for f in self.files]
        if any(format_vertical(f, fmt_name) for f, _ in jobs):   # only the files that render 9:16 must read get('h')
            old = [f for f, i in jobs if format_vertical(f, fmt_name) and not i['vertical']]
            if old:
                a = ask('9:16', f'{OUTDATED}:\n\n' + '\n'.join(os.path.basename(f) for f in old) +
                        '\n\nRender them anyway?\nYes = render all   No = skip these   Cancel = stop')
                if a is None: return
                if a is False:
                    for f in old: self.set_row(f, 'Skipped (outdated, no 9:16)')
                    jobs = [j for j in jobs if j[0] not in old]
                    if not jobs: return
        broken = {f: p for f, p in ((f, rc.contract_problems(f)) for f, _ in jobs if not bc.is_blend(f) and not vsong.is_video(f)) if p}
        if broken:   # explained before the render instead of an error (or a 3-minute wait) in the middle of the queue
            a = ask('Scene check', 'These scenes miss something Seekframe needs and will probably fail:\n\n' +
                    '\n\n'.join(f'{os.path.basename(f)}:\n' + '\n'.join(f'  • {x}' for x in p) for f, p in broken.items()) +
                    '\n\nRender them anyway?\nYes = render all   No = skip these   Cancel = stop')
            if a is None: return
            if a is False:
                for f in broken: self.set_row(f, SKIPPED_SCENE_CHECK)
                jobs = [j for j in jobs if j[0] not in broken]
                if not jobs: return
        for f, _ in jobs: self.set_row(f, 'Queued', '—')
        self.refresh_audio()   # Audio column + the Auto fallback warning on the status line
        with self.lock:
            keep = {f for f, _ in jobs}
            for f in self.files: self.state[f] = 'queued' if f in keep else 'skipped'
        self.opts = dict(vertical=vertical, format=fmt_name, sound=mode, audio_file=self.snd_file.get() or None,
                         capture=CAPTURES.get(self.capture.get(), 'png'), engine=blender_engine(self.bl_engine.get()), device='auto',
                         skip_done=bool(self.skip_done.get()), folder=self.folder_choice.get())
        self._spf = {}; self._run_t0 = {}; self._cur_left = None   # time estimate: measured again in every batch
        self.cancel.clear(); self.go.config(state='disabled'); self.stop.config(state='normal'); self.stop_cur.config(state='normal')
        self.bar['value'] = 0; self.pct.config(text='0%')
        preset = rc.PRESETS[self.preset.get()]
        log.info('batch start: %d file(s), preset=%s, format=%s, sound=%s', len(jobs), self.preset.get(), self.fmt.get(), mode)
        # Tk variables are read here on the main thread; the worker only gets plain values
        self.worker = threading.Thread(target=self.run, args=(preset, self.out_dir.get(), fmt_name), daemon=True); self.worker.start()

    def do_cancel(self):
        """Stop queue: stop the running file and cancel every file still Queued."""
        with self.lock: self.cancel.set(); self.item_cancel.set()
        if self.status.winfo_exists(): self.status.config(text=tr('Stopping the queue...'))
    def do_cancel_current(self):
        """Cancel current: stop only the running file; the queue goes on with the next Queued one."""
        with self.lock: self.item_cancel.set()
        self.status.config(text=tr('Cancelling the current file...'))

    def next_queued(self):
        """Mark the first 'queued' file as 'running' and return (file, how many are still queued after it, its own cancel
        Event, a copy of its narration settings or None); (None, 0, None, None) if none. The Event is new for every file;
        it starts set if the queue was already stopped. The narration copy is taken here, under the lock, so the worker
        never reads the live self.narr while the UI changes it."""
        with self.lock:
            f = next((x for x in self.files if self.state.get(x) == 'queued'), None)
            if not f: return None, 0, None, None
            self.state[f] = 'running'
            ev = self.item_cancel = threading.Event()
            if self.cancel.is_set(): ev.set()
            narr = dict(self.narr[f]) if f in self.narr else None
            return f, sum(1 for x in self.files if self.state.get(x) == 'queued'), ev, narr

    def run(self, preset, out, fmt_name):
        done, failed, warns, used, skipped = [], [], [], set(), []
        k = 0
        while True:
            f, left, ev, narr = self.next_queued()   # live list: files added while rendering are picked up, removed ones are not
            if f is None: break
            n = k + 1 + left
            try:
                self._run_one(f, k, n, preset, out, fmt_name, done, failed, warns, used, ev, narr=narr, skipped=skipped)
            finally:
                with self.lock: self.state[f] = 'finished'
                k += 1
        for w in warns: log.warning(w)
        self.q.put(('end', done, failed, warns, self.cancel.is_set(), skipped))

    def _run_one(self, f, k, n, preset, out, fmt_name, done, failed, warns, used, ev, narr=None, skipped=None):
        """One file in the worker thread. narr: the copy of this file's narration settings from next_queued (or None).
        The work itself is render_scene() (shared with tools/mcp_server.py); this only feeds the UI queue."""
        if self.cancel.is_set() or ev.is_set():
            self.q.put(('row', f, 'Cancelled', None)); return
        def prog(stage, a, b, eta=None, k=k, f=f):
            self.q.put(('p', k, n, f, stage, a, b, eta))
        r = render_scene(f, preset, out, self.opts, narr=narr, cancel=ev, progress=prog, used=used,
                         embedded=f in getattr(self, 'embedded', ()), fmt_name=fmt_name, warns=warns)
        if r['status'] == 'done': done.append(r['mp4'])
        elif r['status'] == 'error': failed.append(r['error'])
        elif r['status'] == 'skipped' and skipped is not None: skipped.append(r['mp4'])
        rp = getattr(self, 'row_problems', None)
        if rp is not None: rp[f] = render_problems(r)
        store = getattr(self, 'out_mp4', None)   # the YouTube dialog's list (tests call _run_one on stand-ins without it)
        if store is not None and r['status'] in ('done', 'skipped') and r.get('mp4'):
            lst = store.setdefault(f, [])
            if r['mp4'] not in lst: lst.append(r['mp4'])
        if r['status'] == 'done' and r.get('mp4') and getattr(self, 'cloud_up', ''):
            self.cloud_upload(r['mp4'], out)   # 3.33: in its own thread, the next render starts right away
        self.q.put(('row', f, r['row'], r['dur']))

    # ------------------------------------------------------------------ time estimate (Time column + the line under the bar)
    def _scene_seconds(self, f):
        """scene_duration_guess for one row, cached until the scene / its audio / its narration changes."""
        ra = self._audio(f); narr = self.narr.get(f)
        deps = [f, ra.get('audio_file')] + ([narr.get('wav'), narr.get('words') if isinstance(narr.get('words'), str) else None] if narr else [])
        try: key = tuple((d, os.path.getmtime(d)) for d in deps if d and os.path.isfile(d))
        except OSError: key = None
        hit = self._dur_cache.get(f)
        if hit and hit[0] == key: return hit[1]
        sec = scene_duration_guess(f, ra.get('audio_file'), narr)
        self._dur_cache[f] = (key, sec); return sec
    def _row_estimate(self, f, preset, capture):
        """Seconds this row will take, or None (unknown length, or skipped because it is up to date)."""
        blend = bc.is_blend(f); spf = self._spf.get('blend' if blend else 'html')
        if blend and spf is None: return None   # a .blend's speed is only known once its first frames are rendered
        return estimate_seconds(self._scene_seconds(f), preset, capture, spf)
    def update_eta(self):
        """Time column of the queued rows + 'about 12 min · done ~15:40' for the whole queue (before and while rendering)."""
        try:
            preset = rc.PRESETS.get(self.preset.get()) or next(iter(rc.PRESETS.values()))
            capture = CAPTURES.get(self.capture.get(), 'png'); busy = self.worker is not None and self.worker.is_alive()
            total, unknown = 0.0, 0
            with self.lock: todo = [f for f in self.files if self.state.get(f) == 'queued']
            for f in todo:
                est = self._row_estimate(f, preset, capture)
                self._set_time(f, f'~{fmt(est)}' if est else '?')
                if est: total += est
                else: unknown += 1
            if busy and self._cur_left: total += self._cur_left[1]
            txt = eta_text(total, unknown=unknown) if (todo or busy) else ''
            self.eta_lbl.config(text=((tr('Queue: ') if busy else tr('Estimate: ')) + i18n.phrase(txt)) if txt else '')
        except Exception:
            log.exception('update_eta')
    def _set_time(self, f, text):
        iid = self.rows.get(f)
        if iid and self.tree.exists(iid):
            v = list(self.tree.item(iid, 'values')); v += [''] * (6 - len(v))
            if v[5] != text: v[5] = text; self.tree.item(iid, values=v)
    def _eta_progress(self, f, stage, a, b, eta):
        """Feed one progress message into the estimate: measured seconds per frame and this file's time left."""
        now = time.time()
        if stage == 'load': self._run_t0[f] = now
        left = None
        if stage == 'frames' and eta is not None and b > a and a >= 3:
            self._spf['blend' if bc.is_blend(f) else 'html'] = eta / (b - a)   # = elapsed / frames done (render_core's own ETA)
        if stage == 'frames' and eta is not None: left = eta + 8   # + encode tail and QC
        elif stage in ('load', 'audio'):
            preset = rc.PRESETS.get(self.preset.get()) or {}
            left = self._row_estimate(f, preset, (getattr(self, 'opts', None) or {}).get('capture', 'png'))
        elif stage in ('encode', 'done'): left = 5
        self._cur_left = (f, left or 0)
        self._set_time(f, f'{fmt(left)} left' if left else '…')

    def poll(self):
        eta_dirty = False
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'p':
                    _, k, n, f, stage, a, b, eta = m
                    self._eta_progress(f, stage, a, b, eta); eta_dirty = True
                    frac = {'load': 0.0, 'audio': 0.02, 'frames': 0.03 + 0.92 * a / max(b, 1), 'encode': 0.96, 'done': 1.0}[stage]   # order: load, audio, frames, encode
                    pct = 100 * (k + frac) / n
                    self.bar['value'] = pct
                    self.pct.config(text=f'{pct:.0f}%' + (f'  ·  {fmt(eta)} left' if eta and stage == 'frames' else ''))
                    label = {'load': 'Loading scene', 'frames': f'Frames {a}/{b}', 'audio': 'Rendering sound', 'encode': 'Encoding MP4', 'done': 'Checking output'}[stage]
                    self.set_row(f, label); self.status.config(text=f'[{k + 1}/{n}] {os.path.basename(f)}: {label}')
                    if stage == 'load': self._update_narr_btn()   # the selected row may have just started rendering
                elif m[0] == 'row':
                    self.set_row(m[1], m[2], m[3]); self._update_narr_btn()
                    t0 = self._run_t0.pop(m[1], None)
                    self._set_time(m[1], f'took {fmt(time.time() - t0)}' if t0 and m[2].startswith('Done') else '')
                    if self._cur_left and self._cur_left[0] == m[1]: self._cur_left = None
                    eta_dirty = True
                elif m[0] == 'ai':
                    self.ai_event(*m[1:])
                elif m[0] == 'check':
                    self.show_check(m[1], m[2])
                elif m[0] == 'mcp':
                    self.show_mcp(m[1])
                elif m[0] == 'client_done':
                    self.client_done(*m[1:])
                elif m[0] == 'acct':
                    self.show_account(m[1], m[2])
                elif m[0] == 'cloud':
                    self.show_cloud(*m[1:])
                elif m[0] == 'cloud_msg':
                    self.status.config(text=m[1])
                elif m[0] == 'check_status':
                    self.status.config(text=m[1])
                elif m[0] == 'check_end':
                    self.check_btn.config(state='normal')
                elif m[0] == 'update':
                    self.show_update(m[1], m[2])
                elif m[0] == 'update_none':
                    self.update_none(m[1], m[2])
                elif m[0] == 'selftest':
                    self.on_selftest(m[1])
                elif m[0] == 'update_p':
                    _, got, total = m
                    self.status.config(text=f'Downloading update: {got / 1e6:.1f}' + (f' of {total / 1e6:.1f} MB' if total else ' MB'))
                    if total: self.bar['value'] = 100 * got / total
                elif m[0] == 'update_ready':
                    self.status.config(text=tr('Starting the installer...')); self.run_installer(m[1]); return   # the window is gone
                elif m[0] == 'update_fail':
                    self.update_failed(m[1])
                elif m[0] == 'end':
                    _, done, failed, warns, cancelled, skipped = m
                    self.go.config(state='normal'); self.stop.config(state='disabled'); self.stop_cur.config(state='disabled')
                    txt = (('Cancelled. ' if cancelled else '') + f'{len(done)} done' + (f', {len(failed)} failed' if failed else '')
                           + (f', {len(skipped)} skipped (up to date)' if skipped else ''))
                    self._cur_left = None; self.update_eta(); eta_dirty = False
                    if self.notify.get() and not cancelled and (done or failed):   # Windows notification; a click opens the folder
                        folders = {os.path.dirname(p) for p in done}
                        self.last_notify = (f'Seekframe: queue finished' if not failed else 'Seekframe: queue finished with errors', txt,
                                            folders.pop() if len(folders) == 1 else self.out_dir.get())
                        notify(*self.last_notify)
                    self.status.config(text=txt); self.bar['value'] = 100 if done and not failed and not cancelled else self.bar['value']
                    if not cancelled and not failed: self.pct.config(text='100%')
                    if failed:
                        messagebox.showerror(tr('Render failed'), '\n\n'.join(failed) + f'\n\nDetails in {LOG}')
                    if warns:
                        messagebox.showwarning(tr('Check the output'), '\n\n'.join(warns))
                    if done and not cancelled:
                        try:
                            import winsound; winsound.MessageBeep()
                        except Exception: pass
                        if self.open_when_done.get(): self.open_out()
        except queue.Empty:
            pass
        if eta_dirty: self.update_eta()
        self._poll_id = self.after(150, self.poll)

    # ------------------------------------------------------------------ Assistant panel (assistant.py, Claude Code headless)
    def build_assistant(self):
        """Collapsible chat on the right: Claude (through the installed Claude Code CLI, the owner's subscription) with Shadow's
        MCP tools. Hidden until the top-bar 'Assistant' button; the chat runs in assistant.Chat's threads (UI never waits)."""
        k = self.winfo_fpixels('1i') / 96
        p = self.ai_frame = ttk.LabelFrame(self, text=tr('Assistant (Claude Code)'), padding=8)
        hd = ttk.Frame(p); hd.pack(fill='x')
        self.ai_dir_lbl = ttk.Label(hd, text='', foreground='#888'); self.ai_dir_lbl.pack(side='left', fill='x', expand=True)
        ttk.Button(hd, text=tr('New chat'), command=self.ai_new).pack(side='right')
        ttk.Button(hd, text=tr('Folder...'), command=self.ai_pick_dir).pack(side='right', padx=(0, 6))
        tf = ttk.Frame(p); tf.pack(fill='both', expand=True, pady=(6, 6))
        self.ai_text = tk.Text(tf, wrap='word', width=48, height=18, state='disabled', relief='flat', padx=8, pady=6,
                               font='SunValleyBodyFont', cursor='arrow')
        sb = ttk.Scrollbar(tf, orient='vertical', command=self.ai_text.yview); self.ai_text.configure(yscrollcommand=sb.set)
        self.ai_text.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.ai_allow_bar = ttk.Frame(p)   # shown when Claude was blocked from a tool that may be allowed once
        self.ai_allow_lbl = ttk.Label(self.ai_allow_bar, text='', wraplength=round(330 * k)); self.ai_allow_lbl.pack(side='left', fill='x', expand=True)
        ttk.Button(self.ai_allow_bar, text=tr('No'), command=self.ai_deny).pack(side='right')
        ttk.Button(self.ai_allow_bar, text=tr('Allow once'), style='Accent.TButton', command=self.ai_allow).pack(side='right', padx=(0, 6))
        self.ai_in = tk.Text(p, wrap='word', height=3, width=48, relief='flat', padx=8, pady=6, font='SunValleyBodyFont', undo=True)
        self.ai_in.pack(fill='x')
        self.ai_in.bind('<Return>', self.ai_on_return)   # Enter sends, Shift+Enter = new line
        bt = ttk.Frame(p); bt.pack(fill='x', pady=(6, 0))
        self.ai_send_btn = ttk.Button(bt, text=tr('Send'), style='Accent.TButton', command=self.ai_send)
        self.ai_stop_btn = ttk.Button(bt, text=tr('Stop'), command=self.ai_stop, state='disabled')
        self.ai_send_btn.pack(side='left', fill='x', expand=True); self.ai_stop_btn.pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.ai_status = ttk.Label(p, text=tr('Ask for a render, a frame check or a QC summary. Uses your Claude subscription via Claude Code.'),
                                   foreground='#888', wraplength=round(380 * k)); self.ai_status.pack(fill='x', pady=(6, 0))
        self.ai_colors(); self._ai_dir_label()
        if self.ai_open: self.ai_open = False; self.after_idle(self.toggle_assistant)

    def ai_colors(self):
        if not hasattr(self, 'ai_text'): return
        dark = self.theme == 'dark'
        bg, fg = ('#2b2b2b', '#e6e6e6') if dark else ('#ececec', '#1b1b1b')
        self.ai_text.configure(background=bg, foreground=fg, insertbackground=fg, selectbackground='#2f6fb5', highlightthickness=0)
        style_input(self.ai_in, dark, hint=tr('Type a message for Claude... (Enter sends)'))   # 3.35: the box you type in stands out
        t = self.ai_text
        t.tag_configure('you', foreground='#58a6ff' if dark else '#0b57d0', spacing1=8)
        t.tag_configure('claude', spacing1=2)
        t.tag_configure('tool', foreground='#8b949e' if dark else '#5f6368')
        t.tag_configure('err', foreground='#ff7b72' if dark else '#b3261e')

    def toggle_assistant(self):
        self.ai_open = not self.ai_open
        self.update_idletasks(); w0 = self.winfo_width()
        # 3.31: the panel takes its room from the pages (no window resize = no squeezed table while it moves);
        # the window only grows when it is too narrow for both, and gives that back on close
        if self.ai_open:
            self._ai_dir_label()
            # room needed = what the window asks for now + the panel; grow FIRST, then pack the panel (packing first
            # squeezed the table for a moment, then the window caught up: the stutter in the owner's recording)
            self.update_idletasks()
            need = max(self.winfo_reqwidth(), self.body.winfo_reqwidth() + (self.side.winfo_reqwidth() if self.side.winfo_manager() else 0)) \
                + self.ai_frame.winfo_reqwidth() + 14
            # 3.34: never wider than the screen; remember how much it really grew, so closing gives back exactly that
            want = min(need, self.winfo_screenwidth() - self.winfo_rootx() - 8) if self.wm_state() != 'zoomed' else w0
            self._ai_grew = 0
            if want > w0:
                self.geometry(f'{want}x{self.winfo_height()}'); self.update_idletasks()
                self._ai_grew = max(0, self.winfo_width() - w0)
            self.ai_frame.pack(side='right', fill='both', padx=(0, 14), pady=14, before=self.body)
            self.ai_in.focus_set()
        else:
            self.ai_frame.pack_forget()
            grew = getattr(self, '_ai_grew', 0); self._ai_grew = 0
            if grew and self.wm_state() != 'zoomed':
                self.update_idletasks(); self.geometry(f'{max(w0 - grew, self.winfo_reqwidth())}x{self.winfo_height()}')
        self.side_colors()   # the Assistant row is marked while the panel is open
        self.save()

    def ai_folder(self):
        """The assistant's working folder: the one picked with Folder..., else the first scene's folder, else Save to."""
        if self.ai_dir_choice and os.path.isdir(self.ai_dir_choice): return self.ai_dir_choice
        sel = self._selected_path() if hasattr(self, 'tree') else None
        for f in ([sel] if sel else []) + list(self.files):
            if f and os.path.isdir(os.path.dirname(f)): return os.path.dirname(f)
        return self.out_dir.get() or os.path.expanduser('~')

    def _ai_dir_label(self):
        d = self.ai.cwd if self.ai else self.ai_folder()
        how = 'chosen' if self.ai_dir_choice else ('this chat' if self.ai else 'auto: scenes\' folder')
        self.ai_dir_lbl.config(text=tr('Folder ({0}): {1}', how, d if len(d) < 48 else '...' + d[-45:]))

    def ai_pick_dir(self):
        d = filedialog.askdirectory(title=tr('Assistant folder (Claude may read files here)'), initialdir=self.ai_folder())
        if not d: return
        self.ai_dir_choice = os.path.normpath(d); self.save()
        if self.ai and os.path.normcase(self.ai.cwd) != os.path.normcase(self.ai_dir_choice):
            self.ai_new(note=f'New folder: {self.ai_dir_choice} - a new conversation starts with the next message.')
        self._ai_dir_label()

    def ai_append(self, text, tag='claude'):
        t = self.ai_text; t.config(state='normal')
        at_end = t.yview()[1] > 0.98
        if tag != self.ai_last or tag in ('you', 'tool', 'err'):
            if t.index('end-1c') != '1.0': t.insert('end', '\n')
            if tag == 'you': t.insert('end', 'You: ', 'you')
            elif tag == 'claude' and self.ai_last != 'claude': t.insert('end', 'Claude: ', 'you')
        t.insert('end', text, tag); self.ai_last = tag
        t.config(state='disabled')
        if at_end: t.see('end')

    def ai_context(self):
        """The [Shadow app] block put in front of each message: the queue, Save to, settings, whether the GUI is rendering."""
        busy = self.worker is not None and self.worker.is_alive()
        lines = [f'[Seekframe app] Save to: {self.out_dir.get()} | Quality: {self.preset.get()} | Format: {self.fmt.get()} | '
                 f'Sound: {self.snd.get()} | Capture: {self.capture.get()} | GUI queue rendering now: {"yes" if busy else "no"}']
        rows = self.files[:30]
        lines.append(f'Queue ({len(self.files)} scene(s))' + (':' if rows else ': empty'))
        for f in rows:
            v = self.tree.item(self.rows[f], 'values') if f in self.rows else ()
            lines.append(f'- {f} | {v[1] if len(v) > 1 else ""} | {v[4] if len(v) > 4 else ""} | audio: {v[3] if len(v) > 3 else ""}')
        if len(self.files) > 30: lines.append(f'... and {len(self.files) - 30} more')
        sel = self._selected_path()
        if sel: lines.append(f'Selected: {sel}')
        return '\n'.join(lines)

    def ai_on_return(self, e=None):
        if e is not None and getattr(e, 'state', 0) & 1: return None   # Shift+Enter: the Text widget adds a new line
        self.ai_send(); return 'break'

    def ai_send(self, text=None, show=True):
        msg = (self.ai_in.get('1.0', 'end') if text is None else text).strip()
        if not msg: return
        if self.ai and self.ai.busy: return
        if text is None: self.ai_in.delete('1.0', 'end')
        if show: self.ai_append(msg, 'you')
        if self.ai is None:
            q = self.q
            self.ai = assistant.Chat(lambda *ev: q.put(('ai',) + ev), self.ai_folder(),
                                     add_dirs=[d for d in {self.out_dir.get()} if d], **self.ai_kw)
            self._ai_dir_label()
        self.ai_allow_bar.pack_forget(); self.ai_pending = None
        self.ai_send_btn.config(state='disabled'); self.ai_stop_btn.config(state='normal'); self.ai_t0 = time.time()
        self.ai.send(self.ai_context() + '\n\n' + msg)

    def ai_stop(self):
        if not self.ai: return
        self.ai.stop()
        self.ai_append('(stopped - a render the assistant started was stopped too; the GUI queue is not affected)', 'tool')
        self._ai_idle('Stopped. The next message continues the same conversation.')

    def ai_new(self, note=None):
        if self.ai: self.ai.close()
        self.ai = None; self.ai_pending = None; self.ai_allow_bar.pack_forget(); self.ai_last = None
        t = self.ai_text; t.config(state='normal'); t.delete('1.0', 'end'); t.config(state='disabled')
        if note: self.ai_append(note, 'tool')
        self._ai_idle('New conversation.'); self._ai_dir_label()

    def ai_allow(self):
        tool = self.ai_pending
        self.ai_allow_bar.pack_forget(); self.ai_pending = None
        if not (tool and self.ai and self.ai.allow_once(tool)): return
        name = assistant.short_tool(tool)
        self.ai_append(f'(you allowed {name} once)', 'tool')
        self.ai_send(f'The owner clicked "Allow once" for {name}. It is allowed for this message only: do the step that was blocked now.', show=False)

    def ai_deny(self):
        tool = self.ai_pending; self.ai_allow_bar.pack_forget(); self.ai_pending = None
        if tool: self.ai_append(f'(not allowed: {assistant.short_tool(tool)})', 'tool')

    def _ai_idle(self, text):
        self.ai_send_btn.config(state='normal'); self.ai_stop_btn.config(state='disabled'); self.ai_status.config(text=text)

    def ai_event(self, kind, *d):
        if kind == 'text':
            self.ai_append(d[0], 'claude')
        elif kind == 'tool':
            self.ai_append('  > ' + d[0], 'tool')
        elif kind == 'status':
            self.ai_status.config(text=d[0])
        elif kind == 'denied':
            tool, summary, allowable = d
            self.ai_append(f'  blocked: {summary}', 'err')
            if allowable:
                self.ai_pending = tool
                self.ai_allow_lbl.config(text=tr('Claude wants to use {0}. Allow it once?', summary))
                self.ai_allow_bar.pack(fill='x', pady=(0, 6), before=self.ai_in)
        elif kind == 'turn_end':
            took = f' · {time.time() - self.ai_t0:.0f} s' if self.ai_t0 else ''
            self._ai_idle(('Done' if not d[0].get('is_error') else 'Finished with an error') + took)
            if self.ai_pending: self.ai_status.config(text=tr('Waiting for you: Allow once or No'))
        elif kind == 'error':
            self.ai_append(d[0], 'err'); self._ai_idle('Error - see the message above.')
            if self.ai and not self.ai.ready_ok: self.ai = None   # not installed / not signed in: check again on the next Send
        elif kind == 'exit':
            if not (self.ai and self.ai.busy): self.ai_stop_btn.config(state='disabled'); self.ai_send_btn.config(state='normal')

    # ------------------------------------------------------------------ AI... (3.19, ai_tasks.py via dialogs.AIWindow)
    def open_ai(self, paths=None, problems=None):
        """The AI... button: one selected row -> the AI window (Fix the scene / Write YouTube text), started from the
        problems Shadow saw for that row (render error, QC, Check frames). Returns the window or None."""
        if paths is None:
            sel = set(self.tree.selection()); paths = [f for f in self.files if self.rows.get(f) in sel]
        if len(paths) != 1:
            self.status.config(text=tr('Select one scene, then press AI...')); return None
        f = paths[0]
        mp4s = [m for m in self.out_mp4.get(f, []) if os.path.isfile(m)]
        probs = list(problems if problems is not None else self.row_problems.get(f, []))
        if not probs and f.lower().endswith(('.html', '.htm')): probs = list(rc.contract_problems(f) or [])
        try: return AIWindow(self, f, probs, mp4=mp4s[-1] if mp4s else None)
        except Exception: log.exception('AI window'); return None
    def on_language(self, ask=None, restart=None):
        """The language list changed: save it and offer to restart Shadow (the window is built once, in one language)."""
        name = self.lang_var.get()
        code = 'auto' if name == self.lang_names[0] else next((c for c, n in i18n.LANGS.items() if n == name), 'en')
        if code == self.lang_choice: return False
        self.lang_choice = code; self.save()
        new = i18n.pick(code)
        if new == self.lang: return True
        if (ask or messagebox.askyesno)(tr('Language'), tr('Seekframe will use {0} after a restart. Restart now?', i18n.name(new))):
            if self.worker and self.worker.is_alive():
                messagebox.showinfo(tr('Language'), tr('A render is running: the new language is used the next time Seekframe starts.')); return True
            (restart or self.restart)()
        return True
    def restart(self, popen=subprocess.Popen):
        """Start a new Shadow and close this one. The new Shadow.exe must NOT reuse this one's _MEI temp folder: that folder is
        deleted when this process exits, and the new one then crashed at start ('pyi_rth_pkgres ... No such file', 3.21).
        PYINSTALLER_RESET_ENVIRONMENT=1 (PyInstaller 6.9+) makes it a fresh, independent instance."""
        args = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, os.path.abspath(__file__)]
        popen(args, **restart_kw())
        self.on_close()
    def open_new_video(self):
        """Top bar 'New video (AI)...': idea -> narration, voice, scene (ai_tasks.new_video) -> into the queue."""
        try: return NewVideoDialog(self)
        except Exception: log.exception('new video window'); return None
    def ai_applied(self, f):
        """The AI window replaced the scene file: forget what was wrong and show it needs a new render."""
        self.row_problems.pop(f, None); self._dur_cache.pop(f, None)
        with self.lock:
            if self.state.get(f) != 'running': self.state[f] = 'queued'
        self.set_row(f, 'Fixed by AI - render again')

    # ------------------------------------------------------------------ Check frames (frame_check.check, in a thread)
    def check_frames(self, paths=None, ask=None):
        """The 'Check frames' button: contact sheet + problems for the selected rows (frame_check, like tools/check_frames.py),
        in a background thread; each result opens a small window. HTML scenes that read get('h') are checked in 16:9 and
        9:16, others in their row's format only. While a render runs it asks first (a second Chrome/Blender slows it).
        Returns the thread, or None with the reason on the status line."""
        if paths is None:
            sel = set(self.tree.selection()); paths = [f for f in self.files if self.rows.get(f) in sel]
        if not paths:
            self.status.config(text=tr('Select one or more scenes, then press Check frames.')); return None
        if self.check_thread and self.check_thread.is_alive():
            self.status.config(text=tr('A frame check is already running.')); return None
        if self.worker and self.worker.is_alive():
            if not (ask or messagebox.askyesno)('Check frames', 'A render is running. Checking frames now starts a second Chrome '
                                                '(or Blender) and slows the render down.\n\nCheck anyway?'):
                return None
        jobs = []
        for f in paths:
            vertical = format_vertical(f, self.fmt.get())
            only = None if bc.is_blend(f) or scene_info(f)['vertical'] else format_label(vertical)
            jobs.append((f, only))
        engine = blender_engine(self.bl_engine.get()); kw = dict(self.check_kw)
        def run():
            for i, (f, only) in enumerate(jobs, 1):
                self.q.put(('check_status', f'Checking frames {i}/{len(jobs)}: {os.path.basename(f)}...'))
                try: res = video_check(f, self._audio(f).get('audio_file')) if vsong.is_video(f) else frame_check.check(f, only=only, engine=engine, **({} if bc.is_blend(f) else kw))
                except Exception as e:
                    log.exception('check frames'); res = dict(ok=False, sheet=None, problems=[f'{type(e).__name__}: {e}'], notes=[])
                log.info('check frames %s: %s', f, 'OK' if res['ok'] else '; '.join(res['problems']))
                self.q.put(('check', f, res))
            self.q.put(('check_end',))
        self.check_btn.config(state='disabled')
        self.check_thread = threading.Thread(target=run, daemon=True); self.check_thread.start()
        return self.check_thread
    def show_check(self, f, res):
        self.check_results.append((f, res))
        if not res.get('ok'): self.row_problems[f] = list(res.get('problems') or [])
        name = os.path.basename(f)
        self.status.config(text=f'{name}: frames OK' if res['ok'] else f'{name}: {len(res["problems"])} problem(s) - see the check window')
        if getattr(self, 'check_window_off', False): return None   # tests
        try: return CheckWindow(self, f, res)
        except Exception: log.exception('check window'); return None


def cloud_folders(env=None):
    """Synced cloud folders found on this PC: [(label, path)]. OneDrive (personal / work), Google Drive (My Drive), Dropbox,
    iCloud Drive. Only folders that exist; nothing is created."""
    env = os.environ if env is None else env
    home = env.get('USERPROFILE') or os.path.expanduser('~'); out = []
    def add(label, p):
        if p and os.path.isdir(p) and all(os.path.normcase(p) != os.path.normcase(q) for _, q in out): out.append((label, p))
    add('OneDrive', env.get('OneDrive')); add('OneDrive (work)', env.get('OneDriveCommercial'))
    for d in [home] + [f'{c}:\\' for c in 'GHIJ']:
        add('Google Drive', os.path.join(d, 'My Drive')); add('Google Drive', os.path.join(d, 'Google Drive', 'My Drive'))
    try:
        info = os.path.join(env.get('LOCALAPPDATA', ''), 'Dropbox', 'info.json')
        if os.path.isfile(info):
            with open(info, encoding='utf-8') as f: d = json.load(f)
            for v in d.values():
                if isinstance(v, dict) and v.get('path'): add('Dropbox', v['path'])
    except Exception:
        pass
    add('Dropbox', os.path.join(home, 'Dropbox')); add('iCloud Drive', os.path.join(home, 'iCloudDrive'))
    add('Box', os.path.join(home, 'Box'))
    return out

CLOUD_APPS = ('OneDrive', 'Google Drive', 'Dropbox', 'iCloud Drive', 'Box')

def storage_places(env=None):
    """The Settings place buttons: This PC (the Videos folder). 3.34: the cloud-app buttons (3.31) are gone, the owner
    uploads to the cloud himself; a synced cloud folder can still be typed or picked with Browse... [(label, path)]"""
    env = os.environ if env is None else env
    home = env.get('USERPROFILE') or os.path.expanduser('~')
    return [('This PC', os.path.join(home, 'Videos'))]

def storage_kind(path):
    """'network' for \\\\server\\share or a mapped network drive, 'cloud' inside a synced cloud folder, else 'local'."""
    p = os.path.abspath(path or '')
    if p.startswith('\\\\'): return 'network'
    try:
        import ctypes
        if os.name == 'nt' and len(p) > 1 and p[1] == ':' and ctypes.windll.kernel32.GetDriveTypeW(p[:2] + '\\') == 4: return 'network'
    except Exception:
        pass
    if any(os.path.normcase(p).startswith(os.path.normcase(c)) for _, c in cloud_folders()): return 'cloud'
    return 'local'

def storage_check(path):
    """Can Seekframe write videos there? -> dict(ok, kind, free_gb, message). Writes and deletes one small test file."""
    p = os.path.abspath(os.path.expanduser(path or ''))
    kind = storage_kind(p)
    try:
        os.makedirs(p, exist_ok=True)
        t = os.path.join(p, f'.seekframe_write_test_{uuid.uuid4().hex[:6]}')
        with open(t, 'wb') as f: f.write(b'x' * 1024)
        os.remove(t)
        free = shutil.disk_usage(p).free / 1e9
    except Exception as e:
        return dict(ok=False, kind=kind, free_gb=None, message=f'{type(e).__name__}: {e}')
    return dict(ok=True, kind=kind, free_gb=round(free, 1), message='')

def mcp_status(claude_json=None, ps=None):
    """Seekframe's connection for Claude (MCP): dict(claude=bool (Claude Code found), registered=bool (the 'shadow' server is
    set up for Claude Code), running=int (MCP server processes alive now)). The process count uses one hidden PowerShell call."""
    out = dict(claude=bool(assistant.find_claude()), registered=False, running=0)
    try:
        with open(claude_json or os.path.join(os.path.expanduser('~'), '.claude.json'), encoding='utf-8') as f:
            out['registered'] = bool((json.load(f).get('mcpServers') or {}).get(assistant.SERVER))
    except Exception:
        pass
    try:
        r = (ps or subprocess.run)(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                    "@(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -like '*mcp_server.py*' }).Count"],
                                   capture_output=True, text=True, timeout=20, creationflags=rc.NOWIN)
        out['running'] = int((r.stdout or '0').strip().splitlines()[-1])
    except Exception:
        pass
    return out


def restart_kw(env=None):
    """Popen arguments for starting Shadow again from inside Shadow: its own environment without PyInstaller's markers of
    this process, plus PYINSTALLER_RESET_ENVIRONMENT=1, so a new onefile exe unpacks itself instead of using our temp folder."""
    return dict(env=updater.child_env(env), close_fds=True, cwd=os.path.expanduser('~'),   # the updater's setup launch fix (3.7)
                creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))


def render_problems(r):
    """What a render_scene() result says went wrong, as lines for the AI window ([] when it went fine)."""
    out = []
    if r.get('status') == 'error':
        out.append(f'The render failed: {r.get("error") or "unknown error"}')
        if r.get('log'): out.append(f'Render log (read it): {r["log"]}')
    q = r.get('qc') or {}
    if q and q.get('status') not in (None, 'OK'):
        out += [f'Quality check {q.get("status")}: {x}' for x in q.get('reasons') or []]
        if r.get('qc_report'): out.append(f'QC report: {r["qc_report"]}')
    return out


def cli_check(argv):
    """Shadow.exe --check scene.html|scene.blend [--only 16:9|9:16] [--times 3,25%,end-2] [--out sheet.jpg]
    tools/check_frames.py inside the exe: prints the sheet path and OK / PROBLEMS; exit 0 = OK, 1 = problems."""
    import argparse
    ap = argparse.ArgumentParser(prog='Seekframe'); ap.add_argument('--check', required=True, metavar='SCENE')
    ap.add_argument('--only', choices=['16:9', '9:16']); ap.add_argument('--times'); ap.add_argument('--out')
    ap.add_argument('--engine', default='scene', choices=list(bc.ENGINES)); a = ap.parse_args(argv)
    res = frame_check.check(a.check, times=a.times, out=a.out, only=a.only, engine=a.engine)
    lines = [f'note: {n}' for n in res['notes']] + ([f'wrote {res["sheet"]}'] if res['sheet'] else [])
    lines.append('OK' if res['ok'] else 'PROBLEMS:\n  ' + '\n  '.join(res['problems']))
    log.info('cli check %s: %s', a.check, ' | '.join(lines))
    try: print('\n'.join(lines))   # a --noconsole exe has no stdout: the log has it too
    except Exception: pass
    return 0 if res['ok'] else 1

SELFTEST_SCENE = """<!doctype html><meta charset=utf-8><title>Seekframe self-test</title><body style="margin:0;background:#000">
<canvas id=c></canvas><script>
const q = new URLSearchParams(location.search), get = k => q.get(k), W = +get('w') || 1280, H = +get('h') || Math.round(W * 9 / 16);
const c = document.getElementById('c'); c.width = W; c.height = H; const g = c.getContext('2d');
window.DURATION = 2;
window.seek = (t) => { g.fillStyle = '#0b1d33'; g.fillRect(0, 0, W, H); const x = W * (0.1 + 0.8 * t / 2);
  g.fillStyle = '#f5a623'; g.beginPath(); g.arc(x, H / 2, H / 6, 0, 7); g.fill();
  g.fillStyle = '#fff'; g.font = `${Math.round(H / 14)}px sans-serif`; g.textAlign = 'center'; g.fillText('Seekframe self-test  t=' + t.toFixed(2), W / 2, H * 0.88); };
window.seek(0); window.__ready = true;
</script>"""

def selftest(progress=lambda msg: None, channel='auto', extra_args=(), keep=False):
    """Self-test: renders a built-in 2-second scene with a test tone through the real pipeline (browser -> frames -> ffmpeg ->
    audio loudness -> QC) in a temp folder. -> dict(ok, steps=[(name, ok, detail)], seconds, browser, mp4 (only with keep)).
    Never raises; the first failing step says what to fix."""
    t0 = time.time(); steps = []; tmp = tempfile_dir('shadow_selftest_'); res = dict(ok=False, steps=steps, browser=None)
    def step(name, ok, detail=''):
        steps.append((name, bool(ok), detail)); progress(f'{name}: {"OK" if ok else "FAILED"}'); return ok
    try:
        env = rc.check_env()
        ch = rc.resolve_channel(channel) if channel == 'auto' else channel; res['browser'] = rc.browser_name(ch) if ch else 'bundled Chromium'
        if not step('Browser', env['chrome'] or channel != 'auto', res['browser'] if env['chrome'] or channel != 'auto'
                    else 'neither Chrome nor Edge found: winget install -e --id Google.Chrome'): return res
        if not step('ffmpeg', env['ffmpeg'], rc.find_ffmpeg() or 'not on PATH: winget install -e --id Gyan.FFmpeg, then sign out and in'): return res
        if not step('playwright', env['playwright'], 'ok' if env['playwright'] else 'pip install playwright'): return res
        scene = os.path.join(tmp, 'selftest.html')
        with open(scene, 'w', encoding='utf-8') as f: f.write(SELFTEST_SCENE)
        tone = os.path.join(tmp, 'selftest.wav')
        r = subprocess.run([rc.find_ffmpeg(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2:sample_rate=48000',
                            '-ac', '2', tone], capture_output=True, creationflags=NOWIN)
        if not step('Test tone (ffmpeg)', r.returncode == 0 and os.path.isfile(tone), rc.ffmpeg_message(r.stderr.decode('utf-8', 'replace').splitlines(), r.returncode) if r.returncode else 'ok'): return res
        mp4 = os.path.join(tmp, 'selftest.mp4'); info = {}; preset = rc.PRESETS['Draft (fast, 720p)']; t1 = time.time()
        try:
            rc.render(scene, mp4, preset, sound='file', audio_file=tone, capture='jpeg', info=info, channel=channel, extra_args=extra_args)
            step('Render (browser + frames + encode)', True, f'{time.time() - t1:.1f} s with {info.get("browser")}')
        except Exception as e:
            step('Render (browser + frames + encode)', False, (str(e).strip().splitlines() or [type(e).__name__])[0]); return res
        pr = probe(mp4)
        if not step('Output file', pr and (pr[0], pr[1]) == (1280, 720) and pr[3], f'{pr[0]}x{pr[1]}, {pr[2]:.1f} s, audio {"yes" if pr and pr[3] else "no"}' if pr else 'ffprobe could not read it'): return res
        qres, _ = quality_check(mp4, preset, False, info, 'file')
        step('Quality check', qres and qres['status'] == qc.OK, (qres or {}).get('status', 'not run') + (': ' + '; '.join(qres['reasons']) if qres and qres.get('reasons') else ''))
        res['ok'] = all(s[1] for s in steps)
        if keep: res['mp4'] = mp4
        return res
    except Exception as e:
        log.exception('self-test'); step('Self-test', False, str(e)); return res
    finally:
        res['seconds'] = round(time.time() - t0, 1)
        log.info('self-test: %s in %s s, %s', 'OK' if res['ok'] else 'FAILED', res['seconds'], '; '.join(f'{n}={"ok" if o else d}' for n, o, d in steps))
        if not keep: shutil.rmtree(tmp, ignore_errors=True)

def tempfile_dir(prefix):
    import tempfile
    return tempfile.mkdtemp(prefix=prefix)

def selftest_text(res):
    lines = [('OK   ' if ok else 'FAIL ') + f'{n}: {d}' for n, ok, d in res['steps']]
    return ('Self-test passed' if res['ok'] else 'Self-test FAILED') + f' ({res.get("seconds", 0)} s)\n\n' + '\n'.join(lines)

def clean_old_updates(dest=None):
    """Delete update setups in %TEMP%\\Shadow-update that are this version or older (installed already). -> bytes freed."""
    dest = dest or os.path.join(os.environ.get('TEMP') or os.path.expanduser('~'), 'Shadow-update'); freed = 0
    for p in glob.glob(os.path.join(dest, '*-Setup.exe')):   # Seekframe-X.Y-Setup.exe, and Shadow-X.Y-Setup.exe from before 3.25
        m = re.match(r'(?:Seekframe|Shadow)-([\d.]+)-Setup\.exe$', os.path.basename(p), re.I)
        try:
            if m and updater.parse_version(m.group(1)) <= updater.parse_version(rc.VERSION):
                n = os.path.getsize(p); os.remove(p); freed += n
        except (OSError, ValueError): pass
    return freed

def startup_cleanup():
    """At start (in a thread): leftover render temp folders of crashed renders + installed update setups."""
    try:
        n, freed = rc.clean_stale_temp(); freed += clean_old_updates()
        if n or freed: log.info('cleanup: %d stale temp folder(s), %.1f MB freed', n, freed / 1048576)
    except Exception: log.exception('startup cleanup')

def cli_selftest(argv):
    """Shadow.exe --selftest: render the built-in test scene with a tone and check it; exit 0 = OK."""
    res = selftest()
    try: print(selftest_text(res))
    except Exception: pass
    return 0 if res['ok'] else 1

def cli(argv):
    """Shadow.exe --render scene.html out.mp4 [--vertical] [--preset draft|good|best] [--silent] [--fast]
    Renders without the window (for scripts and for testing the built exe). Progress and errors go to shadow.log.
    Exit code 0 = done and the output size checked, 1 = failed."""
    import argparse
    ap = argparse.ArgumentParser(prog='Seekframe'); ap.add_argument('--render', nargs=2, metavar=('SCENE', 'OUT'), required=True)
    ap.add_argument('--vertical', action='store_true'); ap.add_argument('--silent', action='store_true')
    ap.add_argument('--preset', default='best', choices=['draft', 'good', 'best', '1440p', '4k'])
    ap.add_argument('--fast', action='store_true', help='Fast capture (JPEG frames, about 2x faster)')
    ap.add_argument('--engine', default='scene', choices=list(bc.ENGINES), help='.blend only: render engine (default: the scene setting)')
    a = ap.parse_args(argv)
    preset = next(v for k, v in rc.PRESETS.items() if k.lower().startswith(a.preset))
    scene, out = (os.path.abspath(x) for x in a.render)
    log.info('cli render %s -> %s preset=%s vertical=%s', scene, out, a.preset, a.vertical)
    try:
        used = {}
        opts = dict(vertical=a.vertical, sound='none' if a.silent else 'generated', capture='jpeg' if a.fast else 'png')
        opts['lufs'] = target_lufs(scene, opts['sound'])   # the scene's shadow-lufs / shadow-folder Music, else -15
        if bc.is_blend(scene): bc.render(scene, out, preset, info=used, engine=a.engine, **opts)
        else: rc.render(scene, out, preset, info=used, **opts)
        pr = probe(out); exp = expected_size(preset, a.vertical)
        log.info('cli done %s %s sound=%s expected=%s', out, pr, used.get('sound'), exp)
        try:   # QC is information only: the exit code below does not depend on it
            res, path = quality_check(out, preset, a.vertical, used, used.get('sound'))
            log.info('cli qc %s %s', res['status'] if res else 'not run', path or '')
        except Exception:
            log.error('cli qc hook failed\n%s', traceback.format_exc())
        return 0 if pr and (pr[0], pr[1]) == exp else 1
    except Exception:
        log.error('cli failed\n%s', traceback.format_exc()); return 1

def main():
    global LOG
    if os.environ.get('SHADOW_LOG'): LOG = os.environ['SHADOW_LOG']   # tests: keep the real ~/shadow.log untouched
    dpi_aware(); setup_log()
    if '--render' in sys.argv:
        sys.exit(cli(sys.argv[1:]))
    if '--check' in sys.argv:
        sys.exit(cli_check(sys.argv[1:]))
    if '--selftest' in sys.argv:
        sys.exit(cli_selftest(sys.argv[1:]))
    threading.Thread(target=startup_cleanup, daemon=True, name='startup-cleanup').start()
    try:
        a = App()
        proj = next((x for x in sys.argv[1:] if x.lower().endswith(PROJECT_EXT) and os.path.isfile(x)), None)
        if proj: a.after(300, lambda: a.open_project(proj))   # Shadow.exe my.shadow (or a double-clicked .shadow file)
        a.mainloop()
    except Exception:
        log.critical('crash\n%s', traceback.format_exc()); raise


from dialogs import AIWindow, CheckWindow, CloudDialog, NarrationDialog, NewVideoDialog, YouTubeDialog   # noqa: E402,F401  (3.16: dialogs.py; AIWindow 3.19)

if __name__ == '__main__':
    main()
