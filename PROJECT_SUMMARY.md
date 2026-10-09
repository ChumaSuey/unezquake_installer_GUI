# Project Summary — unezquake Installer GUI

A modular Python GUI that downloads, builds, and installs the
[unezquake](https://github.com/dusty-qw/unezquake) QuakeWorld client.

## Modules

| File         | Responsibility                                                        | Lines |
| ------------ | --------------------------------------------------------------------- | ----- |
| `main.py`    | Entry point. Imports the app, runs it, handles top-level exceptions.  | ~24   |
| `backend.py` | Config, directory detection, and the `BuildWorker` pipeline. No GUI.  | ~300  |
| `GUI.py`     | All tkinter/ttk code: theme, layout, events, thread marshalling.      | ~500  |

No circular dependencies: `main.py → GUI.py → backend.py → stdlib`.

## Features

- **Update** — platform-aware: on Linux `clone → submodules → build-linux.sh →
  install`; on Windows/macOS it downloads the prebuilt client from the latest
  GitHub release and extracts it into the Install location. Live color-coded
  console and determinate progress bar; already-up-to-date installs are skipped
  with an optional forced reinstall.
- **Settings** — persistent **Build source** / **Install location** directories
  and theme, with browse dialogs and one-click use of detected Quake installs.
  A missing parent folder still saves and is created on Update.
- **Theme** — Sun Valley dark by default (via `sv-ttk`), with light/system
  options and a graceful fallback if the package is absent.
- **Check Version** — queries the latest GitHub release, reads the version
  embedded in the installed binary, and reports whether an update is available.

## Architecture highlights

- **Separation of concerns** — `backend.py` has zero GUI imports and can be
  tested/reused on its own.
- **Thread safety** — `BuildWorker` runs in a daemon thread and marshals all UI
  updates to the main thread through `root.after(0, ...)`.
- **Cancellation & shutdown** — the worker supports `cancel()`, kills the active
  child process, and the window close handler asks before quitting mid-build.
- **Process safety** — the build child is killed on timeout; git/build failures
  surface as clear console errors.
- **Destructive-op guard** — the Build source folder is only deleted when it is
  safe (not home/root/install and it looks like a git repo).
- **Elevation** — installs by direct copy when possible, otherwise via
  `pkexec`/`sudo`, always preserving the executable bit.

## Platform note

The GUI is cross-platform. **Linux** builds from source (`build-linux.sh`).
**Windows/macOS** install the prebuilt client from the latest GitHub release
(`unezquake.exe` / `unezQuake.app`) with no toolchain required — the release
assets are chosen by OS/arch via `pick_platform_asset()`. Other platforms are
unsupported but can still configure directories.

## Configuration

Stored in `unezquake_installer_config.json` next to the scripts:

```json
{
  "game_dir": "…/Games/Quake/unezquake",
  "install_dir": "/games/quake",
  "repo_url": "https://github.com/dusty-qw/unezquake.git",
  "theme": "dark"
}
```

## Running

```bash
pip install sv-ttk        # optional, for the dark theme
python main.py
```

## Credits

- unezquake: https://github.com/dusty-qw/unezquake
- Sun Valley theme: https://github.com/rdbende/Sun-Valley-ttk-theme
- Original bash script: https://github.com/Trismegist0sq3/install_latest_unezquake
