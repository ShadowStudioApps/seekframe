"""Tests must never open a real window on the owner's screen (a file picker popped up during a test run on 2026-11-20).
block(app) replaces every tkinter message box and file dialog the app can reach with a stand-in that records the call
and answers like the user pressed Cancel / No. Tests that need their own answers patch those functions after this."""
CALLS = []

def block(app):
    for n in ('showinfo', 'showwarning', 'showerror'):
        setattr(app.messagebox, n, (lambda n: lambda *a, **k: CALLS.append(n))(n))
    for n in ('askyesno', 'askokcancel', 'askretrycancel'):
        setattr(app.messagebox, n, (lambda n: lambda *a, **k: CALLS.append(n) or False)(n))
    app.messagebox.askyesnocancel = lambda *a, **k: CALLS.append('askyesnocancel') or None
    for n in ('askopenfilename', 'asksaveasfilename', 'askdirectory'):
        setattr(app.filedialog, n, (lambda n: lambda *a, **k: CALLS.append(n) or '')(n))
    app.filedialog.askopenfilenames = lambda *a, **k: CALLS.append('askopenfilenames') or ()
    app.notify = lambda *a, **k: CALLS.append('notify')   # 3.32: no real Windows notification either
    return CALLS
