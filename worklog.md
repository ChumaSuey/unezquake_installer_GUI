# Worklog — unezquake Installer GUI

## 2026-10-05 — Code review of the project

Scope: read-through of `main.py`, `backend.py`, `GUI.py`, and the docs
(`README.md`, `PROJECT_SUMMARY.md`, `SETTINGS_GUIDE.md`). No code changes made yet.

Overall: small, clean 3-module Python/Tkinter app (`main.py` → `GUI.py` → `backend.py`).
Architecture and threading model are sound; `backend.py` is genuinely free of GUI deps.
Several real bugs and one dangerous default found.

### Critical / safety

1. **`backend.py:160` — `shutil.rmtree(self.game_dir)` with no guard.**
   If the user sets Source Directory to e.g. `C:\Users\luism` or `/home/user`, Update
   silently wipes it. No check that the path is the unezquake repo, no home/root guard,
   no `game_dir != install_dir` check. Biggest risk in the project.

2. **Elevated-install path never sets the exec bit (`backend.py:245-260`).**
   Direct copy runs `os.chmod(0o755)`, but the `pkexec cp` / `sudo cp` fallback does not.
   Plain `cp` does not preserve the executable bit, so the binary can be installed
   non-executable.

### Bugs / correctness

3. **Linux-only pipeline presented as cross-platform.**
   `BINARY_NAME = unezquake-linux-x86_64`, `build-linux.sh`, and `/games/quake` are
   Linux-specific, yet `detect_quake_directories()` handles win32/darwin and the README
   claims Windows/macOS support. Update will fail at build/install on those platforms.

4. **`proc.wait(timeout=600)` (`backend.py:216`).**
   On build timeout this raises `TimeoutExpired` but never kills the child; the build
   keeps running orphaned.

5. **No cancel/join on exit.**
   Worker is a daemon thread; closing the window mid-build kills it abruptly.

6. **`setup_theme.py` referenced but missing.**
   Mentioned in README and `GUI.py:129`, but does not exist in the project, so the theme
   install instructions are broken.

7. **Dead / unused code.**
   `check_dependencies()` and `get_config_info()` are never called from the GUI.
   `get_config_info` is even imported in `GUI.py:18` but unused.

### Code quality

8. **Duplicate module docstring** in `backend.py:1-13` (two top-level string literals).

9. **Debug `print()` spam** throughout `_apply_theme` (`GUI.py:64-131`) — noisy for an
   end user.

10. **`append_log` docstring claims thread-safe**, but it directly touches widgets. It is
    only safe because callers marshal via `root.after`. Contract should be clarified.

11. **Theme load catches only `tk.TclError`** (`GUI.py`); other exceptions crash startup.

### Docs / repo hygiene

12. **Leftover diff markers** in `README.md` and `PROJECT_SUMMARY.md`
    (`--- public/README.md (原始)` / `+++ ... (修改后)`), with old + new versions
    concatenated. `SETTINGS_GUIDE.md` also has the marker.

13. **Docs reference files that do not exist**: `setup_theme.py`, `index.html`,
    `src/App.tsx`, `sun-valley.ttk/`.

14. **Changelog-style content** ("What's New", "✅ What Was Built") mixed into files that
    read like current documentation.

### Proposed fix plan (not yet executed)

1. Add a `_safe_clean` guard: refuse to rmtree home/root/drive roots, require the target
   to look like the repo dir (e.g. contains `.git` or a marker), and require
   `game_dir != install_dir`.
2. Refactor install into one helper that always chmods `0o755` (including after
   pkexec/sudo); prefer `install -m 755` / `cp` + chmod.
3. Make the platform explicit: detect OS and gate/replace the Linux-only build path.
4. Kill the child on build timeout; add clean shutdown handling.
5. Add `setup_theme.py` (or remove all references to it).
6. Remove debug prints, dedupe the docstring, drop unused imports/functions.
7. Clean the three markdown files into single coherent current docs.

### Open questions

- Fix code only, or also rewrite the docs?
- Stay Linux-focused (drop win32/darwin detection), or implement real multi-platform support?

---

## 2026-10-05 — Light-mode investigation

Finding: the app always came up in a light theme even though a dark theme was
expected.

Root cause:
- `_apply_theme` looked for the **legacy loose-file** Sun Valley layout
  (`sun-valley.ttk/sun-valley-dark.tcl`, theme name `sun-valley-dark`). Those
  files are not present (`THEME_DIR` does not exist in the project).
- Modern Sun Valley ships as the **`sv_ttk` Python package** (already installed
  on this machine), exposing `sv_ttk.set_theme("dark"/"light"/"system")` — the
  code never used it.
- On fallback the code explicitly forced `style.theme_use("clam")`, which is a
  **light** theme. Net effect: light mode was effectively enforced.

Verified on this machine: `sv_ttk` and `darkdetect` installed; `THEME_DIR` absent;
tkinter defaults to `vista`; available themes include `clam`.

Fix: `_apply_theme` now prefers `sv_ttk.set_theme(mode)`, where `mode` comes from
config (default `dark`); the legacy `.tcl` layout is kept as a secondary fallback;
`clam` is only a last resort. Added a Theme selector (`dark`/`light`/`system`) in
the Settings dialog. After the fix the smoke test reports `theme_mode: dark`, ttk
theme `sun-valley-dark`.

---

## 2026-10-05 — Fixes applied

Code (`backend.py`, `GUI.py`):
1. **Safe-delete guard** `_assert_safe_to_delete()` — refuses filesystem roots,
   home (or an ancestor), the install dir (or a dir containing it), and targets
   without `.git`. Verified with unit checks (all pass).
2. **Install chmod fix** — direct copy chmods `0o755`; elevated fallback now uses
   `install -m 755` via pkexec/sudo, so the executable bit is preserved.
3. **Platform gating** — added `build_supported()`; `_run` aborts early on
   non-Linux; `start_update` shows a clear message instead of failing midway.
4. **Timeout kill** — build timeout now `kill()`s the child before raising;
   git/submodule timeouts handled; missing `git` reported clearly.
5. **Cancellation & shutdown** — `BuildWorker.cancel()` + cancel event + child
   kill; build invoked via `bash build-linux.sh` (no exec-bit dependency); window
   close asks before quitting mid-build.
6. **Cleanup** — removed duplicate module docstring, unused `datetime` import, and
   unused `get_config_info()`; wired `check_dependencies()` into startup logging.
7. **Theme** — rewritten (see light-mode section); removed all debug `print()` spam.

Docs:
8. Rewrote `README.md`, `PROJECT_SUMMARY.md`, `SETTINGS_GUIDE.md` as coherent
   current docs; removed diff markers, nonexistent-file references, and changelog
   text. Documented `pip install sv-ttk`, Linux-only build, theme options, and the
   safety rules.

Verification:
- `ast.parse` syntax OK for all three modules.
- GUI smoke test (create + destroy): `theme_mode: dark`, ttk `sun-valley-dark`.
- Safety-guard unit checks pass.

Not done / open:
- Real Linux build not exercised here (Windows dev box).
- `Check version` button is still a placeholder.

---

## 2026-10-05 — Visual fixes: DPI scaling + centered windows

Goal: make the UI look right on high-DPI displays and open every window centered.

What changed (`GUI.py`):
1. **DPI awareness** — `enable_dpi_awareness()` is called before `tk.Tk()`
   (Windows: `shcore.SetProcessDpiAwareness(1)` → `user32.SetProcessDPIAware()`
   fallback; no-op elsewhere).
2. **DPI scaling** — after `tk.Tk()`: `tk scaling = winfo_fpixels('1i') / 72`
   for point-based fonts, and `self.ui_scale = dpi / (72 if darwin else 96)`
   (clamped 0.75–2.5). A `_px()` helper scales every hard-coded pixel value
   (window size, min size, paddings, button padding, status bar).
3. **Centering helpers** — `center_window()` (screen-centered) and
   `center_over_parent()` (centered over the main window, clamped to screen).
4. **Main window** — sized and centered on screen at startup.
5. **Settings dialog** — no longer uses a fixed `520x470`; it sizes to content
   with a scaled minimum width (500 logical) and centers over the main window.
6. **Native `messagebox` replaced** by a themed, centered modal `AppDialog`
   (info/warning/error/question; Return = accept, Escape = cancel). All call
   sites updated, including the Settings validation errors (centered over the
   Settings dialog). The `messagebox` import was removed.

Verified on this machine (panel is 125%: physical 1920x1080, scale 1.251):
- main window `876x751+522+164` — exactly centered.
- Settings dialog `626x368` (min width enforced) centered over main.
- confirm dialog returns `True`, info dialog returns `False`; both centered.
- `ast.parse` syntax check OK.

Docs: added a "Display & window behavior" section to `README.md`.

Note: only native `filedialog.askdirectory` (Browse) is still an OS dialog — it
is not centerable/themeable, and it is invoked from the Settings window anyway.

---

## 2026-10-05 — Feature: "Find current install" + library check

Requested: a Settings button that finds the unezquake executable on the computer
and then checks the current library. Reminder from the user: there can be
**multiple Quake installs**, so the finder must return *install folders that
contain a unezquake executable*, not a single result.

Backend (`backend.py`, GUI-free):
- `BINARY_CANDIDATES` (linux binary, `unezquake`, `unezquake.exe`).
- `_iter_binary_matches(root, max_depth)` — walks a root (skipping hidden/noisy
  dirs) for executable matches.
- `find_unezquake_binaries(...)` — searches configured dirs, auto-detected Quake
  dirs, and `PATH` (shallow). Fast known-location scan, no full-disk scan.
- `find_unezquake_installs(...)` — dedupes binaries by parent folder and returns
  **every distinct install directory**.
- `inspect_install(folder)` — lists the binaries in the folder and checks the
  Quake data library (`id1/pak0.pak`, `qw/pak0.pak`) plus any `*.pak` files.

GUI (`GUI.py`):
- Added **🔍 Find current install** button to the Settings dialog plus a results
  frame.
- Search runs in a background thread using the safe pattern: the worker only
  writes to a `queue.Queue`, and the main thread polls it via `root.after(100)`
  (calling Tk from the worker thread was found to be unreliable).
- Results: every install gets a **Use: <folder>** button; the first is
  auto-filled (preferring installs not inside the source dir); a themed dialog
  reports the chosen install and its data library; all matches are logged to the
  console.

Settings JSON: already implemented (`unezquake_installer_config.json` via
`load_config`/`save_config`); no change needed.

Verified: backend finds two fake installs and checks `id1/pak0.pak`; GUI
threaded search returns both, auto-fills the first, and the "Use:" button
switches the Install Directory; syntax/import and app smoke tests pass.

Docs: added the feature to `README.md` and `SETTINGS_GUIDE.md`.

---

## 2026-10-05 — Bugfix: theme could not be changed independently of directories

Reported: "You can't change the theme without changing the directory."

Cause: the theme was only persisted inside `_save_settings`, which runs
directory validation first and `return`s early on failure. On the default
install dir (`/games/quake`, whose parent does not exist on Windows) Save always
failed, so the theme could never be changed.

Fix:
- `backend.save_theme(theme)` — persists only the `theme` key, preserving the
  other config values (loads current config, rewrites with new theme).
- Settings theme `Combobox` now binds `<<ComboboxSelected>>` to
  `_on_theme_change()`, which applies the theme and saves it immediately, with
  no directory checks. Added a "Theme applies immediately." hint in the dialog.

Verified: with an invalid `/games/quake` directory, selecting `light` persists
`saved theme: light` while `game_dir`/`install_dir` are preserved. Syntax/import
and app smoke tests pass.

---

## 2026-10-05 — Fix: finder missed installs in drive-root Quake folders (e.g. C:\nQuake)

Reported: the user's `unezquake.exe` lives in `C:\nQuake`, but Find current
install couldn't locate it. Cause: detection only checked a fixed list of paths
and `PATH`, so a top-level `C:\nQuake` folder was never scanned.

Fixes (`backend.py`):
- `_drive_roots()` — enumerate available drive roots (Windows).
- `_quake_folders_on_drives()` — include top-level folders on each drive whose
  name contains "quake" (catches `C:\nQuake`, `C:\Quake`, `D:\nQuake`, …).
- `detect_quake_directories()` now adds those folders (deduped).
- `SKIP_DIR_NAMES` — system/noisy folders (`windows`, `program files`,
  `appdata`, `$recycle.bin`, …) are pruned during walks.
- `find_unezquake_binaries(..., deep=False)` / `find_unezquake_installs(...,
  deep=False)` — new optional `deep` flag scans every drive root recursively
  (with pruning) for installs in unusual locations.

GUI (`GUI.py`):
- Added a **Deep scan (search whole drives — slower)** checkbox in Settings;
  its value is passed to the finder.

Verified: a fake drive root with `nQuake/unezquake.exe` is detected and found
automatically (no deep scan needed); Deep scan additionally finds a nested
`stuff/a/b/unezquake` install; the GUI checkbox reaches the finder. Syntax/import
and smoke tests pass.

Docs: updated `README.md` and `SETTINGS_GUIDE.md`.

---

## 2026-10-05 — Feature: multi-install detection (all clients), Steam, notes file

Requested: handle more than 2 installs (the user has 3), prioritise
multiplayer/QuakeWorld clients (ezQuake — nQuake is an ezQuake package), list
other Quake installs as informational, and add a concept note for a future
"installer in case" (quick GitHub download).

Findings on the machine:
- `C:\nQuake` is an nQuake package containing **both** `ezquake.exe` **and**
  `unezquake.exe`, with `id1` + `qw`.
- `C:\Program Files (x86)\Steam\steamapps\common\Quake` has `ezquake_rls_classic.exe`,
  `qwcl.exe`, `glqwcl.exe`, classic, and the remaster (`rerelease`).
- `C:\quake-leveldesign-workspace` was a false positive (no engine, no data).

Backend (`backend.py`):
- `identify_engine()` + `engines_in_folder()` + `looks_like_quake_install()` —
  classify engines as `qw` (ezQuake, unezquake, classic QW clients) or `other`
  (remaster, source ports, classic SP) and decide if a folder is an install.
- `steam_library_roots()` (registry `SteamPath`/`InstallPath` + `libraryfolders.vdf`)
  and `steam_quake_folders()`.
- `_iter_engine_folders()` — walk a root for install folders.
- `detect_quake_installations(extra_dirs, deep)` — returns ranked info dicts;
  walks extra dirs, known dirs, Steam, and (deep) drives; validates each folder
  and ranks unezquake first, then other QW clients, then other installs.
- `detect_quake_directories()` now validates drive-root candidates and includes
  Steam folders (drops the level-design false positive).
- `inspect_install()` now reports detected engine names.

GUI (`GUI.py`):
- Settings results are grouped: **unezquake installs (update target)** with
  **Use:** buttons, then **Other QuakeWorld clients**, then **Other Quake
  installs**, all informational.
- The Settings content is now **scrollable** with a max height and mouse-wheel
  support; removed the `detected[:3]` / `detected[:5]` caps.
- The find worker uses `detect_quake_installations`; the report lists the update
  target + data library and the other installs.
- Detected installs are logged to the console with their engines.

New file `projectnotes.md`:
- **Concept (not implemented):** a fallback "quick client installer" that
  downloads a client binary directly from GitHub releases (special features /
  no toolchain / Windows), with rationale and open questions.

Verified: real detection lists `C:\nQuake` (ezQuake + unezquake), the Steam Quake
folder (ezQuake + QW classic + classic + remaster) and Quake 2, and excludes the
level-design workspace; a temp root with 3 fake installs (2 QW + 1 classic) is
grouped correctly, base folder is not listed, and the update target is the
unezquake install. Syntax/import and GUI tests pass.

---

## 2026-10-09 — Feature: "Check GH version" (was a placeholder)

Requested: make the placeholder button actually check what the latest version is
("Check Github Version"), noting that reading the version from an executable is
hard and that a manual download is an acceptable fallback.

Findings:
- The upstream repo **does** publish GitHub Releases. Latest = tag `2.1`
  ("unezQuake v2.1", 2026-10-09), assets for linux-x86_64 / macOS-universal /
  windows-x64. The user's installed `C:\nQuake\unezquake.exe` is **2.0.5**, so an
  update genuinely exists.
- The executable **does** embed its version. `src/version.h` defines
  `VERSION_NUMBER`, and `VersionStringFull()` compiles `UNEZQUAKE %s (<platform>)`;
  the version literal sits just before that format string in the binary.
  Validated: scanning for the marker and regexing backwards extracted `2.0.5`.
- Upstream's own `src/version.c` already GETs
  `api.github.com/repos/dusty-qw/unezquake/releases/latest` and compares
  semantic versions, so we mirror that (but our parser also handles 2-part tags
  like `2.1`, which upstream's `sscanf("%d.%d.%d")` rejects).

Scope (per user): **check + report only**; button label **"Check GH version"**;
no download/install.

Backend (`backend.py`, GUI-free, stdlib only):
- `latest_release_url(repo_url)` — derive the `releases/latest` API URL.
- `fetch_latest_release(repo_url, timeout)` — `urllib.request` GET with a
  `User-Agent` (GitHub 403s without one); returns tag/name/published_at/html_url;
  clear errors for 404, 403 (rate limit), offline, bad JSON.
- `parse_version()` / `is_outdated()` — tolerate leading `v`, 2-part tags and
  `-dev`/pre-release suffixes; `None` when unknown.
- `read_binary_version(path)` — marker-anchored scan of the executable.
- `read_source_version(game_dir)` — parse `src/version.h` as a fallback.
- `get_installed_version(install_dir, game_dir)` — binary → source → any detected
  install.

GUI (`GUI.py`):
- Enabled the button (was `state=DISABLED`), text `🏷️  Check GH version`,
  `command=self.check_version`.
- `check_version()` runs the network + scan in a daemon thread writing to a
  `queue.Queue`, polled by `root.after(100)` (same safe pattern as the finder).
- Result shown in a themed `AppDialog` and mirrored to the console:
  latest tag/name/date, installed version, and a verdict
  (**Update available**, **up to date**, or **latest X; installed unknown**).

Not done / open:
- No in-app download of the release asset (still the "quick installer" concept in
  `projectnotes.md`).
- Verified extraction against the real 2.0.5 binary; the live API call itself was
  exercised via PowerShell (the GUI network path is the same endpoint).

---

## 2026-10-09 — Fix: Settings required both directories to save (+ clearer wording)

Reported: "it seems that both directories have to be configured for it to be
saved; I only changed the second (where the install is) and it didn't let me
save." Also: the clone/source vs install directories feel confusing.

Cause: `_save_settings` hard-required **both** parents to exist:
`if not game_dir.parent.exists(): error; return` and the same for `install_dir`.
With the stock defaults the parents (`~/Games/Quake`, `/games/quake`) don't
exist, so a fresh setup (or an Install-only edit) could never be saved.

Fixes:
- `GUI._save_settings` (directory section + save):
  - Hard-block only on empty paths, `source == install` (compared as canonical
    paths, case-insensitively on Windows), or Source/Install nested inside each
    other (the case the build's safe-delete guard would refuse later).
  - Missing parents are now a **non-blocking warning**: the config is saved and
    a console note says the folder will be created on Update.
- `backend.BuildWorker._step_clone`: create `game_dir.parent` before `git clone`
  (which needs the destination's parent to exist). The install parent was already
  created in `_step_install`.

Wording (Settings dialog):
- Intro line explaining the flow: clone → build → copy into the Quake folder.
- Fields relabelled **"1. Build source — temporary"** and
  **"2. Install location — your Quake folder"**, each with a one-line helper, plus
  a `Build source ⟶ Install location` flow cue.
- Finder results now say "use as Install location"; startup/status/log strings
  aligned ("Build source" / "Install location").

Docs: updated `SETTINGS_GUIDE.md` (role table, steps, safety, troubleshooting) and
`README.md` / `PROJECT_SUMMARY.md` wording.

Not done: platform-specific default for `install_dir` (stock `/games/quake` is
meaningless on Windows) — flagged, not changed.

---

## 2026-10-09 — Feature: prebuilt-release install (Windows/macOS) — "unsupported platform" fix

Reported: "it tells me my platform is unsupported, I'm using Windows 11."

Cause: `backend.build_supported()` returns True only on Linux, and `start_update`
showed an "Unsupported platform" dialog on everything else. That gate predates
the project shipping prebuilt releases.

Findings:
- The fork publishes GitHub releases. Release `2.1` ships
  `unezQuake-windows-x64.zip` containing a single statically linked
  `unezquake.exe` (11 MB, verified by listing the zip in memory). Linux asset =
  `unezQuake-linux-x86_64.zip` → `unezQuake-x86_64.AppImage`; macOS =
  `unezQuake-macOS-universal.zip` → a nested zip → `unezQuake.app`.
- Upstream Windows builds need VS2026 + CMake 4.2 + vcpkg (`msbuild-x64`), far
  too heavy for this installer. Downloading the release asset is the right path.

Backend (`backend.py`, GUI-free):
- `install_mode()` → `"build"` (Linux) / `"release"` (Windows/macOS) /
  `"unsupported"`; `release_supported()`.
- `fetch_latest_release()` now also returns `assets` (name, size, url).
- `pick_platform_asset(assets, system, machine)` → matching `.zip` by OS/arch.
- `download_asset(url, dest, progress_cb, timeout, cancel_check)` — streamed
  `urllib` download with progress.
- `extract_release_client(archive, install_dir, system, log)` — Windows `.exe`,
  macOS double-zip `unezQuake.app`, Linux AppImage (+chmod 0755).
- `ReleaseInstallWorker` — threaded (start/is_running/cancel, log/progress/status/
  finished). Flow: fetch release → read installed version → if already latest and
  not `force`, return `uptodate` (no download) → else pick asset, download
  (10–70%), extract (85–100%), verify the installed binary's version. Friendly
  `PermissionError` message ("is unezquake still running?").

GUI (`GUI.py`):
- Imports `ReleaseInstallWorker` / `install_mode`; startup log is platform-aware.
- `start_update` dispatches: Linux → `_start_build()` (unchanged build flow);
  Windows/macOS → `_start_release_install()`.
- `on_release_finished`: on `uptodate` asks "download and reinstall anyway?"
  (Yes → `_start_release_install(force=True)`); otherwise shows success/cancel/error.
- Window-close prompt now says "an update", not "a build".

Docs: README (platform + Update + progress), PROJECT_SUMMARY, SETTINGS_GUIDE,
projectnotes (concept now implemented), worklog.

Verified (offline, since this sandbox blocks Python HTTPS to GitHub):
- `py_compile` clean; `install_mode()` → `release` on this Windows box.
- `pick_platform_asset` picks win/mac/linux assets correctly.
- Windows extraction installs `unezquake.exe`.
- Worker: tag==installed → `uptodate` (no download); tag newer → `installed`;
  `force=True` reinstalls when uptodate.
- GUI `start_update` dispatches to the release path on Windows.

Not done / open: Linux release download (build remains the only Linux path);
checksum/signature verification (FORKS' releases publish no checksums.txt).





