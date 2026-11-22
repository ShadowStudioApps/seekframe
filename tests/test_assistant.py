"""Assistant panel (assistant.py + the panel in app.py). Never calls Claude: a fake CLI (tests/fixtures/fake_claude.py) speaks
the stream-json lines the real Claude Code printed. Fixtures only (copied into a temp folder), the App runs hidden, every
dialog is replaced, config/logs go to the temp folder.
Usage: python tests/test_assistant.py      exit 0 = every check PASS, 1 = any FAIL
  A1 build_args: permissions (dontAsk, read-only built-ins, strict MCP, safe Shadow tools only; cancel not pre-approved)
  A2 parse_event on real event shapes   A3 check_ready: not installed / not signed in / API key refused / ok
  A4 clean_env drops paid API keys      A5 server_entry: source, exe (~/.claude.json), none   A6 tool_summary
  A7 Chat: one process for several messages, Stop + resume, denied -> Allow once (one turn only), crash, usage limit
  A8 GUI: panel toggle, Enter sends, streamed reply, auto folder, context block, Allow once bar, Stop, not signed in, close"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import assistant as A

FIXT = os.path.join(ROOT, 'tests', 'fixtures')
FAKE = [sys.executable, os.path.join(FIXT, 'fake_claude.py')]
TMP = tempfile.mkdtemp(prefix='shadow_assistant_')
LOGF = os.path.join(TMP, 'fake_argv.jsonl'); os.environ['FAKE_LOG'] = LOGF
ENTRY = {'type': 'stdio', 'command': 'python', 'args': ['mcp_server.py']}   # the fake CLI never starts it
res = []
def check(name, ok, info=''):
    res.append(bool(ok)); print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  ({str(info)[:400]})'))
def calls():
    try: return [json.loads(l) for l in open(LOGF, encoding='utf-8')]
    except FileNotFoundError: return []
def opt(argv, k): return argv[argv.index(k) + 1] if k in argv else None

def a1():
    d = os.path.join(TMP, 'a1'); os.makedirs(d)
    a = A.build_args('claude', 'cfg.json', None, [d, os.path.join(TMP, 'missing')], ['Bash', 'mcp__shadow__shadow_cancel', 'Write'])
    check('A1 print mode + stream-json in/out + partial messages', a[:2] == ['claude', '-p'] and opt(a, '--input-format') == 'stream-json'
          and opt(a, '--output-format') == 'stream-json' and '--verbose' in a and '--include-partial-messages' in a, a)
    check('A1 permission mode dontAsk', opt(a, '--permission-mode') == 'dontAsk')
    check('A1 built-in tools: Read,Glob,Grep only', opt(a, '--tools') == 'Read,Glob,Grep')
    check('A1 only Shadow MCP server (strict)', '--strict-mcp-config' in a and opt(a, '--mcp-config') == 'cfg.json')
    al = opt(a, '--allowedTools').split(',')
    check('A1 allowed: 8 safe shadow tools + allowed-once cancel, never Bash/Write',
          set(A.SAFE_TOOLS) <= set(al) and 'mcp__shadow__shadow_cancel' in al and 'Bash' not in al and 'Write' not in al, al)
    b = A.build_args('claude', 'cfg.json', 'sid-1')
    check('A1 cancel NOT pre-approved by default', 'mcp__shadow__shadow_cancel' not in opt(b, '--allowedTools'))
    check('A1 --resume <session> continues the conversation', opt(b, '--resume') == 'sid-1')
    check('A1 --add-dir only existing folders', a.count('--add-dir') == 1 and opt(a, '--add-dir') == d, a)
    check('A1 no prompt / API key on the command line', not any('ANTHROPIC' in x for x in a) and '--bare' not in a)
    check('A1 command list exe (tests)', A.build_args(['py', 'f.py'], 'c')[:3] == ['py', 'f.py', '-p'])

def a2():
    seen = set()
    ev = A.parse_event({'type': 'system', 'subtype': 'init', 'session_id': 's1', 'mcp_servers': [{'name': 'shadow', 'status': 'connected'}]}, seen)
    check('A2 init -> session id', ev == [('session', 's1')], ev)
    ev = A.parse_event({'type': 'system', 'subtype': 'init', 'session_id': 's1', 'mcp_servers': [{'name': 'shadow', 'status': 'failed'}]}, seen)
    check('A2 init with failed shadow server -> warning', any(e[0] == 'warn' for e in ev), ev)
    ev = A.parse_event({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Hi'}}, 'parent_tool_use_id': None}, seen)
    check('A2 text_delta -> text', ev == [('text', 'Hi')], ev)
    ev = A.parse_event({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'input_json_delta', 'partial_json': '{'}}}, seen)
    check('A2 input_json_delta ignored', ev == [], ev)
    ev = A.parse_event({'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'tool_use', 'name': 'mcp__shadow__shadow_info', 'input': {}}]}}, seen)
    check('A2 assistant tool_use -> tool', ev == [('tool', 'mcp__shadow__shadow_info', {})], ev)
    seen.add('m2')
    ev = A.parse_event({'type': 'assistant', 'message': {'id': 'm2', 'content': [{'type': 'text', 'text': 'dup'}]}, 'parent_tool_use_id': None}, seen)
    check('A2 full text not repeated after its deltas', ev == [], ev)
    ev = A.parse_event({'type': 'assistant', 'message': {'id': 'm3', 'content': [{'type': 'text', 'text': 'whole'}]}, 'parent_tool_use_id': None}, seen)
    check('A2 full text used when no deltas came', ev == [('text', 'whole')], ev)
    ev = A.parse_event({'type': 'system', 'subtype': 'permission_denied', 'tool_name': 'mcp__shadow__shadow_cancel', 'tool_input': {'job_id': 'x'}}, seen)
    check('A2 permission_denied -> denied', ev == [('denied', 'mcp__shadow__shadow_cancel', {'job_id': 'x'})], ev)
    check('A2 rate limit allowed -> nothing', A.parse_event({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed'}}) == [])
    ev = A.parse_event({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'resetsAt': 0}})
    check('A2 rate limit rejected -> limit + text', ev[0][0] == 'limit' and 'resets at' in A.limit_text(ev[0][1]), ev)
    ev = A.parse_event({'type': 'result', 'is_error': False, 'session_id': 's1'})
    check('A2 result', ev[0][0] == 'result')

def a3():
    check('A3 no exe -> not installed', A.check_ready(None) == (False, A.NOT_INSTALLED))
    check('A3 missing file -> not installed', A.check_ready(os.path.join(TMP, 'nope', 'claude.exe'))[1] == A.NOT_INSTALLED)
    for mode, want in (('none', False), ('api_key', False), ('ok', True)):
        os.environ['FAKE_AUTH'] = mode
        ok, msg = A.check_ready(FAKE)
        check(f'A3 auth {mode} -> {"ready" if want else "refused"}', ok == want and (mode != 'none' or msg == A.NOT_SIGNED_IN)
              and (mode != 'api_key' or 'paid per use' in msg), msg)
    os.environ['FAKE_AUTH'] = 'ok'
    def boom(*a, **k): raise subprocess.TimeoutExpired('claude', 30)
    ok, msg = A.check_ready('claude', run=boom)
    check('A3 hanging CLI -> clear message, no exception', not ok and 'Could not ask' in msg, msg)

def a4():
    e = A.clean_env({'ANTHROPIC_API_KEY': 'sk', 'CLAUDE_CODE_USE_BEDROCK': '1', 'PATH': 'p'})
    check('A4 paid keys removed, rest kept', e == {'PATH': 'p'}, e)

def a5():
    e = A.server_entry(frozen=False, repo=ROOT, python=r'C:\Py\pythonw.exe')
    check('A5 source: this repo\'s server, python (not pythonw)', e['args'] == [os.path.join(ROOT, 'tools', 'mcp_server.py')]
          and e['command'] == r'C:\Py\python.exe', e)
    cj = os.path.join(TMP, 'claude.json')
    json.dump({'mcpServers': {'shadow': {'type': 'stdio', 'command': 'python', 'args': ['C:/S/tools/mcp_server.py'], 'env': {}}}}, open(cj, 'w'))
    e = A.server_entry(frozen=True, claude_json=cj)
    check('A5 exe: the owner\'s user-scope shadow server', e == {'type': 'stdio', 'command': 'python', 'args': ['C:/S/tools/mcp_server.py']}, e)
    check('A5 exe without it -> None (clear message)', A.server_entry(frozen=True, claude_json=os.path.join(TMP, 'none.json')) is None)
    p = A.write_mcp_config(e, os.path.join(TMP, 'cfg'))
    check('A5 mcp config file', json.load(open(p))['mcpServers']['shadow'] == e)

def a6():
    s = A.tool_summary('mcp__shadow__shadow_render', {'paths': [r'C:\a b\x.html', 'y.html'], 'quality': 'best'})
    check('A6 tool summary short', s == 'shadow_render(paths=[x.html, y.html], quality=best)', s)
    check('A6 long summary cut', len(A.tool_summary('Read', {'file_path': 'x' * 400})) <= 140)

class Rec:
    def __init__(self): self.ev = []; self.cv = threading.Condition()
    def __call__(self, *e):
        with self.cv: self.ev.append(e); self.cv.notify_all()
    def wait(self, kind, n=1, t=30):
        end = time.time() + t
        with self.cv:
            while sum(1 for e in self.ev if e[0] == kind) < n and time.time() < end: self.cv.wait(0.2)
        return sum(1 for e in self.ev if e[0] == kind) >= n
    def text(self): return ''.join(e[1] for e in self.ev if e[0] == 'text')
    def kinds(self, k): return [e for e in self.ev if e[0] == k]

def a7():
    d = os.path.join(TMP, 'chat'); os.makedirs(d)
    r = Rec(); c = A.Chat(r, d, exe=FAKE, entry=ENTRY, cfg_dir=os.path.join(TMP, 'cfg7'))
    os.environ['ANTHROPIC_API_KEY'] = 'sk-test'   # must never reach the CLI
    n0 = len(calls())
    c.send('hello'); ok = r.wait('turn_end', 1)
    check('A7 first reply streamed', ok and r.text() == 'Echo 1: hello', r.ev)
    pid = c.proc.pid
    c.send('again'); r.wait('turn_end', 2)
    check('A7 second message: same process, same conversation', c.proc.pid == pid and r.text().endswith('Echo 2: again') and len(calls()) == n0 + 1, r.text())
    check('A7 API key not passed to the CLI', calls()[-1]['api_key'] is False)
    check('A7 session id kept', bool(c.session_id))
    check('A7 cwd = the chat folder', os.path.normcase(calls()[-1]['cwd']) == os.path.normcase(d))
    del os.environ['ANTHROPIC_API_KEY']
    sid = c.session_id
    c.send('SLOW please'); r.wait('text', 6)
    check('A7 busy while a turn runs (second send refused)', c.busy and c.send('x') is False)
    c.stop(); r.wait('exit', 1)
    check('A7 Stop: process gone, no error shown', not c.alive() and not c.busy and not r.kinds('error'), r.kinds('error'))
    r.ev.clear()
    c.send('after stop'); r.wait('turn_end', 1)
    last = calls()[-1]['argv']
    check('A7 after Stop: new process resumes the conversation', opt(last, '--resume') == sid and r.text() == 'Echo 1: after stop', (last, r.text()))
    r.ev.clear()
    c.send('please CANCEL'); r.wait('turn_end', 1)
    dn = r.kinds('denied')
    check('A7 cancel denied, offered to allow once', dn and dn[0][1] == 'mcp__shadow__shadow_cancel' and dn[0][3] is True and 'blocked' in r.text(), r.ev)
    check('A7 allow_once refuses Bash', c.allow_once('Bash') is False)
    check('A7 allow_once cancel', c.allow_once('mcp__shadow__shadow_cancel'))
    r.ev.clear(); n1 = len(calls())
    c.send('ok go CANCEL'); r.wait('turn_end', 1)
    last = calls()[-1]['argv']
    check('A7 allowed turn: new process with cancel allowed, same conversation', len(calls()) == n1 + 1
          and 'mcp__shadow__shadow_cancel' in opt(last, '--allowedTools') and opt(last, '--resume') == sid and 'Cancelled j1' in r.text(), (last, r.text()))
    end = time.time() + 15
    while c.alive() and time.time() < end: time.sleep(0.1)
    check('A7 "once": that process is ended after the turn', not c.alive())
    r.ev.clear()
    c.send('next'); r.wait('turn_end', 1)
    check('A7 next turn: cancel no longer allowed', 'mcp__shadow__shadow_cancel' not in opt(calls()[-1]['argv'], '--allowedTools'))
    r.ev.clear()
    c.send('LIMIT'); r.wait('turn_end', 1)
    check('A7 usage limit shown', any('usage limit' in e[1] for e in r.kinds('status')), r.kinds('status'))
    r.ev.clear()
    c.send('CRASH'); r.wait('error', 1)
    er = r.kinds('error')
    check('A7 crash -> clear error with stderr', er and 'stopped unexpectedly' in er[0][1] and 'fake crash' in er[0][1] and not c.busy, er)
    c.new_chat()
    check('A7 New chat forgets the session', c.session_id is None)
    c.close()
    r2 = Rec(); os.environ['FAKE_AUTH'] = 'none'
    c2 = A.Chat(r2, d, exe=FAKE, entry=ENTRY, cfg_dir=os.path.join(TMP, 'cfg7'))
    n2 = len(calls()); c2.send('hi'); r2.wait('error', 1)
    check('A7 not signed in -> message, CLI chat not started', r2.kinds('error') and r2.kinds('error')[0][1] == A.NOT_SIGNED_IN and len(calls()) == n2 and not c2.busy, r2.ev)
    os.environ['FAKE_AUTH'] = 'ok'
    r3 = Rec(); c3 = A.Chat(r3, d, exe=FAKE, entry=None, cfg_dir=os.path.join(TMP, 'cfg7'))
    import unittest.mock as um
    with um.patch.object(A, 'server_entry', lambda: None):
        c3.send('hi'); r3.wait('error', 1)
    check('A7 no MCP server -> setup message', r3.kinds('error') and 'MCP server is not set up' in r3.kinds('error')[0][1], r3.ev)

def a8():
    os.environ['SHADOW_LANG'] = 'en'   # 3.20: the tests read the English texts
    import app
    app.notify = lambda *a, **k: None   # 3.32: never a real Windows notification from a test
    app.CFG = os.path.join(TMP, 'cfg.json'); app.LOG = os.path.join(TMP, 'shadow.log'); app.LOG_DIR = os.path.join(TMP, 'logs')
    for h in list(app.log.handlers): app.log.removeHandler(h)
    boxes = []
    for n in ('showwarning', 'showerror', 'showinfo', 'askyesno', 'askyesnocancel', 'askokcancel'):
        setattr(app.messagebox, n, (lambda n: lambda *x, **k: boxes.append((n, x)) or False)(n))
    sd = os.path.join(TMP, 'scenes x'); os.makedirs(sd); scene = os.path.join(sd, 'webgl_min.html')
    shutil.copy(os.path.join(FIXT, 'webgl_min.html'), scene)
    picked = os.path.join(TMP, 'picked'); os.makedirs(picked)
    app.filedialog.askdirectory = lambda **k: picked
    app.filedialog.askopenfilename = lambda **k: ''; app.filedialog.askopenfilenames = lambda **k: ()
    a = app.App(); a.withdraw(); a.ai_kw = dict(exe=FAKE, entry=ENTRY, cfg_dir=os.path.join(TMP, 'cfg8'))
    a.update_rel = None
    def pump(cond, t=30):
        end = time.time() + t
        while time.time() < end and not cond(): a.update(); time.sleep(0.02)
        a.update(); return cond()
    def text(): return a.ai_text.get('1.0', 'end')
    try:
        check('A8 panel hidden at start', not a.ai_frame.winfo_ismapped() and a.ai_open is False)
        a.toggle_assistant(); a.update()
        check('A8 Assistant button shows the panel', a.ai_open and a.ai_frame.winfo_manager() == 'pack')
        a._add(scene); a.update()
        n0 = len(calls())
        a.ai_in.insert('1.0', 'render this folder')
        class Ev: state = 1
        check('A8 Shift+Enter does not send', a.ai_on_return(Ev()) is None and a.ai is None)
        Ev.state = 0; a.ai_on_return(Ev())
        check('A8 Enter sends (input cleared, Send disabled, Stop enabled)', a.ai_in.get('1.0', 'end').strip() == ''
              and str(a.ai_send_btn['state']) == 'disabled' and str(a.ai_stop_btn['state']) == 'normal')
        ok = pump(lambda: 'Echo 1: render this folder' in text())
        check('A8 reply streamed into the panel', ok and 'You: render this folder' in text(), text())
        pump(lambda: str(a.ai_send_btn['state']) == 'normal')
        check('A8 idle after the turn', str(a.ai_send_btn['state']) == 'normal' and a.ai_status.cget('text').startswith('Done'), a.ai_status.cget('text'))
        c = calls()[-1]
        check('A8 auto folder = the scene\'s folder', len(calls()) == n0 + 1 and os.path.normcase(c['cwd']) == os.path.normcase(sd), c['cwd'])
        check('A8 Save to readable (--add-dir)', os.path.normcase(a.out_dir.get()) in [os.path.normcase(x) for x in c['argv'][1:]]
              if os.path.isdir(a.out_dir.get()) else True)
        ctx = a.ai_context()
        check('A8 context block lists the queue and settings', ctx.startswith('[Seekframe app]') and scene in ctx and 'Quality:' in ctx, ctx)
        a.ai_send('please CANCEL')
        ok = pump(lambda: a.ai_allow_bar.winfo_manager() == 'pack' and str(a.ai_send_btn['state']) == 'normal')
        check('A8 blocked cancel -> Allow once bar', ok and 'blocked: shadow_cancel' in text() and 'shadow_cancel' in a.ai_allow_lbl.cget('text'), text())
        a.ai_allow()
        ok = pump(lambda: 'Cancelled j1' in text())
        check('A8 Allow once -> the step runs', ok and '(you allowed shadow_cancel once)' in text() and a.ai_allow_bar.winfo_manager() == '', text())
        pump(lambda: str(a.ai_send_btn['state']) == 'normal')
        a.ai_send('please CANCEL'); pump(lambda: a.ai_allow_bar.winfo_manager() == 'pack')
        a.ai_deny()
        check('A8 No -> bar gone, nothing allowed', a.ai_allow_bar.winfo_manager() == '' and '(not allowed: shadow_cancel)' in text() and not a.ai.pending_allow)
        pump(lambda: str(a.ai_send_btn['state']) == 'normal')
        a.ai_send('SLOW job'); pump(lambda: 'Working on it' in text())
        a.ai_stop(); a.update()
        check('A8 Stop -> idle, process gone', str(a.ai_send_btn['state']) == 'normal' and not a.ai.alive() and '(stopped' in text())
        a.ai_pick_dir(); a.update()
        check('A8 Folder... -> new conversation in that folder', a.ai is None and a.ai_dir_choice == os.path.normpath(picked) and 'New folder' in text())
        a.ai_send('hi there'); pump(lambda: 'Echo 1: hi there' in text())
        check('A8 chosen folder used', os.path.normcase(calls()[-1]['cwd']) == os.path.normcase(os.path.normpath(picked)), calls()[-1]['cwd'])
        a.ai_new(); a.update()
        check('A8 New chat clears the panel', 'hi there' not in text() and a.ai is None)
        os.environ['FAKE_AUTH'] = 'none'
        a.ai_send('hi'); pump(lambda: 'not signed in' in text())
        check('A8 not signed in -> clear message, Send works again', 'claude auth login' in text() and str(a.ai_send_btn['state']) == 'normal' and a.ai is None, text())
        os.environ['FAKE_AUTH'] = 'ok'
        a.ai_send('last'); pump(lambda: 'Echo 1: last' in text())
        proc = a.ai.proc
        a.toggle_assistant(); a.update()
        check('A8 Assistant button hides the panel again', not a.ai_open and a.ai_frame.winfo_manager() == '')
        check('A8 setting saved', json.load(open(app.CFG)).get('assistant_open') is False and json.load(open(app.CFG)).get('assistant_dir') == os.path.normpath(picked))
        a.on_close()
        try: proc.wait(10)
        except Exception: pass
        check('A8 closing Shadow ends the claude process', proc.poll() is not None)
        check('A8 no dialog popped up', not boxes, boxes)
    except Exception:
        traceback.print_exc(); check('A8 GUI run', False)
        try: a.destroy()
        except Exception: pass

for t in (a1, a2, a3, a4, a5, a6, a7, a8):
    try: t()
    except Exception:
        traceback.print_exc(); check(t.__name__ + ' crashed', False)
sys.modules['app'].close_log() if 'app' in sys.modules else None   # shadow.log in the temp folder is open: close it first
shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{sum(res)}/{len(res)} PASS')
sys.exit(0 if all(res) else 1)
