"""AI apps that can use Seekframe through its MCP server (3.32): find them, connect / disconnect Seekframe in each one's own
config file, and see which ones are using it right now.

Each client keeps its own config (paths from each client's docs, see docs/MCP.md). Connecting adds one entry named 'shadow'
(the server name every Seekframe tool and doc uses) and keeps everything else in the file; the first change of a file
keeps a copy next to it (`<file>.seekframe-backup`). A file that cannot be read as JSON / TOML is never rewritten.
Claude Code is changed through its own CLI (`claude mcp add/remove --scope user`): Claude Code rewrites ~/.claude.json
itself all the time. Nothing here starts or talks to an AI; it only edits config files and lists processes.
Tests pass `home` / `env` / `run` / `which` stand-ins and never touch the real files."""
import glob, json, os, re, shutil, subprocess, sys

SERVER = 'shadow'
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
HERE = os.path.dirname(os.path.abspath(__file__))


class Client:
    def __init__(self, key, name, kind='json', style='plain', exe_names=()):
        self.key, self.name, self.kind, self.style, self.exe_names = key, name, kind, style, exe_names


CLIENTS = [Client('claude_code', 'Claude Code', kind='claude_cli', exe_names=('claude.exe',)),
           Client('claude_desktop', 'Claude Desktop'),
           Client('cursor', 'Cursor', style='stdio', exe_names=('cursor.exe',)),
           Client('vscode', 'VS Code (Copilot)', style='copilot', exe_names=('code.exe',)),
           Client('windsurf', 'Windsurf / Devin', exe_names=('windsurf.exe', 'devin.exe')),
           Client('gemini', 'Gemini CLI'),
           # 3.35: the ChatGPT desktop app (winget OpenAI.ChatGPT = the Store package OpenAI.Codex, ChatGPT.exe + Codex.exe)
           # and Codex CLI share ~/.codex/config.toml, so one row covers both
           Client('codex', 'ChatGPT / Codex', kind='toml', exe_names=('codex.exe', 'chatgpt.exe')),
           # 3.35: xAI's Grok Build (the `grok` CLI): ~/.grok/config.toml, [mcp_servers.<name>] like Codex (docs.x.ai)
           Client('grok', 'Grok Build', kind='toml', exe_names=('grok.exe',))]
BY_KEY = {c.key: c for c in CLIENTS}
# 3.34: what to paste in a terminal to install a missing app (winget IDs checked with `winget show --exact`, 2026-11-22;
# Gemini CLI is not in winget: npm, which needs Node.js)
INSTALL = {'claude_code': 'winget install -e --id Anthropic.ClaudeCode', 'claude_desktop': 'winget install -e --id Anthropic.Claude',
           'cursor': 'winget install -e --id Anysphere.Cursor', 'vscode': 'winget install -e --id Microsoft.VisualStudioCode',
           'windsurf': 'winget install -e --id Codeium.Windsurf', 'gemini': 'npm install -g @google/gemini-cli',
           'codex': 'winget install -e --id OpenAI.ChatGPT', 'grok': 'winget install -e --id xAI.GrokBuild'}


def _dirs(env=None, home=None):
    env = os.environ if env is None else env
    home = home or env.get('USERPROFILE') or os.path.expanduser('~')
    return env, home, env.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming'), env.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')


def config_path(key, env=None, home=None):
    """The user-level config file of a client (it may not exist yet)."""
    env, home, roam, local = _dirs(env, home)
    if key == 'claude_code': return os.path.join(home, '.claude.json')
    if key == 'claude_desktop':   # the Microsoft Store build keeps its files in a virtual AppData folder
        for d in sorted(glob.glob(os.path.join(local, 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude'))):
            return os.path.join(d, 'claude_desktop_config.json')
        return os.path.join(roam, 'Claude', 'claude_desktop_config.json')
    if key == 'cursor': return os.path.join(home, '.cursor', 'mcp.json')
    if key == 'vscode': return os.path.join(home, '.copilot', 'mcp-config.json')
    if key == 'windsurf':
        old = os.path.join(home, '.codeium', 'windsurf', 'mcp_config.json')
        return old if os.path.isfile(old) and not os.path.isdir(os.path.join(roam, 'devin')) else os.path.join(roam, 'devin', 'mcp_config.json')
    if key == 'gemini': return os.path.join(home, '.gemini', 'settings.json')
    if key == 'codex': return os.path.join(home, '.codex', 'config.toml')
    if key == 'grok': return os.path.join(home, '.grok', 'config.toml')
    raise KeyError(key)


def installed(key, env=None, home=None, which=shutil.which):
    """Is the client on this PC (its program or its settings folder)?"""
    env, home, roam, local = _dirs(env, home)
    has = lambda *ps: any(os.path.exists(p) for p in ps)
    if key == 'claude_code':
        import assistant
        return bool(which('claude') or assistant.find_claude())
    if key == 'claude_desktop':
        return bool(glob.glob(os.path.join(local, 'Packages', 'Claude_*'))) or has(os.path.join(local, 'AnthropicClaude'), os.path.join(roam, 'Claude'))
    if key == 'cursor': return bool(which('cursor')) or has(os.path.join(local, 'Programs', 'cursor'), os.path.join(home, '.cursor'))
    if key == 'vscode': return bool(which('code')) or has(os.path.join(local, 'Programs', 'Microsoft VS Code'), os.path.join(home, '.copilot'))
    if key == 'windsurf': return has(os.path.join(local, 'Programs', 'Windsurf'), os.path.join(roam, 'devin'), os.path.join(home, '.codeium', 'windsurf'))
    if key == 'gemini': return bool(which('gemini')) or has(os.path.join(home, '.gemini'))
    if key == 'codex': return bool(which('codex')) or has(os.path.join(home, '.codex')) or bool(glob.glob(os.path.join(local, 'Packages', 'OpenAI.Codex_*')))
    if key == 'grok':   # 3.37: winget's own folder too (a Seekframe opened before the install still has the old PATH)
        return bool(which('grok')) or has(os.path.join(home, '.grok')) or bool(glob.glob(os.path.join(local, 'Microsoft', 'WinGet', 'Packages', 'xAI.GrokBuild_*', 'grok.exe')))
    return False


# ---------------------------------------------------------------- the command that starts Seekframe's MCP server
def server_command(home=None, frozen=None):
    """[program, args...] that starts tools/mcp_server.py, or None when this copy cannot run it (the installed exe has no
    server inside: then the entry the owner already set up for Claude Code is reused, see docs/MCP.md)."""
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if not frozen:
        py = sys.executable
        if os.path.basename(py).lower() == 'pythonw.exe': py = os.path.join(os.path.dirname(py), 'python.exe')   # the server talks on stdin/stdout
        return [py.replace('\\', '/'), os.path.join(HERE, 'tools', 'mcp_server.py').replace('\\', '/')]
    for key in ('claude_code', 'claude_desktop', 'gemini', 'cursor'):
        e = read_entry(key, home=home)
        if e and e.get('command'): return [e['command']] + list(e.get('args') or [])
    return None


def entry_for(key, cmd):
    """The 'shadow' entry in that client's own format."""
    e = {'command': cmd[0], 'args': list(cmd[1:])}
    style = BY_KEY[key].style
    if style in ('stdio', 'copilot'): e = {'type': 'stdio', **e}
    if style == 'copilot': e['tools'] = ['*']
    return e


# ---------------------------------------------------------------- read / write the config files
def _read_json(path):
    if not os.path.isfile(path): return {}
    with open(path, encoding='utf-8') as f: txt = f.read()
    return json.loads(txt) if txt.strip() else {}


def _backup(path):
    b = path + '.seekframe-backup'
    if os.path.isfile(path) and not os.path.exists(b): shutil.copy2(path, b)


TOML_HEAD = re.compile(r'^\[mcp_servers\.' + SERVER + r'\]\s*$', re.M)


def _toml_block(txt):
    """(start, end) of the [mcp_servers.shadow] table in a TOML text, or None."""
    m = TOML_HEAD.search(txt)
    if not m: return None
    nxt = re.compile(r'^\s*\[', re.M).search(txt, m.end())
    return m.start(), (nxt.start() if nxt else len(txt))


def read_entry(key, env=None, home=None):
    """The 'shadow' entry set up in that client now (dict), or None."""
    path = config_path(key, env, home)
    try:
        if BY_KEY[key].kind == 'toml':
            if not os.path.isfile(path): return None
            import tomllib
            with open(path, 'rb') as f: d = tomllib.load(f)
            return (d.get('mcp_servers') or {}).get(SERVER)
        return (_read_json(path).get('mcpServers') or {}).get(SERVER)
    except Exception:
        return None


def _toml_str(s):
    return json.dumps(str(s))   # a JSON string is a valid TOML basic string for paths and plain text


def connect(key, cmd, env=None, home=None, run=subprocess.run, claude=None):
    """Set Seekframe up in that client. Returns (ok, message). Never raises."""
    c = BY_KEY[key]
    try:
        if not cmd: return False, 'this copy of Seekframe cannot start its MCP server (see How to connect)'
        if c.kind == 'claude_cli':
            import assistant
            exe = claude or assistant.find_claude()
            if not exe: return False, 'Claude Code was not found'
            run(assistant.cmd(exe) + ['mcp', 'remove', SERVER, '--scope', 'user'], capture_output=True, text=True, timeout=60, creationflags=NOWIN)
            r = run(assistant.cmd(exe) + ['mcp', 'add', SERVER, '--scope', 'user', '--'] + list(cmd),
                    capture_output=True, text=True, timeout=60, creationflags=NOWIN)
            if r.returncode != 0: return False, (r.stderr or r.stdout or f'claude mcp add failed ({r.returncode})').strip()[-300:]
            return True, 'ok'
        path = config_path(key, env, home)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if c.kind == 'toml':
            import tomllib
            txt = open(path, encoding='utf-8').read() if os.path.isfile(path) else ''
            tomllib.loads(txt)   # an unreadable file is left alone (raises)
            blk = _toml_block(txt)
            if blk: txt = txt[:blk[0]] + txt[blk[1]:]
            add = f'[mcp_servers.{SERVER}]\ncommand = {_toml_str(cmd[0])}\nargs = [{", ".join(_toml_str(a) for a in cmd[1:])}]\n'
            new = txt.rstrip('\n') + ('\n\n' if txt.strip() else '') + add
            tomllib.loads(new)
            _backup(path)
            with open(path, 'w', encoding='utf-8', newline='\n') as f: f.write(new)
            return True, 'ok'
        d = _read_json(path)
        if not isinstance(d, dict): return False, f'{path} is not a settings object'
        d.setdefault('mcpServers', {})[SERVER] = entry_for(key, cmd)
        _backup(path)
        with open(path, 'w', encoding='utf-8') as f: json.dump(d, f, indent=2, ensure_ascii=False); f.write('\n')
        return True, 'ok'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def disconnect(key, env=None, home=None, run=subprocess.run, claude=None):
    """Remove Seekframe from that client (only the 'shadow' entry). Returns (ok, message)."""
    c = BY_KEY[key]
    try:
        if c.kind == 'claude_cli':
            import assistant
            exe = claude or assistant.find_claude()
            if not exe: return False, 'Claude Code was not found'
            r = run(assistant.cmd(exe) + ['mcp', 'remove', SERVER, '--scope', 'user'], capture_output=True, text=True, timeout=60, creationflags=NOWIN)
            return (r.returncode == 0 or read_entry(key, env, home) is None), (r.stderr or r.stdout or '').strip()[-300:] or 'ok'
        path = config_path(key, env, home)
        if not os.path.isfile(path): return True, 'ok'
        if c.kind == 'toml':
            import tomllib
            txt = open(path, encoding='utf-8').read(); tomllib.loads(txt)
            blk = _toml_block(txt)
            if not blk: return True, 'ok'
            new = (txt[:blk[0]].rstrip('\n') + '\n' + txt[blk[1]:].lstrip('\n')).lstrip('\n')
            tomllib.loads(new); _backup(path)
            with open(path, 'w', encoding='utf-8', newline='\n') as f: f.write(new)
            return True, 'ok'
        d = _read_json(path)
        if SERVER not in (d.get('mcpServers') or {}): return True, 'ok'
        _backup(path); del d['mcpServers'][SERVER]
        if not d['mcpServers']: del d['mcpServers']   # 3.34: leave no empty section behind
        with open(path, 'w', encoding='utf-8') as f: json.dump(d, f, indent=2, ensure_ascii=False); f.write('\n')
        return True, 'ok'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


# ---------------------------------------------------------------- who is using Seekframe right now
PS_PROCS = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,"
            "@{n='Cmd';e={ if ($_.Name -match '^(python|pythonw|node)') { $_.CommandLine } else { '' } }} | ConvertTo-Json -Compress")


def client_of(chain):
    """Which client started an MCP server process, from its ancestors (nearest first): dicts with Name / ExecutablePath / Cmd."""
    for p in chain:
        name = (p.get('Name') or '').lower(); path = (p.get('ExecutablePath') or '').lower(); cmd = (p.get('Cmd') or '').lower()
        if 'windowsapps\\claude_' in path or 'anthropicclaude' in path: return 'claude_desktop'
        if 'windowsapps\\openai.codex_' in path: return 'codex'   # the ChatGPT desktop app
        if name == 'node.exe' and 'gemini' in cmd: return 'gemini'
        if name == 'node.exe' and '@anthropic-ai' in cmd: return 'claude_code'
        for c in CLIENTS:
            if name in c.exe_names: return c.key
    return None


def in_use(procs=None, run=subprocess.run):
    """{client key or 'other': number of Seekframe MCP servers it runs now}. procs = the process list (tests)."""
    if procs is None:
        try:
            r = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PS_PROCS], capture_output=True, text=True,
                    timeout=30, creationflags=NOWIN)
            procs = json.loads(r.stdout or '[]')
            if isinstance(procs, dict): procs = [procs]
        except Exception:
            return {}
    by_id = {p.get('ProcessId'): p for p in procs}
    out = {}
    for p in procs:
        if not re.search(r'mcp_server\.py', p.get('Cmd') or '', re.I): continue
        chain, cur, seen = [], by_id.get(p.get('ParentProcessId')), set()
        while cur and cur.get('ProcessId') not in seen and len(chain) < 8:
            seen.add(cur.get('ProcessId')); chain.append(cur); cur = by_id.get(cur.get('ParentProcessId'))
        if chain and re.search(r'mcp_server\.py', chain[0].get('Cmd') or '', re.I): continue   # the venv launcher's child: count once
        k = client_of(chain) or 'other'
        out[k] = out.get(k, 0) + 1
    return out


def status(env=None, home=None, which=shutil.which, procs=None, run=subprocess.run):
    """[dict(key, name, installed, connected, using)] for every client."""
    use = in_use(procs, run=run)
    return [dict(key=c.key, name=c.name, installed=installed(c.key, env, home, which), connected=read_entry(c.key, env, home) is not None,
                 using=use.get(c.key, 0)) for c in CLIENTS] + ([dict(key='other', name='Other', installed=True, connected=True, using=use['other'])]
                                                               if use.get('other') else [])
