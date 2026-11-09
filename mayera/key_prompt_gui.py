"""MAYERA - friendly pop-up box for entering the Gemini API key.

Why this exists (v2.6): the black console window does not accept
Ctrl+V paste at the hidden key prompt, which confused the user more
than once. This small tkinter window (tkinter ships with the normal
python.org installer on Windows) gives an ordinary text box instead:

  * Ctrl+V paste works exactly like everywhere else.
  * A "Dikhao" (show) tick lets the user verify what got pasted.
  * A button opens the free key page (Google AI Studio) directly.
  * SAVE returns the key to the caller, which stores it in the
    DPAPI vault (key.dat) - this module never saves anything itself.

Any failure (no tkinter, no display, ...) returns None and the
caller falls back to the console prompt, so behaviour can only
improve, never break.
"""

import os
import webbrowser

_KEY_PAGE = "https://aistudio.google.com/apikey"


def ask_key_gui():
    """Show the pop-up; return the entered key, or None."""
    if os.environ.get("MAYERA_NO_GUI") == "1":
        return None
    try:
        import tkinter as tk
    except Exception:
        return None
    result = {"key": None}
    try:
        root = tk.Tk()
        root.title("MAYERA - API Key")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        frame = tk.Frame(root, padx=18, pady=14)
        frame.pack()

        tk.Label(
            frame, justify="left", font=("Segoe UI", 10),
            text=("MAYERA ko Gemini API key chahiye.\n"
                  "Key neeche wale box me paste karein (Ctrl+V chalega),\n"
                  "phir SAVE dabayein. Key sirf is PC par save hogi.")
        ).pack(anchor="w")

        entry_var = tk.StringVar()
        entry = tk.Entry(frame, textvariable=entry_var, width=58,
                         show="\u2022", font=("Consolas", 10))
        entry.pack(pady=(10, 4))
        entry.focus_set()
        # right-click context menu with Paste, for mouse-only users
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(
            label="Paste",
            command=lambda: entry.event_generate("<<Paste>>"))

        def _popup(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        entry.bind("<Button-3>", _popup)

        show_var = tk.BooleanVar(value=False)

        def _toggle_show():
            entry.config(show="" if show_var.get() else "\u2022")
        tk.Checkbutton(frame, text="Key dikhao (check karne ke liye)",
                       variable=show_var, command=_toggle_show,
                       font=("Segoe UI", 9)).pack(anchor="w")

        buttons = tk.Frame(frame)
        buttons.pack(pady=(10, 0), fill="x")

        def _save():
            key = entry_var.get().strip()
            result["key"] = key or None
            root.destroy()

        def _cancel():
            result["key"] = None
            root.destroy()

        tk.Button(buttons, text="Key banane ki site kholo",
                  font=("Segoe UI", 9),
                  command=lambda: webbrowser.open(_KEY_PAGE)
                  ).pack(side="left")
        tk.Button(buttons, text="Cancel", font=("Segoe UI", 9),
                  command=_cancel).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="SAVE", font=("Segoe UI", 10, "bold"),
                  command=_save).pack(side="right")
        root.bind("<Return>", lambda _e: _save())
        root.bind("<Escape>", lambda _e: _cancel())
        root.protocol("WM_DELETE_WINDOW", _cancel)

        # centre on screen
        root.update_idletasks()
        w = root.winfo_reqwidth()
        h = root.winfo_reqheight()
        x = max(0, (root.winfo_screenwidth() - w) // 2)
        y = max(0, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"+{x}+{y}")
        root.mainloop()
    except Exception:
        return None
    return result["key"]
