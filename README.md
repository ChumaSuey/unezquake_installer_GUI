# unezquake Installer GUI

A Python GUI installer for the [unezquake](https://github.com/dusty-qw/unezquake)
QuakeWorld client, built with **tkinter + ttk** and the
[Sun Valley](https://github.com/rdbende/Sun-Valley-ttk-theme) theme.

The app downloads the repository, builds it, and installs the binary — with a
live console, progress bar, and an editable configuration.

## Project structure

```
unezquake-installer/
├── main.py         Entry point — run this to start the app
├── backend.py      All build/install logic (no GUI dependencies)
├── GUI.py          All tkinter/ttk UI code
├── worklog.md      Development log
└── README.md       This file
```

`unezquake_installer_config.json` is created next to these files the first time
you save settings.

## Requirements

- **Python 3.10+** (tkinter included with the standard installer)
- **`sv-ttk`** for the Sun Valley theme (optional but recommended):
  ```bash
  pip install sv-ttk
  ```
- **`darkdetect`** (optional) — only needed if you choose the `system` theme:
  ```bash
  pip install darkdetect
  ```
- For the actual build (Linux only):
  - **git**, **gcc**, **cmake**, **make** (SDL2 and other build dependencies are
    handled by unezquake's own build script)

## Quick start

```bash
python main.py
```

## Platform support

The **GUI runs anywhere** tkinter runs (Linux, Windows, macOS). How **Update**
installs the client depends on the platform:

- **Linux** — clones the repository and **builds from source** via
  `build-linux.sh` (needs git, gcc, cmake, make).
- **Windows / macOS** — **downloads the prebuilt client** from the latest GitHub
  release (no toolchain needed). Windows gets `unezquake.exe`; macOS gets
  `unezQuake.app`.
- Other platforms are unsupported (the GUI still configures directories).

## Features

### Update button
Platform-aware install:

**Linux (build from source)**
- Clones the unezquake repository with submodules
- Updates submodules to their latest commits
- Builds with `build-linux.sh`, streaming output to the console
- Installs the binary (with `pkexec`/`sudo` fallback when elevation is needed)

**Windows / macOS (install prebuilt release)**
- Downloads the matching asset from the latest GitHub release
- Extracts the client into the **Install location** (replacing any existing one)
- If you are already on the latest version it warns and skips, offering a forced
  reinstall instead

Both paths run in a background thread, can be cancelled, and closing the window
mid-update asks first and stops it.

### Check Version button
- Queries the latest [GitHub release](https://github.com/dusty-qw/unezquake/releases)
  (`releases/latest`) and reports the latest tag, name, and release date
- Reads the version embedded in the installed `unezquake` executable (or
  `src/version.h` when the source tree is available) and compares it
- Verdict: **Update available** (`2.0.5 → 2.1`), **up to date**, or **latest
  version unknown** — with the release URL for a manual download
- Runs in a background thread; network calls never block the UI

### Console output
- Real-time, color-coded log (errors red, successes green, info blue, build
  output dimmed) with auto-scroll

### Progress bar
- Build: 5% Cleaning · 15% Cloning · 35% Submodules · 50% Building · 90%
  Installing · 100% Complete
- Release install: 5% Checking · 10–70% Downloading · 85% Installing · 100%
  Complete

### Settings
- Configure the **Build source** (temporary clone/build folder), the
  **Install location** (your Quake folder), and the theme — Update flows
  **Build source ⟶ Install location**
- Browse for folders or use auto-detected Quake installations; a missing parent
  folder still saves and is created on Update
- **🔍 Find current install** — finds every Quake install and groups them by
  priority:
  - **unezquake installs** (use as Install location) — get a **Use:** button.
  - **Other QuakeWorld clients** (e.g. ezQuake, classic QW clients) — listed
    next, informational.
  - **Other Quake installs** (remaster, source ports…) — listed last,
    informational.
  It searches your configured folders, common Quake locations, drive-root
  Quake folders (e.g. `C:\nQuake`), **Steam libraries** (`libraryfolders.vdf`),
  and `PATH`. It also reports the Quake data library (`id1/pak0.pak`,
  `qw/pak0.pak`) for the selected install. Enable **Deep scan** to also search
  whole drives (slower). The list is scrollable, so any number of installs shows.
- Settings persist to `unezquake_installer_config.json`

## Configuration

Settings are stored in `unezquake_installer_config.json`:

```json
{
  "game_dir": "/home/user/Games/Quake/unezquake",
  "install_dir": "/home/user/Games/Quake",
  "repo_url": "https://github.com/dusty-qw/unezquake.git",
  "theme": "dark"
}
```

| Key           | Meaning                                              |
| ------------- | ---------------------------------------------------- |
| `game_dir`    | Build source — where the repository is cloned and built |
| `install_dir` | Install location — where the compiled client is copied  |
| `repo_url`    | Git repository to build from                         |
| `theme`       | `dark` (default), `light`, or `system`               |

You can also edit defaults in `backend.py`.

## Theme

The app applies the **Sun Valley dark theme** by default through the `sv-ttk`
package. Set `"theme"` to `light` or `system` in the config (or via the Settings
dialog) to change it. In the Settings dialog the theme applies **immediately**
and is saved on selection — independently of the directory settings. If `sv-ttk`
is not installed, the app falls back to the legacy loose-`.tcl` layout and then
to tkinter's built-in `clam` theme, so it still runs without any optional
dependency.

The Sun Valley theme only styles ttk widgets; the console is a `tk.Text` widget
with its own dark colors.

## Display & window behavior

- **DPI scaling** — on Windows the app enables per-monitor DPI awareness and
  scales fonts and pixel sizes from the detected display DPI, so the UI stays
  comfortable at 100%, 125%, 150%, 200%, etc.
- **Centered windows** — the main window and the Settings dialog open centered
  (the Settings dialog over the main window), clamped to the visible screen area.
- **Centered dialogs** — messages and confirmations use a small themed modal
  dialog (with Return = accept, Escape = cancel) instead of the native
  message boxes, so every popup is centered and matches the theme.

## Safety

Because Update deletes and re-clones the **Build source** folder, `backend.py`
refuses to remove obviously dangerous targets:

- filesystem / drive roots
- the home directory or any of its ancestors
- the configured **Install location**, or a directory containing it
- anything that does not look like a git repository (no `.git`)

If a target is refused, the build stops with an explanatory error rather than
deleting anything.

## Architecture

```
main.py
   ↓ imports
GUI.py        (tkinter/ttk, theme, layout, events)
   ↓ imports
backend.py    (config, detection, BuildWorker)
   ↓ uses
Standard library (os, sys, json, shutil, subprocess, threading, pathlib)
```

`backend.py` has **no GUI dependencies**, so the build logic can be tested or
reused independently. Thread-safe UI updates are marshalled from the worker
thread to the main thread with `root.after(0, ...)`.

## Project notes

Ideas and concepts that are **not implemented** (for example a fallback
"quick install from GitHub releases" flow) are collected in
[`projectnotes.md`](projectnotes.md).

## Testing the backend

```python
from backend import BuildWorker, check_dependencies, build_supported

print(build_supported())
print(check_dependencies())
```

## Credits

- unezquake: https://github.com/dusty-qw/unezquake
- Sun Valley theme: https://github.com/rdbende/Sun-Valley-ttk-theme
- Original bash script: https://github.com/Trismegist0sq3/install_latest_unezquake

## License

Same as the original unezquake project (GPL-2.0).
