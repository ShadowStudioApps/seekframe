"""Copies the public part of Shadow (committed state of HEAD) into a separate git repo and commits it there.

The public repo has its own history: no scenes, no private notes, no old commits (they carry a private e-mail).
Usage:  python tools/publish_public.py [--dir C:\\Projects\\shadow-public] [-m "message"] [--push]
First time: create the GitHub repo, then in the public dir:  git remote add origin https://github.com/<owner>/<repo>.git
and set the noreply identity there:  git config user.name ... / git config user.email <id>+<user>@users.noreply.github.com
"""
import argparse, fnmatch, io, os, shutil, subprocess, sys, tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# what goes public (paths or globs, matched against files tracked in HEAD); everything else stays private
PUBLIC = ['app.py', 'assistant.py', 'docs/ASSISTANT.md', 'render_core.py', 'blender_core.py', 'qc.py', 'updater.py', 'frame_check.py', 'subtitles.py', 'tools/blender/*', 'tools/mcp_server.py',
          'tools/check_frames.py', 'docs/MCP.md', 'docs/BLENDER.md', 'claude-skills/shadow-mcp/*', 'CHANGELOG.md', 'docs/banner.png', 'docs/demo.gif', 'docs/screenshot_light.png', 'docs/screenshot_ai_new.png', 'docs/screenshot_ai_fix.png', 'docs/screenshot_arabic.png', 'docs/screenshot_about.png',
          'docs/social_preview.png', '.github/ISSUE_TEMPLATE/*', 'tools/make_brand_images.py', 'README.md', 'LICENSE', '.gitignore',
          'install.bat', 'build_exe.bat', 'build_installer.bat', 'release.bat', 'run.bat', 'publish_update.bat',
          'installer/shadow.iss', 'assets/shadow.ico', 'assets/shadow_1024.png', 'assets/shadow_studio.png', 'docs/screenshot.png',
          'tools/narrate/*', 'tools/publish_public.py', 'tools/publish_update.py', 'tests/*.py', 'tests/fixtures/*', 'tests/fixtures/qc/*',
          'docs/GUIDE.md', 'youtube.py', 'scene_paths.py', 'projects.py', 'shadow_util.py', 'dialogs.py', 'video_song.py', 'ai_tasks.py', 'ai_clients.py', 'i18n.py', 'locales/*.json', 'assets/ai_template.html', 'docs/YOUTUBE.md', 'docs/PRIVACY.md', 'docs/screenshot_youtube.png']
# matched by PUBLIC but kept private (they need the private channel tools)
NOT_PUBLIC = ['tests/test_song_structure.py']


def git(*a, cwd=ROOT, **kw):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, **kw).stdout


def public_files():
    tracked = git('ls-tree', '-r', '--name-only', '-z', 'HEAD').decode('utf-8').split('\0')
    return sorted(f for f in tracked if f and f not in NOT_PUBLIC and any(fnmatch.fnmatchcase(f, p) and f.count('/') == p.count('/') for p in PUBLIC))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(os.path.dirname(ROOT), 'shadow-public'))
    ap.add_argument('-m', '--message', default=None); ap.add_argument('--push', action='store_true')
    a = ap.parse_args()
    files = public_files()
    missing = [p for p in PUBLIC if not any(fnmatch.fnmatchcase(f, p) for f in files)]
    if missing: sys.exit(f'not committed in HEAD: {missing}')
    if not os.path.isdir(os.path.join(a.dir, '.git')):
        os.makedirs(a.dir, exist_ok=True); git('init', '-b', 'main', cwd=a.dir)
    # mirror: remove what the public repo tracks, then write the HEAD versions of the public files
    for f in git('ls-files', '-z', cwd=a.dir).decode('utf-8').split('\0'):
        if f:
            try: os.remove(os.path.join(a.dir, f))
            except FileNotFoundError: pass
    tar = git('archive', '--format=tar', 'HEAD', '--', *files)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t: t.extractall(a.dir, filter='data')
    try: email = git('config', '--local', 'user.email', cwd=a.dir).decode().strip()
    except subprocess.CalledProcessError: email = ''
    if not email.endswith('@users.noreply.github.com'):   # never publish a private e-mail in the public history
        sys.exit(f'set the GitHub noreply e-mail in {a.dir} first: git config user.email <id>+<user>@users.noreply.github.com')
    git('add', '-A', cwd=a.dir)
    if not git('status', '--porcelain', cwd=a.dir).strip():
        print('public repo already up to date')
    else:
        ver = next((l.split('"')[1] for l in open(os.path.join(a.dir, 'render_core.py'), encoding='utf-8') if l.startswith('VERSION')), '?')
        git('commit', '-q', '-m', a.message or f'Seekframe {ver}', cwd=a.dir)
        print(f'committed {len(files)} files in {a.dir} (Seekframe {ver})')
    if a.push:
        subprocess.run(['git', 'push', '-u', 'origin', 'main'], cwd=a.dir, check=True)


if __name__ == '__main__':
    main()
