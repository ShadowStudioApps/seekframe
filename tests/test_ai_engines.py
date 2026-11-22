"""3.37 more AIs for Seekframe's own AI buttons: ChatGPT (Codex CLI) and Grok (Grok Build), chosen in the job windows.
Never calls a real AI: the CLIs are stand-in Python scripts written into a temp folder that print the same JSON lines.
  E1 Codex: its answer's '=== FILE: name ===' blocks are written by Seekframe, ONLY for the job's files; the files the
     prompt names are pasted in (images go as --image); args = no shell, read-only, no user config; resume keeps the thread
  E2 Grok: args allow search_replace only on the job's files, MCP tools denied, no web; text, session id and a refused
     edit (denial) come back from its streaming JSON
  E3 Task() picks the class by ai_tasks.ENGINE; available_engines lists only the AIs that are ready
  E4 the windows: New video shows the AI choice (only the ready AIs) and a moving bar + timer while it works; picking an
     AI changes ai_tasks.ENGINE and the setting; the Settings page no longer shows the AI choice
Usage: python tests/test_ai_engines.py     exit 0 = all PASS"""
import json, os, shutil, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
os.environ['SHADOW_LANG'] = 'en'
import ai_tasks as ai

fails = []
def check(name, ok, info=''):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  ({info})' if info and not ok else ''))
    if not ok: fails.append(name)

TMP = tempfile.mkdtemp(prefix='shadow_engines_')
FAKE_CODEX = os.path.join(TMP, 'fake_codex.py')
open(FAKE_CODEX, 'w', encoding='utf-8').write(r'''import json, sys, os
prompt = sys.stdin.read()
open(os.path.join(os.environ['FAKE_OUT'], 'codex_args.json'), 'w').write(json.dumps({'args': sys.argv[1:], 'prompt': prompt}))
print(json.dumps({'type': 'thread.started', 'thread_id': 'th-1'}))
ans = ("Wrote the script.\n=== FILE: script.txt ===\n```text\nRivers carry salt to the sea.\n```\n"
       "=== FILE: notes.txt ===\n```\nHACKED\n```\n")
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': ans}}))
print(json.dumps({'type': 'turn.completed'}))
''')
FAKE_GROK = os.path.join(TMP, 'fake_grok.py')
open(FAKE_GROK, 'w', encoding='utf-8').write(r'''import json, sys, os
a = sys.argv[1:]
open(os.path.join(os.environ['FAKE_OUT'], 'grok_args.json'), 'w').write(json.dumps(a))
p = open(a[a.index('--prompt-file') + 1], encoding='utf-8').read()
print(json.dumps({'type': 'text', 'data': 'Done: '}))
print(json.dumps({'type': 'tool_call', 'toolCallId': 'c1', 'toolName': 'search_replace', 'rawInput': {'file_path': 'notes.txt'}}))
print(json.dumps({'type': 'tool_call_update', 'toolCallId': 'c1', 'status': 'failed', 'content': [{'type': 'content', 'content': {'type': 'text', 'text': 'User cancelled the execution'}}]}))
print(json.dumps({'type': 'text', 'data': 'wrote the script (' + str(len(p)) + ' chars asked).'}))
print(json.dumps({'type': 'end', 'stopReason': 'end_turn', 'sessionId': 'gs-1'}))
''')
os.environ['FAKE_OUT'] = TMP
ok_ready = lambda exe: (True, 'ok')
try:
    # E1 Codex
    job = os.path.join(TMP, 'job'); os.makedirs(job)
    open(os.path.join(job, 'notes.txt'), 'w').write('The sea is salty.\n')
    open(os.path.join(job, 'sheet.jpg'), 'wb').write(b'\xff\xd8\xff')
    guide = os.path.join(TMP, 'guide dir', 'SKILL.md'); os.makedirs(os.path.dirname(guide)); open(guide, 'w').write('BRIGHT GUIDE')
    ev = []
    t = ai.CodexTask(job, ['script.txt'], on_event=lambda *e: ev.append(e), exe=[sys.executable, FAKE_CODEX], ready=ok_ready)
    r = t.ask(f'Read notes.txt and look at sheet.jpg. This channel\'s own guide (read it): {guide}\nWrite "script.txt".')
    sent = json.load(open(os.path.join(TMP, 'codex_args.json')))
    check('E1 Codex: the job file is written from its answer', r['ok'] and open(os.path.join(job, 'script.txt')).read() == 'Rivers carry salt to the sea.\n', r)
    check('E1 Codex: a file it may not change is left alone', open(os.path.join(job, 'notes.txt')).read() == 'The sea is salty.\n')
    check('E1 Codex: the summary comes back without the file blocks', r['text'].startswith('Wrote the script') and '=== FILE' not in r['text'], r['text'])
    a = sent['args']
    check('E1 Codex: no shell, read-only sandbox, no user config (no MCP servers)', all(x in a for x in ('--disable', 'shell_tool', '--ignore-user-config', 'read-only', '--json')), a)
    check('E1 Codex: the files the prompt names are pasted in, images go as --image',
          'The sea is salty.' in sent['prompt'] and 'BRIGHT GUIDE' in sent['prompt'] and any(x.startswith('--image=') and x.endswith('sheet.jpg') for x in a), a)
    check('E1 Codex: thread id kept', t.session_id == 'th-1')
    t.ask('again'); a2 = json.load(open(os.path.join(TMP, 'codex_args.json')))['args']
    check('E1 Codex: the next round resumes the same thread', a2[a2.index('exec') + 1:a2.index('exec') + 3] == ['resume', 'th-1'], a2)
    s, w_ = ai.take_files('x\n=== FILE: ../evil.txt ===\n```\nno\n```\n', job, ['evil.txt'])
    check('E1 take_files never writes outside the job folder', not os.path.exists(os.path.join(TMP, 'evil.txt')))
    # E2 Grok
    ev = []
    g = ai.GrokTask(job, ['script.txt'], on_event=lambda *e: ev.append(e), exe=[sys.executable, FAKE_GROK], ready=ok_ready)
    r = g.ask('Write script.txt.')
    ga = json.load(open(os.path.join(TMP, 'grok_args.json')))
    check('E2 Grok: text and session id come back', r['ok'] and 'wrote the script' in r['text'] and g.session_id == 'gs-1', r)
    check('E2 Grok: a refused edit is reported', r['denials'] == ['search_replace: notes.txt'], r['denials'])
    allows = [ga[i + 1] for i, x in enumerate(ga) if x == '--allow']
    check('E2 Grok: only the job file may be edited, MCP tools denied, no web, dontAsk',
          allows == ['search_replace(script.txt)'] and ['--deny', 'use_tool'] == ga[ga.index('--deny'):ga.index('--deny') + 2]
          and '--disable-web-search' in ga and ga[ga.index('--permission-mode') + 1] == 'dontAsk' and 'run_terminal_command' not in ','.join(ga), ga)
    g.ask('again'); ga2 = json.load(open(os.path.join(TMP, 'grok_args.json')))
    check('E2 Grok: the next round resumes the session', ga2[ga2.index('-r') + 1] == 'gs-1' if '-r' in ga2 else False, ga2)
    check('E2 Grok: the prompt file is removed after the run', not os.path.exists(g.prompt_file))
    # E3
    real = ai.ENGINE
    try:
        kinds = {}
        for e in ai.ENGINES:
            ai.ENGINE = e; kinds[e] = type(ai.Task(job, [])).__name__
        check('E3 Task() follows the chosen AI', kinds == dict(claude='ClaudeTask', gemini='GeminiTask', codex='CodexTask', grok='GrokTask'), kinds)
    finally: ai.ENGINE = real
    av = ai.available_engines(ready=lambda k: (k in ('claude', 'grok'), ''))
    check('E3 only the ready AIs are offered', av == [('claude', 'Claude Code'), ('grok', 'Grok')], av)
    check('E3 progress messages name the AI', ai.ai_name('codex') == 'ChatGPT' and ai.ai_name('grok') == 'Grok')
    # E4 windows
    import app, no_dialogs
    app.LOG = os.path.join(TMP, 'l.log'); app.close_log()
    no_dialogs.block(app)
    saved = {}; app.save_cfg = lambda d: saved.update(d); app.load_cfg = lambda: {}
    app.App.start_update_check = lambda *a, **k: None
    w = app.App()
    try:
        w.ai_voice = ''; w.ai_available = [('claude', 'Claude Code'), ('codex', 'ChatGPT (Codex)'), ('grok', 'Grok')]
        w.update()
        check('E4 Settings no longer shows the AI choice', not w.engine_row.winfo_manager())
        d = w.open_new_video(); w.update()
        check('E4 New video offers only the ready AIs', list(d.picker.btns) == ['claude', 'codex', 'grok'], list(d.picker.btns))
        app.ai_tasks.engine_ready = lambda k: (True, '')
        w.engine.set('grok'); d.picker.pick(); w.update()
        check('E4 picking Grok: used by the jobs, saved, named in the window', app.ai_tasks.ENGINE == 'grok' and saved.get('ai', {}).get('engine') == 'grok'
              and 'Grok writes the script' in d.hint_lbl.cget('text'), (app.ai_tasks.ENGINE, d.hint_lbl.cget('text')))
        d.busy(True); w.update(); time.sleep(1.2); w.update()
        check('E4 while it works: a moving bar and a timer, the AI choice locked', d.working.bar.winfo_manager() == 'pack'
              and d.working.clock.cget('text').startswith('0:0') and d.picker.btns['claude'].instate(['disabled']), d.working.clock.cget('text'))
        d.busy(False); w.update()
        check('E4 when it stops the bar goes away', not d.working.bar.winfo_manager() and not d.working.running)
        d.close()
        w.ai_available = []
        d = w.open_new_video(); w.update()
        check('E4 no AI signed in: the window says where to look', 'Settings > AI connections' in d.picker.msg.cget('text'))
        d.close()
        check('E4 no real dialog opened', not [c for c in no_dialogs.CALLS if c.startswith('ask')], no_dialogs.CALLS)
    finally:
        app.ai_tasks.ENGINE = 'claude'
        w.destroy(); app.close_log()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print('ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}')
sys.exit(1 if fails else 0)
