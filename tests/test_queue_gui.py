"""Queue behaviour of the real GUI (app.App), checked with asserts. Windows and Linux.
Usage: python tests/test_queue_gui.py      exit 0 = every check PASS, 1 = any FAIL (or a crash / timeout)

Drives the real App with its window hidden. Nothing in app.py / render_core.py is changed on disk; inside this process only:
  - message boxes are replaced by recorders (so nothing pops up),
  - app.LOG / app.LOG_DIR point into the temp folder (the real ~/shadow.log and ~/logs/ are checked to be untouched),
  - rc.PRESETS gets a tiny 'Test (640 px)' preset,
  - rc.render is wrapped to add software WebGL + a frame cap (like smoke_test.py) and to record the order of renders.
  Q1 queue of 3 renders in order   Q2a 'Cancel current' at #2: #3 still renders   Q2b 'Stop queue' at #2: #2 and #3 cancelled
  Q3 add / remove a queued file / remove the running one, while rendering   Q4 clear while rendering
  Q5 a normal render shows 'Done · QC OK|Warn' and writes <scene>/<name>.qc.txt   Q6 a QC that raises leaves the row 'Done'
  Q13 Format = Auto (by file name): short_*.html -> 9:16, others 16:9 in one queue; Format column; 9:16 warning per file
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import render_core as rc
os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts
import app
app.notify = lambda *a, **k: None   # 3.32: never a real Windows notification from a test
import qc
from regression import browsers, probe, render_dirs, _band_db   # helpers only (its tests run only under __main__)

WEBGL = os.path.join(ROOT, 'tests', 'fixtures', 'webgl_min.html')   # never read scenes/ in tests
FRAMES = 15
rc.PRESETS['Test (640 px)'] = dict(w=640, samples=2)
_render = rc.render; started = []
# Gate: the tiny fixture renders its 15 frames in ~50 ms, far faster than the UI (poll() every 150 ms) or a test watcher
# can see 'Frames n/15'. So a test that must act WHILE an item renders arms the gate for that scene: its render is held
# inside the progress callback after frame GATE_FRAME (the worker thread waits), the test acts on the Tk thread, then
# opens the gate. render_core checks cancel before every frame, so a cancel pressed while held always takes effect.
GATE_FRAME = 3
GATE = dict(name=None, reached=threading.Event(), release=threading.Event())
def render_wrapped(html, out, preset, **kw):
    b = os.path.basename(html)   # a narrated item renders its hidden temp scene: record it under the original name
    orig = re.sub(r'^\.shadow_narr_[0-9a-f]+_', '', b)
    started.append(orig + (' (narrated)' if b.startswith('.shadow_narr_') else ''))
    if GATE['name'] == orig:   # one-shot: only the first render of the armed scene is held
        GATE['name'] = None; prog = kw.get('progress', lambda *_: None)
        def gated(stage, n, total, *rest):
            prog(stage, n, total, *rest)
            if stage == 'frames' and n == GATE_FRAME:
                GATE['reached'].set(); GATE['release'].wait(60)   # never hang the worker for good
        kw['progress'] = gated
    kw.setdefault('max_frames', FRAMES); kw.setdefault('channel', None)
    kw.setdefault('extra_args', ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    return _render(html, out, preset, **kw)
rc.render = render_wrapped

msgs = []
for n in ('showwarning', 'showerror', 'showinfo'):
    setattr(app.messagebox, n, (lambda n: lambda title, text, **k: msgs.append((n, title, text)))(n))
app.filedialog.askopenfilename = lambda **k: ''
app.messagebox.askyesno = lambda *x, **k: False; app.filedialog.askdirectory = lambda **k: ''   # never a real dialog (Add folder / Check frames)

ROOT_TMP = tempfile.mkdtemp(prefix='shadow_queue_gui_')
tempfile.tempdir = ROOT_TMP            # render_core's bq_render_* folders land here, so leftovers are visible

# Logs go to the temp folder for the whole run: the real ~/shadow.log and ~/logs/ must never be touched.
REAL_LOG, REAL_LOG_DIR = app.LOG, app.LOG_DIR
def _stat(p):
    if os.path.isfile(p): s = os.stat(p); return ('file', s.st_size, s.st_mtime_ns)
    if os.path.isdir(p): return ('dir', sorted(os.listdir(p)), os.stat(p).st_mtime_ns)
    return None
REAL_BEFORE = (_stat(REAL_LOG), _stat(REAL_LOG_DIR))
app.LOG = os.path.join(ROOT_TMP, 'shadow.log'); app.LOG_DIR = os.path.join(ROOT_TMP, 'logs')
for h in list(app.log.handlers): app.log.removeHandler(h)   # setup_log() in App() then opens the temp shadow.log
scenes_dir = os.path.join(ROOT_TMP, 'scenes'); os.makedirs(scenes_dir)
S = []
for name in ('q_a.html', 'q_b.html', 'q_c.html', 'q_extra.html'):
    p = os.path.join(scenes_dir, name); shutil.copy(WEBGL, p); S.append(p)
# narration material: a 2D scene with a SOUND kit, a WebGL scene, one already narrated, one without a SOUND kit
FIXT = os.path.join(ROOT, 'tests', 'fixtures')
N2D = os.path.join(scenes_dir, 'q_n2d.html'); shutil.copy(os.path.join(FIXT, 'narr_2d.html'), N2D)
NARRQ = os.path.join(scenes_dir, 'q_narr.html'); shutil.copy(WEBGL, NARRQ)
NOLD = os.path.join(scenes_dir, 'q_old.html')
with open(os.path.join(FIXT, 'narr_2d.html'), encoding='utf-8') as fh: open(NOLD, 'w', encoding='utf-8').write(fh.read() + '<script>window.NARR={}</script>')
NPLAIN = os.path.join(scenes_dir, 'q_plain.html'); shutil.copy(os.path.join(FIXT, 'minimal_silent.html'), NPLAIN)
VOICE, EXT = os.path.join(ROOT_TMP, 'voice.wav'), os.path.join(ROOT_TMP, 'external 1k.wav')
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=f=300:d=3,volume=0.6', '-ac', '1', '-c:a', 'pcm_s16le', VOICE], check=True)
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=f=1000:d=3', EXT], check=True)
WORDS = os.path.join(ROOT_TMP, 'words.json')
with open(WORDS, 'w', encoding='utf-8') as fh: json.dump({'words': [{'w': 'Hello', 's': 0.1, 'e': 0.4}]}, fh)
def temps(): return sorted(f for f in os.listdir(scenes_dir) if f.startswith('.shadow_narr_'))

a = app.App(); a.withdraw()
a.open_when_done.set(False); a.skip_done.set(False); a.notify.set(False)   # Q12 expects _2; no toasts from tests
a.folder_choice.set(app.FOLDER_NONE)   # the Q checks below look at <out>\<scene>\ (Folder = Auto is checked in test_queue_logic / test_mcp_server)
_fv = a.folder_values()
assert _fv[0] == app.FOLDER_AUTO and _fv[-1] == app.FOLDER_NONE and 'Music' in _fv and 'Video' in _fv, _fv
a.preset.set('Test (640 px)'); a.fmt.set('16:9 (YouTube)'); a.snd.set(app.SOUNDS[0])
results = {}; checks = []
BLOCKED_MSG = "can't be removed"      # part of the status-line message when the running file is asked to go

def check(q, what, ok, seen, expected):
    """Record one assert: PASS/FAIL, what was seen, and what was expected (printed on FAIL)."""
    checks.append((q, what, bool(ok), seen, expected))
def rows_full(): return [tuple(a.tree.item(i, 'values')) for i in a.tree.get_children()]
def rows():   # status without the ' · QC ...' suffix, so the queue checks do not depend on the QC verdict
    return [(r[0], r[1].split(' · ')[0], *r[2:]) for r in rows_full()]
def names(rs): return ', '.join(f'{r[0]}={r[1]}' for r in rs) or 'none'
def mp4s(d):
    """mp4 files under the output root as 'scene/scene.mp4' (every scene has its own output folder)."""
    return sorted(os.path.relpath(os.path.join(r, f), d).replace(os.sep, '/') for r, _, fs in os.walk(d) for f in fs if f.endswith('.mp4'))
def allfiles(d):
    """every file under the output root, as 'folder/file'."""
    return sorted(os.path.relpath(os.path.join(r, f), d).replace(os.sep, '/') for r, _, fs in os.walk(d) for f in fs)
def folders(d): return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))
def qc_only(m):   # a "Check the output" window that only lists QC lines (tiny 15-frame clips are too short for loudness)
    return m[0] == 'showwarning' and all(' QC ' in p for p in m[2].split('\n\n'))
def other_msgs(): return [m for m in msgs if not qc_only(m)]
def dialogs(): return '; '.join(f'{m[0]}: {m[2][:60]}' for m in other_msgs()) or 'none'
def row_status(path): iid = a.rows.get(os.path.normpath(path)); return a.tree.item(iid, 'values')[1] if iid else None
def busy(): return a.worker is not None and a.worker.is_alive()
def when_idle(then):
    if busy(): a.after(200, when_idle, then); return
    a.after(500, then)                 # let poll() drain the queue
def outdir(q):
    d = os.path.join(ROOT_TMP, 'out_' + q); os.makedirs(d, exist_ok=True); a.out_dir.set(d); return d
def start_gated(target, act, end):
    """Start the queue with target's render held after frame GATE_FRAME. Once held, give poll() time to show the row,
    then call act(True) on the Tk thread (the item is 'running', its row shows 'Frames 3/15'), open the gate and run end()
    when idle. If the worker finishes without reaching the gate, act(False) runs instead: a check fails, nothing hangs."""
    GATE['reached'].clear(); GATE['release'].clear(); GATE['name'] = os.path.basename(target)
    a.start()
    def wait():
        if GATE['reached'].is_set(): a.after(400, fire, True); return
        if not busy(): fire(False); return
        a.after(50, wait)
    def fire(ok):
        try: act(ok)
        finally: GATE['name'] = None; GATE['release'].set(); when_idle(end)
    a.after(50, wait)

def setup(q, files):
    a.clear(); started.clear(); msgs.clear()
    for f in files: a._add(f)
    return outdir(q)

# ---------------------------------------------------------------- Q1
def q1():
    results['Q1_dir'] = setup('q1', S[:3]); a.start(); when_idle(q1_end)
def q1_end():
    d = results['Q1_dir']; files = mp4s(d); sizes = {f: probe(os.path.join(d, f)) for f in files}
    check('Q1', 'render order', started == ['q_a.html', 'q_b.html', 'q_c.html'], ' -> '.join(started), 'q_a -> q_b -> q_c')
    check('Q1', 'row status', [r[1] for r in rows()] == ['Done'] * 3, names(rows()), 'all Done')
    check('Q1', 'mp4 on disk', files == ['q_a/q_a.mp4', 'q_b/q_b.mp4', 'q_c/q_c.mp4'] and all(v == (640, 360, True) for v in sizes.values()),
          ', '.join(f'{f} {v}' for f, v in sizes.items()) or 'none', 'q_a/q_a.mp4, q_b/q_b.mp4, q_c/q_c.mp4, (640, 360, audio=True)')
    check('Q1', 'dialogs', not other_msgs(), dialogs(), 'none')
    q2()

# ---------------------------------------------------------------- Q2: cancel at item 2 of 3 (a: Cancel current, b: Stop queue)
Q2 = {'a': dict(name='Cancel current', press=lambda: a.do_cancel_current(), rows=['Done', 'Cancelled', 'Done'],
                started=['q_a.html', 'q_b.html', 'q_c.html'], files=['q_a/q_a.mp4', 'q_c/q_c.mp4'], folders=['q_a', 'q_c'], stopped=False),
      'b': dict(name='Stop queue', press=lambda: a.do_cancel(), rows=['Done', 'Cancelled', 'Cancelled'],
                started=['q_a.html', 'q_b.html'], files=['q_a/q_a.mp4'], folders=['q_a'], stopped=True)}
def q2(v='a'):
    r = results['Q2' + v] = dict(dir=setup('q2' + v, S[:3]), b0=browsers(), t0=render_dirs(ROOT_TMP), at=None)
    start_gated(S[1], lambda ok: q2_press(v, ok), lambda: q2_end(v))
def q2_press(v, ok):   # item 2 is held at frame 3: press the button now
    r = results['Q2' + v]; st = row_status(S[1]) or ''
    if ok and st.startswith('Frames'):
        r['at'] = st; Q2[v]['press'](); r['label'] = a.status.cget('text')
def q2_end(v):
    r = results['Q2' + v]; e = Q2[v]; q = 'Q2' + v; files = mp4s(r['dir']); b1 = browsers()
    left = sorted(set(render_dirs(ROOT_TMP)) - set(r['t0']))
    nb = None if r['b0'] is None or b1 is None else max(0, len(b1) - len(r['b0']))
    st = (a.status.cget('text'), str(a.go['state']), str(a.stop_cur['state']), str(a.stop['state']))
    check(q, f"{e['name']} at item 2", r['at'] is not None, f"{r['at']} (label {r.get('label')!r})", 'item 2 rendering frames')
    check(q, 'renders started', started == e['started'], ' -> '.join(started), ' -> '.join(e['started']))
    check(q, 'row status', [x[1] for x in rows()] == e['rows'], names(rows()), ', '.join(e['rows']))
    check(q, 'mp4 on disk', files == e['files'], ', '.join(files) or 'none', ', '.join(e['files']))
    check(q, 'output folders (none left empty for the cancelled item)', folders(r['dir']) == e['folders'], ', '.join(folders(r['dir'])) or 'none', ', '.join(e['folders']))
    check(q, 'leftover temp', not left, ', '.join(left) or 'none', 'none')
    check(q, 'browsers left', nb in (None, 0), 'check skipped' if nb is None else str(nb), '0')
    check(q, 'status line / buttons', st[0].startswith('Cancelled') == e['stopped'] and st[1:] == ('normal', 'disabled', 'disabled'),
          f'{st[0]!r}; Render={st[1]}, Cancel current={st[2]}, Stop queue={st[3]}',
          ("'Cancelled. ...'" if e['stopped'] else "not 'Cancelled...'") + '; Render=normal, both cancel buttons disabled')
    check(q, 'dialogs', not other_msgs(), dialogs(), 'none')
    q2('b') if v == 'a' else q3()

# ---------------------------------------------------------------- Q3
def q3():
    results['Q3_dir'] = setup('q3', S[:2]); start_gated(S[0], q3_act, q3_end)
def q3_act(ok):   # q_a is held at frame 3 (ok=False: never seen rendering; the checks below then fail)
    r = results['Q3'] = {'before': len(rows())}
    a._add(S[3]); r['after_add'] = len(rows())                                           # add while #1 renders
    a.tree.selection_set(a.rows[os.path.normpath(S[1])]); a.remove(); r['after_rm_q'] = len(rows())   # remove a waiting one
    a.status.config(text=''); a.tree.selection_set(a.rows[os.path.normpath(S[0])]); a.remove()         # remove the running one
    r['after_rm_run'] = len(rows()); r['msg'] = a.status.cget('text')
    r['go'] = str(a.go['state']); r['stop'] = str(a.stop['state'])
def q3_end():
    r = results['Q3']; d = results['Q3_dir']; files = mp4s(d)
    check('Q3', 'add while running', r['after_add'] == r['before'] + 1, f"rows {r['before']} -> {r['after_add']}", 'one row more')
    check('Q3', 'remove a Queued one', r['after_rm_q'] == r['after_add'] - 1, f"rows {r['after_add']} -> {r['after_rm_q']}", 'one row less')
    check('Q3', 'remove the running one', r['after_rm_run'] == r['after_rm_q'] and BLOCKED_MSG in r['msg'],
          f"rows {r['after_rm_q']} -> {r['after_rm_run']}; status line {r['msg']!r}", f'blocked, status line mentions {BLOCKED_MSG!r}')
    check('Q3', 'buttons while running', (r['go'], r['stop']) == ('disabled', 'normal'), f"Render={r['go']}, Cancel={r['stop']}", 'Render=disabled, Cancel=normal')
    check('Q3', 'renders started', started == ['q_a.html', 'q_extra.html'], ' -> '.join(started), 'q_a -> q_extra (q_b was removed)')
    check('Q3', 'row status at end', [(x[0], x[1]) for x in rows()] == [('q_a.html', 'Done'), ('q_extra.html', 'Done')], names(rows()), 'q_a=Done, q_extra=Done')
    check('Q3', 'mp4 on disk', files == ['q_a/q_a.mp4', 'q_extra/q_extra.mp4'], ', '.join(files) or 'none', 'q_a/q_a.mp4, q_extra/q_extra.mp4')
    q4()

# ---------------------------------------------------------------- Q4
def q4():
    results['Q4_dir'] = setup('q4', S[:3]); start_gated(S[0], q4_act, q4_end)
def q4_act(ok):   # q_a is held at frame 3
    before = len(rows()); a.status.config(text=''); a.clear()
    results['Q4'] = dict(before=before, after=len(rows()), msg=a.status.cget('text'), left=[x[0] for x in rows()])
def q4_end():
    r = results['Q4']; d = results['Q4_dir']; files = mp4s(d)
    check('Q4', 'clear while running', r['before'] == 3 and r['left'] == ['q_a.html'] and BLOCKED_MSG in r['msg'],
          f"rows {r['before']} -> {r['after']} (kept: {', '.join(r['left']) or 'none'}); status line {r['msg']!r}",
          f'3 -> 1, keeps the running q_a, status line mentions {BLOCKED_MSG!r}')
    check('Q4', 'renders started', started == ['q_a.html'], ' -> '.join(started), 'q_a only')
    check('Q4', 'row status at end', [(x[0], x[1]) for x in rows()] == [('q_a.html', 'Done')], names(rows()), 'q_a=Done')
    check('Q4', 'mp4 on disk', files == ['q_a/q_a.mp4'], ', '.join(files) or 'none', 'q_a/q_a.mp4 only')
    q5()

# ---------------------------------------------------------------- Q5: a normal render gets a QC verdict and a report
def q5():
    results['Q5_dir'] = setup('q5', S[:1]); a.start(); when_idle(q5_end)
def q5_end():
    d = results['Q5_dir']; full = rows_full(); st = full[0][1] if full else ''
    rep = os.path.join(d, 'q_a', 'q_a.qc.txt')
    check('Q5', 'row shows the QC verdict', st in ('Done · QC OK', 'Done · QC Warn'), st or 'no row', "'Done · QC OK' or 'Done · QC Warn'")
    check('Q5', 'report next to the mp4', os.path.isfile(rep) and mp4s(d) == ['q_a/q_a.mp4'],
          ', '.join(allfiles(d)) or 'none', 'q_a/q_a.mp4 + q_a/q_a.qc.txt')
    check('Q5', 'no error dialog', not [m for m in msgs if m[0] == 'showerror'], dialogs(), 'no showerror')
    q6()

# ---------------------------------------------------------------- Q6: a QC that crashes leaves the render Done
def q6():
    results['Q6_real'] = qc.run_qc
    def broken(*a_, **k): raise RuntimeError('QC bug on purpose')
    qc.run_qc = broken
    results['Q6_dir'] = setup('q6', S[:1]); a.start(); when_idle(q6_end)
def q6_end():
    qc.run_qc = results['Q6_real']
    d = results['Q6_dir']; full = rows_full(); st = full[0][1] if full else ''
    check('Q6', 'row stays Done when QC raises', st == 'Done', st or 'no row', "'Done' (no QC suffix, not Error)")
    check('Q6', 'mp4 kept, no report', mp4s(d) == ['q_a/q_a.mp4'] and not os.path.exists(os.path.join(d, 'q_a', 'q_a.qc.txt')),
          ', '.join(allfiles(d)) or 'none', 'q_a/q_a.mp4 only')
    check('Q6', 'no dialogs', not msgs, dialogs() if other_msgs() else '; '.join(m[2][:60] for m in msgs) or 'none', 'none')
    q7()

# ---------------------------------------------------------------- Q7: set_narration validates early, returns errors (no render)
def q7():
    setup('q7', [N2D, NOLD, NPLAIN])
    bad_json = os.path.join(ROOT_TMP, 'bad words.json'); open(bad_json, 'w').write('{not json')
    empty = os.path.join(ROOT_TMP, 'empty words.json'); json.dump({'words': []}, open(empty, 'w'))
    cases = [('file not in the list', lambda: a.set_narration(S[3], VOICE, WORDS), 'not in the list'),
             ('missing WAV', lambda: a.set_narration(N2D, os.path.join(ROOT_TMP, 'nope.wav'), WORDS), 'WAV not found'),
             ('missing words.json', lambda: a.set_narration(N2D, VOICE, os.path.join(ROOT_TMP, 'nope.json')), 'words file not found'),
             ('broken words.json', lambda: a.set_narration(N2D, VOICE, bad_json), 'could not be read'),
             ('empty word list', lambda: a.set_narration(N2D, VOICE, empty), 'non-empty list'),
             ('bad style', lambda: a.set_narration(N2D, VOICE, WORDS, style='bounce'), 'style must be'),
             ('scene already narrated', lambda: a.set_narration(NOLD, VOICE, WORDS), 'already has narration'),
             ('scene without SOUND kit', lambda: a.set_narration(NPLAIN, VOICE, WORDS), 'not a Seekframe scene')]
    for label, fn, text in cases:
        try: err = fn()
        except Exception as e: err = f'RAISED {type(e).__name__}: {e}'
        check('Q7', label, isinstance(err, str) and text in err and not err.startswith('RAISED'), repr(err), f'error string mentioning {text!r}')
    check('Q7', 'nothing stored after errors', not a.narr and all('[voice]' not in r[0] for r in rows_full()), str(a.narr) or 'none', 'no narration, no marker')
    ok = a.set_narration(N2D, VOICE, WORDS)
    name = next((r[0] for r in rows_full() if r[0].startswith('q_n2d.html')), '')
    check('Q7', 'valid narration -> None + [voice] marker', ok is None and name == 'q_n2d.html [voice]', f'{ok!r}, row {name!r}', "None, 'q_n2d.html [voice]'")
    a.clear_narration(N2D); name = next((r[0] for r in rows_full() if r[0].startswith('q_n2d.html')), '')
    check('Q7', 'clear_narration removes it and the marker', os.path.normpath(N2D) not in a.narr and name == 'q_n2d.html', repr(name), "'q_n2d.html'")
    a.set_narration(N2D, VOICE, WORDS); a.tree.selection_set(a.rows[os.path.normpath(N2D)]); a.remove()
    check('Q7', 'removing the item drops its narration', os.path.normpath(N2D) not in a.narr and os.path.normpath(N2D) not in a.files, str(list(a.narr)) or 'none', 'none')
    q8()

# ---------------------------------------------------------------- Q8: Sound = External file + a narrated item -> Generated, warned
def q8():
    d = results['Q8_dir'] = setup('q8', [N2D])
    a.set_narration(N2D, VOICE, WORDS)
    a.snd_file.set(EXT); a.snd.set(app.SOUNDS[2])          # External file (the picker is patched; the file is already set)
    a.start(); when_idle(q8_end)
def q8_end():
    a.snd.set(app.SOUNDS[0])
    d = results['Q8_dir']; files = mp4s(d); full = rows_full()
    warned = [m for m in msgs if m[0] == 'showwarning' and 'narration needs generated sound' in m[2]]
    db = _band_db(os.path.join(d, files[0]), 0.0, 0.5) if files else None
    check('Q8', 'renders the narrated temp scene', started == ['q_n2d.html (narrated)'], ' -> '.join(started), 'q_n2d.html (narrated)')
    check('Q8', 'row Done, marker kept', full and full[0][0] == 'q_n2d.html [voice]' and full[0][1].startswith('Done'), names(full), "q_n2d.html [voice]=Done ...")
    check('Q8', 'warning: needs generated sound', bool(warned), warned[0][2].split('\n')[0][:90] if warned else 'no such warning', "'... narration needs generated sound ...'")
    check('Q8', 'voice in the mp4 (not the external file)', files == ['q_n2d/q_n2d.mp4'] and db is not None and db > -25,
          f"{', '.join(files) or 'none'}; 300 Hz band {db if db is None else round(db, 1)} dB", 'q_n2d/q_n2d.mp4, 300 Hz band above -25 dB')
    check('Q8', 'no temp scene left', not temps(), ', '.join(temps()) or 'none', 'none')
    q9()

# ---------------------------------------------------------------- Q9: Cancel current while a narrated (WebGL) item renders
def q9():
    d = results['Q9_dir'] = setup('q9', [NARRQ, S[1]])
    a.set_narration(NARRQ, VOICE, WORDS)
    start_gated(NARRQ, q9_act, q9_end)
def q9_act(ok):   # the narrated item (its hidden temp scene) is held at frame 3
    st = row_status(NARRQ) or ''
    results['Q9_at'] = st if ok and st.startswith('Frames') else None
    if results['Q9_at']: results['Q9_temps_running'] = temps(); a.do_cancel_current()
def q9_end():
    d = results['Q9_dir']; files = mp4s(d)
    check('Q9', 'cancel reached the narrated item', results.get('Q9_at') is not None and results.get('Q9_temps_running'),
          f"{results.get('Q9_at')}; temp scene while rendering: {results.get('Q9_temps_running')}", 'frames running, one temp scene present')
    check('Q9', 'row status', [r[1] for r in rows()] == ['Cancelled', 'Done'], names(rows()), 'Cancelled, Done')
    check('Q9', 'renders started', started == ['q_narr.html (narrated)', 'q_b.html'], ' -> '.join(started), 'q_narr.html (narrated) -> q_b.html')
    check('Q9', 'mp4 on disk', files == ['q_b/q_b.mp4'] and folders(d) == ['q_b'], ', '.join(files) + ' | folders: ' + ', '.join(folders(d)), 'q_b/q_b.mp4 only, no folder for the cancelled narrated item')
    check('Q9', 'no temp scene left', not temps(), ', '.join(temps()) or 'none', 'none')
    q10()

# ---------------------------------------------------------------- Q10: auto-detect, [voice embedded], words.json shapes, the dialog (no render)
def _scene(name, src=os.path.join(FIXT, 'narr_2d.html')):
    p = os.path.join(scenes_dir, name); shutil.copy(src, p); return p
def _words(name, data):
    p = os.path.join(scenes_dir, name)
    with open(p, 'w', encoding='utf-8') as fh: json.dump(data, fh)
    return p
W1 = [{'w': 'Hello', 's': 0.1, 'e': 0.4}]
def row_name(p): return a.tree.item(a.rows[os.path.normpath(p)], 'values')[0] if os.path.normpath(p) in a.rows else None
def select(p): a.tree.selection_set(a.rows[os.path.normpath(p)]); a.update(); a._update_narr_btn()

def q10():
    setup('q10', [])
    auto = _scene('q_auto.html'); shutil.copy(VOICE, os.path.join(scenes_dir, 'q_auto.wav')); _words('q_auto.words.json', {'words': W1, 'duration': 3.0})
    bad = _scene('q_autobad.html'); shutil.copy(VOICE, os.path.join(scenes_dir, 'q_autobad.wav')); open(os.path.join(scenes_dir, 'q_autobad.words.json'), 'w').write('[]')
    gen = _scene('q_gen.html'); shutil.copy(VOICE, os.path.join(scenes_dir, 'narr.wav')); _words('words.json', {'words': W1})
    a._add(auto); st_auto = a.status.cget('text')
    check('Q10', 'auto-detect <scene>.wav + <scene>.words.json', os.path.normpath(auto) in a.narr and row_name(auto) == 'q_auto.html [voice]' and 'narration found' in st_auto,
          f'{row_name(auto)!r}; status {st_auto!r}', "'q_auto.html [voice]', status says found")
    check('Q10', 'auto-detected settings', a.narr.get(os.path.normpath(auto), {}).get('style') == 'pop', str(a.narr.get(os.path.normpath(auto))), 'style pop')
    a._add(bad); st_bad = a.status.cget('text')
    check('Q10', 'auto-detect with a bad words file is not used, status says why', os.path.normpath(bad) not in a.narr and 'not used' in st_bad and row_name(bad) == 'q_autobad.html',
          repr(st_bad), "'... found but not used: ...'")
    a._add(gen)
    check('Q10', 'generic narr.wav + words.json are NOT picked up', os.path.normpath(gen) not in a.narr and row_name(gen) == 'q_gen.html', repr(row_name(gen)), "'q_gen.html'")
    a._add(NOLD); select(NOLD)
    check('Q10', 'embedded narration shows [voice embedded]', row_name(NOLD) == 'q_old.html [voice embedded]', repr(row_name(NOLD)), "'q_old.html [voice embedded]'")
    blocked = a.open_narration_dialog()
    check('Q10', 'embedded: button disabled, dialog refused', str(a.narr_btn['state']) == 'disabled' and blocked is None and 'already has narration' in a.status.cget('text'),
          f"button {a.narr_btn['state']}, dialog {blocked}, status {a.status.cget('text')!r}", 'disabled, None, status explains')
    # words.json shapes: {"words":[...],"duration":..}, a plain list file, a Python list
    for label, w in (('dict shape with duration', _words('w_dict.json', {'words': W1, 'duration': 3.0})),
                     ('plain list file', _words('w_list.json', W1)), ('Python list', W1)):
        err = a.set_narration(gen, VOICE, w)
        check('Q10', f'set_narration accepts {label}', err is None and os.path.normpath(gen) in a.narr, repr(err), 'None')
    # the dialog, driven through its handlers
    select(auto); state = str(a.narr_btn['state']); dlg = a.open_narration_dialog()
    pre = (dlg.wav.get(), os.path.basename(dlg.words.get()), dlg.style.get(), dlg.captions.get()) if dlg else None
    check('Q10', 'dialog opens prefilled for the selected row', state == 'normal' and pre == (os.path.join(scenes_dir, 'q_auto.wav'), 'q_auto.words.json', 'pop', True),
          f'button {state}; {pre}', "button normal; q_auto.wav, q_auto.words.json, pop, True")
    themed = all(w.winfo_class().startswith('T') for w in dlg.top.winfo_children()[0].winfo_children() if w.winfo_class() not in ('Frame',)) if dlg else False
    check('Q10', 'dialog uses themed (ttk) widgets', themed, 'all ttk' if themed else 'non-ttk widget found', 'ttk only (follows dark/light)')
    dlg.style.set('karaoke'); dlg.captions.set(False); err = dlg.ok()
    n = a.narr.get(os.path.normpath(auto), {})
    check('Q10', 'OK stores the choices and closes', err is None and n.get('style') == 'karaoke' and n.get('captions') is False and not dlg.top.winfo_exists(),
          f"{err!r}; {n.get('style')}, captions {n.get('captions')}", 'None; karaoke, captions False, closed')
    msgs.clear(); dlg2 = a.open_narration_dialog(); dlg2.wav.set(os.path.join(ROOT_TMP, 'missing.wav')); err2 = dlg2.ok()
    shown = [m for m in msgs if m[0] == 'showerror' and m[1] == 'Narration']
    check('Q10', 'OK with a bad WAV: error box, dialog stays, nothing changed', err2 and shown and dlg2.top.winfo_exists() and a.narr[os.path.normpath(auto)]['wav'].endswith('q_auto.wav'),
          f'{err2!r}; error box {bool(shown)}; open {dlg2.top.winfo_exists()}', 'error box, still open, wav unchanged')
    dlg2.cancel()
    dlg3 = a.open_narration_dialog(); dlg3.remove()
    check('Q10', 'Remove narration clears it and the marker', os.path.normpath(auto) not in a.narr and row_name(auto) == 'q_auto.html' and not dlg3.top.winfo_exists(),
          repr(row_name(auto)), "'q_auto.html'")
    msgs.clear(); q11()

# ---------------------------------------------------------------- Q11: the button is blocked for the row that is rendering
def q11():
    d = results['Q11_dir'] = setup('q11', [S[0]])
    start_gated(S[0], q11_act, q11_end)
def q11_act(ok):   # q_a is held at frame 3
    select(S[0]); results['Q11'] = (str(a.narr_btn['state']), a.open_narration_dialog(), a.status.cget('text'))
def q11_end():
    s, dlg, msg = results['Q11']; select(S[0]); after = str(a.narr_btn['state'])
    check('Q11', 'rendering row: button disabled, dialog refused', s == 'disabled' and dlg is None and 'is rendering' in msg, f'{s}, {dlg}, {msg!r}', "disabled, None, '... is rendering ...'")
    check('Q11', 'after the render the button is enabled again', after == 'normal', after, 'normal')
    q12()

# ---------------------------------------------------------------- Q12: one output folder per scene
# run 1: a normal scene, a failing scene, a narrated scene and a scene with spaces/#/Arabic in its name (16:9)
# run 2: the same normal + narrated scenes again -> nothing is overwritten (_2 suffix inside the same folder)
# run 3: 9:16 -> <scene>_shorts.mp4 lands in the SAME folder as the 16:9 file
def q12():
    results['Q12_scene'] = {'ar': os.path.join(scenes_dir, 'سين #1 scene.html'), 'bad': os.path.join(scenes_dir, 'q_broken.html')}
    shutil.copy(os.path.join(FIXT, 'narr_2d.html'), results['Q12_scene']['ar'])
    shutil.copy(os.path.join(FIXT, 'broken_no_seek.html'), results['Q12_scene']['bad'])
    d = results['Q12_dir'] = setup('q12', [S[0], results['Q12_scene']['bad'], N2D, results['Q12_scene']['ar']])
    a.set_narration(N2D, VOICE, WORDS)
    a.start(); when_idle(q12_run1_end)
def q12_run1_end():
    d = results['Q12_dir']; sc = results['Q12_scene']; files = allfiles(d); r = rows()
    results['Q12_before'] = {f: (os.path.getsize(os.path.join(d, f)), os.path.getmtime(os.path.join(d, f))) for f in files if f.endswith('.mp4')}
    check('Q12', 'run 1: row status', [(x[0], x[1]) for x in r] == [('q_a.html', 'Done'), ('q_broken.html', 'Error'), ('q_n2d.html [voice]', 'Done'), ('سين #1 scene.html', 'Done')],
          names(r), 'q_a=Done, q_broken=Error, q_n2d [voice]=Done, سين #1 scene=Done')
    check('Q12', 'run 1: one folder per scene, named after the original file', folders(d) == sorted(['q_a', 'q_broken', 'q_n2d', 'سين #1 scene']), ', '.join(folders(d)), 'q_a, q_broken, q_n2d, سين #1 scene')
    check('Q12', 'run 1: mp4 sits in its own folder', mp4s(d) == ['q_a/q_a.mp4', 'q_n2d/q_n2d.mp4', 'سين #1 scene/سين #1 scene.mp4'], ', '.join(mp4s(d)), 'q_a/q_a.mp4, q_n2d/q_n2d.mp4, سين #1 scene/سين #1 scene.mp4')
    qcs = [f for f in files if f.endswith('.qc.txt')]
    check('Q12', 'run 1: the QC report is in the same folder as its mp4', qcs == ['q_a/q_a.qc.txt', 'q_n2d/q_n2d.qc.txt', 'سين #1 scene/سين #1 scene.qc.txt'], ', '.join(qcs) or 'none', 'one .qc.txt next to each mp4')
    logs = [f for f in files if f.endswith('.log')]
    check('Q12', 'run 1: the failure log is in the failing scene folder', len(logs) == 1 and logs[0].startswith('q_broken/q_broken_') and not [f for f in files if f.startswith('q_broken/') and f.endswith('.mp4')],
          ', '.join(logs) or 'none', 'q_broken/q_broken_<time>.log, no mp4 there')
    fb = [m for m in msgs if m[0] == 'showerror']
    check('Q12', 'run 1: the error window shows that log path', bool(fb) and logs and ('q_broken' + os.sep + 'q_broken_') in fb[0][2], (fb[0][2][:160].replace('\n', ' | ') if fb else 'no error window'), 'Log: ...\\q_broken\\q_broken_<time>.log')
    check('Q12', 'run 1: nothing went to the fallback logs folder', not os.path.exists(app.LOG_DIR) or not os.listdir(app.LOG_DIR), str(os.listdir(app.LOG_DIR)) if os.path.exists(app.LOG_DIR) else 'no logs folder', 'empty / absent')
    check('Q12', 'run 1: no hidden narration file in the output tree or next to the scenes', not [f for f in files if '.shadow_narr_' in f] and not temps(), ', '.join(temps()) or 'none', 'none')
    check('Q12', 'run 1: narrated render is named after the original scene', 'q_n2d/q_n2d.mp4' in files, ', '.join(f for f in files if f.startswith('q_n2d')), 'q_n2d/q_n2d.mp4')
    # run 2: the same two scenes again
    msgs.clear(); setup('q12', [S[0], N2D]); a.set_narration(N2D, VOICE, WORDS); a.start(); when_idle(q12_run2_end)
def q12_run2_end():
    d = results['Q12_dir']; files = allfiles(d); before = results['Q12_before']
    now = {f: (os.path.getsize(os.path.join(d, f)), os.path.getmtime(os.path.join(d, f))) for f in before}
    check('Q12', 'run 2: existing mp4 files are untouched', now == before, 'same size and time' if now == before else 'CHANGED', 'unchanged')
    check('Q12', 'run 2: new files get _2 in the same folder (mp4 and QC report)',
          {'q_a/q_a_2.mp4', 'q_a/q_a_2.qc.txt', 'q_n2d/q_n2d_2.mp4', 'q_n2d/q_n2d_2.qc.txt'} <= set(files), ', '.join(f for f in files if '_2' in f) or 'none', 'q_a_2.mp4 + .qc.txt, q_n2d_2.mp4 + .qc.txt')
    check('Q12', 'run 2: no new folders', folders(d) == sorted(['q_a', 'q_broken', 'q_n2d', 'سين #1 scene']), ', '.join(folders(d)), 'the same 4 folders')
    # run 3: 9:16 for the normal scene
    msgs.clear(); setup('q12', [S[0]]); a.fmt.set('9:16 (Shorts)'); a.start(); when_idle(q12_run3_end)
def q12_run3_end():
    a.fmt.set('16:9 (YouTube)')
    d = results['Q12_dir']; files = allfiles(d); v = probe(os.path.join(d, 'q_a', 'q_a_shorts.mp4'))
    check('Q12', 'run 3: 9:16 file is <scene>_shorts.mp4 in the same folder as the 16:9 files', 'q_a/q_a_shorts.mp4' in files and 'q_a/q_a.mp4' in files and v and v[:2] == (360, 640),
          f"{', '.join(f for f in files if f.startswith('q_a/') and f.endswith('.mp4'))}; shorts {v and v[:2]}", 'q_a/q_a.mp4, q_a/q_a_shorts.mp4 (360x640)')
    q13()

# ---------------------------------------------------------------- Q13: Format = Auto (by file name), mixed 9:16 / 16:9 in one queue
SHORT = os.path.join(scenes_dir, 'short_q.html'); shutil.copy(WEBGL, SHORT)
WIDE_OLD = os.path.join(scenes_dir, 'q_oldwide.html'); shutil.copy(os.path.join(FIXT, 'outdated_no_h.html'), WIDE_OLD)
SHORT_OLD = os.path.join(scenes_dir, 'short_old.html'); shutil.copy(os.path.join(FIXT, 'outdated_no_h.html'), SHORT_OLD)
def fmt_col(): return [(r[0], r[4]) for r in rows_full()]
def q13():
    d = results['Q13_dir'] = setup('q13', [SHORT, S[1], WIDE_OLD])
    a.fmt.set(app.FORMAT_AUTO); a.update()
    check('Q13', 'Format column follows Auto: short_ -> 9:16, others 16:9', fmt_col() == [('short_q.html', '9:16'), ('q_b.html', '16:9'), ('q_oldwide.html', '16:9')],
          fmt_col(), 'short_q 9:16, q_b 16:9, q_oldwide 16:9')
    a.fmt.set('9:16 (Shorts)'); a.update(); col916 = [c for _, c in fmt_col()]
    a.fmt.set(app.FORMAT_AUTO); a.update()
    check('Q13', 'Format column follows a fixed 9:16 too', col916 == ['9:16'] * 3, col916, "all '9:16'")
    asked = []
    a._add(SHORT_OLD)   # outdated scene WITH the short_ prefix: the 9:16 warning names only it
    a.start(ask=lambda t, m: asked.append(m) or None)   # Cancel = stop, nothing starts
    check('Q13', 'outdated warning lists only the outdated short_ scene (the outdated 16:9 one renders fine)',
          len(asked) == 1 and 'short_old.html' in asked[0] and 'q_oldwide.html' not in asked[0] and not busy(),
          (' | '.join(asked[0].splitlines())[:120] if asked else 'not asked'), 'asked once, short_old.html only, nothing started')
    a.tree.selection_set(a.rows[os.path.normpath(SHORT_OLD)]); a.remove()
    asked.clear(); a.start(ask=lambda t, m: asked.append(m) or True); results['Q13_asked'] = list(asked)
    when_idle(q13_end)
def q13_end():
    d = results['Q13_dir']; files = mp4s(d)
    sizes = {f: probe(os.path.join(d, f)) for f in files}
    check('Q13', 'no 9:16 warning for the outdated 16:9 scene', not results['Q13_asked'], len(results['Q13_asked']), 'not asked')
    check('Q13', 'row status', [r[1] for r in rows()] == ['Done', 'Done', 'Done (silent)'], names(rows()), 'Done, Done, Done (silent) (the outdated fixture has no sound)')
    check('Q13', 'one queue: short_q -> _shorts.mp4 360x640, the others .mp4 640x360',
          files == ['q/q_shorts.mp4', 'q_b/q_b.mp4', 'q_oldwide/q_oldwide.mp4']
          and sizes.get('q/q_shorts.mp4', (0,))[:2] == (360, 640)
          and sizes.get('q_b/q_b.mp4', (0,))[:2] == (640, 360) and sizes.get('q_oldwide/q_oldwide.mp4', (0,))[:2] == (640, 360),
          ', '.join(f'{f} {v}' for f, v in sizes.items()) or 'none', 'q_b/q_b.mp4 640x360, q_oldwide/q_oldwide.mp4 640x360, q/q_shorts.mp4 360x640 (Short next to its video)')
    extra = [p for m in other_msgs() for p in m[2].splitlines() if p.strip() and 'rendered silent' not in p and ' QC ' not in p]
    check('Q13', 'no size / setup warnings (only the silent-scene note)', not extra, '; '.join(extra) or 'none', 'none')
    a.fmt.set('16:9 (YouTube)')
    finish()

def finish():
    try: a.after_cancel(a._poll_id)
    except Exception: pass
    try: a.destroy()
    except Exception: pass

def main():
    code = 0
    def callback_error(*exc):            # an error inside a Tk callback would otherwise leave the loop waiting forever
        traceback.print_exception(*exc); checks.append(('--', 'callback error', False, str(exc[1]), 'no error')); finish()
    a.report_callback_exception = callback_error
    try:
        a.after(500, q1)
        a.after(300_000, lambda: (checks.append(('--', 'timeout', False, 'not finished after 300 s', 'finish in time')), finish()))
        a.mainloop()
        tmp_log = app.LOG
        check('--', 'log went to the temp folder', os.path.isfile(tmp_log) and os.path.getsize(tmp_log) > 0,
              f'{os.path.basename(tmp_log)} {os.path.getsize(tmp_log) if os.path.isfile(tmp_log) else "missing"} bytes', 'non-empty temp shadow.log')
        after = (_stat(REAL_LOG), _stat(REAL_LOG_DIR))
        check('--', 'real shadow.log untouched', after[0] == REAL_BEFORE[0], 'unchanged' if after[0] == REAL_BEFORE[0] else f'{REAL_BEFORE[0]} -> {after[0]}', 'same size and mtime')
        check('--', 'real logs folder untouched', after[1] == REAL_BEFORE[1], 'unchanged' if after[1] == REAL_BEFORE[1] else f'{REAL_BEFORE[1]} -> {after[1]}', 'same files and mtime')
        w = max([len(c[1]) for c in checks] + [10])
        for q, what, ok, seen, exp in checks:
            print(f"{'PASS' if ok else 'FAIL'}  {q}  {what:<{w}}  {seen}" + ('' if ok else f'   (expected: {exp})'))
        fails = sum(not c[2] for c in checks)
        print(f'{len(checks) - fails}/{len(checks)} checks passed')
        code = 1 if fails or not checks else 0
    except Exception:
        traceback.print_exc(); code = 1
    finally:
        for h in list(app.log.handlers):   # release the temp shadow.log so the folder can be deleted (Windows)
            app.log.removeHandler(h); h.close()
        app.LOG, app.LOG_DIR = REAL_LOG, REAL_LOG_DIR
        tempfile.tempdir = None
        sys.modules['app'].close_log() if 'app' in sys.modules else None   # shadow.log in the temp folder is open: close it first
        shutil.rmtree(ROOT_TMP, ignore_errors=True)
    return code

if __name__ == '__main__':
    sys.exit(main())
