# Settings Guide

The installer keeps its configuration in `unezquake_installer_config.json`
(next to the scripts). You can change everything from the **⚙️ Settings**
dialog, or edit the file directly.

## What you can configure

| Setting                | Description                                                |
| ---------------------- | ---------------------------------------------------------- |
| **Build source**       | Temporary folder where the repository is cloned and built  |
| **Install location**   | Your Quake folder; the compiled client is copied here      |
| **Theme**              | `dark` (default), `light`, or `system`                     |

On **Linux**, Update clones the repository into **Build source**, compiles the
client, then copies the binary into **Install location** (next to your
`id1`/`qw` game data), so think of it as **Build source ⟶ Install location**. On
**Windows/macOS** there is no compile step: Update downloads the prebuilt client
from GitHub and puts it straight into **Install location** (Build source is not
used). The two folders must be different and must not be inside each other.

The repository URL is also stored but is only editable through the config file.

## Using the Settings dialog

1. Launch the app: `python main.py`
2. Click **⚙️ Settings**
3. Set the **Build source** and **Install location** (type a path, or click
   **Browse...**)
4. Click **Save** to persist the directories

A parent folder that doesn't exist yet is not a problem: the settings still save
and the folder is created when you run **Update**.

The **Theme** is separate: it applies and is saved **immediately** when you pick
it from the dropdown — you don't need to click Save, and it works even if the
directories aren't valid yet.

The main window's status bar always shows the current source and install paths.

## Finding an existing install

Click **🔍 Find current install** in the Settings dialog to scan the machine. It
searches:

- your configured Source and Install directories,
- the common Quake locations listed below,
- **Quake-named folders at the top level of each drive** (for example
  `C:\nQuake`, `C:\Quake`, `D:\nQuake`) on Windows,
- **Steam libraries** (from `libraryfolders.vdf` and the Steam registry),
- the entries on your `PATH`.

Results are grouped by priority:

1. **unezquake installs (use as Install location)** — each gets a **Use: …**
   button, and the first is auto-filled into the **Install location**.
2. **Other QuakeWorld clients** — for example **ezQuake** (nQuake is basically an
   ezQuake package). Informational only.
3. **Other Quake installs** — remaster, source ports, classic. Informational only.

Every install shows its detected engines. The list is scrollable, so any number
of installs is visible. The action (install/update) always targets a
**unezquake** install.

For the selected install the app reports the **Quake data library** — whether
`id1/pak0.pak` and `qw/pak0.pak` are present — so you can tell whether the client
has the game data it needs to run.

Tick **Deep scan (search whole drives — slower)** before searching to also walk
each drive recursively (system folders are skipped). Use this if your install is
somewhere unusual, e.g. nested deep in a folder that isn't named after Quake.

## Using detected Quake installations

On startup (and when the Settings dialog opens) the app scans common Quake
locations and lists the installs it finds, grouped the same way as above.
Clicking **Use: …** on a unezquake install sets the **Install location**.

## Detected locations

**Linux**
- `~/Games/Quake`
- `~/games/quake`
- `~/.quake`
- `/opt/quake`
- `/usr/local/games/quake`
- `/games/quake`

**Windows**
- `~/Games/Quake`
- `~/Documents/Quake`
- `C:/Games/Quake`
- `C:/Program Files/Quake`
- `C:/Program Files (x86)/Quake`

**macOS**
- `~/Games/Quake`
- `~/Library/Application Support/Quake`
- `/Applications/Quake`

Detection is only a suggestion — browse to set your real paths.

## Configuration file

```json
{
  "game_dir": "/home/user/Games/Quake/unezquake",
  "install_dir": "/home/user/Games/Quake",
  "repo_url": "https://github.com/dusty-qw/unezquake.git",
  "theme": "dark"
}
```

- Edit it manually, or
- Delete it to reset to defaults, or
- Back it up to preserve your settings.

## Safety rules for the Build source folder

Update deletes and re-clones the Build source folder, so the installer refuses to
remove:

- a filesystem / drive root,
- your home directory (or an ancestor of it),
- the Install location (or a directory containing it),
- anything without a `.git` folder (i.e. not the cloned repository).

If a path is refused, the build stops with an error and nothing is deleted.
Always keep Build source and Install location different and not nested inside
each other, and point Build source at a dedicated `…/unezquake` folder.

## Troubleshooting

- **"… parent does not exist yet" warning** — not an error: the settings are
  saved and the folder is created when you run **Update**.
- **Settings not saving** — check that you can write
  `unezquake_installer_config.json` in the app folder.
- **Wrong detected directories** — detection is a hint only; use Browse.
- **Theme looks plain/light** — install the theme package: `pip install sv-ttk`,
  then restart the app (or re-save Settings).
- **Update says Linux only** — the build pipeline is Linux-only; the rest of the
  app works everywhere.
