"""Shadow's Assistant panel engine: a chat with Claude through the installed Claude Code CLI (headless / print mode), so it
runs on the owner's Claude subscription - no API key, no paid API. No GUI here (app.py draws the panel); tests drive it with a
fake `claude` executable (tests/fixtures/fake_claude.py), so they never call Claude.

One `claude -p` process per conversation stays open between messages (`--input-format stream-json`): each message is one JSON
line on its stdin, the reply streams back as JSON lines (`--output-format stream-json --verbose --include-partial-messages`).
Keeping the process alive keeps Shadow's MCP server (its child) alive too, so a render the assistant started keeps running
between messages. Stop / New chat / closing Shadow kill that process tree (and with it a render the assistant started -
the GUI's own queue is a different process and is never touched). After a Stop the next message resumes the same
conversation (`--resume <session_id>`).

Permissions (verified with Claude Code 2.1.327, see docs/ASSISTANT.md):
  --permission-mode dontAsk         anything not pre-approved is denied, never waits for an answer nobody can give
  --tools Read,Glob,Grep            the only built-in tools: reading files. No Bash/PowerShell, no Edit/Write, no web.
  --strict-mcp-config --mcp-config  only Shadow's own MCP server, none of the owner's other servers or plugins' servers
  --allowedTools <SAFE_TOOLS>       the Shadow tools that create new files only (render never overwrites) or only read
  shadow_cancel (stops a render) and shadow_upload (publishes to YouTube) are NOT pre-approved: it is denied, the panel shows it and offers "Allow once", which
  re-runs that one turn with it allowed.
Reading works in the session folder and the Save-to folder (--add-dir); a Read elsewhere is denied and can be allowed once.
"""
import json, os, shutil, subprocess, sys, threading, time

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NL = '\n'
SERVER = 'shadow'
SAFE_TOOLS = [f'mcp__{SERVER}__shadow_{t}' for t in ('info', 'plan', 'render', 'progress', 'jobs', 'check_frames', 'qc', 'outputs',
                                                     'youtube', 'upload_preview', 'upload_progress', 'upload_cancel',
                                                     'video_look', 'video_song', 'video_song_progress')]   # video+song only makes new files
ASK_TOOLS = [f'mcp__{SERVER}__shadow_{t}' for t in ('cancel', 'upload')]   # denied unless the owner clicks "Allow once"
READ_TOOLS = ['Read', 'Glob', 'Grep']                # built-in tools that exist at all; reading outside the folders asks
ALLOWABLE = set(ASK_TOOLS) | set(READ_TOOLS)         # what "Allow once" may ever grant (nothing that runs code or edits)
# keys that would make Claude Code bill per use instead of using the subscription: never passed to it
PAID_ENV = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
SUBSCRIPTION_AUTH = ('claude.ai', 'oauth_token')     # `claude auth status` authMethod values that use the subscription

SYSTEM = """You are the assistant inside the Seekframe desktop app (its Assistant panel). Seekframe renders three.js HTML scenes and
Blender .blend scenes to MP4 (1080p, 30 fps, with sound; 16:9 and 9:16 Shorts) for the owner's YouTube channels.
Tools: the shadow_* MCP tools (render, plan, progress, check_frames, qc, outputs, info, jobs, cancel) and Read/Glob/Grep for
reading files. You cannot run commands, edit, move or delete files - say so if asked and tell the owner how to do it himself.
Typical flow: shadow_check_frames(scene) -> look at the sheet -> shadow_plan -> shadow_render -> shadow_progress(wait_seconds=55)
until the job ends -> shadow_qc / shadow_outputs. A render you start lives only while this chat runs: after shadow_render keep
calling shadow_progress(wait_seconds=55) until the job has finished, then report the result (outputs, QC, warnings) briefly.
Files are never overwritten (a new _2 file is made). shadow_cancel stops a render: ask the owner first; if it is blocked the
app shows him an "Allow once" button. YouTube: shadow_upload_preview(video) shows what would be uploaded - show it to the
owner; shadow_upload sends it and is blocked until he clicks "Allow once", then follow it with shadow_upload_progress. Each message starts with a [Seekframe app] block describing the app's queue and settings;
"this folder" / "these scenes" usually means those. Reply in the owner's language (Arabic, Iraqi dialect is fine), short
and direct, plain text (no tables)."""


def find_claude(env=None):
    """Path of the Claude Code CLI, or None. PATH first, then where the native installer / npm put it on Windows."""
    env = os.environ if env is None else env
    p = shutil.which('claude', path=env.get('PATH'))
    if p: return p
    home = env.get('USERPROFILE') or os.path.expanduser('~')
    for c in (os.path.join(home, '.local', 'bin', 'claude.exe'), os.path.join(env.get('APPDATA', ''), 'npm', 'claude.cmd'),
              os.path.join(env.get('LOCALAPPDATA', ''), 'Programs', 'claude', 'claude.exe')):
        if c and os.path.isfile(c): return c
    return None


# ---- 3.30: how the AI features sign in. 'subscription' (default): the user's Claude subscription through Claude Code; API keys
# and cloud switches are removed so nothing is billed per use. 'api_key' (a user's explicit choice in Settings): Claude Code
# runs with the user's own Anthropic API key (paid per use, by Anthropic) - kept encrypted by Windows (DPAPI) in KEY_FILE.
AUTH_MODE = 'subscription'
KEY_FILE = os.path.join(os.path.expanduser('~'), '.shadow_ai_key.bin')

def _dpapi(data, decrypt=False):
    """Windows DPAPI for the current user (only this Windows account on this PC can decrypt it)."""
    import ctypes, ctypes.wintypes as wt
    class BLOB(ctypes.Structure): _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data)); inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))); out = BLOB()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out)):   # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
        raise OSError('Windows could not ' + ('decrypt' if decrypt else 'encrypt') + ' the API key')
    try: return ctypes.string_at(out.pbData, out.cbData)
    finally: ctypes.windll.kernel32.LocalFree(out.pbData)

def valid_api_key(key):
    return isinstance(key, str) and key.strip().startswith('sk-ant-') and len(key.strip()) > 30 and ' ' not in key.strip()

def save_api_key(key, path=None):
    """Store the key encrypted (DPAPI). Raises ValueError for something that is not an Anthropic key."""
    key = (key or '').strip()
    if not valid_api_key(key): raise ValueError('That does not look like an Anthropic API key (it starts with sk-ant-).')
    with open(path or KEY_FILE, 'wb') as f: f.write(_dpapi(key.encode('utf-8')))

def load_api_key(path=None):
    try:
        with open(path or KEY_FILE, 'rb') as f: return _dpapi(f.read(), decrypt=True).decode('utf-8')
    except Exception:
        return None

def delete_api_key(path=None):
    try: os.remove(path or KEY_FILE); return True
    except OSError: return False

def key_hint(key):
    """sk-ant-...abcd: enough to recognise a key, never the key itself."""
    return f'{key[:7]}...{key[-4:]}' if key else ''

def clean_env(env=None, mode=None):
    """The environment for Claude Code. Subscription (default): without API keys / cloud-provider switches (they would bill
    per use). API-key mode: the same, plus the user's own stored key as ANTHROPIC_API_KEY."""
    e = dict(os.environ if env is None else env)
    for k in PAID_ENV: e.pop(k, None)
    if (mode or AUTH_MODE) == 'api_key':
        key = load_api_key()
        if key: e['ANTHROPIC_API_KEY'] = key
    return e


NOT_INSTALLED = ('Claude Code is not installed (the "claude" command was not found).\n'
                 'Install it (free with your Claude subscription), then press Send again:\n'
                 '  PowerShell:  irm https://claude.ai/install.ps1 | iex\n'
                 'Then run "claude" once in a terminal and sign in.')
NOT_SIGNED_IN = ('Claude Code is installed but not signed in.\nOpen a terminal, run:  claude auth login\n'
                 '(sign in with your Claude account - Pro/Max subscription), then press Send again.')


def cmd(exe):
    """exe may be a path or a command list (tests: [python, fake_claude.py])."""
    return list(exe) if isinstance(exe, (list, tuple)) else [exe]


def check_ready(exe, run=subprocess.run, env=None):
    """(ok, message). Uses `claude auth status --json` (exit 0 = signed in). Refuses API-key / cloud-provider sign-ins:
    the assistant must use the subscription, never a paid API."""
    if not exe: return False, NOT_INSTALLED
    if AUTH_MODE == 'api_key':   # the user chose their own API key in Settings (paid per use)
        key = load_api_key()
        if not key: return False, 'API key mode is on but no key is saved. Open Settings > AI account and add your key, or switch back to your subscription.'
        return True, f'Claude Code with your Anthropic API key {key_hint(key)} (paid per use)'
    try:
        r = run(cmd(exe) + ['auth', 'status', '--json'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=30, env=clean_env(env), creationflags=NOWIN)
    except FileNotFoundError:
        return False, NOT_INSTALLED
    except Exception as e:
        return False, f'Could not ask Claude Code whether it is signed in: {e}'
    try: st = json.loads(r.stdout or '{}')
    except ValueError: st = {}
    if not st.get('loggedIn'):
        return False, NOT_SIGNED_IN
    m = st.get('authMethod', '')
    if m and m not in SUBSCRIPTION_AUTH:
        return False, (f'Claude Code is signed in with "{m}" (paid per use), not your Claude subscription.\n'
                       'Seekframe only uses the subscription. In a terminal run:  claude auth login  and pick your Claude account.')
    plan = st.get('subscriptionType') or st.get('planTier') or ''
    return True, f'Claude Code ready ({m or "signed in"}{", " + plan if plan else ""})'


def server_entry(frozen=None, repo=None, claude_json=None, python=None):
    """The stdio entry for Shadow's MCP server, or None. From source: this Python + this repo's tools/mcp_server.py.
    In the installed exe (the server does not run inside the exe): the owner's own user-scope `shadow` server from
    ~/.claude.json (`claude mcp add shadow --scope user ...`, docs/MCP.md)."""
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    repo = repo or os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(repo, 'tools', 'mcp_server.py')
    if not frozen and os.path.isfile(script):
        py = python or sys.executable
        if os.path.basename(py).lower() == 'pythonw.exe':   # run.bat may start the GUI with pythonw; the server needs stdio
            py = os.path.join(os.path.dirname(py), 'python.exe')
        return {'type': 'stdio', 'command': py, 'args': [script]}
    try:
        with open(claude_json or os.path.join(os.path.expanduser('~'), '.claude.json'), encoding='utf-8') as f:
            e = (json.load(f).get('mcpServers') or {}).get(SERVER)
    except Exception:
        e = None
    if e and e.get('command'):
        return {'type': 'stdio', 'command': e['command'], 'args': list(e.get('args') or []), **({'env': e['env']} if e.get('env') else {})}
    return None


NO_SERVER = ("Seekframe's MCP server is not set up, so the assistant cannot use Seekframe. It needs a copy of Seekframe's source; then run:\n"
             '  claude mcp add shadow --scope user -- python C:\\path\\to\\shadow\\tools\\mcp_server.py\n'
             'Details: docs/MCP.md.')


def write_mcp_config(entry, folder):
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, 'assistant_mcp.json')
    with open(p, 'w', encoding='utf-8') as f: json.dump({'mcpServers': {SERVER: entry}}, f, indent=1)
    return p


def build_args(exe, mcp_config, session_id=None, add_dirs=(), extra_allowed=(), model=None):
    """The exact command line (documented in docs/ASSISTANT.md). The prompt goes to stdin, never on the command line."""
    a = cmd(exe) + ['-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
         '--permission-mode', 'dontAsk', '--tools', ','.join(READ_TOOLS),
         '--strict-mcp-config', '--mcp-config', mcp_config,
         '--allowedTools', ','.join(SAFE_TOOLS + [t for t in extra_allowed if t in ALLOWABLE]),
         '--append-system-prompt', SYSTEM]
    for d in add_dirs:
        if d and os.path.isdir(d): a += ['--add-dir', d]
    if model: a += ['--model', model]
    if session_id: a += ['--resume', session_id]
    return a


def user_line(text):
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text}}, ensure_ascii=False) + '\n'


def short_tool(name):
    return name.split('__')[-1] if name.startswith('mcp__') else name


def tool_summary(name, inp):
    """'shadow_render(paths=[a.html], quality=best)' - one short line for the chat."""
    def v(x):
        if isinstance(x, list): return '[' + ', '.join(v(i) for i in x[:3]) + (', ...' if len(x) > 3 else '') + ']'
        if isinstance(x, str):
            if '\\' in x or '/' in x: x = os.path.basename(x.rstrip('\\/')) or x   # paths: the file name is enough
            return x if len(x) <= 40 else x[:37] + '...'
        return json.dumps(x)
    args = ', '.join(f'{k}={v(x)}' for k, x in (inp or {}).items())
    s = f'{short_tool(name)}({args})'
    return s if len(s) <= 140 else s[:137] + '...'


def parse_event(d, seen_text=None):
    """One stream-json object -> list of ('session', id) | ('text', s) | ('tool', name, input) | ('denied', name, input)
    | ('limit', info) | ('result', dict). seen_text: set of message ids whose text already arrived as deltas."""
    seen_text = set() if seen_text is None else seen_text
    t = d.get('type'); out = []
    if t == 'system' and d.get('subtype') == 'init':
        out.append(('session', d.get('session_id')))
        bad = [s.get('name') for s in d.get('mcp_servers') or [] if s.get('status') not in ('connected', None)]
        if bad: out.append(('warn', 'Seekframe MCP server not connected (' + ', '.join(map(str, bad)) + '): the shadow tools are missing.'))
    elif t == 'stream_event':
        e = d.get('event') or {}
        if e.get('type') == 'message_start':
            d['_mid'] = (e.get('message') or {}).get('id')
        if e.get('type') == 'content_block_delta' and (e.get('delta') or {}).get('type') == 'text_delta' and d.get('parent_tool_use_id') is None:
            out.append(('text', e['delta'].get('text', '')))
    elif t == 'assistant':
        m = d.get('message') or {}
        for b in m.get('content') or []:
            if b.get('type') == 'tool_use':
                out.append(('tool', b.get('name', ''), b.get('input') or {}))
            elif b.get('type') == 'text' and m.get('id') not in seen_text and d.get('parent_tool_use_id') is None:
                out.append(('text', b.get('text', '')))   # no partial deltas came for this message (older CLI): use the whole text
    elif t == 'system' and d.get('subtype') == 'permission_denied':
        out.append(('denied', d.get('tool_name', ''), d.get('tool_input') or {}))
    elif t == 'rate_limit_event':
        info = d.get('rate_limit_info') or {}
        if info.get('status') not in (None, 'allowed'): out.append(('limit', info))
    elif t == 'result':
        out.append(('result', d))
    return out


def limit_text(info):
    when = info.get('resetsAt')
    at = time.strftime('%H:%M', time.localtime(when)) if isinstance(when, (int, float)) else '?'
    return (f'Claude usage limit: {info.get("status")} ({info.get("rateLimitType", "")}), resets at {at}.')


def kill_tree(proc):
    """Stop the claude process and its children (Shadow's MCP server, its Chrome). Windows: taskkill /T."""
    if proc is None or proc.poll() is not None: return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, timeout=15, creationflags=NOWIN)
        else:
            proc.kill()
    except Exception:
        pass
    try: proc.kill()
    except Exception: pass
    try: proc.wait(5)
    except Exception: pass


class Chat:
    """One conversation. on_event(kind, *data) is called from a reader thread (the GUI forwards it to its queue):
    ('status', text) ('text', s) ('tool', summary) ('denied', tool, summary, allowable) ('turn_end', result dict)
    ('error', text) ('exit', returncode, stderr_tail, expected)."""

    def __init__(self, on_event, cwd, add_dirs=(), exe=None, entry=None, cfg_dir=None, popen=subprocess.Popen,
                 ready=check_ready, model=None):
        self.on_event = on_event; self.cwd = cwd; self.add_dirs = list(add_dirs); self.model = model
        self.exe = exe; self.entry = entry; self.popen = popen; self.ready = ready
        self.cfg_dir = cfg_dir or os.path.join(os.path.expanduser('~'), '.shadow_assistant')
        self.proc = None; self.session_id = None; self.busy = False; self.lock = threading.Lock()
        self.ready_ok = False; self.launched_extra = (); self.pending_allow = set(); self.denied = []
        self.args = None

    def alive(self): return self.proc is not None and self.proc.poll() is None

    def _kill(self, p):
        # marked on the process object itself: an id() of a finished Popen can be reused by the next one, which then hid a
        # real crash as "expected" (seen in tests/test_assistant.py A7, 2 of 3 runs)
        if p is not None: p.shadow_expected_exit = True
        kill_tree(p)

    def _launch(self, extra=()):
        if not self.ready_ok:
            self.exe = self.exe or find_claude()
            ok, msg = self.ready(self.exe)
            if not ok: raise RuntimeError(msg)
            self.ready_ok = True
        entry = self.entry or server_entry()
        if not entry: raise RuntimeError(NO_SERVER)
        cfg = write_mcp_config(entry, self.cfg_dir)
        self.args = build_args(self.exe, cfg, self.session_id, [self.cwd] + self.add_dirs, extra, self.model)
        os.makedirs(self.cwd, exist_ok=True)
        p = self.proc = self.popen(self.args, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=clean_env(), creationflags=NOWIN)
        self.launched_extra = tuple(extra); p_err = []
        threading.Thread(target=self._read, args=(p, p_err, tuple(extra)), daemon=True).start()
        threading.Thread(target=self._drain, args=(p, p_err), daemon=True).start()

    def send(self, text):
        """Send one message (from the GUI thread; returns at once). Errors arrive as ('error', ...) events."""
        with self.lock:
            if self.busy: return False
            self.busy = True; self.denied = []
        extra = tuple(sorted(self.pending_allow)); self.pending_allow = set()
        try:
            if self.alive() and set(extra) != set(self.launched_extra):
                self._kill(self.proc)   # other permissions need a new process (same conversation via --resume)
            if not self.alive():
                self.on_event('status', 'Starting Claude Code...')
                self._launch(extra)
            self.proc.stdin.write(user_line(text).encode('utf-8')); self.proc.stdin.flush()
            self.on_event('status', 'Claude is thinking...')
            return True
        except Exception as e:
            with self.lock: self.busy = False
            self.on_event('error', str(e)); return False

    def allow_once(self, tool):
        """Pre-approve tool for the next message only (the panel then sends 'allowed, go on')."""
        if tool in ALLOWABLE: self.pending_allow.add(tool); return True
        return False

    def stop(self):
        """Stop button: kill the process tree (an assistant render stops too). The conversation is kept (--resume next time)."""
        self._kill(self.proc)
        with self.lock: self.busy = False

    def new_chat(self):
        self.stop(); self.session_id = None; self.pending_allow = set()

    def close(self): self.stop()

    def _drain(self, p, err):
        for line in iter(p.stderr.readline, b''):
            err.append(line.decode('utf-8', 'replace').rstrip()); del err[:-40]

    def _read(self, p, err, extra):
        seen = set(); mid = None
        for raw in iter(p.stdout.readline, b''):
            try: d = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError: continue
            evs = parse_event(d, seen)
            if d.get('_mid'): mid = d['_mid']
            for ev in evs:
                k = ev[0]
                if k == 'session':
                    if ev[1]: self.session_id = ev[1]
                elif k == 'text':
                    if d.get('type') == 'stream_event' and mid: seen.add(mid)
                    self.on_event('text', ev[1])
                elif k == 'tool':
                    self.on_event('status', f'Working: {short_tool(ev[1])}'); self.on_event('tool', tool_summary(ev[1], ev[2]))
                elif k == 'denied':
                    self.denied.append(ev[1]); self.on_event('denied', ev[1], tool_summary(ev[1], ev[2]), ev[1] in ALLOWABLE)
                elif k == 'warn':
                    self.on_event('error', ev[1])
                elif k == 'limit':
                    self.on_event('status', limit_text(ev[1]))
                elif k == 'result':
                    r = ev[1]
                    if r.get('session_id'): self.session_id = r['session_id']
                    if p is self.proc:
                        with self.lock: self.busy = False
                    if r.get('is_error'):
                        self.on_event('error', NL.join(map(str, r.get('errors') or [])) or str(r.get('result') or r.get('subtype')))
                    self.on_event('turn_end', r)
                    if extra and p is self.proc:   # "Allow once" was for that one turn: drop the permission again
                        self._kill(p)
        code = p.wait()
        expected = bool(getattr(p, 'shadow_expected_exit', False))
        was_busy = False
        if p is self.proc:
            with self.lock: was_busy = self.busy; self.busy = False
        tail = NL.join(err[-8:])
        self.on_event('exit', code, tail, expected)
        if was_busy and not expected:
            self.on_event('error', 'Claude Code stopped unexpectedly' + (f' (exit {code}):' + NL + tail if tail else f' (exit {code}).'))
