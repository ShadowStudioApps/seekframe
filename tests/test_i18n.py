"""App languages (3.20): i18n.py + locales/*.json. No real dialog opens (no_dialogs).
  L1 every text the code passes to tr() (app.py, dialogs.py) has a translation in every language, with the same {0} slots
  L2 every drop-down choice (Quality, Format, Sound, Capture, Blender, Folder, Privacy, AI style / length) and Status word too
  L3 t(): translation + format; a broken translation falls back to English; unknown text stays as it is
  L4 pick(): SHADOW_LANG wins, then the setting, then Windows' language, else English; unknown codes -> English
  L5 Combo shows translations while the variable keeps the English key (both ways); set_values keeps the choice
  L6 status() / phrase() translate the known words of dynamic texts; English is untouched
  L7 window in Arabic: buttons and Options translated, keys unchanged (settings stay English), the Arabic font is used,
     the language choice is saved and a change offers a restart
Usage: python tests/test_i18n.py     exit 0 = all PASS"""
import ast, glob, json, os, re, sys, tempfile, shutil
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts (L7 switches on purpose)
import i18n

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

LOC = {os.path.splitext(os.path.basename(p))[0]: json.load(open(p, encoding='utf-8')) for p in glob.glob(os.path.join(ROOT, 'locales', '*.json'))}
check('L1 a file for every language but English', set(LOC) == set(i18n.LANGS) - {'en'}, sorted(LOC))
ids = set()
for fn in ('app.py', 'dialogs.py'):
    for n in ast.walk(ast.parse(open(os.path.join(ROOT, fn), encoding='utf-8').read())):
        if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'tr' and n.args and isinstance(n.args[0], ast.Constant): ids.add(n.args[0].value)
BRAND = {'Seekframe', 'Seekframe v{0}', 'Seekframe - {0}', 'YouTube'}
# 3.28 sidebar / page labels reach tr() through a variable: check them too
NAV = {'Queue', 'New video', 'AI tools', 'Settings', 'About', 'GitHub page', 'User guide', "What's new", 'Report a problem', 'Privacy policy', 'Shadow Studio', 'by Shadow Studio'}
slots = lambda s: sorted(re.findall(r'\{\d*\}', s))
for code, d in sorted(LOC.items()):
    miss = sorted(i for i in (ids | NAV) - BRAND if i not in d)
    check(f'L1 {code}: every tr() text translated', not miss, miss[:5])
    bad = [k for k, v in d.items() if not k.startswith('_') and slots(k) != slots(v)]
    check(f'L1 {code}: the same {{0}} slots as English', not bad, bad[:3])

import app, ai_tasks, youtube, render_core as rc
choices = (list(rc.PRESETS) + app.FORMAT_CHOICES + app.SOUNDS + list(app.CAPTURES) + [e for e in app.BLENDER_ENGINES if e != 'Eevee'] +
           [app.FOLDER_AUTO, app.FOLDER_NONE] + list(youtube.PRIVACY) + list(ai_tasks.STYLES) + list(ai_tasks.LENGTHS) + i18n.STATUS_WORDS)
for code, d in sorted(LOC.items()):
    miss = [c for c in choices if c not in d]
    check(f'L2 {code}: every drop-down choice and Status word', not miss, miss[:5])

# ---------------------------------------------------------------- L3
i18n.set_lang('de')
check('L3 t() translates and formats', i18n.t('Project saved: {0}', 'x.shadow') == 'Projekt gespeichert: x.shadow')
i18n._tab['Not fixed: {0}'] = 'kaputt {5}'
check('L3 a broken translation falls back to English', i18n.t('Not fixed: {0}', 'a') == 'Not fixed: a')
check('L3 unknown text stays', i18n.t('no such text') == 'no such text')

# ---------------------------------------------------------------- L4
os.environ['SHADOW_LANG'] = 'ja'; check('L4 SHADOW_LANG wins over the setting', i18n.pick('fr') == 'ja')
os.environ.pop('SHADOW_LANG')
check('L4 the setting', i18n.pick('fr') == 'fr')
real = i18n.windows_lang; i18n.windows_lang = lambda: 'es'
check('L4 auto = Windows language when Shadow has it', i18n.pick('auto') == 'es' and i18n.pick(None) == 'es')
i18n.windows_lang = lambda: 'sw'
check('L4 auto with a language Shadow lacks -> English', i18n.pick('auto') == 'en' and i18n.pick('xx') == 'en')
i18n.windows_lang = real; os.environ['SHADOW_LANG'] = 'en'

# ---------------------------------------------------------------- L5
import tkinter as tk
i18n.set_lang('fr')
r = tk.Tk(); r.withdraw()
var = tk.StringVar(master=r, value='Draft (fast, 720p)')
cb = i18n.Combo(r, var, list(rc.PRESETS))
check('L5 shows the translation of the key', cb.shown.get() == 'Brouillon (rapide, 720p)' and 'Meilleure (1080p, 64 échantillons)' in cb.cget('values'))
cb.shown.set('Meilleure (1080p, 64 échantillons)')
check('L5 picking a translation sets the English key', var.get() == 'Best (1080p, 64 samples)')
var.set('4K (UHD, 64 samples)')
check('L5 setting the key shows its translation', cb.shown.get() == '4K (UHD, 64 échantillons)')
fv = tk.StringVar(master=r, value='Music'); fb = i18n.Combo(r, fv, ['Music', 'Video']); fb.set_values(['Music', 'Video', 'Shorts 2026'])
check('L5 set_values keeps the choice and adds new names as they are', fv.get() == 'Music' and 'Shorts 2026' in fb.cget('values'))
r.destroy()

# ---------------------------------------------------------------- L6
check('L6 status words', i18n.status('Done · QC OK · thumb') == 'Terminé · Contrôle OK · miniature' and i18n.status('Frames 12/300') == 'Images 12/300')
check('L6 time estimate phrases', i18n.phrase('about 12 min · done ~15:40') == 'environ 12 min · fin ~15:40')
i18n.set_lang('en')
check('L6 English untouched', i18n.status('Done · QC OK') == 'Done · QC OK' and i18n.phrase('about 3 min') == 'about 3 min')

# ---------------------------------------------------------------- L7
import no_dialogs
TMP = tempfile.mkdtemp(prefix='shadow_i18n_'); app.LOG = os.path.join(TMP, 'l.log'); app.close_log(); no_dialogs.block(app)
os.environ['SHADOW_LANG'] = 'ar'
w = app.App(); w.withdraw()
try:
    w.update()
    texts = []
    def walk(x):
        try: texts.append(str(x.cget('text')))
        except Exception: pass
        for c in x.winfo_children(): walk(c)
    walk(w)
    check('L7 buttons in Arabic', 'رندر' in texts and 'فحص الإطارات' in texts and 'إضافة...' in texts, [t for t in texts if t][:8])
    check('L7 settings keep the English keys', w.preset.get() in rc.PRESETS and w.snd.get() in app.SOUNDS and w.fmt.get() in app.FORMAT_CHOICES)
    import tkinter.font as tkf
    check('L7 the Arabic font is used', tkf.nametofont('TkDefaultFont', root=w).actual('family') == 'Segoe UI' or 'Segoe UI' not in tkf.families(w),
          tkf.nametofont('TkDefaultFont', root=w).actual('family'))
    w.set_row(w.files[0] if w.files else None, 'Done')   # nothing there: no error
    restarted = []; asked = []
    w.lang_var.set('Deutsch')
    os.environ.pop('SHADOW_LANG')
    saved = {}; app.save_cfg = lambda d: saved.update(d)
    ch = w.on_language(ask=lambda *a: asked.append(a) or True, restart=lambda: restarted.append(1))
    check('L7 a new language is saved and a restart is offered', ch and saved.get('language') == 'de' and asked and restarted, (saved.get('language'), asked, restarted))
    restarted.clear(); w.lang_var.set(w.lang_names[0])
    w.on_language(ask=lambda *a: False, restart=lambda: restarted.append(1))
    check('L7 Auto is saved as "auto"; No = no restart', saved.get('language') == 'auto' and not restarted)
    kw = app.restart_kw({'PATH': 'x', '_PYI_APPLICATION_HOME_DIR': 'C:/T/_MEI1', '_MEIPASS2': 'C:/T/_MEI1', '_PYI_ARCHIVE_FILE': 'a'})
    check('L7 restart: the new Shadow.exe unpacks its own temp folder (3.21 crashed reusing the closing one)',
          kw['env'].get('PYINSTALLER_RESET_ENVIRONMENT') == '1' and not [k for k in kw['env'] if k.upper().startswith(('_PYI_', '_MEIPASS'))]
          and kw['env'].get('PATH') == 'x', kw['env'])
    started = []; w.on_close = lambda: started.append('closed')
    w.restart(popen=lambda args, **k: started.append((args, k.get('env', {}).get('PYINSTALLER_RESET_ENVIRONMENT'))))
    check('L7 restart starts Shadow with that environment, then closes', len(started) == 2 and started[0][1] == '1' and started[1] == 'closed', started)
finally:
    w.destroy(); os.environ['SHADOW_LANG'] = 'en'
    app.close_log(); shutil.rmtree(TMP, ignore_errors=True)
check('L7 no real dialog opened', not [c for c in no_dialogs.CALLS if c.startswith('ask')], no_dialogs.CALLS)

print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAIL: " + ", ".join(fails)}')
sys.exit(1 if fails else 0)
