"""Smart Shadow (3.19): jobs the app hands to Claude from its own buttons, without a chat.

Claude runs through the installed Claude Code CLI on the owner's subscription, exactly like the Assistant panel
(assistant.check_ready refuses API-key / cloud sign-ins, assistant.clean_env drops ANTHROPIC_API_KEY): never a paid API.
Each job is one `claude -p` run (resumed with --resume for a second round), and Claude may only:
  - read files (Read / Glob / Grep; it also reads images, e.g. a contact sheet),
  - edit or write the ONE file the job names (permission rule Edit(./<file>) / Write(./<file>), cwd = that file's folder,
    --permission-mode dontAsk: everything else is refused without asking). No shell, no web, no MCP servers.
Verified with Claude Code 2.1.329: asked to edit two files with only one allowed, it changed that one and was refused the other.

Jobs:
  fix_scene(scene, problems, ...)  "Fix with AI": Claude repairs a COPY of the scene (.shadow_fix_<id>.html next to it, so its
      relative files load); after each round Shadow itself runs the scene check + Check frames on the copy and sends any
      problem left back to Claude (max `rounds`). Nothing changes until the owner presses Apply: apply_fix() keeps the
      original in <folder>/.shadow_backup/ (a dot folder, never collected as a scene) and puts the fix in its place.
  write_metadata(mp4, ...)          "YouTube text (AI)": Claude looks at a contact sheet of the video (+ the scene's text and
      narration words) and writes metadata.txt next to the mp4 in youtube.py's format (never overwriting one).
  new_video(idea, root, ...)        "New video (AI)": a new folder with the narration (Claude), the voice (Kokoro, English,
      in a Python that has it), word timings and the scene (Claude, from assets/ai_template.html), checked by Shadow."""
import glob, json, os, re, shutil, subprocess, threading, time, uuid
import assistant as asst

NOWIN = asst.NOWIN
FIX_PREFIX = '.shadow_fix_'
FIX_STALE_S = 6 * 3600
BACKUP_DIR = '.shadow_backup'
READ = ['Read', 'Glob', 'Grep']

SYSTEM = """You work inside the Seekframe desktop app, called by one of its buttons (not a chat): do the job, then stop.
Seekframe renders self-contained three.js / canvas HTML scenes to MP4 (30 fps, with sound, 16:9 and 9:16 Shorts) for the
owner's YouTube channels. You may read files; you may change ONLY the file the job names (anything else is refused).
You cannot run commands or open web pages. End with a short plain-text summary (no tables, no code) in {lang}."""

CONTRACT = """The Seekframe scene contract (what every scene must do):
- one <canvas id="c">; the size comes from the URL params w and h (read h too, e.g. get('h'), so 9:16 works; lay out for
  W/H < 1: camera, bigger wrapped captions kept above the Shorts UI);
- with ?render=1 it must not autoplay; set window.__ready = true once everything is loaded;
- window.DURATION = length in seconds; window.seek(t) draws exactly the frame at time t (a pure function of t: no real-time
  animate loop, no Math.random / Date.now without a fixed seed, no state carried from the previous frame);
- sound (optional): window.STYLE_SOUND(k) = the score for the SOUND kit's renderOffline;
- optional window.THUMBNAIL_T = the time of the thumbnail frame."""


# ---------------------------------------------------------------- which AI does the jobs (3.32: Settings > AI connections)
ENGINE = 'claude'   # 'claude' (Claude Code, the default) or 'gemini' (Gemini CLI); the Assistant chat is always Claude Code
ENGINES = {'claude': 'Claude Code', 'gemini': 'Gemini CLI'}


def Task(cwd, edit_files=(), **kw):
    """One AI job with the engine chosen in Settings (ClaudeTask or GeminiTask; both: ask(), stop(), session_id)."""
    return (GeminiTask if ENGINE == 'gemini' else ClaudeTask)(cwd, edit_files, **kw)


# ---------------------------------------------------------------- one Claude job
class ClaudeTask:
    """Claude runs in `cwd`; `edit_files` = names (inside cwd) it may edit / write. on_event(kind, *data) from a reader
    thread: ('status', s) ('text', s) ('tool', summary) ('denied', summary). ask() blocks and returns
    dict(ok, text, error, session_id, denials). stop() kills it (from any thread)."""

    def __init__(self, cwd, edit_files=(), on_event=lambda *a: None, lang='English', exe=None, popen=subprocess.Popen,
                 ready=asst.check_ready, model=None, add_dirs=()):
        self.cwd = cwd; self.edit_files = [os.path.basename(f) for f in edit_files]; self.on_event = on_event
        self.lang = lang; self.exe = exe; self.popen = popen; self.ready = ready; self.model = model
        self.add_dirs = list(add_dirs); self.session_id = None; self.proc = None; self.stopped = False; self.ready_ok = False

    def args(self):
        allowed = READ + [f'{t}(./{f})' for f in self.edit_files for t in ('Edit', 'Write')]
        a = asst.cmd(self.exe) + ['-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
                                  '--include-partial-messages', '--permission-mode', 'dontAsk',
                                  '--tools', ','.join(READ + (['Edit', 'Write'] if self.edit_files else [])),
                                  '--allowedTools', ','.join(allowed), '--strict-mcp-config',
                                  '--append-system-prompt', SYSTEM.format(lang=self.lang)]
        for d in self.add_dirs:
            if d and os.path.isdir(d): a += ['--add-dir', d]
        if self.model: a += ['--model', self.model]
        if self.session_id: a += ['--resume', self.session_id]
        return a

    def ask(self, prompt):
        if self.stopped: return dict(ok=False, text='', error='stopped', session_id=self.session_id, denials=[])
        if not self.ready_ok:
            self.exe = self.exe or asst.find_claude()
            ok, msg = self.ready(self.exe)
            if not ok: return dict(ok=False, text='', error=msg, session_id=None, denials=[])
            self.ready_ok = True
        self.on_event('status', 'Starting Claude...')
        try:
            p = self.proc = self.popen(self.args(), cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=asst.clean_env(), creationflags=NOWIN)
        except Exception as e:
            return dict(ok=False, text='', error=f'could not start Claude Code: {e}', session_id=None, denials=[])
        err = []
        threading.Thread(target=lambda: [err.append(l.decode('utf-8', 'replace').rstrip()) for l in iter(p.stderr.readline, b'')], daemon=True).start()
        try:
            p.stdin.write(asst.user_line(prompt).encode('utf-8')); p.stdin.close()
        except Exception: pass
        self.on_event('status', 'Claude is working...')
        text, seen, result, denials = [], set(), None, []
        for raw in iter(p.stdout.readline, b''):
            try: d = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError: continue
            for ev in asst.parse_event(d, seen):
                k = ev[0]
                if k == 'session' and ev[1]: self.session_id = ev[1]
                elif k == 'text':
                    if d.get('type') == 'stream_event' and d.get('_mid'): seen.add(d['_mid'])
                    text.append(ev[1]); self.on_event('text', ev[1])
                elif k == 'tool':
                    self.on_event('tool', asst.tool_summary(ev[1], ev[2])); self.on_event('status', f'Claude: {asst.short_tool(ev[1])}')
                elif k == 'denied':
                    denials.append(asst.tool_summary(ev[1], ev[2])); self.on_event('denied', denials[-1])
                elif k == 'limit':
                    self.on_event('status', asst.limit_text(ev[1]))
                elif k == 'result':
                    result = ev[1]
                    if result.get('session_id'): self.session_id = result['session_id']
        code = p.wait(); self.proc = None
        if self.stopped: return dict(ok=False, text=''.join(text), error='stopped', session_id=self.session_id, denials=denials)
        if result is None or result.get('is_error'):
            why = (result and (', '.join(map(str, result.get('errors') or [])) or str(result.get('result') or ''))) or \
                  f'Claude Code stopped (exit {code})' + (': ' + ' / '.join(err[-3:]) if err else '')
            return dict(ok=False, text=''.join(text), error=why, session_id=self.session_id, denials=denials)
        final = result.get('result') if isinstance(result.get('result'), str) else ''.join(text)
        return dict(ok=True, text=final or ''.join(text), error=None, session_id=self.session_id, denials=denials)

    def stop(self):
        self.stopped = True; asst.kill_tree(self.proc)


# ---------------------------------------------------------------- one Gemini CLI job (3.32)
GEMINI_AUTH = 'account'   # 3.34: 'account' = Gemini CLI's own sign-in, 'api_key' = the Google AI Studio key saved in Seekframe
GEMINI_KEY_FILE = os.path.join(os.path.expanduser('~'), '.shadow_gemini_key.bin')


def valid_gemini_key(key):
    key = (key or '').strip()
    return key.startswith('AIza') and len(key) >= 30 and ' ' not in key


def save_gemini_key(key, path=None):
    """Store a Google AI Studio key encrypted for this Windows account (DPAPI). ValueError for something else."""
    key = (key or '').strip()
    if not valid_gemini_key(key): raise ValueError('That does not look like a Google AI Studio API key (it starts with AIza).')
    with open(path or GEMINI_KEY_FILE, 'wb') as f: f.write(asst._dpapi(key.encode('utf-8')))


def load_gemini_key(path=None):
    try:
        with open(path or GEMINI_KEY_FILE, 'rb') as f: return asst._dpapi(f.read(), decrypt=True).decode('utf-8')
    except Exception:
        return None


def delete_gemini_key(path=None):
    try: os.remove(path or GEMINI_KEY_FILE)
    except OSError: pass


def key_provider(key):
    """Which company an API key belongs to, from its start: 'anthropic' (sk-ant-), 'google' (AIza), 'openai' (sk-), else None."""
    k = (key or '').strip()
    if k.startswith('sk-ant-'): return 'anthropic'
    if k.startswith('AIza'): return 'google'
    if k.startswith('sk-'): return 'openai'
    return None


def account_status(engine, run=subprocess.run, home=None):
    """(signed_in True/False/None, short text) of the chosen AI's own sign-in. Claude Code: `claude auth status` (JSON);
    Gemini CLI: its settings (security.auth.selectedType) + saved Google sign-in. Never shows the e-mail."""
    home = home or os.path.expanduser('~')
    try:
        if engine == 'claude':
            exe = asst.find_claude()
            if not exe: return False, 'Claude Code is not installed'
            r = run(asst.cmd(exe) + ['auth', 'status'], capture_output=True, text=True, timeout=30, creationflags=NOWIN, env=asst.clean_env())
            d = json.loads(r.stdout or '{}')
            if not d.get('loggedIn'): return False, 'not signed in'
            plan = d.get('subscriptionType') or d.get('planTier') or ''
            return True, 'signed in' + (f' (Claude {plan.capitalize()})' if plan else '') if d.get('authMethod') == 'claude.ai' else 'signed in (' + str(d.get('authMethod')) + ')'
        g = os.path.join(home, '.gemini')
        try:
            with open(os.path.join(g, 'settings.json'), encoding='utf-8') as f: sel = ((json.load(f).get('security') or {}).get('auth') or {}).get('selectedType')
        except Exception: sel = None
        if sel == 'oauth-personal' and (glob.glob(os.path.join(g, 'oauth_creds*.json')) or os.path.isfile(os.path.join(g, 'google_accounts.json'))):
            return True, 'signed in with Google'
        if sel == 'gemini-api-key': return True, 'set to an API key in Gemini CLI itself (GEMINI_API_KEY)'
        if sel: return True, f'signed in ({sel})'
        return False, 'not signed in'
    except Exception as e:
        return None, f'could not check ({type(e).__name__})'


def login_command(engine):
    """The command that signs the chosen AI in, run in its own console window: `claude auth login`, or Gemini CLI itself
    (it asks how to sign in on its first start; /auth changes it later)."""
    if engine == 'claude':
        exe = asst.find_claude()
        return asst.cmd(exe) + ['auth', 'login'] if exe else None
    return find_gemini()


def gemini_env(base=None, folder=None):
    """The environment for a Gemini job. API-key mode: GEMINI_API_KEY + a system settings file that selects the key
    (Gemini CLI 0.68 reads security.auth.selectedType from settings BEFORE the environment, so the variable alone does
    not switch an account sign-in; system settings win over the user's, and the user's file is never changed)."""
    env = dict(os.environ if base is None else base)
    if GEMINI_AUTH == 'api_key':
        key = load_gemini_key()
        if key:
            env['GEMINI_API_KEY'] = key
            if folder:
                p = os.path.join(folder, 'system-settings.json')
                with open(p, 'w', encoding='utf-8') as f: json.dump({'security': {'auth': {'selectedType': 'gemini-api-key'}}}, f)
                env['GEMINI_CLI_SYSTEM_SETTINGS_PATH'] = p
    return env


def find_gemini(which=shutil.which):
    """[node.exe, gemini.js] of the installed Gemini CLI (npm's gemini.cmd only starts node with that script; running the
    script directly keeps the prompt away from cmd.exe's quoting), else [gemini] when only that is found, else None."""
    g = which('gemini')
    if not g: return None
    d = os.path.dirname(g)
    js = os.path.join(d, 'node_modules', '@google', 'gemini-cli', 'bundle', 'gemini.js')
    node = os.path.join(d, 'node.exe') if os.path.isfile(os.path.join(d, 'node.exe')) else which('node')
    if os.path.isfile(js) and node: return [node, js]
    return [g]


def gemini_ready(cmd):
    """(ok, message) like assistant.check_ready: Gemini CLI installed and signed in (it keeps its Google sign-in in ~/.gemini),
    or, in API-key mode, a key saved in Seekframe."""
    if not cmd: return False, 'Gemini CLI was not found. Install it (npm install -g @google/gemini-cli) and sign in once by running gemini.'
    if GEMINI_AUTH == 'api_key':
        key = load_gemini_key()
        return (True, 'Gemini CLI (API key ' + asst.key_hint(key) + ')') if key else (False, 'no Gemini API key saved yet (Settings > AI connections)')
    home = os.path.join(os.path.expanduser('~'), '.gemini')
    if not (os.environ.get('GEMINI_API_KEY') or glob.glob(os.path.join(home, 'oauth_creds*.json')) or os.path.isfile(os.path.join(home, 'google_accounts.json'))):
        return False, 'Gemini CLI is not signed in yet: run gemini once in a terminal and sign in with Google.'
    return True, 'Gemini CLI'


def _js_regex_escape(s):
    return re.sub(r'([.^$*+?()\[\]{}|\\/])', r'\\\1', s)


def gemini_policy(edit_files):
    """Gemini CLI policy rules (TOML): read files; write / replace ONLY the named files; every other tool is refused (shell,
    web, sub-agents, MCP). Measured with Gemini CLI 0.68: a deny rule WITH an argsPattern keeps tools visible to the model
    (a global deny hides them), and Gemini refuses nested-quantifier regexes, so the file rule stays one simple pattern."""
    rules = []
    for f in edit_files:
        pat = '"file_path":"[^"]*' + _js_regex_escape(f) + '"'
        rules.append(f'[[rule]]\ntoolName = ["write_file", "replace"]\nargsPattern = {json.dumps(pat)}\ndecision = "allow"\npriority = 900\n')
    rules.append('[[rule]]\ntoolName = ["read_file", "read_many_files", "list_directory", "glob", "grep_search", "search_file_content"]\n'
                 'decision = "allow"\npriority = 500\n')
    rules.append('[[rule]]\ntoolName = "*"\nargsPattern = "."\ndecision = "deny"\npriority = 100\n'
                 'denyMessage = "Seekframe allows only reading files and editing the one file named in the task."\n')
    return '\n'.join(rules)


class GeminiTask:
    """The same job as ClaudeTask, done by Gemini CLI (`gemini -p` headless, --output-format stream-json). Gemini may read
    files and change only `edit_files` (gemini_policy, loaded with --policy); --approval-mode default, so anything without
    an allow rule is refused in headless mode. Uses the owner's own Gemini sign-in; nothing is paid through Seekframe."""

    def __init__(self, cwd, edit_files=(), on_event=lambda *a: None, lang='English', exe=None, popen=subprocess.Popen,
                 ready=gemini_ready, model=None, add_dirs=(), find=None, **_ignored):
        self.cwd = cwd; self.edit_files = [os.path.basename(f) for f in edit_files]; self.on_event = on_event
        self.lang = lang; self.exe = exe; self.popen = popen; self.ready = ready; self.model = model
        self.add_dirs = list(add_dirs); self.session_id = None; self.proc = None; self.stopped = False; self.ready_ok = False
        self.policy = None; self.find = find or find_gemini

    def _policy_file(self):
        if not self.policy:
            import tempfile
            d = tempfile.mkdtemp(prefix='shadow_gemini_')
            self.policy = os.path.join(d, 'seekframe.toml')
            with open(self.policy, 'w', encoding='utf-8') as f: f.write(gemini_policy(self.edit_files))
        return self.policy

    def args(self):
        cmd = list(self.exe if isinstance(self.exe, (list, tuple)) else [self.exe])
        a = cmd + ['-p', 'Do the job described above.', '--output-format', 'stream-json', '--approval-mode', 'default',
                   '--skip-trust', '--allowed-mcp-server-names', 'none', '--policy', self._policy_file()]
        for d in self.add_dirs:
            if d and os.path.isdir(d): a += ['--include-directories', d]
        if self.model: a += ['--model', self.model]
        if self.session_id: a += ['--resume', self.session_id]
        return a

    def ask(self, prompt):
        if self.stopped: return dict(ok=False, text='', error='stopped', session_id=self.session_id, denials=[])
        if not self.ready_ok:
            self.exe = self.exe or self.find()
            ok, msg = self.ready(self.exe)
            if not ok: return dict(ok=False, text='', error=msg, session_id=None, denials=[])
            self.ready_ok = True
        self.on_event('status', 'Starting Gemini...')
        try:
            args = self.args()
            p = self.proc = self.popen(args, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=NOWIN, env=gemini_env(folder=os.path.dirname(self._policy_file())))
        except Exception as e:
            return dict(ok=False, text='', error=f'could not start Gemini CLI: {e}', session_id=None, denials=[])
        err = []
        threading.Thread(target=lambda: [err.append(l.decode('utf-8', 'replace').rstrip()) for l in iter(p.stderr.readline, b'')], daemon=True).start()
        try:   # the prompt goes in on stdin (Gemini appends -p to it): no length limit, no command-line quoting
            p.stdin.write((SYSTEM.format(lang=self.lang) + '\n\n' + prompt).encode('utf-8')); p.stdin.close()
        except Exception: pass
        self.on_event('status', 'Gemini is working...')
        text, result, denials, names = [], None, [], {}
        for raw in iter(p.stdout.readline, b''):
            try: d = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError: continue
            t = d.get('type')
            if t == 'init' and d.get('session_id'): self.session_id = d['session_id']
            elif t == 'message' and d.get('role') == 'assistant' and d.get('content'):
                text.append(d['content']); self.on_event('text', d['content'])
            elif t == 'tool_use':
                prm = d.get('parameters') or {}
                s = f"{d.get('tool_name')}: {os.path.basename(str(prm.get('file_path') or prm.get('dir_path') or prm.get('pattern') or ''))}".rstrip(': ')
                names[d.get('tool_id')] = s
                self.on_event('tool', s); self.on_event('status', f'Gemini: {d.get("tool_name")}')
            elif t == 'tool_result' and d.get('status') == 'error' and (d.get('error') or {}).get('type') == 'policy_violation':
                denials.append(names.get(d.get('tool_id'), '?')); self.on_event('denied', denials[-1])
            elif t == 'error':
                self.on_event('status', str(d.get('message') or d.get('error') or 'Gemini error')[:200])
            elif t == 'result':
                result = d
        code = p.wait(); self.proc = None
        if self.stopped: return dict(ok=False, text=''.join(text), error='stopped', session_id=self.session_id, denials=denials)
        bad = (result or {}).get('status') not in (None, 'success') or code != 0
        if bad:
            msgs = [l for l in err if l.strip() and not l.startswith('    at ')]
            why = str(((result or {}).get('error') or {}).get('message') or '') or f'Gemini CLI stopped (exit {code})' + (': ' + ' / '.join(msgs[-3:]) if msgs else '')
            return dict(ok=False, text=''.join(text), error=why, session_id=self.session_id, denials=denials)
        return dict(ok=True, text=''.join(text), error=None, session_id=self.session_id, denials=denials)

    def stop(self):
        self.stopped = True; asst.kill_tree(self.proc)


# ---------------------------------------------------------------- Fix with AI
def clean_stale_fixes(folder, now=None):
    """Remove .shadow_fix_* copies (and their check sheets) older than FIX_STALE_S in folder (a crash left them)."""
    now = now or time.time()
    for f in glob.glob(os.path.join(folder, FIX_PREFIX + '*')):
        try:
            if now - os.path.getmtime(f) > FIX_STALE_S: os.remove(f)
        except OSError: pass

def work_copy(scene):
    d = os.path.dirname(os.path.abspath(scene)); clean_stale_fixes(d)
    w = os.path.join(d, f'{FIX_PREFIX}{uuid.uuid4().hex[:8]}{os.path.splitext(scene)[1] or ".html"}')
    shutil.copyfile(scene, w); return w

def fix_prompt(scene, work, problems, notes=()):
    p = '\n'.join(f'- {x}' for x in problems) or '- (none listed: check the scene against the contract and fix anything that breaks it)'
    n = ('\nNotes from Seekframe (not errors):\n' + '\n'.join(f'- {x}' for x in notes)) if notes else ''
    return (f'Job: FIX this Seekframe scene so it renders.\n\nThe scene is {os.path.basename(scene)}. Work ONLY on its copy '
            f'"{os.path.basename(work)}" in this folder (same content; edit it with the Edit tool). Other files in this folder '
            f'(scripts, sounds, images it loads) may be read but not changed.\n\nShadow found these problems:\n{p}{n}\n\n'
            f'{CONTRACT}\n\nRules: keep the scene\'s look, story, text and timing; change only what is needed to fix the problems. '
            'If a problem is in a file you may not change, or cannot be fixed in this file, say so. '
            'After your edits Seekframe checks the copy again and tells you if something is still wrong.')

def scene_problems(path, check=None, cancel=None):
    """What Shadow itself finds: the contract check + Check frames (contact sheet, page errors, seek purity)."""
    import render_core as rc
    probs = list(rc.contract_problems(path) or [])
    res = None
    if check is not None:
        try: res = check(path, cancel=cancel)
        except Exception as e: res = dict(ok=False, sheet=None, problems=[f'Check frames crashed: {type(e).__name__}: {e}'], notes=[])
        probs += [x for x in res.get('problems') or [] if x not in probs]
    return probs, res

def fix_scene(scene, problems, task=None, check=None, rounds=3, notes=(), progress=lambda s: None, **task_kw):
    """Repair a copy of scene. problems: what failed (render error, QC, Check frames...). check: frame_check.check (None =
    contract check only). Returns dict(ok, work, rounds, summary, problems (left), sheet, error). The original is untouched."""
    work = work_copy(scene)
    task = task or Task(os.path.dirname(work), [work], **task_kw)
    task.cwd, task.edit_files = os.path.dirname(work), [os.path.basename(work)]   # a Task made by the window: only this copy
    prompt = fix_prompt(scene, work, problems, notes); out = dict(ok=False, work=work, rounds=0, summary='', problems=list(problems), sheet=None, error=None)
    before = open(work, 'rb').read()
    for r in range(1, max(1, rounds) + 1):
        progress(f'Round {r}: Claude is fixing the scene...')
        res = task.ask(prompt); out['rounds'] = r
        if not res['ok']: out['error'] = res['error']; out['summary'] = res['text']; break
        out['summary'] = res['text']
        if task.stopped: out['error'] = 'stopped'; break
        progress(f'Round {r}: Seekframe checks the fixed copy...')
        left, chk = scene_problems(work, check)
        out['problems'] = left; out['sheet'] = chk and chk.get('sheet')
        if not left:
            out['ok'] = open(work, 'rb').read() != before or not problems
            if not out['ok']: out['error'] = 'Claude did not change the scene'
            break
        prompt = ('Seekframe checked your fixed copy again. Still wrong:\n' + '\n'.join(f'- {x}' for x in left) +
                  f'\nFix these in "{os.path.basename(work)}" too, then give the short summary again.')
    return out

def diff_lines(a_path, b_path, n=400):
    import difflib
    a = open(a_path, encoding='utf-8', errors='replace').read().splitlines()
    b = open(b_path, encoding='utf-8', errors='replace').read().splitlines()
    d = list(difflib.unified_diff(a, b, 'before', 'after', n=1, lineterm=''))
    return d[:n] + ([f'... ({len(d) - n} more lines)'] if len(d) > n else [])

def apply_fix(scene, work):
    """The owner pressed Apply: the original goes to <folder>/.shadow_backup/<name>_<time><ext>, the fix takes its place.
    Returns the backup path."""
    d = os.path.dirname(os.path.abspath(scene)); bdir = os.path.join(d, BACKUP_DIR); os.makedirs(bdir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(scene))
    bak = os.path.join(bdir, f'{stem}_{time.strftime("%Y%m%d-%H%M%S")}{ext}'); k = 2
    while os.path.exists(bak): bak = os.path.join(bdir, f'{stem}_{time.strftime("%Y%m%d-%H%M%S")}_{k}{ext}'); k += 1
    shutil.copy2(scene, bak)
    shutil.copyfile(work, scene)
    discard(work)
    return bak

def discard(work):
    for f in (work, os.path.splitext(work)[0] + '.check.jpg'):
        try: os.remove(f)
        except OSError: pass


# ---------------------------------------------------------------- YouTube text (AI)
META_FORMAT = """metadata.txt format (Seekframe reads it when uploading; keep the field names exactly):
TITLE: one line, under 70 characters, curious and clear (no clickbait lies, no ALL CAPS)
DESCRIPTION:
several lines: a hook sentence, what the video shows, a short call to subscribe; for a song: the lyrics' theme
TAGS: comma separated, 8-15 tags, most important first
AUDIENCE: yes | no          (yes = made for kids; only when the video is made for children)
AI: yes | no               (yes when the visuals or voice were made with AI tools)
=== SHORT ===
TITLE: / DESCRIPTION: / TAGS: for the 9:16 Short version (title under 60 characters, #shorts in the description)"""

def contact_sheet(mp4, out_jpg, tiles=12):
    """12 frames across the video in one jpg (ffmpeg), for Claude to look at. Returns out_jpg or None."""
    import render_core as rc
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=width,height', '-of', 'json', mp4],
                           capture_output=True, text=True, creationflags=NOWIN)
        info = json.loads(r.stdout); dur = float(info['format']['duration'])
        st = next(s for s in info['streams'] if s.get('width')); vert = st['height'] > st['width']
        cols = 6 if vert else 4; rows = (tiles + cols - 1) // cols
        subprocess.run([rc.find_ffmpeg() or 'ffmpeg', '-v', 'error', '-y', '-i', mp4, '-vf',
                        f'fps={tiles / max(dur, 0.1):.5f},scale={200 if vert else 400}:-2,tile={cols}x{rows}:padding=4', '-frames:v', '1', '-q:v', '3', out_jpg],
                       check=True, capture_output=True, creationflags=NOWIN)
        return out_jpg
    except Exception:
        return None

def scene_text(scene, limit=6000):
    """The words a scene shows / says (captions, narration words.json, visible strings), cut to `limit` characters."""
    if not scene or not os.path.isfile(scene) or not scene.lower().endswith(('.html', '.htm')): return ''
    parts = []
    w = os.path.splitext(scene)[0] + '.words.json'
    if os.path.isfile(w):
        try: parts.append('Narration: ' + ' '.join(x.get('w', '') for x in json.load(open(w, encoding='utf-8')).get('words', [])))
        except Exception: pass
    src = open(scene, encoding='utf-8', errors='replace').read()
    t = re.search(r'<title>(.*?)</title>', src, re.S | re.I)
    if t: parts.append('Title tag: ' + t.group(1).strip())
    strs = re.findall(r"['\"`]([A-Za-z؀-ۿ][^'\"`\n]{12,160})['\"`]", src)
    keep = [s for s in strs if ' ' in s and not re.search(r'[{};=<>]|https?:|\.js|\.png|rgba?\(', s)]
    if keep: parts.append('Text in the scene: ' + ' | '.join(dict.fromkeys(keep)))
    return '\n'.join(parts)[:limit]

def meta_path(mp4, replace=False):
    """metadata.txt next to the mp4 (the name uploads read). One there already: replace=True moves it to
    .shadow_backup/metadata_<time>.txt first; else a free metadata_N.txt (never overwritten)."""
    d = os.path.dirname(os.path.abspath(mp4)); p = os.path.join(d, 'metadata.txt')
    if os.path.exists(p) and replace:
        b = os.path.join(d, BACKUP_DIR); os.makedirs(b, exist_ok=True)
        shutil.move(p, os.path.join(b, f'metadata_{time.strftime("%Y%m%d-%H%M%S")}_{uuid.uuid4().hex[:4]}.txt'))
    k = 2
    while os.path.exists(p): p = os.path.join(d, f'metadata_{k}.txt'); k += 1
    return p

def write_metadata(mp4, scene=None, channel='', notes='', replace=False, task=None, progress=lambda s: None, **task_kw):
    """Claude writes metadata.txt (or metadata_N.txt) next to mp4. Returns dict(ok, path, text, summary, error)."""
    import youtube
    d = os.path.dirname(os.path.abspath(mp4)); stem = os.path.splitext(os.path.basename(mp4))[0]
    sheet = contact_sheet(mp4, os.path.join(d, f'.shadow_sheet_{uuid.uuid4().hex[:6]}.jpg'))
    path = meta_path(mp4, replace)
    task = task or Task(d, [path], **task_kw)
    task.cwd, task.edit_files = d, [os.path.basename(path)]   # only the new metadata file
    if scene: task.add_dirs = [os.path.dirname(os.path.abspath(scene))]
    prompt = (f'Job: write the YouTube text for the video "{os.path.basename(mp4)}".\n'
              + (f'Look at the contact sheet first (12 frames across the video): {os.path.basename(sheet)}\n' if sheet else '')
              + (f'Channel: {channel}\n' if channel else '') + (f'Owner notes: {notes}\n' if notes else '')
              + (f'The scene it was rendered from: {scene}\n' + scene_text(scene) + '\n' if scene else '')
              + f'\nWrite the file "{os.path.basename(path)}" in this folder with the Write tool.\n{META_FORMAT}\n'
              'Write the TITLE / DESCRIPTION / TAGS in the language the video itself uses. Then give a one-line summary.')
    progress('Claude is watching the video and writing the text...')
    try: res = task.ask(prompt)
    finally:
        if sheet:
            try: os.remove(sheet)
            except OSError: pass
    if not res['ok']: return dict(ok=False, path=None, text='', summary=res['text'], error=res['error'])
    if not os.path.isfile(path): return dict(ok=False, path=None, text='', summary=res['text'], error='Claude did not write the file')
    text = open(path, encoding='utf-8', errors='replace').read()
    try: m = youtube.parse_metadata(text)
    except Exception as e: m = None; err = f'the file does not parse: {e}'
    else: err = None if any(sec.get('title') for sec in (m or {}).values()) else 'the file has no TITLE'
    return dict(ok=err is None, path=path, text=text, summary=res['text'], error=err)


# ---------------------------------------------------------------- New video (AI)
STYLES = {   # name -> (what the picture should look like, a Claude skill folder in ~/.claude/skills to read when it is there)
    'Explainer (science, narrated)': ('a friendly cartoon / infographic explainer: bold shapes, labels, arrows, a clear step by step '
                                      'story that follows the narration, bright colours on a calm background', 'bright-questions-pipeline'),
    'Tech diagram (narrated)': ('an animated network / home-lab diagram: devices as icons in boxes, links that light up, data packets '
                                'flowing along the links as the narration mentions them', 'homelab-visual-episode'),
    'Music visual (no voice)': ('an abstract, beat-feeling visual: layered shapes, particles and light that pulse in time (keep it pure '
                                'of t), title card at the start, calm ending', 'moonshift-cover-video'),
    'Kids (simple, colourful)': ('a simple, warm cartoon for small children: big friendly shapes, slow clear motion, few words on screen, '
                                 'no scary or fast flashing parts', 'waddle-club-production'),
    'Free (describe it in the idea)': ('whatever the idea asks for', None),
}
LENGTHS = {'30 seconds': 30, '1 minute': 60, '2 minutes': 120, '3 minutes': 180}
WORDS_PER_S = 2.4                       # ~145 words a minute (Kokoro af_heart, measured on Home Lab episodes)
VOICE_NAME = 'af_heart'

def template_path():
    import sys
    for b in (getattr(sys, '_MEIPASS', None), os.path.dirname(os.path.abspath(__file__))):
        if b and os.path.isfile(os.path.join(b, 'assets', 'ai_template.html')): return os.path.join(b, 'assets', 'ai_template.html')
    return None

def skill_file(style):
    s = (STYLES.get(style) or ('', None))[1]
    if not s: return None
    p = os.path.join(os.path.expanduser('~'), '.claude', 'skills', s, 'SKILL.md')
    return p if os.path.isfile(p) else None

def slug(text, n=40):
    s = re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')[:n].strip('_')
    return s or time.strftime('video_%Y%m%d_%H%M')

def new_folder(root, name):
    p = os.path.join(root, name); k = 2
    while os.path.exists(p): p = os.path.join(root, f'{name}_{k}'); k += 1
    os.makedirs(p); return p

# ---- the voice: Kokoro (English) speaks the script AND gives each word's time (no whisper needed), in a Python that has it
def _py_has(py, mods):
    try:
        r = subprocess.run([py, '-c', 'import ' + ', '.join(mods)], capture_output=True, timeout=120, creationflags=NOWIN)
        return r.returncode == 0
    except Exception:
        return False

def find_voice_python(setting=None):
    r"""A python.exe with kokoro + soundfile: the setting, else Shadow's kit_captions\.venv, else this Python (source runs).
    None = no voice (the video gets music only). Takes a few seconds (it imports kokoro): call it off the UI thread."""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [setting, os.path.join(here, 'kit_captions', '.venv', 'Scripts', 'python.exe')]
    if not getattr(sys, 'frozen', False): cands.append(sys.executable)
    for py in cands:
        if py and os.path.isfile(py) and _py_has(py, ('kokoro', 'soundfile', 'numpy')): return py
    return None

# Kokoro's own token times (measured on a 30 s script: 76 words, the same words as the script); punctuation joins the word before
KOKORO = """import sys, json, numpy as np, soundfile as sf
from kokoro import KPipeline
p = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')
text = open(sys.argv[1], encoding='utf-8').read()
audio, words, off = [], [], 0.0
for r in p(text, voice=sys.argv[4]):
    a = r.audio.numpy(); audio.append(a)
    for tok in (r.tokens or []):
        if not any(ch.isalnum() for ch in tok.text):
            if words and tok.text.strip(): words[-1]['w'] += tok.text.strip()
            continue
        if tok.start_ts is None or tok.end_ts is None: continue
        words.append({'w': tok.text, 's': round(off + tok.start_ts, 3), 'e': round(off + tok.end_ts, 3)})
    off += len(a) / 24000
sf.write(sys.argv[2], np.concatenate(audio), 24000)
json.dump({'words': words, 'source': 'kokoro'}, open(sys.argv[3], 'w', encoding='utf-8'))
print(len(words), round(off, 2))
"""

def make_voice(py, script, wav, words, voice=VOICE_NAME, timeout=1800):
    """script.txt -> wav + words.json ({"words":[{"w","s","e"}]}) with Kokoro. Raises RuntimeError with the reason."""
    r = subprocess.run([py, '-c', KOKORO, script, wav, words, voice], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout, creationflags=NOWIN)
    if r.returncode or not os.path.isfile(wav) or not os.path.isfile(words):
        raise RuntimeError('the voice (Kokoro) failed: ' + ' / '.join((r.stderr or '').strip().splitlines()[-3:]))
    try: n = len(json.load(open(words, encoding='utf-8'))['words'])
    except Exception: n = 0
    if not n: raise RuntimeError('the voice has no word timings')

def wav_seconds(wav):
    import wave
    with wave.open(wav) as w: return w.getnframes() / float(w.getframerate())

def check_loop(task, path, prompt, check, rounds, progress, what='scene'):
    """Ask, then Shadow checks `path` itself; anything left goes back to Claude, up to `rounds`. -> dict(ok, rounds, summary,
    problems, sheet, error)."""
    out = dict(ok=False, rounds=0, summary='', problems=[], sheet=None, error=None)
    for r in range(1, max(1, rounds) + 1):
        progress(f'Round {r}: Claude is working on the {what}...')
        res = task.ask(prompt); out['rounds'] = r; out['summary'] = res['text']
        if not res['ok']: out['error'] = res['error']; break
        if task.stopped: out['error'] = 'stopped'; break
        progress(f'Round {r}: Seekframe checks it (scene check + frames)...')
        left, chk = scene_problems(path, check)
        out['problems'] = left; out['sheet'] = chk and chk.get('sheet')
        if not left: out['ok'] = True; break
        prompt = ('Seekframe checked "' + os.path.basename(path) + '" and found:\n' + '\n'.join(f'- {x}' for x in left) +
                  '\nFix these in that file, then give the short summary again.')
    return out

def new_video(idea, root, style='Free (describe it in the idea)', seconds=60, voice=True, task=None, check=None, voice_py=None,
              voice_maker=make_voice, rounds=3, progress=lambda s: None, **task_kw):
    """An idea -> a new folder <root>/<slug>/ with <slug>.html (+ <slug>.script.txt, <slug>.wav, <slug>.words.json when voiced:
    Shadow then attaches the narration and word captions by itself). Claude writes the script and the scene (only those
    files); Shadow makes the voice and checks the scene, sending problems back. Returns dict(ok, scene, folder, script, wav,
    words, duration, rounds, problems, sheet, summary, error). Never touches anything outside the new folder."""
    tpl = template_path()
    if not tpl: return dict(ok=False, error='assets/ai_template.html is missing', scene=None, folder=None)
    name = slug(idea); folder = new_folder(root, name); scene = os.path.join(folder, name + '.html')
    out = dict(ok=False, scene=scene, folder=folder, script=None, wav=None, words=None, duration=seconds, rounds=0, problems=[],
               sheet=None, summary='', error=None)
    task = task or Task(folder, [], **task_kw)
    look, _ = STYLES.get(style, STYLES['Free (describe it in the idea)'])
    sk = skill_file(style)
    if voice and voice_py:
        script = os.path.join(folder, name + '.script.txt'); out['script'] = script
        task.cwd, task.edit_files = folder, [os.path.basename(script)]
        n = int(seconds * WORDS_PER_S)
        progress('Claude is writing the narration...')
        res = task.ask(f'Job 1 of 2: write the NARRATION for a {seconds}-second video.\nIdea: {idea}\nStyle: {style} - {look}\n'
                       + (f'This channel\'s own guide (read it): {sk}\n' if sk else '') +
                       f'Write "{os.path.basename(script)}" in this folder: about {n} words of spoken English (the voice is English '
                       'even if the idea is in another language), plain sentences, no headings, no stage directions, no emojis, numbers '
                       'written as words. A strong first sentence (a question or surprise), one clear idea per sentence, a short ending.')
        if not res['ok'] or task.stopped or not os.path.isfile(script):
            out.update(error=res.get('error') or ('stopped' if task.stopped else 'Claude did not write the narration'), summary=res.get('text', ''))
            return out
        progress('Making the voice (Kokoro) and the word timings...')
        wav, words = os.path.join(folder, name + '.wav'), os.path.join(folder, name + '.words.json')
        try: voice_maker(voice_py, script, wav, words)
        except Exception as e:
            out['error'] = f'{e}'; return out
        out.update(wav=wav, words=words, duration=round(wav_seconds(wav) + 1.5, 1))
    shutil.copyfile(tpl, scene)
    task.cwd, task.edit_files = folder, [os.path.basename(scene)]
    voiced = bool(out['words'])
    prompt = (f'Job{" 2 of 2" if voiced else ""}: make the PICTURE - a Seekframe scene for this video.\nIdea: {idea}\nStyle: {style} - {look}\n'
              + (f'This channel\'s own guide (read it for the look): {sk}\n' if sk else '') +
              f'"{os.path.basename(scene)}" in this folder is a working template: rewrite it into the real video (Write or Edit). '
              f'window.DURATION = {out["duration"]}.\n'
              + (f'The narration is "{os.path.basename(out["script"])}" and its word times are in "{os.path.basename(out["words"])}" '
                 '({"words":[{"w","s","e"}]}, seconds): read them and time every visual change to the words that mention it '
                 '(put the times as constants in the scene). Seekframe adds the voice and big word captions at the bottom by itself: '
                 'do NOT play audio or draw subtitles yourself, keep the bottom 25% of the picture free, keep the 2D canvas '
                 '(captions only work on a 2D canvas) and turn the music bed down under the voice (k.voiceover).\n' if voiced else
                 'There is no voice: on-screen titles and labels tell the story; keep the music bed (STYLE_SOUND) and make it fit.\n') +
              f'{CONTRACT}\nAlso: it must look good in 16:9 AND 9:16 (PORTRAIT in the template): in 9:16 do not just shrink the 16:9 picture - stack the parts vertically and make text and drawings bigger so they fill the height above the caption area; text never cut off; every scene part '
              'visible long enough to read; no blank frames; three.js from a CDN is allowed (then a WebGL canvas#c) but only '
              'when there is no voice. Keep the template\'s seeded rand(), SOUND kit and the ?render=1 rule. When done, give a short summary.')
    out.update(check_loop(task, scene, prompt, check, rounds, progress, 'scene'))
    return out
