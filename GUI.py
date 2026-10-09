"""
GUI.py — All user interface code for the unezquake installer.
==============================================================
Contains:
    - UnezquakeInstallerApp class (main window)
    - AppDialog class (centered, themed modal dialogs)
    - DPI scaling and window-centering helpers
    - Theme loading and styling
    - UI layout and event handlers

This module imports from backend.py for configuration and the BuildWorker.
"""

import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from backend import (
    BuildWorker, ReleaseInstallWorker, THEME_DIR, BUILD_TOOLS, install_mode,
    load_config, save_config, save_theme, check_dependencies,
    detect_quake_installations, inspect_install,
    fetch_latest_release, get_installed_version, is_outdated
)


# ─── DPI / geometry helpers ───────────────────────────────────────────────────

def enable_dpi_awareness():
    """Best-effort per-monitor DPI awareness.

    Windows only; must be called before any Tk window is created. Safe to call
    when awareness is already set (the call simply fails and is ignored).
    """
    if not sys.platform.startswith("win"):
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def scale_px(widget, value):
    """Scale a pixel value by the widget's UI scale factor."""
    scale = getattr(widget, "ui_scale", 1.0)
    return int(round(value * scale))


def center_window(win, width=None, height=None):
    """Center a top-level window on the screen, clamped to the visible area."""
    win.update_idletasks()
    w = width or win.winfo_reqwidth()
    h = height or win.winfo_reqheight()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    w = min(w, sw)
    h = min(h, sh)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


def center_over_parent(win, parent, width=None, height=None):
    """Center a window over its parent, clamped to the visible screen area."""
    win.update_idletasks()
    w = width or win.winfo_reqwidth()
    h = height or win.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = min(max(0, x), max(0, sw - w))
    y = min(max(0, y), max(0, sh - h))
    win.geometry(f"{w}x{h}+{x}+{y}")


# ─── Centered themed dialog ───────────────────────────────────────────────────

class AppDialog:
    """A small modal, themed dialog centered over a parent window.

    The dialog is used instead of the native `messagebox` so that it can be
    centered and styled to match the app theme. `result` is True when the user
    confirms / accepts and False otherwise.
    """

    _ICONS = {
        "info": ("ℹ", "#58a6ff"),
        "question": ("❓", "#58a6ff"),
        "warning": ("⚠", "#d29922"),
        "error": ("✖", "#f85149"),
    }

    def __init__(self, parent, title, message, kind="info",
                 confirm=False, yes_text="Yes", no_text="No", ok_text="OK"):
        self.result = False
        icon, color = self._ICONS.get(kind, self._ICONS["info"])
        px = lambda n: scale_px(parent, n)  # noqa: E731

        win = tk.Toplevel(parent)
        self.win = win
        win.title(title)
        win.transient(parent)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._cancel)

        frame = ttk.Frame(win, padding=px(20))
        frame.pack(fill=tk.BOTH, expand=True)

        heading = ttk.Label(
            frame, text=f"{icon}  {title}",
            font=("Segoe UI", 12, "bold"), foreground=color
        )
        heading.pack(anchor=tk.W, pady=(0, px(8)))

        ttk.Label(
            frame, text=message, justify=tk.LEFT, wraplength=scale_px(parent, 380)
        ).pack(anchor=tk.W)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(px(18), 0))

        if confirm:
            self.primary = ttk.Button(
                btn_row, text=yes_text, style="Action.TButton", command=self._yes
            )
            self.primary.pack(side=tk.RIGHT, padx=(px(8), 0))
            ttk.Button(btn_row, text=no_text, command=self._cancel).pack(side=tk.RIGHT)
            win.bind("<Return>", lambda e: self._yes())
            win.bind("<Escape>", lambda e: self._cancel())
        else:
            self.primary = ttk.Button(
                btn_row, text=ok_text, style="Action.TButton", command=self._ok
            )
            self.primary.pack(side=tk.RIGHT)
            win.bind("<Return>", lambda e: self._ok())
            win.bind("<Escape>", lambda e: self._ok())

        win.update_idletasks()
        w = max(win.winfo_reqwidth(), scale_px(parent, 360))
        center_over_parent(win, parent, width=w)
        win.grab_set()
        self.primary.focus_set()
        win.wait_window()

    def _ok(self):
        self.result = True
        self._close()

    def _yes(self):
        self.result = True
        self._close()

    def _cancel(self):
        self.result = False
        self._close()

    def _close(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.destroy()


# ─── Main Application ─────────────────────────────────────────────────────────

class UnezquakeInstallerApp:
    """Main application window for the unezquake installer."""

    def __init__(self):
        # DPI awareness must be set before the first Tk window is created.
        enable_dpi_awareness()

        self.root = tk.Tk()
        self.root.title("unezquake Installer")

        # DPI scaling: scale point-based fonts via Tk, and remember the factor
        # for pixel-based geometry/padding.
        self.ui_scale = self._compute_ui_scale()
        self.root.ui_scale = self.ui_scale
        self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)

        self.root.minsize(self._px(600), self._px(500))

        self.worker = None
        self.theme_mode = "dark"
        self.config = load_config()

        # Apply theme and build UI
        self._apply_theme()
        self._build_ui()

        # Center the main window on screen
        center_window(self.root, self._px(700), self._px(600))

        # Clean shutdown when the window is closed
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial log messages
        self.append_log("unezquake Installer GUI started.")
        self.append_log(f"Build source: {self.config['game_dir']}")
        self.append_log(f"Install location: {self.config['install_dir']}")
        self.append_log(f"Repository: {self.config['repo_url']}")

        # Platform / dependency information
        mode = install_mode()
        if mode == "build":
            deps = check_dependencies()
            missing = [t for t in BUILD_TOOLS if not deps.get(t)]
            if missing:
                self.append_log(f"⚠ Missing build tools: {', '.join(missing)}")
            else:
                self.append_log("✓ All required build tools detected.")
            self.append_log("Update will clone and build unezquake from source.")
        elif mode == "release":
            self.append_log(
                "Update will download the latest prebuilt unezquake client "
                "from GitHub releases."
            )
        else:
            self.append_log("⚠ This platform is not supported for installing unezquake.")
            self.append_log("  This window can still be used to configure directories.")

        # Show detected installs
        detected = detect_quake_installations()
        if detected:
            self.append_log(f"Detected {len(detected)} Quake installation(s):")
            for info in detected:
                engines = ", ".join(info["engines"]) or "unknown"
                self.append_log(f"  • {info['folder']}  ({engines})")

        self.append_log("Click 'Update' to download and build the latest version.")
        self.append_log("Use '⚙️ Settings' to change directories.")
        self.append_log("")

    # ── DPI helpers ──────────────────────────────────────────────────────

    def _compute_ui_scale(self) -> float:
        """Return a UI scale factor derived from the display DPI."""
        try:
            dpi = self.root.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        baseline = 72.0 if sys.platform == "darwin" else 96.0
        return max(0.75, min(dpi / baseline, 2.5))

    def _px(self, value: int) -> int:
        """Scale a pixel value by the UI scale factor."""
        return int(round(value * self.ui_scale))

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_theme(self):
        """Apply the configured theme, preferring the sv-ttk package."""
        style = ttk.Style(self.root)
        mode = self.config.get("theme", "dark")
        if mode not in ("dark", "light", "system"):
            mode = "dark"

        if not self._apply_sv_ttk(mode):
            self._apply_legacy_theme()
            if "clam" in style.theme_names():
                style.theme_use("clam")

        self._configure_styles(style)

    def _apply_sv_ttk(self, mode: str) -> bool:
        """Apply the Sun Valley theme through the `sv_ttk` package."""
        try:
            import sv_ttk
        except ImportError:
            return False

        if mode == "system":
            try:
                import darkdetect
                mode = "dark" if darkdetect.theme() == "Dark" else "light"
            except Exception:
                mode = "dark"

        try:
            sv_ttk.set_theme(mode)
        except Exception:
            return False

        self.theme_mode = mode
        return True

    def _apply_legacy_theme(self) -> bool:
        """Fallback for the old loose-file Sun Valley layout."""
        style = ttk.Style(self.root)
        options = (
            (THEME_DIR / "sun-valley-dark.tcl", "sun-valley-dark"),
            (THEME_DIR / "sun-valley-light.tcl", "sun-valley-light"),
        )
        for path, name in options:
            if not path.exists():
                continue
            try:
                self.root.tk.call("source", str(path))
                if name in style.theme_names():
                    style.theme_use(name)
                    self.theme_mode = name.replace("sun-valley-", "")
                    return True
            except Exception:
                continue
        return False

    def _configure_styles(self, style: ttk.Style):
        """Define custom widget styles."""
        # Console text styling
        self.console_bg = "#0d1117"
        self.console_fg = "#c9d1d9"
        self.console_font = ("Consolas", 10) if sys.platform == "win32" else ("Monospace", 10)

        # Button styles
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=self._px(8))
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=self._px(8))

        # Label styles
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 9))
        style.configure("Info.TLabel", font=("Segoe UI", 9))

    # ── UI Layout ────────────────────────────────────────────────────────

    def _build_ui(self):
        """Construct the main window layout."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding=self._px(16))
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── Title ────────────────────────────────────────────────────────
        title_label = ttk.Label(main_frame, text="unezquake Installer", style="Title.TLabel")
        title_label.pack(pady=(0, self._px(4)))

        subtitle = ttk.Label(
            main_frame,
            text="Download, build, and install the latest unezquake client",
            style="Info.TLabel"
        )
        subtitle.pack(pady=(0, self._px(16)))

        # ── Button Frame ─────────────────────────────────────────────────
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, self._px(8)))

        # Update button (primary action)
        self.update_btn = ttk.Button(
            btn_frame,
            text="🔄  Update",
            style="Action.TButton",
            command=self.start_update
        )
        self.update_btn.pack(side=tk.LEFT, padx=(0, self._px(4)), fill=tk.X, expand=True)

        # Check Version button
        self.version_btn = ttk.Button(
            btn_frame,
            text="🏷️  Check Version",
            style="Secondary.TButton",
            command=self.check_version
        )
        self.version_btn.pack(side=tk.LEFT, padx=(0, self._px(4)), fill=tk.X, expand=True)

        # Settings button
        self.settings_btn = ttk.Button(
            btn_frame,
            text="⚙️  Settings",
            style="Secondary.TButton",
            command=self.open_settings
        )
        self.settings_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Progress Bar ─────────────────────────────────────────────────
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(self._px(8), self._px(4)))

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate"
        )
        self.progress_bar.pack(fill=tk.X)

        # ── Status Label ─────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(
            main_frame,
            textvariable=self.status_var,
            style="Status.TLabel"
        )
        status_label.pack(anchor=tk.W, pady=(0, self._px(8)))

        # ── Console Output ───────────────────────────────────────────────
        console_label = ttk.Label(main_frame, text="Console Output", style="Info.TLabel")
        console_label.pack(anchor=tk.W, pady=(self._px(4), self._px(2)))

        console_frame = ttk.Frame(main_frame)
        console_frame.pack(fill=tk.BOTH, expand=True)

        self.console = tk.Text(
            console_frame,
            wrap=tk.WORD,
            font=self.console_font,
            bg=self.console_bg,
            fg=self.console_fg,
            insertbackground=self.console_fg,
            selectbackground="#264f78",
            selectforeground="#ffffff",
            relief=tk.FLAT,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#30363d",
            highlightcolor="#30363d",
            padx=self._px(8),
            pady=self._px(8),
            spacing1=1,
            spacing3=1
        )

        # Scrollbar
        scrollbar = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.console.yview)
        self.console.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure text tags for colored output
        self.console.tag_configure("error", foreground="#f85149")
        self.console.tag_configure("success", foreground="#3fb950")
        self.console.tag_configure("info", foreground="#58a6ff")
        self.console.tag_configure("dim", foreground="#8b949e")

        # ── Status Bar (bottom) ──────────────────────────────────────────
        self.status_bar = ttk.Label(
            self.root,
            text=f"Build: {self.config['game_dir']}  |  Install: {self.config['install_dir']}",
            style="Info.TLabel",
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(self._px(8), self._px(4))
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ── UI Update Methods (marshalled to the main thread) ────────────────

    def append_log(self, message: str):
        """Append a message to the console output.

        Must only be called on the main thread. Background threads marshal to
        the main thread via `root.after(0, self.append_log, message)`.
        """
        self.console.configure(state=tk.NORMAL)

        # Color-code certain messages
        tag = None
        if "❌" in message or "ERROR" in message:
            tag = "error"
        elif "✅" in message or "✓" in message:
            tag = "success"
        elif "[INFO]" in message or message.startswith("["):
            tag = "info"
        elif message.startswith("  │"):
            tag = "dim"

        self.console.insert(tk.END, message + "\n", tag)
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)

    def set_progress(self, value: int):
        """Update the progress bar value (0-100)."""
        self.progress_var.set(value)

    def set_status(self, text: str):
        """Update the status label text."""
        self.status_var.set(text)

    def _message(self, kind, title, message, confirm=False, parent=None,
                 yes_text="Yes", no_text="No"):
        """Show a centered, themed modal dialog and return the result."""
        dialog = AppDialog(
            parent or self.root, title, message, kind=kind, confirm=confirm,
            yes_text=yes_text, no_text=no_text
        )
        return dialog.result

    # ── Event Handlers ───────────────────────────────────────────────────

    def open_settings(self):
        """Open the settings dialog to configure directories."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.transient(self.root)
        dialog.resizable(True, True)

        px = self._px

        # ── Scrollable content area ──────────────────────────────────────
        container = ttk.Frame(dialog)
        container.pack(fill=tk.BOTH, expand=True)

        try:
            canvas_bg = ttk.Style(self.root).lookup("TFrame", "background") or "#1c1c1c"
        except Exception:
            canvas_bg = "#1c1c1c"

        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0, bg=canvas_bg)
        vbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        main_frame = ttk.Frame(canvas, padding=px(16))
        window_id = canvas.create_window((0, 0), window=main_frame, anchor="nw")

        main_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width)
        )

        def _wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        dialog.bind("<MouseWheel>", _wheel)
        dialog.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        dialog.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        # Title + explanation of the flow
        ttk.Label(main_frame, text="Configure Directories",
                  style="Title.TLabel").pack(pady=(0, px(4)))
        ttk.Label(
            main_frame,
            text="Update clones the repository, builds the client, then copies "
                 "it into your Quake folder.",
            style="Info.TLabel", wraplength=px(480), justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, px(16)))

        # Build source directory
        ttk.Label(main_frame, text="1.  Build source  —  temporary",
                  style="Info.TLabel").pack(anchor=tk.W)
        source_frame = ttk.Frame(main_frame)
        source_frame.pack(fill=tk.X, pady=(px(2), px(2)))
        self.source_var = tk.StringVar(value=str(self.config['game_dir']))
        ttk.Entry(source_frame, textvariable=self.source_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(8)))
        ttk.Button(source_frame, text="Browse...",
                   command=lambda: self._browse_directory(self.source_var)).pack(side=tk.RIGHT)
        ttk.Label(main_frame, text="Cloned and compiled here. No game files needed.",
                  style="Info.TLabel").pack(anchor=tk.W, pady=(0, px(8)))

        # Flow cue between the two directories
        ttk.Label(main_frame, text="Build source   ⟶   Install location",
                  style="Info.TLabel", anchor=tk.CENTER).pack(fill=tk.X, pady=(0, px(8)))

        # Install directory
        ttk.Label(main_frame, text="2.  Install location  —  your Quake folder",
                  style="Info.TLabel").pack(anchor=tk.W)
        install_frame = ttk.Frame(main_frame)
        install_frame.pack(fill=tk.X, pady=(px(2), px(2)))
        self.install_var = tk.StringVar(value=str(self.config['install_dir']))
        ttk.Entry(install_frame, textvariable=self.install_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(8)))
        ttk.Button(install_frame, text="Browse...",
                   command=lambda: self._browse_directory(self.install_var)).pack(side=tk.RIGHT)
        ttk.Label(main_frame,
                  text="The compiled client is copied here, next to your id1 / qw game data.",
                  style="Info.TLabel").pack(anchor=tk.W, pady=(0, px(12)))

        # Find existing installs
        self.find_btn = ttk.Button(
            main_frame, text="🔍  Find current install", style="Secondary.TButton",
            command=lambda: self._find_current_install(dialog)
        )
        self.find_btn.pack(anchor=tk.W, pady=(0, px(4)))

        self.deep_scan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="Deep scan (search whole drives — slower)",
                        variable=self.deep_scan_var).pack(anchor=tk.W, pady=(0, px(8)))

        # Results (grouped, priority-sorted)
        ttk.Label(main_frame, text="Quake installations found (Use sets the Install location):",
                  style="Info.TLabel").pack(anchor=tk.W, pady=(0, px(2)))
        self.found_frame = ttk.Frame(main_frame)
        self.found_frame.pack(fill=tk.X, pady=(0, px(8)))

        # Theme
        ttk.Label(main_frame, text="Theme:",
                  style="Info.TLabel").pack(anchor=tk.W, pady=(0, px(4)))
        self.theme_var = tk.StringVar(value=self.config.get("theme", "dark"))
        theme_combo = ttk.Combobox(main_frame, textvariable=self.theme_var,
                                   values=("dark", "light", "system"), state="readonly")
        theme_combo.pack(fill=tk.X, pady=(0, px(4)))
        theme_combo.bind("<<ComboboxSelected>>", self._on_theme_change)
        ttk.Label(main_frame, text="Theme applies immediately.",
                  style="Info.TLabel").pack(anchor=tk.W, pady=(0, px(12)))

        # ── Buttons (fixed at the bottom) ────────────────────────────────
        btn_frame = ttk.Frame(dialog, padding=(px(16), px(12)))
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="Save",
                   command=lambda: self._save_settings(dialog)).pack(side=tk.RIGHT, padx=(px(8), 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)

        # Show what we can already detect.
        extra = [self.config["game_dir"], self.config["install_dir"]]
        self._render_install_results(detect_quake_installations(extra_dirs=extra))

        # Size and center
        dialog.update_idletasks()
        width = max(dialog.winfo_reqwidth(), px(540))
        content_h = main_frame.winfo_reqheight() + px(80)
        height = min(content_h, int(self.root.winfo_screenheight() * 0.8))
        dialog.minsize(px(480), px(360))
        center_over_parent(dialog, self.root, width=width, height=height)
        dialog.grab_set()
        dialog.focus_set()

    def _render_install_results(self, installs):
        """Render grouped, priority-sorted install results into the settings dialog."""
        if not hasattr(self, "found_frame"):
            return
        for child in self.found_frame.winfo_children():
            child.destroy()
        px = self._px
        wrap = self._px(470)

        unezquake = [i for i in installs if i["has_unezquake"]]
        qw_other = [i for i in installs if i["has_qw"] and not i["has_unezquake"]]
        other = [i for i in installs if not i["has_qw"]]

        if unezquake:
            ttk.Label(self.found_frame, text="unezquake installs (use as Install location):",
                      style="Info.TLabel").pack(anchor=tk.W, pady=(px(4), px(2)))
            for info in unezquake:
                ttk.Button(
                    self.found_frame, text=f"Use: {info['folder']}",
                    command=lambda p=info['folder']: self._use_install_dir(p)
                ).pack(fill=tk.X, pady=px(2))
                ttk.Label(self.found_frame, text="engines: " + ", ".join(info["engines"]),
                          style="Info.TLabel", wraplength=wrap,
                          justify=tk.LEFT).pack(anchor=tk.W)

        if qw_other:
            ttk.Label(self.found_frame, text="Other QuakeWorld clients:",
                      style="Info.TLabel").pack(anchor=tk.W, pady=(px(8), px(2)))
            for info in qw_other:
                ttk.Label(self.found_frame,
                          text=f"• {info['folder']}\n   engines: {', '.join(info['engines'])}",
                          style="Info.TLabel", wraplength=wrap,
                          justify=tk.LEFT).pack(anchor=tk.W)

        if other:
            ttk.Label(self.found_frame, text="Other Quake installs:",
                      style="Info.TLabel").pack(anchor=tk.W, pady=(px(8), px(2)))
            for info in other:
                ttk.Label(self.found_frame,
                          text=f"• {info['folder']}\n   engines: {', '.join(info['engines'])}",
                          style="Info.TLabel", wraplength=wrap,
                          justify=tk.LEFT).pack(anchor=tk.W)

        if not installs:
            ttk.Label(self.found_frame, text="No Quake installations detected yet.",
                      style="Info.TLabel").pack(anchor=tk.W, pady=px(2))

    def _browse_directory(self, var: tk.StringVar):
        """Open a directory browser dialog."""
        initial_dir = var.get()
        if not Path(initial_dir).exists():
            initial_dir = str(Path.home())

        directory = filedialog.askdirectory(
            title="Select Directory",
            initialdir=initial_dir
        )

        if directory:
            var.set(directory)

    def _use_install_dir(self, path: Path):
        """Use a found install folder as the Install location."""
        self.install_var.set(str(path))
        self.append_log(f"  → Install location set to: {path}")

    def _find_current_install(self, dialog):
        """Find Quake installs on this computer (background)."""
        self.find_btn.configure(state=tk.DISABLED, text="⏳  Searching...")
        self.append_log("🔍 Searching for Quake installs...")

        extra = [self.config["game_dir"], self.config["install_dir"]]
        deep = bool(getattr(self, "deep_scan_var", None) and self.deep_scan_var.get())
        result_queue = queue.Queue()

        def worker():
            try:
                installs = detect_quake_installations(extra_dirs=extra, deep=deep)
            except Exception:
                installs = []
            # Only put to the queue from the worker; never touch Tk here.
            result_queue.put(installs)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_find_results(dialog, result_queue)

    def _poll_find_results(self, dialog, result_queue):
        """Poll the worker queue on the main thread and handle the results."""
        try:
            installs = result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, lambda: self._poll_find_results(dialog, result_queue))
            return
        self._on_find_done(dialog, installs)

    def _on_find_done(self, dialog, installs):
        """Handle search results (called on the main thread)."""
        alive = bool(dialog.winfo_exists())
        if alive:
            self.find_btn.configure(state=tk.NORMAL, text="🔍  Find current install")
            self._render_install_results(installs)

        # Log everything found, in priority order.
        self.append_log(f"  Found {len(installs)} Quake installation(s):")
        for info in installs:
            tag = "install location" if info["has_unezquake"] else info["category"]
            self.append_log(
                f"    • [{tag}] {info['folder']}  ({', '.join(info['engines'])})"
            )

        unezquake = [i for i in installs if i["has_unezquake"]]
        if unezquake:
            target = unezquake[0]["folder"]
            if alive:
                self.install_var.set(str(target))
            info = inspect_install(target)
            report = self._format_install_report(info, installs)
            title = "Current install"
        else:
            report = self._format_install_report(None, installs)
            title = "Quake installs found" if installs else "Not found"

        self._message("info", title, report, parent=dialog if alive else None)

    def _format_install_report(self, info, installs) -> str:
        """Build a human-readable report for the found installs and library."""
        lines = []
        if info is not None:
            lines.append(f"Update target: {info['install_dir']}")
            if info.get("engines"):
                lines.append(f"Engines: {', '.join(info['engines'])}")
            if info["binaries"]:
                lines.append(f"Binary: {info['binaries'][0].name}")
            lines.append("")
            lines.append("Quake data library:")
            for sub, present in info["data"].items():
                lines.append(f"  {sub}/pak0.pak: {'found ✓' if present else 'missing'}")
        elif not installs:
            lines.append("No Quake installation was found.")
        else:
            lines.append("No unezquake install found, so there is nothing to update.")
            lines.append("Only the installs below were detected.")

        qw_other = [i for i in installs if i["has_qw"] and not i["has_unezquake"]]
        other = [i for i in installs if not i["has_qw"]]
        if qw_other:
            lines.append("")
            lines.append("Other QuakeWorld clients:")
            for i in qw_other:
                lines.append(f"  • {i['folder']}  ({', '.join(i['engines'])})")
        if other:
            lines.append("")
            lines.append("Other Quake installs:")
            for i in other:
                lines.append(f"  • {i['folder']}  ({', '.join(i['engines'])})")
        return "\n".join(lines)

    # ── Check Version ────────────────────────────────────────────────────

    def check_version(self):
        """Check the latest GitHub release against the installed client version."""
        if getattr(self, "version_check_running", False):
            return

        self.version_check_running = True
        self.version_btn.configure(state=tk.DISABLED, text="⏳  Checking...")
        self.append_log("Checking GitHub for the latest unezquake release...")

        repo_url = self.config["repo_url"]
        install_dir = self.config["install_dir"]
        game_dir = self.config["game_dir"]
        result_queue = queue.Queue()

        def worker():
            result = {"error": None, "release": None, "installed": None}
            try:
                result["release"] = fetch_latest_release(repo_url)
                result["installed"] = get_installed_version(install_dir, game_dir)
            except Exception as e:
                result["error"] = str(e)
            # Only touch the queue from the worker; never call Tk here.
            result_queue.put(result)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_version_result(result_queue)

    def _poll_version_result(self, result_queue):
        """Poll the version-check worker on the main thread."""
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, lambda: self._poll_version_result(result_queue))
            return
        self._on_version_checked(result)

    def _on_version_checked(self, result):
        """Handle a completed version check (called on the main thread)."""
        self.version_check_running = False
        self.version_btn.configure(state=tk.NORMAL, text="🏷️  Check Version")

        if result.get("error"):
            self.append_log(f"❌ Version check failed: {result['error']}")
            self._message("warning", "Check Version", result["error"])
            return

        release = result.get("release") or {}
        installed = result.get("installed")
        tag = release.get("tag") or "unknown"
        name = release.get("name") or f"unezquake {tag}"
        published = (release.get("published_at") or "")[:10]

        lines = [f"Latest: {name}  (tag {tag})"]
        if published:
            lines.append(f"Released: {published}")
        lines.append(f"Installed: {installed or 'unknown'}")
        lines.append("")

        outdated = is_outdated(installed, tag)
        if outdated is True:
            lines.append(f"⬆ Update available: {installed} → {tag}")
        elif outdated is False:
            lines.append("✓ You are on the latest version.")
        else:
            lines.append(f"Latest available version is {tag}.")
            lines.append("The installed version could not be read — if it looks")
            lines.append("newer, download it manually from GitHub.")

        if release.get("html_url"):
            lines.append("")
            lines.append(release["html_url"])

        report = "\n".join(lines)
        self.append_log("  " + report.replace("\n", "\n  "))
        self._message("info", "Check Version", report)

    def _on_theme_change(self, _event=None):
        """Apply and persist a theme change immediately (no directory check)."""
        theme = self.theme_var.get()
        self.config["theme"] = theme
        save_theme(theme)
        self._apply_theme()
        self.append_log(f"✓ Theme changed to: {theme}")

    def _save_settings(self, dialog):
        """Save settings and close dialog."""
        source_raw = self.source_var.get().strip()
        install_raw = self.install_var.get().strip()

        if not source_raw or not install_raw:
            self._message(
                "error", "Error",
                "Both the Build source and Install location must be set.",
                parent=dialog
            )
            return

        game_dir = Path(source_raw).expanduser()
        install_dir = Path(install_raw).expanduser()

        # Compare canonical paths (case-insensitively on Windows).
        def canonical(path):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            text = str(resolved)
            return text.casefold() if sys.platform.startswith("win") else text

        source_key = canonical(game_dir)
        install_key = canonical(install_dir)

        if source_key == install_key:
            self._message(
                "error", "Error",
                "Build source and Install location must be different.",
                parent=dialog
            )
            return

        # Refuse nested directories (one inside the other).
        source_parts = Path(source_key).parts
        install_parts = Path(install_key).parts
        shorter, longer = sorted(
            (source_parts, install_parts), key=len
        )
        if shorter != longer and longer[:len(shorter)] == shorter:
            self._message(
                "error", "Error",
                "Build source and Install location cannot be inside each other.\n\n"
                "Pick two separate folders.",
                parent=dialog
            )
            return

        # Missing parents are not an error: folders are created on Update.
        path_warnings = []
        if not game_dir.parent.exists():
            path_warnings.append(
                f"Build source parent does not exist yet: {game_dir.parent}"
            )
        if not install_dir.parent.exists():
            path_warnings.append(
                f"Install location parent does not exist yet: {install_dir.parent}"
            )

        # Save config
        theme = self.theme_var.get() if hasattr(self, "theme_var") else self.config.get("theme", "dark")
        self.config['game_dir'] = game_dir
        self.config['install_dir'] = install_dir
        self.config['theme'] = theme
        save_config(game_dir, install_dir, self.config['repo_url'], theme)

        # Apply the chosen theme immediately
        self._apply_theme()

        # Update UI
        self.status_bar.configure(
            text=f"Build: {game_dir}  |  Install: {install_dir}"
        )

        self.append_log("✓ Settings updated:")
        self.append_log(f"  Build source: {game_dir}")
        self.append_log(f"  Install location: {install_dir}")
        for warning in path_warnings:
            self.append_log(f"⚠ {warning} (will be created on Update)")

        dialog.destroy()

    def start_update(self):
        """Handle the Update button click (platform-aware)."""
        mode = install_mode()
        if mode == "unsupported":
            self._message(
                "error", "Unsupported platform",
                "Installing unezquake is not supported on this platform.\n\n"
                "You can still use Settings to configure directories."
            )
            return

        if self.worker is not None and self.worker.is_running():
            self._message("info", "Busy", "An update is already running.")
            return

        if mode == "build":
            self._start_build()
        else:
            self._start_release_install()

    def _start_build(self):
        """Clone and build unezquake from source (Linux)."""
        # Confirmation dialog
        if not self._message(
            "question", "Confirm Update",
            "This will delete the existing source directory and rebuild from scratch.\n\n"
            "Any local changes in the source folder will be lost.\n\n"
            "Do you want to continue?",
            confirm=True
        ):
            return

        # Disable button, reset state
        self.update_btn.configure(state=tk.DISABLED, text="⏳  Building...")
        self.progress_var.set(0)
        self.status_var.set("Starting...")

        # Clear console
        self.console.configure(state=tk.NORMAL)
        self.console.delete(1.0, tk.END)
        self.console.configure(state=tk.DISABLED)

        # Create thread-safe callbacks that marshal to main thread
        def log_callback(msg):
            self.root.after(0, self.append_log, msg)

        def progress_callback(val):
            self.root.after(0, self.set_progress, val)

        def status_callback(text):
            self.root.after(0, self.set_status, text)

        def finished_callback(success, message):
            self.root.after(0, self.on_build_finished, success, message)

        # Start worker thread with current config
        self.worker = BuildWorker(
            log_callback=log_callback,
            progress_callback=progress_callback,
            status_callback=status_callback,
            finished_callback=finished_callback,
            game_dir=self.config['game_dir'],
            install_dir=self.config['install_dir'],
            repo_url=self.config['repo_url']
        )
        self.worker.start()

    def _start_release_install(self, force: bool = False):
        """Download and install the latest prebuilt client (Windows/macOS)."""
        install_dir = self.config["install_dir"]

        if not force and not self._message(
            "question", "Confirm Update",
            "This will download the latest unezquake client and install it to:\n\n"
            f"{install_dir}\n\n"
            "An existing unezquake there will be replaced. Do you want to continue?",
            confirm=True
        ):
            return

        # Disable button, reset state
        self.update_btn.configure(state=tk.DISABLED, text="⏳  Installing...")
        self.progress_var.set(0)
        self.status_var.set("Starting...")

        # Clear console
        self.console.configure(state=tk.NORMAL)
        self.console.delete(1.0, tk.END)
        self.console.configure(state=tk.DISABLED)

        # Create thread-safe callbacks that marshal to main thread
        def log_callback(msg):
            self.root.after(0, self.append_log, msg)

        def progress_callback(val):
            self.root.after(0, self.set_progress, val)

        def status_callback(text):
            self.root.after(0, self.set_status, text)

        def finished_callback(success, message, info):
            self.root.after(0, self.on_release_finished, success, message, info)

        self.worker = ReleaseInstallWorker(
            log_callback=log_callback,
            progress_callback=progress_callback,
            status_callback=status_callback,
            finished_callback=finished_callback,
            install_dir=install_dir,
            repo_url=self.config["repo_url"],
            force=force,
        )
        self.worker.start()

    def on_release_finished(self, success: bool, message: str, info: dict):
        """Handle release-install completion (called on main thread)."""
        info = info or {}
        status = info.get("status")

        # Already on the latest version: offer to force a reinstall.
        if status == "uptodate":
            self.update_btn.configure(state=tk.NORMAL, text="🔄  Update")
            self.status_var.set("✅ Up to date")
            if self._message(
                "question", "Already up to date",
                f"{message}\n\nDownload and reinstall anyway?",
                confirm=True
            ):
                self._start_release_install(force=True)
                return
            self.root.after(3000, lambda: self.status_var.set("Ready"))
            return

        self.update_btn.configure(state=tk.NORMAL, text="🔄  Update")

        if success:
            self.status_var.set("✅ Complete!")
            self._message("info", "Success", message)
        elif status == "cancelled":
            self.status_var.set("Cancelled")
            self._message("info", "Cancelled", message)
        else:
            self.status_var.set("❌ Failed")
            self._message("error", "Error", f"Install failed:\n\n{message}")

        # Reset status after a moment
        self.root.after(3000, lambda: self.status_var.set("Ready"))

    def on_build_finished(self, success: bool, message: str):
        """Handle build completion (called on main thread)."""
        self.update_btn.configure(state=tk.NORMAL, text="🔄  Update")

        if success:
            self.status_var.set("✅ Complete!")
            self._message("info", "Success", message)
        elif message == "Build cancelled by user.":
            self.status_var.set("Cancelled")
            self._message("info", "Cancelled", message)
        else:
            self.status_var.set("❌ Failed")
            self._message("error", "Error", f"Build failed:\n\n{message}")

        # Reset status after a moment
        self.root.after(3000, lambda: self.status_var.set("Ready"))

    def _on_close(self):
        """Handle window close, cancelling any running build."""
        if self.worker is not None and self.worker.is_running():
            if not self._message(
                "question", "Quit",
                "An update is still running. Cancel it and quit?",
                confirm=True
            ):
                return
            self.worker.cancel()
        self.root.destroy()

    # ── Main Loop ────────────────────────────────────────────────────────

    def run(self):
        """Start the main event loop."""
        self.root.mainloop()
