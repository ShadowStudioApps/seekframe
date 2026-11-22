"""The smaller windows of the Shadow app: YouTube... (YouTubeDialog), Narration... (NarrationDialog) and the Check frames
result (CheckWindow), AI... (AIWindow, 3.19) and New video (AI) (NewVideoDialog, 3.19). Split out of app.py (3.16); app.py imports them back (app.YouTubeDialog etc.).
They only use the App instance they are given and the helpers below - nothing from app.py's module state."""
import logging, os, threading, webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import blender_core as bc
from scene_paths import scene_for_mp4
from shadow_util import dark_titlebar, narrate_module, open_path, style_input, style_output
from i18n import t as tr   # 3.20: what the user reads is translated (i18n.py)
import i18n
log = logging.getLogger('shadow')

class YouTubeDialog:
    """YouTube...: upload rendered videos to a signed-in channel (youtube.py, YouTube Data API, your own OAuth client).
    Titles / descriptions / tags / Made for Kids come from metadata.txt next to the video or next to its scene ('=== SHORT ===' section
    for *_shorts.mp4). Privacy defaults to Private. Until the Google Cloud project passes YouTube's audit, YouTube keeps every
    API upload Private whatever is chosen. upload() runs in a thread; tests call add()/start() with youtube.py patched."""
    def __init__(self, app, items):
        import youtube as ytm
        self.app, self.ytm, self.items, self.cancel, self.busy, self.last = app, ytm, [], threading.Event(), False, None
        t = self.top = tk.Toplevel(app); t.title(tr('Upload to YouTube')); t.transient(app); t.minsize(640, 360)
        f = ttk.Frame(t, padding=14); f.pack(fill='both', expand=True)
        ttk.Label(f, text=tr('Channel')).grid(row=0, column=0, sticky='w')
        self.channel = tk.StringVar(); self.ch_box = ttk.Combobox(f, textvariable=self.channel, state='readonly', width=34)
        self.ch_box.grid(row=0, column=1, sticky='w', padx=8)
        ttk.Button(f, text=tr('Sign in...'), command=self.sign_in).grid(row=0, column=2, sticky='w')
        self.tree = ttk.Treeview(f, columns=('title', 'when', 'status'), height=6)
        for c, w, txt in (('#0', 200, 'Video'), ('title', 240, 'Title (metadata.txt)'), ('when', 120, 'Publish'), ('status', 170, 'Status')):
            self.tree.heading(c, text=tr(txt)); self.tree.column(c, width=w, stretch=c != 'status')
        self.tree.grid(row=1, column=0, columnspan=4, sticky='nsew', pady=10)
        self.tree.bind('<Double-1>', lambda e: self.open_selected())
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.show_source())
        self.ask = lambda title, text: messagebox.askyesno(title, text, parent=self.top)   # tests replace it
        ttk.Label(f, text=tr('Privacy')).grid(row=2, column=0, sticky='w')
        self.privacy = tk.StringVar(value='private')
        i18n.Combo(f, self.privacy, list(ytm.PRIVACY), width=12).grid(row=2, column=1, sticky='w', padx=8)
        self.kids = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=tr('Made for kids'), variable=self.kids).grid(row=2, column=2, sticky='w')
        self.ai, self.thumb, self.sched = tk.BooleanVar(value=False), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        opt = ttk.Frame(f); opt.grid(row=3, column=0, columnspan=4, sticky='w', pady=(6, 0))
        ttk.Checkbutton(opt, text=tr('Altered or synthetic (AI) content'), variable=self.ai).pack(side='left')
        ttk.Checkbutton(opt, text=tr('Set thumbnail (*_thumb.jpg)'), variable=self.thumb).pack(side='left', padx=12)
        ttk.Checkbutton(opt, text=tr('Schedule (PUBLISH: time)'), variable=self.sched).pack(side='left')
        ttk.Label(f, text=tr('Until Google approves the app (YouTube API audit), YouTube keeps API uploads Private.'),
                  foreground='#888').grid(row=4, column=0, columnspan=4, sticky='w', pady=(6, 0))
        self.bar = ttk.Progressbar(f, maximum=100); self.bar.grid(row=5, column=0, columnspan=4, sticky='we', pady=(10, 0))
        self.msg = ttk.Label(f, text='', foreground='#888'); self.msg.grid(row=6, column=0, columnspan=4, sticky='w')
        bt = ttk.Frame(f); bt.grid(row=7, column=0, columnspan=4, sticky='we', pady=(10, 0))
        ttk.Button(bt, text=tr('Add video...'), command=self.pick).pack(side='left')
        ttk.Button(bt, text=tr('Remove'), command=self.remove).pack(side='left', padx=6)
        self.studio_btn = ttk.Button(bt, text=tr('Open in Studio'), command=self.open_selected, state='disabled'); self.studio_btn.pack(side='left')
        ttk.Button(bt, text=tr('Close'), command=self.close).pack(side='right')
        self.up_btn = ttk.Button(bt, text=tr('Upload'), style='Accent.TButton', command=self.start); self.up_btn.pack(side='right', padx=6)
        f.columnconfigure(3, weight=1); f.rowconfigure(1, weight=1)
        t.protocol('WM_DELETE_WINDOW', self.close); t.bind('<Escape>', lambda e: self.close())
        dark_titlebar(t, app.theme == 'dark')
        self.refresh_channels()
        for mp4, scene in items: self.add(mp4, scene)
        if not self.items: self.msg.config(text=tr('Render first, or "Add video..." to pick mp4 files.'))

    def refresh_channels(self, select=None):
        ch = self.ytm.channels(); names = [c['title'] for c in ch]
        self.ch_box.config(values=names)
        if select: self.channel.set(select)
        elif self.channel.get() not in names: self.channel.set(names[0] if len(names) == 1 else '')
        try: self.ytm.load_client()
        except self.ytm.YouTubeError as e: self.msg.config(text=str(e))

    def add(self, mp4, scene=None):
        """One video row. Its metadata.txt is looked for next to the video, then next to its scene: the row's scene, or for
        "Add video..." the queued scene that makes this file (scene_for_mp4), so a picked mp4 still gets its metadata."""
        mp4 = os.path.normpath(mp4)   # the file picker gives C:/... - the same file must not be listed twice
        if any(os.path.normcase(i['mp4']) == os.path.normcase(mp4) for i in self.items): return
        scene = scene or scene_for_mp4(mp4, getattr(self.app, 'files', []))
        it = dict(mp4=mp4, scene=scene, cands=[os.path.dirname(scene)] if scene else [], meta=None, src=None, result=None)
        it['iid'] = self.tree.insert('', 'end', text=os.path.basename(mp4), values=('', '', 'Ready'))
        self.items.append(it); self.load_meta(it)
        meta = it['meta']
        if meta and meta.get('kids') is not None and len(self.items) == 1: self.kids.set(bool(meta['kids']))
        if meta and meta.get('ai') is not None and len(self.items) == 1: self.ai.set(bool(meta['ai']))

    def load_meta(self, it):
        """(Re)read the row's metadata.txt from disk (also right before Upload: a file written after the dialog opened counts)."""
        it['meta'], it['src'] = self.ytm.metadata_for(it['mp4'], it['cands'])
        m = it['meta'] or {}
        self.tree.set(it['iid'], 'title', m.get('title') or '(no metadata.txt: file name)'); self.tree.set(it['iid'], 'when', self.when_text(m))

    def show_source(self):
        """Status line for the selected row: which metadata.txt its upload will use."""
        sel = set(self.tree.selection()); it = next((i for i in self.items if i['iid'] in sel), None)
        if it: self.msg.config(text=f"metadata: {it['src']}" if it['src'] else 'no metadata.txt next to this video'
                               + (f" or its scene ({os.path.basename(it['scene'])})" if it['scene'] else ' (and no queued scene makes it)'))

    @staticmethod
    def when_text(meta):
        """Publish column: the PUBLISH: time in this PC's zone, '' without PUBLISH:, '(not a date)' when it has no date + time."""
        m = meta or {}
        if m.get('publish_at'):
            import datetime
            t = datetime.datetime.strptime(m['publish_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).astimezone()
            return t.strftime('%a %d %b %H:%M')
        return '(not a date)' if m.get('publish') else ''

    def pick(self):
        for p in filedialog.askopenfilenames(parent=self.top, filetypes=[('MP4 video', '*.mp4')], initialdir=self.app.out_dir.get()): self.add(p)

    def remove(self):
        if self.busy: return
        sel = set(self.tree.selection())
        for it in [i for i in self.items if i['iid'] in sel]: self.tree.delete(it['iid']); self.items.remove(it)

    def sign_in(self):
        if self.busy: return
        self.msg.config(text=tr('Sign in on the Google page that opened in your browser...'))
        def work():
            try: ch = self.ytm.sign_in(); self.top.after(0, lambda: (self.refresh_channels(ch['title']), self.msg.config(text=tr('Signed in: {0}', ch['title']))))
            except Exception as e: self.top.after(0, lambda e=e: self.msg.config(text=tr('Sign-in failed: {0}', e)))
        threading.Thread(target=work, daemon=True).start()

    def start(self, wait=False):
        """Upload every video that is not uploaded yet. wait=True (tests) runs in this thread."""
        if self.busy:
            self.cancel.set(); self.msg.config(text=tr('Stopping after the current chunk...')); return
        todo = [i for i in self.items if not i['result']]
        if not todo: self.msg.config(text=tr('Nothing to upload.')); return
        if not self.channel.get(): self.msg.config(text=tr('Choose a channel (or Sign in...).')); return
        for it in todo: self.load_meta(it)   # what is on disk now, not what was there when the dialog opened
        bare = [os.path.basename(i['mp4']) for i in todo if not i['meta']]
        if bare and not self.ask('YouTube', 'No metadata.txt found for:\n\n' + '\n'.join(bare) +
                                 '\n\nThey would be uploaded with the file name as title and no description, tags or schedule. Upload them anyway?'):
            self.msg.config(text=tr('Put metadata.txt next to the video or its scene, then press Upload.')); return
        self.busy = True; self.cancel.clear(); self.up_btn.config(text=tr('Stop')); ch = self.channel.get()
        privacy, kids, ai, thumb, sched = self.privacy.get(), self.kids.get(), self.ai.get(), self.thumb.get(), self.sched.get()
        bad_thumb = []
        def set_row(it, status): self.top.after(0, lambda: self.tree.set(it['iid'], 'status', status))
        def work():
            ok = 0
            for n, it in enumerate(todo):
                set_row(it, 'Uploading 0%')
                def prog(d, t, it=it, n=n):
                    pct = d * 100 // max(t, 1); set_row(it, f'Uploading {pct}%')
                    self.top.after(0, lambda: self.bar.config(value=(n + d / max(t, 1)) * 100 / len(todo)))
                try:
                    r = self.ytm.upload_video(it['mp4'], ch, it['meta'] or {}, privacy, progress=prog, cancel=self.cancel,
                                              overrides=dict(kids=kids, privacy=privacy, ai=ai), meta_path=it['src'],
                                              thumbnail=thumb, schedule=sched)
                    it['result'] = r; self.last = r; ok += 1
                    extra = (['scheduled'] if r.get('publish_at') else []) + (['thumbnail'] if r.get('thumb') == 'set' else [])
                    if str(r.get('thumb') or '').startswith('error'): extra.append('no thumbnail'); bad_thumb.append(r['thumb'][7:])
                    set_row(it, f"Done ({', '.join([r.get('privacy') or privacy] + extra)})")
                    log.info('youtube upload %s -> %s %s thumb=%s publish=%s', it['mp4'], r['channel'], r['url'], r.get('thumb'), r.get('publish_at'))
                except Exception as e:
                    set_row(it, 'Stopped' if self.cancel.is_set() else 'Error'); log.warning('youtube upload %s: %s', it['mp4'], e)
                    self.top.after(0, lambda e=e: self.msg.config(text=str(e)))
                    if self.cancel.is_set(): break
            def end():
                self.busy = False; self.up_btn.config(text=tr('Upload'))
                if ok:
                    self.studio_btn.config(state='normal')
                    self.msg.config(text=f'{ok} uploaded to {ch}. Double-click a row to open it in YouTube Studio.'
                                    + (f' Thumbnail not set: {bad_thumb[-1]}' if bad_thumb else ''))
            self.top.after(0, end)
        if wait: work()
        else: threading.Thread(target=work, daemon=True).start()

    def open_selected(self):
        sel = set(self.tree.selection())
        it = next((i for i in self.items if i['iid'] in sel and i['result']), None) or (self.last and {'result': self.last})
        if it: webbrowser.open(it['result']['studio'])

    def close(self):
        if self.busy and not messagebox.askyesno(tr('YouTube'), tr('An upload is running. Stop it and close?'), parent=self.top): return
        self.cancel.set(); self.top.destroy()

class NarrationDialog:
    """Small dialog for one queue row: narration WAV, words.json, style, captions; OK / Remove narration / Cancel.
    Plain ttk widgets, so it follows the app's sv-ttk dark/light theme; the title bar follows it too.
    ok() / remove() / cancel() are the button handlers (tests call them directly)."""
    def __init__(self, app, path):
        self.app, self.path = app, path
        cur = app.narr.get(path) or {}
        base = os.path.splitext(path)[0]
        guess = lambda ext: base + ext if os.path.isfile(base + ext) else ''
        self.wav = tk.StringVar(value=cur.get('wav') or guess('.wav'))
        w = cur.get('words'); self.words = tk.StringVar(value=w if isinstance(w, str) else guess('.words.json'))
        self.style = tk.StringVar(value=cur.get('style', 'pop'))
        self.captions = tk.BooleanVar(value=cur.get('captions', True))
        t = self.top = tk.Toplevel(app); t.title(tr('Narration - {0}', os.path.basename(path))); t.transient(app); t.resizable(False, False)
        f = ttk.Frame(t, padding=14); f.pack(fill='both', expand=True)
        for r, (label, var, pick) in enumerate((('Voice (WAV)', self.wav, self.pick_wav), ('Words (words.json)', self.words, self.pick_words))):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky='w', pady=4)
            ttk.Entry(f, textvariable=var, width=46).grid(row=r, column=1, sticky='we', padx=8, pady=4)
            ttk.Button(f, text=tr('Browse...'), command=pick).grid(row=r, column=2, pady=4)
        ttk.Label(f, text=tr('Caption style')).grid(row=2, column=0, sticky='w', pady=4)
        ttk.Combobox(f, textvariable=self.style, values=list(narrate_module().STYLES), state='readonly', width=12).grid(row=2, column=1, sticky='w', padx=8, pady=4)
        ttk.Checkbutton(f, text=tr('Word captions (2D scenes; WebGL scenes get the voice only)'), variable=self.captions).grid(row=3, column=1, columnspan=2, sticky='w', padx=8, pady=4)
        bt = ttk.Frame(f); bt.grid(row=4, column=0, columnspan=3, sticky='e', pady=(10, 0))
        ttk.Button(bt, text=tr('OK'), style='Accent.TButton', command=self.ok).pack(side='left')
        ttk.Button(bt, text=tr('Remove narration'), command=self.remove, state='normal' if path in app.narr else 'disabled').pack(side='left', padx=6)
        ttk.Button(bt, text=tr('Cancel'), command=self.cancel).pack(side='left')
        t.protocol('WM_DELETE_WINDOW', self.cancel); t.bind('<Escape>', lambda e: self.cancel())
        dark_titlebar(t, app.theme == 'dark')
        try: t.grab_set()
        except tk.TclError: pass   # the main window may be hidden (tests)
    def pick_wav(self):
        p = filedialog.askopenfilename(parent=self.top, filetypes=[('WAV', '*.wav'), ('Audio', '*.wav *.mp3 *.m4a *.flac *.ogg')])
        if p: self.wav.set(p)
    def pick_words(self):
        p = filedialog.askopenfilename(parent=self.top, filetypes=[('Word timings', '*.json')])
        if p: self.words.set(p)
    def ok(self):
        err = self.app.set_narration(self.path, self.wav.get().strip(), self.words.get().strip(), style=self.style.get(), captions=self.captions.get())
        if err:
            messagebox.showerror(tr('Narration'), err, parent=self.top); return err   # stays open to fix it
        self.app.status.config(text=tr('{0}: narration set ({1})', os.path.basename(self.path), self.style.get())); self.close(); return None
    def remove(self):
        self.app.clear_narration(self.path); self.app.status.config(text=tr('{0}: narration removed', os.path.basename(self.path))); self.close()
    def cancel(self): self.close()
    def close(self):
        try: self.top.grab_release()
        except tk.TclError: pass
        self.top.destroy(); self.app._update_narr_btn()

class CheckWindow:
    """Result of 'Check frames' for one scene: the contact sheet (scaled to fit), OK or the problems (page errors, impure
    seek(t), never ready...), notes, and Open image / Close. Follows the app's theme."""
    def __init__(self, app, path, res):
        self.app, self.path, self.res = app, path, res
        t = self.top = tk.Toplevel(app); t.title(tr('Frame check - {0}', os.path.basename(path))); t.transient(app)
        f = ttk.Frame(t, padding=12); f.pack(fill='both', expand=True)
        self.photo = None
        if res.get('sheet') and os.path.isfile(res['sheet']):
            try:
                import base64, io
                from PIL import Image
                with Image.open(res['sheet']) as f0: im = f0.copy()   # closed at once: an open file would stay locked on Windows
                k = app.winfo_fpixels('1i') / 96
                im.thumbnail((round(1100 * k), round(560 * k)))
                buf = io.BytesIO(); im.save(buf, 'PNG')   # Tk reads PNG itself: no PIL.ImageTk needed
                self.photo = tk.PhotoImage(master=t, data=base64.b64encode(buf.getvalue()).decode('ascii'), format='png')
                ttk.Label(f, image=self.photo).pack(anchor='w')
            except Exception:
                log.exception('check window image')
        ok = res.get('ok')
        lines = (['OK: no page errors, seek(t) is pure.' if not bc.is_blend(path) else 'OK: no problems.'] if ok
                 else ['Problems:'] + [f'  • {p}' for p in res.get('problems') or []])
        lines += [f'Note: {n}' for n in res.get('notes') or []]
        if res.get('sheet'): lines.append(f'Sheet: {res["sheet"]}')
        ttk.Label(f, text='\n'.join(lines), justify='left', wraplength=round(1100 * app.winfo_fpixels('1i') / 96),
                  foreground='#3fb950' if ok else '#f85149').pack(anchor='w', pady=(8, 0))
        bt = ttk.Frame(f); bt.pack(anchor='e', pady=(10, 0))
        ttk.Button(bt, text=tr('Open image'), command=self.open_image, state='normal' if res.get('sheet') else 'disabled').pack(side='left')
        if not ok and path.lower().endswith(('.html', '.htm')) and hasattr(app, 'open_ai'):   # 3.19: straight to the AI window
            ttk.Button(bt, text=tr('Fix with AI...'), command=lambda: (self.close(), app.open_ai([path], list(res.get('problems') or [])))).pack(side='left', padx=(6, 0))
        ttk.Button(bt, text=tr('Close'), style='Accent.TButton', command=self.close).pack(side='left', padx=(6, 0))
        t.protocol('WM_DELETE_WINDOW', self.close); t.bind('<Escape>', lambda e: self.close())
        dark_titlebar(t, app.theme == 'dark')
    def open_image(self):
        if self.res.get('sheet'): open_path(self.res['sheet'])
    def close(self): self.top.destroy()
class AIPicker:
    """3.37: which AI does this job - only the AIs installed and signed in on this PC (ai_tasks.available_engines, found in
    a thread). The choice is app.engine / ai_tasks.ENGINE (setting ai.engine), the same in every AI window.
    app.ai_available = [(key, name)] (tests) skips the search; with app.ai_task_kw (tests) only the current AI is shown."""
    def __init__(self, parent, app, on_change=None):
        import queue
        import ai_tasks
        self.app, self.ai, self.on_change, self.q = app, ai_tasks, on_change, queue.Queue()
        self.frame = ttk.Frame(parent); self.btns = {}
        ttk.Label(self.frame, text=tr('AI:')).pack(side='left')
        self.box = ttk.Frame(self.frame); self.box.pack(side='left')
        self.msg = ttk.Label(self.frame, text=tr('looking for your AIs...'), foreground='#888'); self.msg.pack(side='left', padx=(10, 0))
        avail = getattr(app, 'ai_available', None)
        if avail is None and getattr(app, 'ai_task_kw', None) is not None: avail = [(ai_tasks.ENGINE, ai_tasks.ENGINES[ai_tasks.ENGINE])]
        if avail is not None: self.show(avail)
        else:
            threading.Thread(target=lambda: self.q.put(ai_tasks.available_engines()), daemon=True).start()
            self._wait()
    def _wait(self):
        try: avail = self.q.get_nowait()
        except Exception:
            try: self.frame.after(150, self._wait)
            except tk.TclError: pass
            return
        self.show(avail)
    def show(self, avail):
        if not self.frame.winfo_exists(): return
        for w in self.box.winfo_children(): w.destroy()
        self.btns = {}
        if not avail:
            self.msg.config(text=tr('No AI is signed in on this PC: Settings > AI connections shows how.'), foreground='#f85149'); return
        keys = [k for k, _ in avail]
        if self.ai.ENGINE not in keys:   # the saved AI is gone or signed out: take the first one that works
            self.app.engine.set(keys[0]); self.app.on_engine(ready=lambda *a: (True, ''), toast=lambda *a: None)
        self.app.engine.set(self.ai.ENGINE)
        for k, n in avail:
            rb = ttk.Radiobutton(self.box, text=n, value=k, variable=self.app.engine, command=self.pick)
            rb.pack(side='left', padx=(10, 0)); self.btns[k] = rb
        self.msg.config(text='')
        if self.on_change: self.on_change()
    def pick(self):
        ok = self.app.on_engine(toast=lambda *a: None)
        self.msg.config(text='' if ok else self.app.engine_lbl.cget('text'), foreground='#f85149')
        if self.on_change: self.on_change()
        return ok
    def lock(self, on):   # no switching while a job runs
        for b in self.btns.values(): b.state(['disabled'] if on else ['!disabled'])


class Working:
    """3.37: a moving bar + the time since the job started, so it is plain that the AI is working."""
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.bar = ttk.Progressbar(self.frame, mode='indeterminate', length=180)
        self.clock = ttk.Label(self.frame, text='', foreground='#888', width=7)
        self.t0 = None; self.job = None
    def start(self):
        import time
        self.t0 = time.time()
        self.bar.pack(side='left'); self.clock.pack(side='left', padx=(8, 0)); self.bar.start(12); self._tick()
    def _tick(self):
        import time
        if self.t0 is None: return
        s = int(time.time() - self.t0); self.clock.config(text=f'{s // 60}:{s % 60:02d}')
        try: self.job = self.frame.after(1000, self._tick)
        except tk.TclError: pass
    def stop(self):
        self.t0 = None
        try:
            if self.job: self.frame.after_cancel(self.job)
            self.bar.stop(); self.bar.pack_forget(); self.clock.pack_forget()
        except tk.TclError: pass
        self.job = None
    @property
    def running(self): return self.t0 is not None


class AIWindow:
    """AI... (3.19, Smart Shadow): Claude through the installed Claude Code on the owner's subscription (ai_tasks.py).
      Fix the scene  - Claude repairs a copy of the selected HTML scene (the problems Shadow found + the owner's own note);
                       Shadow checks the copy itself after each round; the original changes only on Apply (backup kept in
                       <folder>/.shadow_backup/), Discard throws the copy away.
      YouTube text   - Claude looks at the row's rendered video and writes metadata.txt next to it (asks before replacing one).
    The work runs in a thread; this window polls its own queue. app.ai_task_kw: tests pass exe/popen/ready here;
    app.ai_check: tests replace Check frames."""
    def __init__(self, app, path, problems=(), mp4=None):
        import queue
        import ai_tasks
        self.app, self.path, self.mp4, self.ai = app, path, mp4, ai_tasks
        self.q = queue.Queue(); self.task = None; self.thread = None; self.fix = None; self.result_file = None
        self.html = path.lower().endswith(('.html', '.htm'))
        t = self.top = tk.Toplevel(app); t.title(tr('AI - {0}', os.path.basename(path))); t.transient(app); t.minsize(680, 520)
        f = ttk.Frame(t, padding=14); f.pack(fill='both', expand=True); f.columnconfigure(0, weight=1)
        ttk.Label(f, text=os.path.basename(path), font=('Segoe UI', 11, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(f, text=tr('What is wrong (Seekframe fills in what it found; add your own words, in any language):'),
                  foreground='#888').grid(row=1, column=0, sticky='w', pady=(8, 2))
        self.note = tk.Text(f, height=5, wrap='word', relief='solid', borderwidth=1, padx=8, pady=6, font='SunValleyBodyFont', undo=True); self.note.grid(row=2, column=0, sticky='nsew')
        style_input(self.note, app.theme == 'dark', hint=tr('Type here what is wrong with the scene...'))
        if problems: self.note.insert('1.0', '\n'.join(f'- {p}' for p in problems))
        hold = ttk.Frame(f); hold.grid(row=3, column=0, sticky='w', pady=8)
        self.picker = AIPicker(hold, app); self.picker.frame.pack(anchor='w')
        bt = ttk.Frame(hold); bt.pack(anchor='w', pady=(8, 0))
        self.fix_btn = ttk.Button(bt, text=tr('Fix the scene'), style='Accent.TButton', command=self.start_fix)
        self.fix_btn.pack(side='left')
        self.meta_btn = ttk.Button(bt, text=tr('Write YouTube text'), command=self.start_meta); self.meta_btn.pack(side='left', padx=(6, 0))
        self.stop_btn = ttk.Button(bt, text=tr('Stop'), command=self.stop); self.stop_btn.pack(side='left', padx=(6, 0))
        hint = [] if self.html else ['Fix works on HTML scenes only.']
        if not mp4: hint.append('YouTube text needs a rendered video of this row (render it first).')
        ttk.Label(f, text='  '.join(hint) or tr('The AI reads files and changes nothing in your scene until you press Apply.'),
                  foreground='#888').grid(row=4, column=0, sticky='w')
        sr = ttk.Frame(f); sr.grid(row=5, column=0, sticky='w', pady=(6, 2))
        self.working = Working(sr); self.working.frame.pack(side='left')
        self.status = ttk.Label(sr, text=''); self.status.pack(side='left', padx=(8, 0))
        self.out = tk.Text(f, height=14, wrap='word', state='disabled', relief='solid', borderwidth=1, padx=8, pady=6, font='SunValleyBodyFont'); self.out.grid(row=6, column=0, sticky='nsew'); f.rowconfigure(6, weight=1)
        style_output(self.out, app.theme == 'dark')
        ab = ttk.Frame(f); ab.grid(row=7, column=0, sticky='e', pady=(10, 0))
        self.apply_btn = ttk.Button(ab, text=tr('Apply fix'), style='Accent.TButton', command=self.apply); self.apply_btn.pack(side='left')
        self.discard_btn = ttk.Button(ab, text=tr('Discard'), command=self.discard); self.discard_btn.pack(side='left', padx=(6, 0))
        self.open_btn = ttk.Button(ab, text=tr('Open file'), command=self.open_result); self.open_btn.pack(side='left', padx=(6, 0))
        ttk.Button(ab, text=tr('Close'), command=self.close).pack(side='left', padx=(6, 0))
        self.busy(False); self.apply_btn.config(state='disabled'); self.discard_btn.config(state='disabled'); self.open_btn.config(state='disabled')
        t.protocol('WM_DELETE_WINDOW', self.close); t.bind('<Escape>', lambda e: self.close())
        dark_titlebar(t, app.theme == 'dark')
        self._poll()

    # -------------------------------------------------- helpers
    def note_lines(self):
        return [l.strip().lstrip('-•').strip() for l in self.note.get('1.0', 'end').splitlines() if l.strip()]
    def write(self, s, clear=False):
        self.out.config(state='normal')
        if clear: self.out.delete('1.0', 'end')
        self.out.insert('end', s); self.out.see('end'); self.out.config(state='disabled')
    def busy(self, on):
        self.fix_btn.config(state='normal' if self.html and not on else 'disabled')
        self.meta_btn.config(state='normal' if self.mp4 and not on else 'disabled')
        self.stop_btn.config(state='normal' if on else 'disabled')
        if on: self.apply_btn.config(state='disabled'); self.discard_btn.config(state='disabled')
        if hasattr(self, 'working'):
            (self.working.start if on else self.working.stop)(); self.picker.lock(on)
    def new_task(self, lang):
        kw = dict(getattr(self.app, 'ai_task_kw', {}))
        self.task = self.ai.Task(os.path.dirname(os.path.abspath(self.path)), (), on_event=lambda *e: self.q.put(('ev',) + e), lang=lang, **kw)
        return self.task
    @property
    def NOTE_LANG(self):   # 3.20: else the app's own language
        return f"the language the owner wrote his own words in, else {i18n.name()}"

    # -------------------------------------------------- Fix the scene
    def start_fix(self):
        if self.thread and self.thread.is_alive() or not self.html: return None
        self.discard(quiet=True)
        notes = self.note_lines(); self.busy(True); self.write('', clear=True)
        check = getattr(self.app, 'ai_check', None)
        if check is None:
            import frame_check
            kw = dict(getattr(self.app, 'check_kw', {}))
            check = lambda p, cancel=None: frame_check.check(p, cancel=cancel, **kw)
        task = self.new_task(self.NOTE_LANG)
        def run():
            try: r = self.ai.fix_scene(self.path, notes, task=task, check=check, progress=lambda s: self.q.put(('status', s)))
            except Exception as e:
                log.exception('AI fix'); r = dict(ok=False, work=None, error=f'{type(e).__name__}: {e}', summary='', problems=[], rounds=0)
            self.q.put(('fix_done', r))
        self.thread = threading.Thread(target=run, daemon=True); self.thread.start()
        return self.thread
    def fix_done(self, r):
        self.busy(False); self.fix = r
        self.write('\n\n' + (r.get('summary') or '').strip() + '\n')
        has_copy = bool(r.get('work') and os.path.isfile(r['work']))
        if has_copy:
            d = self.ai.diff_lines(self.path, r['work'], 200)
            self.write('\nChanges (- before, + after):\n' + ('\n'.join(d) if d else '(no change)') + '\n')
        if r['ok']:
            self.status.config(text=tr('Fixed in {0} round(s); Seekframe checked the copy: OK. Press Apply to use it.', r['rounds']), foreground='#3fb950')
        else:
            left = r.get('problems') or []
            self.status.config(text=tr('Not fixed: {0}', r.get('error') or '; '.join(left[:3])), foreground='#f85149')
        self.apply_btn.config(state='normal' if has_copy and r.get('error') not in ('stopped',) else 'disabled')
        self.discard_btn.config(state='normal' if has_copy else 'disabled')
        log.info('AI fix %s: ok=%s rounds=%s left=%s error=%s', self.path, r['ok'], r.get('rounds'), r.get('problems'), r.get('error'))
    def apply(self, ask=None):
        r = self.fix
        if not r or not r.get('work') or not os.path.isfile(r['work']): return None
        if not r['ok'] and not (ask or messagebox.askyesno)('Apply fix', 'The fix is not complete (see the message). Use the changed scene anyway?', parent=self.top):
            return None
        bak = self.ai.apply_fix(self.path, r['work']); self.fix = None
        self.apply_btn.config(state='disabled'); self.discard_btn.config(state='disabled')
        self.status.config(text=tr('Applied. The original is kept in {0}', bak), foreground='#3fb950')
        self.result_file = self.path; self.open_btn.config(state='normal')
        try: self.app.ai_applied(self.path)
        except Exception: log.exception('ai_applied')
        return bak
    def discard(self, quiet=False):
        if self.fix and self.fix.get('work'): self.ai.discard(self.fix['work'])
        self.fix = None; self.apply_btn.config(state='disabled'); self.discard_btn.config(state='disabled')
        if not quiet: self.status.config(text=tr('Discarded: the scene is unchanged.'), foreground='')

    # -------------------------------------------------- YouTube text
    def start_meta(self, ask=None):
        if self.thread and self.thread.is_alive() or not self.mp4: return None
        replace = False
        if os.path.isfile(os.path.join(os.path.dirname(self.mp4), 'metadata.txt')):
            a = (ask or messagebox.askyesnocancel)('YouTube text', 'metadata.txt is already next to this video.\n\nYes = replace it '
                                                   '(the old one is kept in .shadow_backup)\nNo = write metadata_2.txt beside it', parent=self.top)
            if a is None: return None
            replace = bool(a)
        notes = '\n'.join(self.note_lines()); self.busy(True); self.write('', clear=True)
        scene = self.path if self.html else None
        task = self.new_task('English')
        def run():
            try: r = self.ai.write_metadata(self.mp4, scene=scene, notes=notes, replace=replace, task=task, progress=lambda s: self.q.put(('status', s)))
            except Exception as e:
                log.exception('AI metadata'); r = dict(ok=False, path=None, text='', summary='', error=f'{type(e).__name__}: {e}')
            self.q.put(('meta_done', r))
        self.thread = threading.Thread(target=run, daemon=True); self.thread.start()
        return self.thread
    def meta_done(self, r):
        self.busy(False)
        if r.get('text'): self.write('\n' + r['text'] + '\n')
        if r['ok']: self.status.config(text=tr('Written: {0}  (YouTube... uses metadata.txt)', r['path']), foreground='#3fb950')
        else: self.status.config(text=tr('No YouTube text: {0}', r.get('error')), foreground='#f85149')
        if r.get('path'): self.result_file = r['path']; self.open_btn.config(state='normal')
        log.info('AI metadata %s: ok=%s path=%s error=%s', self.mp4, r['ok'], r.get('path'), r.get('error'))

    # -------------------------------------------------- common
    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'status': self.status.config(text=m[1], foreground='')
                elif m[0] == 'ev':
                    if m[1] == 'text': self.write(m[2])
                    elif m[1] == 'tool': self.write(f'\n[{m[2]}]\n')
                    elif m[1] == 'denied': self.write(f'\n[refused: {m[2]}]\n')
                    elif m[1] == 'status': self.status.config(text=m[2], foreground='')
                elif m[0] == 'fix_done': self.fix_done(m[1])
                elif m[0] == 'meta_done': self.meta_done(m[1])
        except Exception as e:
            if type(e).__name__ != 'Empty': log.exception('AI window')
        try:
            if self.top.winfo_exists(): self.top.after(150, self._poll)
        except tk.TclError:
            pass
    def stop(self):
        if self.task: self.task.stop()
        self.status.config(text=tr('Stopping...'), foreground='')
    def open_result(self):
        if self.result_file: open_path(self.result_file)
    def close(self):
        if self.thread and self.thread.is_alive(): self.stop()
        if self.fix and self.fix.get('work'): self.ai.discard(self.fix['work'])
        self.top.destroy()
class NewVideoDialog:
    """New video (AI) (3.19): an idea -> ai_tasks.new_video() -> a new scene folder under the chosen folder (the narration,
    the voice + word timings when a Kokoro voice is installed, and the scene, checked by Shadow) -> added to the queue.
    The work runs in a thread; this window polls its own queue. app.ai_task_kw / app.ai_check / app.ai_voice: tests."""
    def __init__(self, app):
        import queue
        import ai_tasks
        self.app, self.ai, self.q = app, ai_tasks, queue.Queue()
        self.task = None; self.thread = None; self.result = None
        t = self.top = tk.Toplevel(app); t.title(tr('New video (AI)')); t.transient(app); t.minsize(680, 560)
        f = ttk.Frame(t, padding=14); f.pack(fill='both', expand=True); f.columnconfigure(1, weight=1)
        ttk.Label(f, text=tr('Your idea (any language): what the video is about, and anything it must show or say')).grid(row=0, column=0, columnspan=3, sticky='w')
        self.idea = tk.Text(f, height=4, wrap='word', relief='solid', borderwidth=1, padx=8, pady=6, font='SunValleyBodyFont', undo=True); self.idea.grid(row=1, column=0, columnspan=3, sticky='nsew', pady=(2, 8))
        style_input(self.idea, app.theme == 'dark', hint=tr('Type or paste your idea here...'))   # 3.35: clearly a box to type in
        self.style = tk.StringVar(value=app.cfg_ai.get('style') if app.cfg_ai.get('style') in ai_tasks.STYLES else next(iter(ai_tasks.STYLES)))
        self.length = tk.StringVar(value=app.cfg_ai.get('length') if app.cfg_ai.get('length') in ai_tasks.LENGTHS else '1 minute')
        self.voice = tk.BooleanVar(value=app.cfg_ai.get('voice', True))
        self.root = tk.StringVar(value=app.cfg_ai.get('dir') or os.path.join(os.path.expanduser('~'), 'Videos', 'Seekframe scenes'))
        for r, (lbl, var, vals) in enumerate((('Style', self.style, list(ai_tasks.STYLES)), ('Length', self.length, list(ai_tasks.LENGTHS))), start=2):
            ttk.Label(f, text=tr(lbl)).grid(row=r, column=0, sticky='w', pady=3)
            i18n.Combo(f, var, vals, width=34).grid(row=r, column=1, sticky='w', padx=8)
        self.voice_py = getattr(app, 'ai_voice', None)
        self.voice_cb = ttk.Checkbutton(f, text=tr('English voice + word captions (Kokoro, free, on this PC)'), variable=self.voice)
        self.voice_cb.grid(row=4, column=0, columnspan=2, sticky='w', pady=3)
        self.voice_lbl = ttk.Label(f, text=tr('looking for the voice...'), foreground='#888'); self.voice_lbl.grid(row=4, column=2, sticky='w')
        ttk.Label(f, text=tr('Save scenes in')).grid(row=5, column=0, sticky='w', pady=3)
        ttk.Entry(f, textvariable=self.root).grid(row=5, column=1, sticky='we', padx=8)
        ttk.Button(f, text=tr('Choose...'), command=self.choose_root).grid(row=5, column=2, sticky='w')
        hold = ttk.Frame(f); hold.grid(row=6, column=0, columnspan=3, sticky='w', pady=8)
        self.picker = AIPicker(hold, app, on_change=self._ai_hint); self.picker.frame.pack(anchor='w')
        bt = ttk.Frame(hold); bt.pack(anchor='w', pady=(8, 0))
        self.go_btn = ttk.Button(bt, text=tr('Make the video'), style='Accent.TButton', command=self.start); self.go_btn.pack(side='left')
        self.stop_btn = ttk.Button(bt, text=tr('Stop'), command=self.stop, state='disabled'); self.stop_btn.pack(side='left', padx=(6, 0))
        self.hint_lbl = ttk.Label(bt, text='', foreground='#888'); self.hint_lbl.pack(side='left', padx=(10, 0)); self._ai_hint()
        sr = ttk.Frame(f); sr.grid(row=7, column=0, columnspan=3, sticky='w')
        self.working = Working(sr); self.working.frame.pack(side='left')
        self.status = ttk.Label(sr, text=''); self.status.pack(side='left', padx=(8, 0))
        self.out = tk.Text(f, height=12, wrap='word', state='disabled', relief='solid', borderwidth=1, padx=8, pady=6, font='SunValleyBodyFont'); self.out.grid(row=8, column=0, columnspan=3, sticky='nsew', pady=(4, 0))
        style_output(self.out, app.theme == 'dark')   # the progress log: flat, nothing to type in
        f.rowconfigure(8, weight=1)
        ab = ttk.Frame(f); ab.grid(row=9, column=0, columnspan=3, sticky='e', pady=(10, 0))
        self.check_btn = ttk.Button(ab, text=tr('Check frames'), command=self.check, state='disabled'); self.check_btn.pack(side='left')
        self.folder_btn = ttk.Button(ab, text=tr('Open folder'), command=self.open_folder, state='disabled'); self.folder_btn.pack(side='left', padx=(6, 0))
        ttk.Button(ab, text=tr('Close'), command=self.close).pack(side='left', padx=(6, 0))
        t.protocol('WM_DELETE_WINDOW', self.close); t.bind('<Escape>', lambda e: self.close())
        dark_titlebar(t, app.theme == 'dark')
        t.after(150, lambda: t.winfo_exists() and self.idea.focus_set())   # the cursor starts in the idea box
        if self.voice_py is None:   # finding a Python with Kokoro takes a few seconds: not on the UI thread
            threading.Thread(target=lambda: self.q.put(('voice', ai_tasks.find_voice_python(app.cfg_ai.get('voice_python')))), daemon=True).start()
        else:
            self.q.put(('voice', self.voice_py or None))
        self._poll()

    def choose_root(self):
        d = filedialog.askdirectory(parent=self.top, initialdir=self.root.get())
        if d: self.root.set(d)
    def write(self, s, clear=False):
        self.out.config(state='normal')
        if clear: self.out.delete('1.0', 'end')
        self.out.insert('end', s); self.out.see('end'); self.out.config(state='disabled')
    def busy(self, on):
        self.go_btn.config(state='disabled' if on else 'normal'); self.stop_btn.config(state='normal' if on else 'disabled')
        (self.working.start if on else self.working.stop)(); self.picker.lock(on)
    def _ai_hint(self):
        if hasattr(self, 'hint_lbl'):
            self.hint_lbl.config(text=tr('{0} writes the script and the scene; Seekframe makes the voice and checks every frame.', self.ai.ai_name()))

    def start(self):
        if self.thread and self.thread.is_alive(): return None
        idea = self.idea.get('1.0', 'end').strip()
        if not idea: self.status.config(text=tr('Write the idea first.'), foreground='#f85149'); return None
        root = self.root.get().strip()
        try: os.makedirs(root, exist_ok=True)
        except OSError as e: self.status.config(text=tr('Cannot use that folder: {0}', e), foreground='#f85149'); return None
        self.app.cfg_ai.update(style=self.style.get(), length=self.length.get(), voice=self.voice.get(), dir=root)
        voice_py = self.voice_py if self.voice.get() else None
        self.busy(True); self.write('', clear=True); self.result = None
        self.check_btn.config(state='disabled'); self.folder_btn.config(state='disabled')
        check = getattr(self.app, 'ai_check', None)
        if check is None:
            import frame_check
            kw = dict(getattr(self.app, 'check_kw', {}))
            check = lambda p, cancel=None: frame_check.check(p, cancel=cancel, **kw)
        self.task = self.ai.Task(root, (), on_event=lambda *e: self.q.put(('ev',) + e), lang='the language of the idea',
                                 **dict(getattr(self.app, 'ai_task_kw', {})))
        args = dict(style=self.style.get(), seconds=self.ai.LENGTHS[self.length.get()], voice=bool(voice_py), voice_py=voice_py,
                    task=self.task, check=check, progress=lambda s: self.q.put(('status', s)))
        if getattr(self.app, 'ai_voice_maker', None): args['voice_maker'] = self.app.ai_voice_maker
        def run():
            try: r = self.ai.new_video(idea, root, **args)
            except Exception as e:
                log.exception('new video'); r = dict(ok=False, scene=None, folder=None, error=f'{type(e).__name__}: {e}', summary='', problems=[])
            self.q.put(('done', r))
        self.thread = threading.Thread(target=run, daemon=True); self.thread.start()
        return self.thread

    def done(self, r):
        self.busy(False); self.result = r
        if r.get('summary'): self.write('\n\n' + r['summary'].strip() + '\n')
        scene = r.get('scene')
        if scene and os.path.isfile(scene) and r.get('ok'):
            self.app._add(scene); self.app.refresh_audio()
            self.status.config(text=f'Ready: {os.path.basename(scene)} is in the queue ({r.get("duration")} s'
                               + (', with voice + captions' if r.get('words') else '') + '). Look at it, then Render.', foreground='#3fb950')
        elif scene and os.path.isfile(scene):
            left = r.get('problems') or []
            self.status.config(text=tr('Made, but not clean: {0}. Use AI... > Fix, or Check frames.', r.get('error') or '; '.join(left[:2])), foreground='#f85149')
            if r.get('error') != 'stopped': self.app._add(scene); self.app.refresh_audio()
        else:
            self.status.config(text=tr('No video: {0}', r.get('error')), foreground='#f85149')
        st = 'normal' if scene and os.path.isfile(scene) else 'disabled'
        self.check_btn.config(state=st); self.folder_btn.config(state='normal' if r.get('folder') else 'disabled')
        log.info('new video: ok=%s scene=%s rounds=%s left=%s error=%s', r.get('ok'), scene, r.get('rounds'), r.get('problems'), r.get('error'))
    def check(self):
        if self.result and self.result.get('scene'): self.app.check_frames([self.result['scene']])
    def open_folder(self):
        if self.result and self.result.get('folder'): open_path(self.result['folder'])

    def _poll(self):
        import queue as _q
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'status': self.status.config(text=m[1], foreground='')
                elif m[0] == 'voice':
                    self.voice_py = m[1]
                    if m[1]: self.voice_lbl.config(text=tr('voice found'))
                    else:
                        self.voice.set(False); self.voice_cb.config(state='disabled')
                        self.voice_lbl.config(text=tr('not installed: music only (see the guide to add a voice)'))
                elif m[0] == 'ev':
                    if m[1] == 'text': self.write(m[2])
                    elif m[1] == 'tool': self.write(f'\n[{m[2]}]\n')
                    elif m[1] == 'denied': self.write(f'\n[refused: {m[2]}]\n')
                    elif m[1] == 'status': self.status.config(text=m[2], foreground='')
                elif m[0] == 'done': self.done(m[1])
        except _q.Empty:
            pass
        except Exception:
            log.exception('new video window')
        try:
            if self.top.winfo_exists(): self.top.after(150, self._poll)
        except tk.TclError:
            pass
    def stop(self):
        if self.task: self.task.stop()
        self.status.config(text=tr('Stopping...'), foreground='')
    def close(self):
        if self.thread and self.thread.is_alive(): self.stop()
        self.top.destroy()


class CloudDialog:
    """3.33 "Cloud...": browse a signed-in cloud account (cloud.py / rclone) and add scenes or videos to the queue.
    A chosen file brings its whole folder (a scene needs the song, voice and pictures next to it) into
    <Videos>\\Seekframe cloud\\<Provider>\\<path>; at the top of an account only the chosen files come (not the whole
    drive). A chosen folder is downloaded and its scenes are added like Add folder. Listing and downloading run in a
    thread; open(path) / add() are the handlers (tests call them with wait=True)."""
    BIG = 1 << 30   # ask before downloading more than 1 GB

    def __init__(self, app, rc=None, accounts=None):
        import cloud
        self.app, self.cloud = app, cloud
        self.rc = rc or cloud.Rclone()
        accts = accounts if accounts is not None else self.rc.accounts()
        self.keys = [k for k, _, _, _ in cloud.PROVIDERS if k in accts]
        self.path = ''; self.items = []; self.busy = False; self.cancel = threading.Event()
        t = self.top = tk.Toplevel(app); t.title(tr('Add from the cloud')); t.transient(app); t.geometry('760x520'); t.minsize(560, 360)
        f = ttk.Frame(t, padding=12); f.pack(fill='both', expand=True)
        top = ttk.Frame(f); top.pack(fill='x')
        self.acct = tk.StringVar(value=cloud.LABEL[self.keys[0]] if self.keys else '')
        self.acct_box = ttk.Combobox(top, textvariable=self.acct, values=[cloud.LABEL[k] for k in self.keys], state='readonly', width=18)
        self.acct_box.pack(side='left'); self.acct_box.bind('<<ComboboxSelected>>', lambda e: self.open(''))
        ttk.Button(top, text=tr('Up'), command=self.go_up).pack(side='left', padx=6)
        self.path_lbl = ttk.Label(top, text='/', foreground='#888'); self.path_lbl.pack(side='left', padx=6)
        box = ttk.Frame(f); box.pack(fill='both', expand=True, pady=8)
        self.tree = ttk.Treeview(box, columns=('size', 'date'), selectmode='extended')
        self.tree.heading('#0', text=tr('Name')); self.tree.heading('size', text=tr('Size')); self.tree.heading('date', text=tr('Modified'))
        self.tree.column('#0', width=420); self.tree.column('size', width=90, anchor='e'); self.tree.column('date', width=140)
        sb = ttk.Scrollbar(box, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.bind('<Double-1>', lambda e: self.open_selected())
        self.bar = ttk.Progressbar(f, maximum=1000); self.bar.pack(fill='x')
        bt = ttk.Frame(f); bt.pack(fill='x', pady=(8, 0))
        self.status = ttk.Label(bt, text=tr('Pick a scene, a video or a folder. Its whole folder is downloaded with it.'), foreground='#888')
        self.status.pack(side='left')
        ttk.Button(bt, text=tr('Close'), command=self.close).pack(side='right')
        self.add_btn = ttk.Button(bt, text=tr('Add to queue'), style='Accent.TButton', command=self.add); self.add_btn.pack(side='right', padx=6)
        t.protocol('WM_DELETE_WINDOW', self.close); t.bind('<Escape>', lambda e: self.close())
        dark_titlebar(t, app.theme == 'dark')
        if self.keys: self.open('')
        else: self.status.config(text=tr('Sign in to a cloud account first (Settings > Cloud accounts).'), foreground='#d29922')

    def key(self):
        return next((k for k in self.keys if self.cloud.LABEL[k] == self.acct.get()), None)

    def _bg(self, work, done, wait=False):
        """work() in a thread, done(result or exception) back on the Tk thread; wait=True runs both here (tests)."""
        if wait:
            try: res = work()
            except Exception as e: res = e
            done(res); return
        def run():
            try: res = work()
            except Exception as e: res = e
            try: self.top.after(0, lambda: done(res))
            except Exception: pass
        threading.Thread(target=run, daemon=True).start()

    def open(self, path, wait=False):
        key = self.key()
        if not key: return
        self.status.config(text=tr('Loading...'), foreground='#888')
        def show(res):
            if isinstance(res, Exception):
                self.status.config(text=tr('Could not open the folder: {0}', res), foreground='#f85149'); return
            self.path, self.items = path, res
            self.path_lbl.config(text='/' + path)
            self.tree.delete(*self.tree.get_children())
            for i, d in enumerate(res):
                name = ('📁 ' if d.get('IsDir') else '') + d.get('Name', '')
                size = '' if d.get('IsDir') else _size(d.get('Size', 0))
                self.tree.insert('', 'end', iid=str(i), text=name, values=(size, (d.get('ModTime') or '')[:16].replace('T', ' ')))
            self.status.config(text=tr('{0} items', len(res)), foreground='#888')
        self._bg(lambda: self.rc.listdir(key, path), show, wait)

    def go_up(self):
        if self.path: self.open('/'.join(self.path.split('/')[:-1]))

    def full(self, d):
        return f"{self.path}/{d['Name']}" if self.path else d['Name']

    def open_selected(self):
        sel = self.tree.selection()
        if len(sel) == 1 and self.items[int(sel[0])].get('IsDir'): self.open(self.full(self.items[int(sel[0])]))

    def add(self, wait=False, ask=None):
        """Download what is selected and add it to the queue. Returns the local files added (filled when wait=True)."""
        key = self.key(); items = [self.items[int(i)] for i in self.tree.selection()]
        if not key or not items or self.busy: return []
        okext = self.cloud.SCENE_EXT + self.cloud.MEDIA_EXT
        folders = sorted({self.full(d) for d in items if d.get('IsDir')})
        files = [self.full(d) for d in items if not d.get('IsDir') and os.path.splitext(d['Name'])[1].lower() in okext]
        if not folders and not files:
            self.status.config(text=tr('Pick a scene (.html / .blend), a video or a folder.'), foreground='#d29922'); return []
        # (remote path, local target, one file?): a file brings its whole folder, except at the top of the account
        if files and self.path:
            jobs = [(j, self.cloud.cache_dir(key, j), False) for j in sorted(set(folders) | {self.path})]
        else:
            jobs = [(j, self.cloud.cache_dir(key, j), False) for j in folders] + \
                   [(p, os.path.join(self.cloud.cache_dir(key, ''), os.path.basename(p)), True) for p in files]
        here = self.cloud.cache_dir(key, self.path)
        self.busy = True; self.add_btn.state(['disabled']); self.cancel.clear()
        out = []
        def work():
            sizes = [self.rc.size(key, j)[0] for j, _, _ in jobs]; total = sum(sizes)
            if total > self.BIG and not (ask or (lambda: messagebox.askyesno(tr('Add from the cloud'), tr('This downloads {0}. Continue?', _size(total)), parent=self.top)))():
                return 'no'
            base = 0
            for (j, dest, one), sz in zip(jobs, sizes):
                if wait: prog = lambda a, b: None
                else: prog = lambda a, b, base=base: self.top.after(0, lambda: self.bar.config(value=1000 * (base + a) / max(total, 1)))
                ok, msg = self.rc.copy(f'{key}:{j}', dest, progress=prog, cancel=self.cancel, one_file=one)
                if not ok: raise RuntimeError(msg)
                base += sz
            return 'ok'
        def finish(res):
            self.busy = False; self.add_btn.state(['!disabled']); self.bar.config(value=0)
            if res == 'no': self.status.config(text=tr('Nothing downloaded.'), foreground='#888'); return
            if isinstance(res, Exception):
                self.status.config(text=tr('Download failed: {0}', res), foreground='#f85149'); return
            before = set(self.app.files)
            for p in files: self.app._add(os.path.join(here, os.path.basename(p)))
            for d in folders: self.app.add_folder(self.cloud.cache_dir(key, d), ask=ask)
            out.extend(f for f in self.app.files if f not in before)
            self.status.config(text=tr('{0} added to the queue.', len(out)), foreground='#3fb950')
        self._bg(work, finish, wait)
        return out

    def close(self):
        self.cancel.set()
        try: self.top.destroy()
        except tk.TclError: pass


def _size(n):
    n = float(n or 0)
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB': return f'{n:.0f} {u}' if u == 'B' else f'{n:.1f} {u}'
        n /= 1024
