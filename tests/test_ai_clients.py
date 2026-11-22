"""3.32 AI connections (ai_clients.py) and Gemini CLI as the engine of the AI jobs (ai_tasks.GeminiTask).
Everything runs in a temp "home": no real config file, no real AI, no network.
  C1 which apps are on this PC (from their folders); config paths (Claude Desktop Store build in its virtual AppData)
  C2 connect / disconnect in JSON configs: only the 'shadow' entry changes, each client's own format, backup kept,
     an unreadable file is never rewritten
  C3 Codex (TOML): the [mcp_servers.shadow] table is added / removed, the rest of the file stays
  C4 Claude Code goes through `claude mcp add/remove --scope user` (never edits ~/.claude.json itself)
  C5 who uses Seekframe now: the app that started each MCP server, from the process tree
  C6 the server command: python.exe (never pythonw.exe) + tools/mcp_server.py
  G1 the Gemini policy: read files, edit only the named file, everything else refused
  G2 GeminiTask reads Gemini's stream-json (session, text, tools, refusals, errors); the Settings choice picks the engine
Usage: python tests/test_ai_clients.py     exit 0 = all PASS"""
import json, os, shutil, sys, tempfile, tomllib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import ai_clients as ac, ai_tasks as ai

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_clients_')
HOME = os.path.join(TMP, 'home'); ENV = {'USERPROFILE': HOME, 'APPDATA': os.path.join(HOME, 'AppData', 'Roaming'),
                                        'LOCALAPPDATA': os.path.join(HOME, 'AppData', 'Local')}
CMD = ['C:/Python/python.exe', 'C:/Seek frame/tools/mcp_server.py']
no_which = lambda n: None
try:
    # C1
    os.makedirs(os.path.join(ENV['LOCALAPPDATA'], 'Packages', 'Claude_abc', 'LocalCache', 'Roaming', 'Claude'))
    os.makedirs(os.path.join(HOME, '.gemini')); os.makedirs(os.path.join(HOME, '.codex'))
    inst = {c.key: ac.installed(c.key, ENV, which=no_which) for c in ac.CLIENTS if c.key != 'claude_code'}
    check('C1 found: Claude Desktop (Store), Gemini CLI, Codex; not: Cursor, VS Code, Windsurf',
          inst == dict(claude_desktop=True, cursor=False, vscode=False, windsurf=False, gemini=True, codex=True), inst)
    check('C1 Claude Desktop Store build: config in its virtual AppData', ac.config_path('claude_desktop', ENV).endswith(
          os.path.join('Claude_abc', 'LocalCache', 'Roaming', 'Claude', 'claude_desktop_config.json')))
    # C2 JSON
    g = ac.config_path('gemini', ENV)
    json.dump({'security': {'auth': 'oauth'}, 'mcpServers': {'other': {'command': 'x'}}}, open(g, 'w'))
    ok, msg = ac.connect('gemini', CMD, ENV)
    d = json.load(open(g))
    check('C2 Gemini: shadow added, other settings and servers kept', ok and d['security'] == {'auth': 'oauth'} and 'other' in d['mcpServers']
          and d['mcpServers']['shadow'] == {'command': CMD[0], 'args': CMD[1:]}, (ok, msg, d))
    check('C2 the first change keeps a backup of the old file', json.load(open(g + '.seekframe-backup')) == {'security': {'auth': 'oauth'}, 'mcpServers': {'other': {'command': 'x'}}})
    check('C2 read_entry sees it', ac.read_entry('gemini', ENV) == {'command': CMD[0], 'args': CMD[1:]})
    ok, msg = ac.connect('cursor', CMD, ENV)
    check('C2 Cursor: a new file with type stdio', ok and json.load(open(ac.config_path('cursor', ENV)))['mcpServers']['shadow']['type'] == 'stdio')
    ac.connect('vscode', CMD, ENV)
    check('C2 VS Code (Copilot): type stdio + tools *', json.load(open(ac.config_path('vscode', ENV)))['mcpServers']['shadow'].get('tools') == ['*'])
    ok, msg = ac.disconnect('gemini', ENV); d = json.load(open(g))
    check('C2 disconnect removes only shadow', ok and 'shadow' not in d['mcpServers'] and 'other' in d['mcpServers'] and d['security'], d)
    bad = ac.config_path('claude_desktop', ENV); open(bad, 'w').write('{ not json')
    ok, msg = ac.connect('claude_desktop', CMD, ENV)
    check('C2 an unreadable config is never rewritten', not ok and open(bad).read() == '{ not json' and msg, msg)
    check('C2 no command (installed exe without the source): refused with a reason', ac.connect('cursor', None, ENV)[0] is False)
    # C3 TOML
    t = ac.config_path('codex', ENV)
    open(t, 'w', encoding='utf-8').write('model = "x"\n\n[desktop]\nfoo = 1\n\n[plugins."a@b"]\nenabled = true\n')
    ok, msg = ac.connect('codex', CMD, ENV); d = tomllib.load(open(t, 'rb'))
    check('C3 Codex: [mcp_servers.shadow] added, the rest kept, valid TOML', ok and d['mcp_servers']['shadow'] == {'command': CMD[0], 'args': CMD[1:]}
          and d['desktop'] == {'foo': 1} and d['plugins']['a@b'] == {'enabled': True} and d['model'] == 'x', (ok, msg, d))
    ac.connect('codex', CMD, ENV)
    check('C3 connecting twice keeps one table', open(t, encoding='utf-8').read().count('[mcp_servers.shadow]') == 1)
    ok, msg = ac.disconnect('codex', ENV); d = tomllib.load(open(t, 'rb'))
    check('C3 disconnect removes the table only', ok and 'mcp_servers' not in d and d['desktop'] == {'foo': 1} and d['plugins']['a@b'], d)
    # C4 Claude Code through its CLI
    calls = []
    class R:
        def __init__(s, rc=0): s.returncode, s.stdout, s.stderr = rc, '', ''
    run = lambda a, **k: (calls.append(a), R())[1]
    ok, msg = ac.connect('claude_code', CMD, ENV, run=run, claude='C:/x/claude.exe')
    check('C4 Claude Code: claude mcp remove, then add --scope user -- <command>', ok and calls[0][1:3] == ['mcp', 'remove']
          and calls[-1][1:7] == ['mcp', 'add', 'shadow', '--scope', 'user', '--'] and calls[-1][7:] == CMD, calls)
    ok, msg = ac.disconnect('claude_code', ENV, run=run, claude='C:/x/claude.exe')
    check('C4 disconnect: claude mcp remove shadow --scope user', ok and calls[-1][1:] == ['mcp', 'remove', 'shadow', '--scope', 'user'], calls[-1])
    check('C4 ~/.claude.json itself was never written', not os.path.exists(os.path.join(HOME, '.claude.json')))
    # C5 process tree
    procs = [dict(ProcessId=1, ParentProcessId=0, Name='Claude.exe', ExecutablePath=r'C:\Program Files\WindowsApps\Claude_6.2_x64__pzs\app\Claude.exe', Cmd=''),
             dict(ProcessId=2, ParentProcessId=1, Name='python.exe', ExecutablePath=r'C:\venv\Scripts\python.exe', Cmd='python C:/s/tools/mcp_server.py'),
             dict(ProcessId=3, ParentProcessId=2, Name='python.exe', ExecutablePath=r'C:\Python\python.exe', Cmd='python C:/s/tools/mcp_server.py'),
             dict(ProcessId=10, ParentProcessId=0, Name='node.exe', ExecutablePath=r'C:\n\node.exe', Cmd='node C:/n/node_modules/@google/gemini-cli/bundle/gemini.js'),
             dict(ProcessId=11, ParentProcessId=10, Name='python.exe', ExecutablePath='', Cmd='python mcp_server.py'),
             dict(ProcessId=20, ParentProcessId=0, Name='claude.exe', ExecutablePath=r'C:\Users\u\.local\bin\claude.exe', Cmd=''),
             dict(ProcessId=21, ParentProcessId=20, Name='python.exe', ExecutablePath='', Cmd='python C:/s/tools/mcp_server.py'),
             dict(ProcessId=22, ParentProcessId=20, Name='python.exe', ExecutablePath='', Cmd='python C:/s/tools/mcp_server.py'),
             dict(ProcessId=30, ParentProcessId=0, Name='explorer.exe', ExecutablePath='', Cmd=''),
             dict(ProcessId=31, ParentProcessId=30, Name='python.exe', ExecutablePath='', Cmd='python C:/s/tools/mcp_server.py --http')]
    use = ac.in_use(procs)
    check('C5 Claude Desktop 1 (venv launcher counted once), Gemini 1, Claude Code 2, other 1', use == dict(claude_desktop=1, gemini=1, claude_code=2, other=1), use)
    st = ac.status(ENV, which=no_which, procs=procs)
    check('C5 status lists every app + the other one', [s['key'] for s in st][-1] == 'other' and len(st) == len(ac.CLIENTS) + 1)
    # C6
    real = sys.executable
    try:
        sys.executable = r'C:\Py\pythonw.exe'
        cmd = ac.server_command(frozen=False)
        check('C6 source run: python.exe (stdio needs a console Python) + this repo\'s mcp_server.py',
              cmd[0] == 'C:/Py/python.exe' and cmd[1].endswith('tools/mcp_server.py') and os.path.isfile(cmd[1]), cmd)
    finally:
        sys.executable = real
    # G1
    pol = tomllib.loads(ai.gemini_policy(['.shadow_fix_ab-1.html']))['rule']
    import re
    pat = re.compile(pol[0]['argsPattern'])
    check('G1 edit rule matches the file (relative or full path), not another file',
          pat.search('{"file_path":".shadow_fix_ab-1.html","content":"x"}') and pat.search('{"file_path":"C:\\\\a b\\\\.shadow_fix_ab-1.html"}')
          and not pat.search('{"file_path":"other.html"}') and pol[0]['decision'] == 'allow', pol[0])
    check('G1 no nested quantifiers (Gemini 0.68 refuses them) and "-" left as is (JavaScript regex)', '(?:' not in pol[0]['argsPattern'] and '\\-' not in pol[0]['argsPattern'])
    check('G1 reading allowed, everything else denied with an args pattern (so tools stay visible)',
          'read_file' in pol[1]['toolName'] and pol[2]['toolName'] == '*' and pol[2]['decision'] == 'deny' and pol[2]['argsPattern'] and pol[2]['priority'] < pol[1]['priority'] < pol[0]['priority'])
    # G2
    lines = [{'type': 'init', 'session_id': 'S1', 'model': 'auto'},
             {'type': 'message', 'role': 'user', 'content': 'prompt'},
             {'type': 'tool_use', 'tool_name': 'read_file', 'tool_id': 'a', 'parameters': {'file_path': 'scene.html'}},
             {'type': 'tool_result', 'tool_id': 'a', 'status': 'success', 'output': ''},
             {'type': 'tool_use', 'tool_name': 'write_file', 'tool_id': 'b', 'parameters': {'file_path': 'other.txt', 'content': 'x'}},
             {'type': 'tool_result', 'tool_id': 'b', 'status': 'error', 'error': {'type': 'policy_violation', 'message': 'denied'}},
             {'type': 'message', 'role': 'assistant', 'content': 'Fixed ', 'delta': True},
             {'type': 'message', 'role': 'assistant', 'content': 'the seek.', 'delta': True},
             {'type': 'result', 'status': 'success', 'stats': {}}]
    import io
    class P:
        def __init__(s, out, code=0, err=b''):
            s.stdout = io.BytesIO(b''.join(json.dumps(l).encode() + b'\n' for l in out)); s.stderr = io.BytesIO(err); s.stdin = io.BytesIO(); s.code = code
            s.stdin.close = lambda: None
        def wait(s): return s.code
    seen = {}
    def popen(args, **kw): seen['args'] = args; seen['kw'] = kw; p = P(lines); seen['p'] = p; return p
    evs = []
    t = ai.GeminiTask(TMP, [os.path.join(TMP, 'x.html')], exe=['node', 'gemini.js'], popen=popen, ready=lambda c: (True, 'ok'), on_event=lambda *e: evs.append(e))
    r = t.ask('fix it')
    check('G2 stream-json read: text, session, refusal', r['ok'] and r['text'] == 'Fixed the seek.' and r['session_id'] == 'S1' and r['denials'] == ['write_file: other.txt'], r)
    a = seen['args']
    check('G2 headless, policy file, no MCP servers, default approval (never yolo)', a[:3] == ['node', 'gemini.js', '-p'] and '--policy' in a
          and a[a.index('--allowed-mcp-server-names') + 1] == 'none' and a[a.index('--approval-mode') + 1] == 'default' and '--yolo' not in a, a)
    check('G2 the prompt goes in on stdin with the job rules', seen['p'].stdin.getvalue().decode().startswith('You work inside the Seekframe') and seen['p'].stdin.getvalue().decode().endswith('fix it'))
    check('G2 the policy file allows x.html', 'x\\\\.html' in open(a[a.index('--policy') + 1]).read())
    t.ask('again'); check('G2 the second round resumes the session', seen['args'][seen['args'].index('--resume') + 1] == 'S1')
    lines[:] = [{'type': 'init', 'session_id': 'S2'}, {'type': 'result', 'status': 'error', 'error': {'type': 'unknown', 'message': '[API Error: You have exhausted your daily quota on this model.]'}}]
    r = ai.GeminiTask(TMP, [], exe=['g'], popen=lambda a, **k: P(lines, code=1), ready=lambda c: (True, '')).ask('x')
    check('G2 an error (quota) comes back as the message', not r['ok'] and 'quota' in r['error'], r)
    r = ai.GeminiTask(TMP, [], exe=None, ready=ai.gemini_ready, find=lambda: ai.find_gemini(which=no_which)).ask('x')
    check('G2 Gemini not installed: a clear message', r and not r['ok'] and 'Gemini CLI was not found' in r['error'], r)
    try:
        ai.ENGINE = 'gemini'; check('G2 Settings = Gemini -> GeminiTask', isinstance(ai.Task(TMP, []), ai.GeminiTask))
        ai.ENGINE = 'claude'; check('G2 Settings = Claude -> ClaudeTask (default)', isinstance(ai.Task(TMP, []), ai.ClaudeTask))
    finally:
        ai.ENGINE = 'claude'
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAIL: " + ", ".join(fails)}')
sys.exit(1 if fails else 0)
