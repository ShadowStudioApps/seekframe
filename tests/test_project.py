"""Project files (3.14): the queue + each row's narration + the render options saved as <name>.shadow and opened again.
Everything in a temp folder (scenes copied from tests/fixtures, never scenes/). GUI test (window hidden), no render.
  P1 write/read: paths saved relative to the project file, read back absolute; not a project -> ValueError
  P2 GUI Save project -> Clear + change options -> Open project: same scenes in order, narration, options, window title
  P3 the project folder moved elsewhere still opens (relative paths); a missing scene is listed, the rest opens
  P4 open with scenes already in the list: Cancel = nothing, No = add, Yes = replace; dropping a .shadow file opens it
Usage: python tests/test_project.py     exit 0 = all PASS"""
import json, os, shutil, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts
import app
app.notify = lambda *a, **k: None   # 3.32: never a real Windows notification from a test

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_project_test_')
app.LOG = os.path.join(TMP, 'shadow.log'); app.LOG_DIR = os.path.join(TMP, 'logs'); app.close_log()
FIX = os.path.join(ROOT, 'tests', 'fixtures')
proj_dir = os.path.join(TMP, 'my videos'); os.makedirs(os.path.join(proj_dir, 'ep1'))
A = os.path.join(proj_dir, 'ep1', 'a scene.html'); shutil.copy(os.path.join(FIX, 'narr_2d.html'), A)
B = os.path.join(proj_dir, 'short_b.html'); shutil.copy(os.path.join(FIX, 'webgl_min.html'), B)
VOICE = os.path.join(proj_dir, 'ep1', 'voice.wav'); WORDS = os.path.join(proj_dir, 'ep1', 'voice.words.json')
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=f=300:d=3,volume=0.6', '-ac', '1', '-c:a', 'pcm_s16le', VOICE], check=True)
json.dump({'words': [{'w': 'Hello', 's': 0.1, 'e': 0.4}]}, open(WORDS, 'w'))
SONG = os.path.join(proj_dir, 'song.mp3'); open(SONG, 'wb').write(b'x')
P = os.path.join(proj_dir, 'episode.shadow')

# ---------------------------------------------------------------- P1
data = dict(files=[A, B], narration={A: dict(wav=VOICE, words=WORDS, style='karaoke', yh=0.8, gain=1.2, captions=False)},
            options=dict(quality='Draft (fast, 720p)', format=app.FORMAT_AUTO, sound=app.SOUNDS[2], sound_file=SONG, capture='Fast (JPEG, ~2x faster)',
                         blender=app.BLENDER_ENGINES[0], folder='Music', save_to=os.path.join(TMP, 'out'), skip_done=False))
app.write_project(P, data)
raw = json.load(open(P, encoding='utf-8'))
check('P1 file: paths relative to the project, version stamped', raw['files'] == [os.path.join('ep1', 'a scene.html'), 'short_b.html']
      and raw['narration'][os.path.join('ep1', 'a scene.html')]['wav'] == os.path.join('ep1', 'voice.wav') and raw['options']['sound_file'] == 'song.mp3'
      and raw['shadow_project'] == 1 and raw['shadow_version'], raw)
back = app.read_project(P)
check('P1 read back: absolute paths, narration + options the same', back['files'] == [A, B] and back['narration'][A]['words'] == WORDS
      and back['narration'][A]['style'] == 'karaoke' and back['options']['sound_file'] == SONG and back['options']['quality'] == 'Draft (fast, 720p)', back)
for bad in ('{"files": []}', '[1, 2]', 'not json'):
    p = os.path.join(TMP, 'bad.shadow'); open(p, 'w').write(bad)
    try: app.read_project(p); check(f'P1 rejects {bad[:12]!r}', False)
    except ValueError: check(f'P1 rejects {bad[:12]!r}', True)

# ---------------------------------------------------------------- P2..P4 GUI
warn = []; app.messagebox.showwarning = lambda *x, **k: warn.append(x); app.messagebox.showerror = lambda *x, **k: warn.append(x)
picked = []   # no real file picker may ever open on the owner's screen from this test
for n in ('askopenfilename', 'askopenfilenames', 'asksaveasfilename', 'askdirectory'):
    setattr(app.filedialog, n, (lambda n: lambda *x, **k: picked.append(n) or '')(n))
try:
    a = app.App(); a.withdraw(); a.skip_done.set(True)
    a._add(A); a._add(B)
    check('P2 (setup) narration attached to the first scene', a.set_narration(A, VOICE, WORDS, style='karaoke', captions=False) is None)
    a.preset.set('Draft (fast, 720p)'); a.fmt.set(app.FORMAT_AUTO); a.capture.set(list(app.CAPTURES)[1]); a.snd.set(app.SOUNDS[3])
    a.folder_choice.set(app.FOLDER_NONE); a.out_dir.set(os.path.join(TMP, 'renders')); a.skip_done.set(False)
    saved = a.save_project(P)
    check('P2 Save project: file written, title shows the project', saved == P and os.path.isfile(P) and a.title() == 'Seekframe - episode', a.title())
    a.clear(); a.preset.set('Best (1080p, 64 samples)'); a.fmt.set('16:9 (YouTube)'); a.capture.set('Best quality (PNG)'); a.snd.set(app.SOUNDS[0])
    a.folder_choice.set(app.FOLDER_AUTO); a.out_dir.set(TMP); a.skip_done.set(True)
    added = a.open_project(P)
    check('P2 Open project: same scenes in the same order', added == [A, B] and a.files == [A, B], a.files)
    check('P2 narration back on its row (style, captions)', a.narr.get(A, {}).get('style') == 'karaoke' and a.narr[A].get('captions') is False
          and a.narr[A]['wav'] == VOICE, a.narr.get(A))
    check('P2 options back', (a.preset.get(), a.fmt.get(), a.capture.get(), a.snd.get(), a.folder_choice.get(), a.out_dir.get(), a.skip_done.get())
          == ('Draft (fast, 720p)', app.FORMAT_AUTO, list(app.CAPTURES)[1], app.SOUNDS[3], app.FOLDER_NONE, os.path.join(TMP, 'renders'), False))
    check('P2 rows show the narration mark and the Format Auto result', '[voice]' in a.tree.item(a.rows[A], 'values')[0]
          and a.tree.item(a.rows[B], 'values')[4] == app.format_label(True), [a.tree.item(a.rows[x], 'values') for x in (A, B)])

    moved = os.path.join(TMP, 'moved copy'); shutil.copytree(proj_dir, moved); os.remove(os.path.join(moved, 'short_b.html'))
    a.clear(); warn.clear()
    added = a.open_project(os.path.join(moved, 'episode.shadow'))
    A2 = os.path.join(moved, 'ep1', 'a scene.html')
    check('P3 a moved project folder opens from its new place (relative paths), narration from there too', added == [A2]
          and a.narr.get(A2, {}).get('wav') == os.path.join(moved, 'ep1', 'voice.wav'), (added, a.narr))
    check('P3 the missing scene is named in a warning, the rest opened', warn and 'short_b.html' in warn[-1][1] and 'Not found' in warn[-1][1], warn)

    n = len(a.files)
    check('P4 Cancel keeps the list as it was', a.open_project(P, ask=lambda *x: None) == [] and len(a.files) == n)
    added = a.open_project(P, ask=lambda *x: False)
    check('P4 No = add the project to the list', a.files == [A2, A, B] and added == [A, B], a.files)
    a.open_project(P, ask=lambda *x: True)
    check('P4 Yes = replace the list', a.files == [A, B], a.files)
    a.clear()
    class Ev: data = '{' + P + '}'
    a.on_drop(Ev())
    check('P4 dropping a .shadow file opens it', a.files == [A, B], a.files)
    old = os.path.join(TMP, 'old.shadow'); app.write_project(old, data)   # data still says 'Fast (JPEG, ~2x faster)' (3.16 label)
    picked.clear(); a.open_project(old, ask=lambda *x: True)
    check('P5 a project saved with the old JPEG label opens as the new Fast label', a.capture.get() == list(app.CAPTURES)[1], a.capture.get())
    check('P6 a project with Sound = External file opens with its song and asks for no file (3.17 fix)', picked == []
          and a.snd.get() == app.SOUNDS[2] and a.snd_file.get() == SONG, (picked, a.snd.get(), a.snd_file.get()))
    a.snd.set(app.SOUNDS[0]); picked.clear(); a.snd.set(app.SOUNDS[2])
    check('P6 choosing External file by hand still opens the picker', picked == ['askopenfilename'], picked)
    a.destroy()
    real_cfg = app.CFG; app.CFG = os.path.join(TMP, 'cfg.json'); json.dump({'capture': 'Fast (JPEG, ~2x faster)'}, open(app.CFG, 'w'))
    try:
        b = app.App(); b.withdraw()
        check('P5 settings saved with the old JPEG label keep Fast (not reset to PNG)', b.capture.get() == list(app.CAPTURES)[1]
              and app.CAPTURES[b.capture.get()] == 'jpeg', b.capture.get())
        b.destroy()
    finally: app.CFG = real_cfg
except Exception as e:
    import traceback; traceback.print_exc(); check('P GUI test ran', False, e)

app.close_log(); shutil.rmtree(TMP, ignore_errors=True)
print('\nALL PASS' if not fails else f'\n{len(fails)} FAIL: {fails}'); sys.exit(1 if fails else 0)
