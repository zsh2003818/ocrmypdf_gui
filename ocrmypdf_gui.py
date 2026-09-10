import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import os
import sys
import threading
import queue

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
def get_installed_languages():
    try:
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        langs = [l.strip() for l in lines[1:] if l.strip() and l.strip() != "osd"]
        return langs if langs else ["eng"]
    except Exception:
        return ["eng"]


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.process = None          # currently running subprocess.Popen, or None
        self.worker_thread = None
        self.msg_queue = queue.Queue()
        self.is_overwrite_run = False
        self.tmp_output = None
        self.final_output = None


state = AppState()

# ---------------------------------------------------------------------------
# GUI helpers (file pickers / fields)
# ---------------------------------------------------------------------------
def select_input():
    path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if not path:
        return
    set_input_output(path)


def set_entry_text(entry, text):
    """Write into an Entry regardless of its current (possibly disabled) state."""
    prev_state = entry.cget("state")
    entry.configure(state="normal")
    entry.delete(0, tk.END)
    entry.insert(0, text)
    entry.configure(state=prev_state)


def set_input_output(path):
    input_entry.delete(0, tk.END)
    input_entry.insert(0, path)

    if overwrite_var.get():
        set_entry_text(output_entry, path)
    else:
        folder = os.path.dirname(path)
        name = os.path.splitext(os.path.basename(path))[0]
        output_path = os.path.join(folder, f"{name} -ocr.pdf")
        set_entry_text(output_entry, output_path)


def select_output():
    path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
    if not path:
        return
    output_entry.delete(0, tk.END)
    output_entry.insert(0, path)


def update_output_field_state():
    """When overwriting, the output path is always == input path, so make the
    field greyed-out/uneditable rather than leaving a stale, misleading path
    the user could edit."""
    if overwrite_var.get():
        output_entry.configure(state="disabled")
        browse_out_btn.configure(state=tk.DISABLED)
    else:
        output_entry.configure(state="normal")
        browse_out_btn.configure(state=tk.NORMAL)


def on_overwrite_toggle():
    update_output_field_state()
    input_path = input_entry.get()
    if input_path:
        set_input_output(input_path)


def open_output():
    path = output_entry.get()
    if not os.path.exists(path):
        messagebox.showerror("Error", "Output file does not exist.")
        return
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open file: {e}")


# ---------------------------------------------------------------------------
# Command construction (shared by Run and Copy-to-clipboard)
# ---------------------------------------------------------------------------
def format_command(cmd_list):
    """Convert command list to a copyable, shell-quoted-ish string."""
    parts = []
    for c in cmd_list:
        if " " in c or c == "":
            parts.append(f'"{c}"')
        else:
            parts.append(c)
    return " ".join(parts)


def build_command():
    """
    Returns (cmd_list, is_overwrite, actual_output, final_output) or None (with
    an error already shown to the user) if inputs are invalid.
    """
    input_file = input_entry.get().strip()
    output_file = output_entry.get().strip()

    if not input_file or not output_file:
        messagebox.showerror("Error", "Please select input and output files.")
        return None

    selected = [lang for lang, var in lang_vars.items() if var.get()]
    if not selected:
        messagebox.showerror("Error", "Please select at least one language.")
        return None

    lang_string = "+".join(selected)
    cmd = ["ocrmypdf", "-l", lang_string]

    cmd += ["--mode", mode_var.get()]

    opt_level = optimize_var.get()
    if opt_level == 1:
        cmd += ["--optimize", "1"]
    elif opt_level == 2:
        cmd += ["--optimize", "2"]
    elif opt_level == 3:
        cmd += ["--optimize", "3", "--fast-web-view", "0"]

    cmd += ["--output-type", output_type_var.get()]

    pages_value = pages_entry.get().strip()
    if pages_value:
        cmd += ["--pages", pages_value]

    is_overwrite = (os.path.abspath(input_file) == os.path.abspath(output_file))
    actual_output = output_file
    if is_overwrite:
        actual_output = output_file + ".tmp.pdf"

    cmd += [input_file, actual_output]
    return cmd, is_overwrite, actual_output, output_file


def copy_command():
    result = build_command()
    if result is None:
        return
    cmd, _, _, _ = result
    cmd_str = format_command(cmd)
    root.clipboard_clear()
    root.clipboard_append(cmd_str)
    # On some Linux setups the clipboard is only kept alive while the app has
    # focus / the event loop is spinning; update() flushes it to the system
    # clipboard so it survives even if the app closes right after.
    root.update()
    status_var.set("Command copied to clipboard.")


# ---------------------------------------------------------------------------
# OCR execution: runs in a background thread, communicates via a queue.
# Nothing in the worker thread touches Tkinter widgets directly - this is
# what keeps the UI responsive (and therefore stable) on long PDFs, and it
# avoids the old pattern of calling widget.update() once per output line,
# which could freeze the UI long enough for a user to double-click "Run OCR"
# and start a second process against the same temp file.
# ---------------------------------------------------------------------------
def ocr_worker(cmd, is_overwrite, actual_output, final_output):
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        state.process = process

        for line in process.stdout:
            state.msg_queue.put(("line", line))

        returncode = process.wait()
        state.process = None

        if returncode == 0:
            if is_overwrite:
                try:
                    os.replace(actual_output, final_output)
                except Exception as replace_err:
                    if os.path.exists(actual_output):
                        try:
                            os.remove(actual_output)
                        except OSError:
                            pass
                    state.msg_queue.put(("error", f"Failed to overwrite original file: {replace_err}"))
                    return
            state.msg_queue.put(("done", 0))
        else:
            if is_overwrite and os.path.exists(actual_output):
                try:
                    os.remove(actual_output)
                except OSError:
                    pass
            state.msg_queue.put(("done", returncode))

    except FileNotFoundError:
        state.msg_queue.put(("error", "Could not find 'ocrmypdf'. Is it installed and on your PATH?"))
    except Exception as e:
        if is_overwrite and os.path.exists(actual_output):
            try:
                os.remove(actual_output)
            except OSError:
                pass
        state.msg_queue.put(("error", f"OCR failed: {e}"))


def poll_queue():
    """Runs on the main thread via root.after; drains the queue safely."""
    try:
        while True:
            kind, payload = state.msg_queue.get_nowait()
            if kind == "line":
                text_output.insert(tk.END, payload)
                text_output.see(tk.END)
            elif kind == "done":
                progress_bar.stop()
                set_running(False)
                if payload == 0:
                    status_var.set("Finished successfully.")
                    messagebox.showinfo("Finished", "OCR and optimization completed successfully.")
                else:
                    status_var.set(f"OCR failed (exit code {payload}).")
                    messagebox.showerror("Error", "OCR failed. See output above.")
            elif kind == "error":
                progress_bar.stop()
                set_running(False)
                status_var.set("Error.")
                messagebox.showerror("Error", payload)
    except queue.Empty:
        pass
    root.after(75, poll_queue)


def set_running(running):
    # output_entry / browse_out_btn are handled separately below, since their
    # enabled state also depends on the "Overwrite" checkbox.
    state_widgets = [run_button, input_entry, browse_in_btn, overwrite_chk, copy_btn, pages_entry]
    for w in state_widgets:
        w.configure(state=(tk.DISABLED if running else tk.NORMAL))
    for chk in lang_checkbuttons:
        chk.configure(state=(tk.DISABLED if running else tk.NORMAL))
    for rb in mode_radios:
        rb.configure(state=(tk.DISABLED if running else tk.NORMAL))
    for rb in optimize_radios:
        rb.configure(state=(tk.DISABLED if running else tk.NORMAL))
    for rb in output_type_radios:
        rb.configure(state=(tk.DISABLED if running else tk.NORMAL))
    stop_button.configure(state=(tk.NORMAL if running else tk.DISABLED))

    if running:
        output_entry.configure(state="disabled")
        browse_out_btn.configure(state=tk.DISABLED)
    else:
        update_output_field_state()


def run_ocr():
    if state.process is not None:
        # Guard against re-entrancy even if a stray event slips through.
        return

    result = build_command()
    if result is None:
        return
    cmd, is_overwrite, actual_output, final_output = result

    text_output.delete(1.0, tk.END)
    text_output.insert(tk.END, "=== Command ===\n")
    text_output.insert(tk.END, format_command(cmd) + "\n\n")
    text_output.insert(tk.END, "=== Output ===\n")
    text_output.see(tk.END)

    set_running(True)
    status_var.set("Running OCR...")
    progress_bar.start(12)

    state.worker_thread = threading.Thread(
        target=ocr_worker,
        args=(cmd, is_overwrite, actual_output, final_output),
        daemon=True,
    )
    state.worker_thread.start()


def stop_ocr():
    if state.process is not None:
        try:
            state.process.terminate()
            status_var.set("Stopping...")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
root = tk.Tk()
root.title("OCRmyPDF GUI")
root.geometry("780x780")
root.minsize(680, 680)

style = ttk.Style()
try:
    style.theme_use("clam")
except tk.TclError:
    pass
style.configure("TLabelframe", padding=8)
style.configure("TButton", padding=4)

root.columnconfigure(0, weight=1)
root.rowconfigure(2, weight=1)

# --- Files frame ---
files_frame = ttk.LabelFrame(root, text="Files")
files_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
files_frame.columnconfigure(1, weight=1)

ttk.Label(files_frame, text="Input PDF").grid(row=0, column=0, sticky="w", pady=3)
input_entry = ttk.Entry(files_frame)
input_entry.grid(row=0, column=1, sticky="ew", padx=5)
browse_in_btn = ttk.Button(files_frame, text="Browse...", command=select_input)
browse_in_btn.grid(row=0, column=2)

ttk.Label(files_frame, text="Output PDF").grid(row=1, column=0, sticky="w", pady=3)
output_entry = ttk.Entry(files_frame)
output_entry.grid(row=1, column=1, sticky="ew", padx=5)
browse_out_btn = ttk.Button(files_frame, text="Browse...", command=select_output)
browse_out_btn.grid(row=1, column=2)

overwrite_var = tk.BooleanVar(value=True)
overwrite_chk = ttk.Checkbutton(files_frame, text="Overwrite original file", variable=overwrite_var,
                                 command=on_overwrite_toggle)
overwrite_chk.grid(row=2, column=1, sticky="w", pady=(4, 0))

# --- Options frame ---
options_frame = ttk.LabelFrame(root, text="Options")
options_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
options_frame.columnconfigure(1, weight=1)

ttk.Label(options_frame, text="Languages").grid(row=0, column=0, sticky="nw")

# Language list is wrapped in a fixed-height, scrollable canvas so that
# installs with many tesseract language packs don't stretch the window's
# layout out of shape.
LANG_LIST_MAX_HEIGHT = 110

lang_outer = ttk.Frame(options_frame)
lang_outer.grid(row=0, column=1, sticky="w")

lang_canvas = tk.Canvas(lang_outer, height=LANG_LIST_MAX_HEIGHT, highlightthickness=0)
lang_scrollbar = ttk.Scrollbar(lang_outer, orient="vertical", command=lang_canvas.yview)
lang_frame = ttk.Frame(lang_canvas)

lang_frame.bind(
    "<Configure>",
    lambda e: lang_canvas.configure(scrollregion=lang_canvas.bbox("all")),
)
lang_canvas.create_window((0, 0), window=lang_frame, anchor="nw")
lang_canvas.configure(yscrollcommand=lang_scrollbar.set)


def _on_lang_mousewheel(event):
    # Cross-platform mouse wheel handling (Windows/Mac send delta, Linux sends Button-4/5).
    if event.num == 4:
        lang_canvas.yview_scroll(-1, "units")
    elif event.num == 5:
        lang_canvas.yview_scroll(1, "units")
    else:
        lang_canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")


def _bind_lang_scroll(_event=None):
    lang_canvas.bind_all("<MouseWheel>", _on_lang_mousewheel)
    lang_canvas.bind_all("<Button-4>", _on_lang_mousewheel)
    lang_canvas.bind_all("<Button-5>", _on_lang_mousewheel)


def _unbind_lang_scroll(_event=None):
    lang_canvas.unbind_all("<MouseWheel>")
    lang_canvas.unbind_all("<Button-4>")
    lang_canvas.unbind_all("<Button-5>")


lang_canvas.bind("<Enter>", _bind_lang_scroll)
lang_canvas.bind("<Leave>", _unbind_lang_scroll)

installed_languages = get_installed_languages()
lang_vars = {}
lang_checkbuttons = []
cols = 4
for i, lang in enumerate(installed_languages):
    var = tk.BooleanVar(value=(lang == "eng"))
    chk = ttk.Checkbutton(lang_frame, text=lang, variable=var)
    chk.grid(row=i // cols, column=i % cols, sticky="w", padx=(0, 12), pady=1)
    lang_vars[lang] = var
    lang_checkbuttons.append(chk)

# Only show the scrollbar (and cap the height) once there's enough content
# to actually need it, so small installs still look clean and compact.
lang_canvas.update_idletasks()
if lang_canvas.bbox("all") and lang_canvas.bbox("all")[3] > LANG_LIST_MAX_HEIGHT:
    lang_canvas.grid(row=0, column=0)
    lang_scrollbar.grid(row=0, column=1, sticky="ns")
else:
    lang_canvas.configure(height=lang_canvas.bbox("all")[3] if lang_canvas.bbox("all") else LANG_LIST_MAX_HEIGHT)
    lang_canvas.grid(row=0, column=0)

ttk.Label(options_frame, text="Mode").grid(row=1, column=0, sticky="nw", pady=(8, 0))
mode_frame = ttk.Frame(options_frame)
mode_frame.grid(row=1, column=1, sticky="w", pady=(8, 0))
mode_var = tk.StringVar(value="force")
mode_options = [
    ("default", "Default  (error if the PDF already has text)"),
    ("force", "Force OCR  (rasterize everything, re-OCR from scratch)"),
    ("skip", "Skip text pages  (OCR only pages without existing text)"),
    ("redo", "Redo OCR  (replace an existing OCR text layer)"),
]
mode_radios = []
for i, (val, label) in enumerate(mode_options):
    rb = ttk.Radiobutton(mode_frame, text=label, variable=mode_var, value=val)
    rb.grid(row=i, column=0, sticky="w")
    mode_radios.append(rb)

ttk.Label(options_frame, text="Compression").grid(row=2, column=0, sticky="w", pady=(8, 0))
optimize_frame = ttk.Frame(options_frame)
optimize_frame.grid(row=2, column=1, sticky="w", pady=(8, 0))
optimize_var = tk.IntVar(value=1)  # True lossless per OCRmyPDF docs (--optimize 1)
optimize_labels = [("None", 0), ("Lossless", 1), ("Lossy", 2), ("Aggressive", 3)]
optimize_radios = []
for i, (label, val) in enumerate(optimize_labels):
    rb = ttk.Radiobutton(optimize_frame, text=label, variable=optimize_var, value=val)
    rb.grid(row=0, column=i, sticky="w", padx=(0, 10))
    optimize_radios.append(rb)

ttk.Label(options_frame, text="Output type").grid(row=3, column=0, sticky="w", pady=(8, 0))
output_type_frame = ttk.Frame(options_frame)
output_type_frame.grid(row=3, column=1, sticky="w", pady=(8, 0))
output_type_var = tk.StringVar(value="auto")
output_type_options = [
    ("auto", "auto  (fast, PDF/A when possible)"),
    ("pdfa", "pdfa  (always via Ghostscript)"),
    ("pdf", "pdf  (never PDF/A, fastest)"),
]
output_type_radios = []
for i, (val, label) in enumerate(output_type_options):
    rb = ttk.Radiobutton(output_type_frame, text=label, variable=output_type_var, value=val)
    rb.grid(row=i, column=0, sticky="w")
    output_type_radios.append(rb)

ttk.Label(options_frame, text="Pages").grid(row=4, column=0, sticky="w", pady=(8, 0))
pages_entry = ttk.Entry(options_frame)
pages_entry.grid(row=4, column=1, sticky="ew", pady=(8, 0))
ttk.Label(
    options_frame,
    text="Optional — e.g. 2,3,13-17  or  3-end  or  end. Leave blank to OCR the whole file.",
    foreground="#666666",
).grid(row=5, column=1, sticky="w")

# --- Actions row ---
actions_frame = ttk.Frame(root)
actions_frame.grid(row=2, column=0, sticky="new", padx=10, pady=(0, 5))
actions_frame.columnconfigure(4, weight=1)

run_button = ttk.Button(actions_frame, text="Run OCR", command=run_ocr)
run_button.grid(row=0, column=0, padx=(0, 6))

stop_button = ttk.Button(actions_frame, text="Stop", command=stop_ocr, state=tk.DISABLED)
stop_button.grid(row=0, column=1, padx=6)

copy_btn = ttk.Button(actions_frame, text="Copy Command", command=copy_command)
copy_btn.grid(row=0, column=2, padx=6)

open_btn = ttk.Button(actions_frame, text="Open OCR'ed File", command=open_output)
open_btn.grid(row=0, column=3, padx=6)

progress_bar = ttk.Progressbar(actions_frame, mode="indeterminate")
progress_bar.grid(row=0, column=4, sticky="ew", padx=(12, 0))

# --- Output / log frame ---
log_frame = ttk.LabelFrame(root, text="OCR Output")
log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(5, 5))
log_frame.columnconfigure(0, weight=1)
log_frame.rowconfigure(0, weight=1)
root.rowconfigure(3, weight=1)

text_output = scrolledtext.ScrolledText(log_frame, width=80, height=10, wrap="none")
text_output.grid(row=0, column=0, sticky="nsew")

# --- Status bar ---
status_var = tk.StringVar(value="Ready.")
status_bar = ttk.Label(root, textvariable=status_var, anchor="w", relief="sunken", padding=(6, 2))
status_bar.grid(row=4, column=0, sticky="ew")

# Reflect the default "Overwrite" checkbox state (greys out Output PDF).
update_output_field_state()

# --- Command line argument preload ---
if len(sys.argv) > 1:
    arg_path = sys.argv[1]
    if os.path.exists(arg_path):
        set_input_output(arg_path)

root.after(75, poll_queue)
root.mainloop()