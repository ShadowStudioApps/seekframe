"""One-step release: new VERSION -> tests -> commit -> Shadow.exe -> Setup -> public code -> GitHub release.
Run it with publish_update.bat (double-click). It asks for the new version and one line of notes, shows the plan, then does it.
  python tools/publish_update.py [--dry-run] [--skip-tests]
--dry-run: asks and checks everything, prints the plan, changes nothing."""
import argparse, os, re, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import updater

TESTS = ['test_queue_logic', 'test_qc_parse', 'test_updater', 'test_theme', 'test_capture', 'test_make_words', 'test_narrate_build', 'test_audio_encode',
         'test_qc_run', 'test_narrate_render', 'regression', 'test_queue_gui', 'test_queue_extras', 'test_assistant', 'test_youtube', 'test_scene_check', 'test_loudness', 'test_cleanup_browser', 'test_project', 'test_parallel_capture', 'test_color_determinism', 'test_video_song', 'test_ai_tasks', 'test_i18n', 'test_sidebar', 'test_ai_clients', 'test_cloud', 'test_text_fields', 'test_ai_engines']   # quick ones first (the CLAUDE.md list)
VER_RE = re.compile(r'^VERSION = "([^"]+)"', re.M)


def current_version(text=None):
    text = text if text is not None else open(os.path.join(ROOT, 'render_core.py'), encoding='utf-8').read()
    return VER_RE.search(text).group(1)


def bump_version(text, new):
    """render_core.py text with VERSION = "<new>" (only that line changes)."""
    out, n = VER_RE.subn(f'VERSION = "{new}"', text, count=1)
    if n != 1: raise ValueError('VERSION line not found in render_core.py')
    return out


def valid_new(new, cur):
    if not re.fullmatch(r'\d+(\.\d+){1,2}', new or ''): return 'use numbers like 3.1'
    if not updater.is_newer(new, cur): return f'{new} is not newer than {cur}'
    return None


def run(cmd, **kw):
    print('\n> ' + (cmd if isinstance(cmd, str) else ' '.join(cmd)), flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode == 0


def out(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout


def changed_files():
    """tracked files with changes, without the owner's scenes/ (never committed by this tool)"""
    files = []
    for line in out('git', 'status', '--porcelain', '--untracked-files=no').splitlines():
        p = line[3:].strip().strip('"')
        if p and not p.startswith('scenes/'): files.append(p)
    return files


def stop(msg):
    print(f'\nSTOPPED: {msg}'); sys.exit(1)


def ask(prompt):
    try: return input(prompt).strip()
    except EOFError: stop('no answer (input closed)')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--skip-tests', action='store_true')
    ap.add_argument('--version', help='the new version (or the current one to finish a stopped run); skips that question')
    ap.add_argument('--notes', help='the one-line release notes; skips that question')
    a = ap.parse_args()
    cur = current_version()
    print(f'Seekframe publish update   (now v{cur}, GitHub: {updater.REPO})\n')

    # checks before asking anything
    if out('git', 'branch', '--show-current').strip() != 'master': stop('switch to the master branch first')
    if not shutil.which('gh'): stop('GitHub CLI missing: winget install -e --id GitHub.cli, then gh auth login --web')
    if subprocess.run(['gh', 'auth', 'status'], capture_output=True).returncode != 0: stop('not signed in to GitHub: gh auth login --web -h github.com -p https')
    if any(n.lower() in subprocess.run(['tasklist', '/fi', f'imagename eq {n}'], capture_output=True, text=True).stdout.lower()
           for n in ('Seekframe.exe', 'Shadow.exe')):
        if not a.dry_run: stop('close Seekframe first (the tests and the build need it closed)')
        print('note: Seekframe is open (fine for --dry-run; close it for the real run)')
    if not os.path.isdir(os.path.join(os.path.dirname(ROOT), 'shadow-public', '.git')): stop('C:\\Projects\\shadow-public (the public repo) is missing')

    sug = '.'.join(cur.split('.')[:-1] + [str(int(cur.split('.')[-1]) + 1)])
    for _ in range(3):   # Enter = the suggested number; a wrong entry is asked again
        new = a.version or ask(f'New version (now {cur}; press Enter for {sug}): ') or sug
        if a.version and new != cur and valid_new(new, cur): stop(f'--version {new}: {valid_new(new, cur)}')
        if new == cur or not valid_new(new, cur): break
        print(f'  {valid_new(new, cur)}')
    else: stop('no valid version entered')
    # resume: a run that stopped after the commit (build / upload failed) is finished by entering the same version again
    resume = False
    if new == cur:
        try: live = updater.latest_release()
        except Exception as e: stop(f'cannot reach GitHub: {e}')
        if live and live['version'] == cur: stop(f'v{cur} is already released; enter a newer version')
        resume = True
    else:
        err = valid_new(new, cur)
        if err: stop(err)
    notes = a.notes or ask('What changed? (one line, shown in the update window): ') or f'Seekframe {new}'
    files = changed_files()
    since = out('git', 'rev-list', '--count', f'v{cur}..HEAD').strip()   # commits since the last release (tag v<cur>)
    if not resume and not files and since == '0':
        if ask(f'Nothing changed since v{cur}. Publish v{new} anyway? (y/n): ').lower() not in ('y', 'yes'): stop('nothing was changed')
    print(f'\nPlan for v{new}:')
    if resume:
        print(f'  1-3. (resume: v{cur} is committed but not released yet; skipping version, tests and commit)')
        if files: stop('there are uncommitted changes; for new changes enter a newer version')
    else:
        print(f'  1. VERSION {cur} -> {new} in render_core.py')
        print(f'  2. tests: {"SKIPPED" if a.skip_tests else ", ".join(TESTS)}  (about 10-15 min)')
        print(f'  3. commit on master: render_core.py' + (', ' + ', '.join(files) if files else '') + ' (scenes/ is never committed)')
    print( '  4. build_exe.bat -> dist\\Seekframe.exe     5. build_installer.bat -> dist\\Seekframe-%s-Setup.exe' % new)
    print( '  6. public code -> github.com/%s       7. release v%s with the setup + notes: %s' % (updater.REPO, new, notes))
    if a.dry_run:
        print('\n--dry-run: nothing was changed.'); return
    if ask('\nPress Enter to publish (type n or close this window to cancel): ').lower() in ('n', 'no'): stop('nothing was changed')

    t0 = time.time(); rc_path = os.path.join(ROOT, 'render_core.py')
    if not resume: commit_new_version(a, rc_path, new, cur, notes, files)
    build_and_publish(new, notes, t0)


def commit_new_version(a, rc_path, new, cur, notes, files):
    old_text = open(rc_path, encoding='utf-8', newline='').read()
    open(rc_path, 'w', encoding='utf-8', newline='').write(bump_version(old_text, new))
    print(f'\n[1/7] VERSION = "{new}"')
    if not a.skip_tests:
        print('[2/7] tests')
        for t in TESTS:
            if not run([sys.executable, os.path.join('tests', t + '.py')]):
                open(rc_path, 'w', encoding='utf-8', newline='').write(old_text)
                stop(f'test {t} failed (VERSION put back to {cur}; nothing was published)')
        if not run([sys.executable, '-c', "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('ast ok')"]):
            open(rc_path, 'w', encoding='utf-8', newline='').write(old_text); stop('app.py does not parse')
    print('[3/7] commit')
    if not (run(['git', 'add', '--', 'render_core.py', *files]) and run(['git', 'commit', '-q', '-m', f'Seekframe {new}: {notes}'])):
        stop('git commit failed')


def build_and_publish(new, notes, t0):
    print('[4/7] build Seekframe.exe')
    if not run(r'.\build_exe.bat < nul', shell=True) or not os.path.exists(os.path.join(ROOT, 'dist', 'Seekframe.exe')): stop('build_exe.bat failed')
    print('[5/7] build the setup')
    setup = os.path.join(ROOT, 'dist', f'Seekframe-{new}-Setup.exe')
    if not run(r'.\build_installer.bat < nul', shell=True) or not os.path.exists(setup): stop('build_installer.bat failed')
    print('[6/7] public code')
    if not run([sys.executable, os.path.join('tools', 'publish_public.py'), '-m', f'Seekframe {new}: {notes}', '--push']): stop('publishing the code failed')
    print('[7/7] GitHub release')
    notes_file = os.path.join(ROOT, 'release_notes.txt')
    with open(notes_file, 'w', encoding='utf-8') as f:
        # first paragraph = what changed (the in-app update window shows only that); then install help and the changelog
        f.write(f'{notes}\n\n'
                f'**Install:** download `Seekframe-{new}-Setup.exe` below and run it (no admin needed; if Windows SmartScreen warns, '
                f'choose *More info* -> *Run anyway*). **Already installed?** Open Seekframe and press **Update to v{new}**.\n\n'
                f'All changes: [CHANGELOG.md](https://github.com/Reemon88IQ/shadow/blob/main/CHANGELOG.md)\n')
    try: ok = run(r'.\release.bat < nul', shell=True)   # .\ : cmd may not search the current folder (NoDefaultCurrentDirectoryInExePath)
    finally:
        try: os.remove(notes_file)
        except OSError: pass
    if not ok: stop('release.bat failed')
    run(['git', 'tag', '-f', f'v{new}'])   # marks the released commit (for 'nothing changed since')
    try:
        rel = updater.latest_release()
        live = rel and rel['version'] == new
    except Exception: live = False
    mins = (time.time() - t0) / 60
    print(f'\nDONE in {mins:.0f} min: v{new} is ' + ('live' if live else 'published (GitHub may need a minute)') +
          f'\n  https://github.com/{updater.REPO}/releases/latest\nEveryone with Seekframe sees "Update to v{new}" the next time they open it.')


if __name__ == '__main__':
    main()
