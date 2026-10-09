"""
backend.py — All build/install logic for the unezquake installer.
=================================================================
Contains:
    - Configuration constants
    - Configuration management (load/save/detect)
    - BuildWorker class (clone → build → install, Linux)
    - ReleaseInstallWorker class (download a prebuilt client, Windows/macOS)

This module has NO GUI dependencies. It only uses the standard library.
"""

import os
import sys
import re
import json
import shutil
import zipfile
import tempfile
import platform
import subprocess
import threading
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_GAME_DIR = Path.home() / "Games" / "Quake" / "unezquake"
DEFAULT_INSTALL_DIR = Path("/games/quake")
REPO_URL = "https://github.com/dusty-qw/unezquake.git"
BINARY_NAME = "unezquake-linux-x86_64"
BINARY_CANDIDATES = (
    "unezquake-linux-x86_64",
    "unezquake",
    "unezquake.exe",
)
DEFAULT_THEME = "dark"

# Engine categories. "qw" = QuakeWorld / multiplayer client (priority for us);
# "other" = any other Quake engine (informational only).
CATEGORY_QW = "qw"
CATEGORY_OTHER = "other"

CONFIG_FILE = Path(__file__).parent.resolve() / "unezquake_installer_config.json"
THEME_DIR = Path(__file__).parent.resolve() / "sun-valley.ttk"

BUILD_TOOLS = ("git", "gcc", "cmake", "make")

# Directories skipped when scanning drives (system / noisy folders).
SKIP_DIR_NAMES = {
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "$recycle.bin", "recycle.bin", "system volume information",
    "perflogs", "recovery", "msocache", "node_modules", "__pycache__",
    ".git", ".cache", ".local",
}


# ─── Platform support ─────────────────────────────────────────────────────────

def build_supported() -> bool:
    """Return True if this platform can build/install unezquake from source.

    The unezquake project builds with `build-linux.sh` and produces a Linux
    binary, so the full clone → build → install pipeline is Linux-only. Windows
    and macOS get a prebuilt client from GitHub releases instead (see
    `install_mode()`).
    """
    return sys.platform.startswith("linux")


def release_supported() -> bool:
    """Return True if this platform installs from a prebuilt GitHub release."""
    return sys.platform.startswith("win") or sys.platform == "darwin"


def install_mode() -> str:
    """How the Update action installs the client on this platform.

    Returns "build" (clone + compile, Linux), "release" (download a prebuilt
    client, Windows/macOS), or "unsupported".
    """
    if build_supported():
        return "build"
    if release_supported():
        return "release"
    return "unsupported"


# ─── Configuration Management ─────────────────────────────────────────────────

def load_config() -> dict:
    """Load configuration from JSON file, or return defaults."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {
                "game_dir": Path(config.get("game_dir", str(DEFAULT_GAME_DIR))),
                "install_dir": Path(config.get("install_dir", str(DEFAULT_INSTALL_DIR))),
                "repo_url": config.get("repo_url", REPO_URL),
                "theme": config.get("theme", DEFAULT_THEME),
            }
        except Exception as e:
            print(f"⚠ Could not load config: {e}")

    return {
        "game_dir": DEFAULT_GAME_DIR,
        "install_dir": DEFAULT_INSTALL_DIR,
        "repo_url": REPO_URL,
        "theme": DEFAULT_THEME,
    }


def save_config(game_dir: Path, install_dir: Path,
                repo_url: str = REPO_URL, theme: str = DEFAULT_THEME):
    """Save configuration to JSON file."""
    config = {
        "game_dir": str(game_dir),
        "install_dir": str(install_dir),
        "repo_url": repo_url,
        "theme": theme,
    }

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠ Could not save config: {e}")


def save_theme(theme: str):
    """Persist only the theme setting, preserving the other config values."""
    config = load_config()
    save_config(config["game_dir"], config["install_dir"],
                config["repo_url"], theme)


# ─── Quake engine detection ───────────────────────────────────────────────────

def identify_engine(filename: str):
    """Return (friendly_name, category) for a Quake executable, or None.

    QuakeWorld / multiplayer clients are category "qw"; everything else is
    "other". Matching is done most-specific-first.
    """
    low = filename.lower()
    if low.startswith("unezquake"):
        return ("unezquake", CATEGORY_QW)
    if low.startswith("ezquake"):
        return ("ezQuake", CATEGORY_QW)
    if low in ("qwcl.exe", "qwcl", "glqwcl.exe", "glqwcl", "qw-client.exe"):
        return ("QuakeWorld classic client", CATEGORY_QW)
    if low.startswith("quake_x64_steam") or low == "rerelease":
        return ("Quake (remaster)", CATEGORY_OTHER)
    if low.startswith("quakespasm-spiked"):
        return ("QuakeSpasm-Spiked", CATEGORY_OTHER)
    if low.startswith("quakespasm"):
        return ("QuakeSpasm", CATEGORY_OTHER)
    if low.startswith("vkquake"):
        return ("VkQuake", CATEGORY_OTHER)
    if low.startswith("ironwail"):
        return ("Ironwail", CATEGORY_OTHER)
    if low in ("quake.exe", "winquake.exe", "glquake.exe"):
        return ("Quake (classic)", CATEGORY_OTHER)
    return None


def engines_in_folder(folder) -> list:
    """Return a list of (name, category) engines found at a folder's top level."""
    folder = Path(folder)
    engines = []
    seen = set()
    try:
        entries = list(folder.iterdir())
    except OSError:
        return engines

    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        ident = identify_engine(entry.name)
        if ident and ident not in seen:
            seen.add(ident)
            engines.append(ident)

    # The remaster keeps its binary in a `rerelease` subfolder.
    try:
        if (folder / "rerelease").is_dir() and ("Quake (remaster)", CATEGORY_OTHER) not in seen:
            engines.append(("Quake (remaster)", CATEGORY_OTHER))
    except OSError:
        pass

    # Multiplayer clients first.
    engines.sort(key=lambda e: 0 if e[1] == CATEGORY_QW else 1)
    return engines


def looks_like_quake_install(folder) -> bool:
    """Heuristically decide whether a folder is a Quake install."""
    folder = Path(folder)
    if engines_in_folder(folder):
        return True
    for sub in ("id1", "qw", "rerelease"):
        try:
            if (folder / sub).is_dir():
                return True
        except OSError:
            continue
    return False


def steam_library_roots() -> list:
    """Return Steam library root folders (Windows registry + libraryfolders.vdf)."""
    candidates = []

    if sys.platform == "win32":
        try:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    candidates.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
            except OSError:
                pass
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"
                ) as key:
                    candidates.append(Path(winreg.QueryValueEx(key, "InstallPath")[0]))
            except OSError:
                pass
        except ImportError:
            pass
        candidates.append(Path("C:/Program Files (x86)/Steam"))
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "Steam")
    else:
        candidates.extend([
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
        ])

    # Expand with every library listed in libraryfolders.vdf.
    for base in list(candidates):
        vdf = base / "steamapps" / "libraryfolders.vdf"
        try:
            if vdf.is_file():
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s*"([^"]+)"', text):
                    candidates.append(Path(match.group(1).replace("\\\\", "\\")))
        except OSError:
            continue

    roots = []
    seen = set()
    for c in candidates:
        try:
            key = str(c.resolve())
        except OSError:
            key = str(c)
        if os.name == "nt":
            key = key.lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(c)
    return roots


def steam_quake_folders() -> list:
    """Return Quake folders inside Steam 'steamapps/common' directories."""
    found = []
    seen = set()
    for lib in steam_library_roots():
        common = lib / "steamapps" / "common"
        try:
            if not common.is_dir():
                continue
            entries = list(common.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if not (entry.is_dir() and "quake" in entry.name.lower()):
                    continue
                if not looks_like_quake_install(entry):
                    continue
                key = str(entry.resolve())
            except OSError:
                continue
            if os.name == "nt":
                key = key.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(entry)
    return found


def detect_quake_directories() -> list:
    """Auto-detect common Quake installation directories."""
    candidates = []

    if sys.platform.startswith("linux"):
        home = Path.home()
        candidates.extend([
            home / "Games" / "Quake",
            home / "games" / "quake",
            home / ".quake",
            Path("/opt/quake"),
            Path("/usr/local/games/quake"),
            Path("/games/quake"),
        ])
    elif sys.platform == "win32":
        home = Path.home()
        candidates.extend([
            home / "Games" / "Quake",
            home / "Documents" / "Quake",
            Path("C:/Games/Quake"),
            Path("C:/Program Files/Quake"),
            Path("C:/Program Files (x86)/Quake"),
        ])
        # Also look at the top level of every drive (e.g. C:\nQuake).
        candidates.extend(_quake_folders_on_drives())
        # Steam libraries (e.g. ...\steamapps\common\Quake).
        candidates.extend(steam_quake_folders())
    elif sys.platform == "darwin":
        home = Path.home()
        candidates.extend([
            home / "Games" / "Quake",
            home / "Library" / "Application Support" / "Quake",
            Path("/Applications/Quake"),
        ])

    result = []
    seen = set()
    for path in candidates:
        try:
            if not (path.exists() and path.is_dir()):
                continue
            key = str(path.resolve())
        except OSError:
            continue
        if os.name == "nt":
            key = key.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _drive_roots() -> list:
    """Return the root of every available drive (empty on non-Windows)."""
    roots = []
    if sys.platform == "win32":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:/")
            try:
                if root.is_dir():
                    roots.append(root)
            except OSError:
                continue
    return roots


def _quake_folders_on_drives() -> list:
    """Return drive-root folders that look like actual Quake installs.

    Only folders whose name mentions Quake *and* that contain an engine or a
    data folder (id1/qw/rerelease) are returned, which avoids false positives
    such as level-editing workspaces.
    """
    found = []
    for root in _drive_roots():
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if not (entry.is_dir() and "quake" in entry.name.lower()):
                    continue
                if looks_like_quake_install(entry):
                    found.append(entry)
            except OSError:
                continue
    return found


def _iter_engine_folders(root, max_depth: int):
    """Yield folders under `root` (to `max_depth`) that look like Quake installs."""
    root = Path(root)
    try:
        if not root.is_dir():
            return
    except OSError:
        return

    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth

        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d.lower() not in SKIP_DIR_NAMES
        ]
        if depth >= max_depth:
            dirnames[:] = []

        has_engine = any(identify_engine(name) for name in filenames)
        has_data = any(sub in dirnames for sub in ("id1", "qw", "rerelease"))
        if has_engine or has_data:
            yield current


def detect_quake_installations(extra_dirs=(), deep: bool = False) -> list:
    """Return info dicts for every Quake install found, ranked by priority.

    Each dict has: folder, engines (list of names), category, has_unezquake,
    has_qw, has_id1, has_rerelease. QuakeWorld/multiplayer installs come first,
    then installs that contain a unezquake binary rise to the top.
    """
    folders = []
    seen = set()

    def add(folder):
        folder = Path(folder)
        if not looks_like_quake_install(folder):
            return
        try:
            key = str(folder.resolve())
        except OSError:
            key = str(folder)
        if os.name == "nt":
            key = key.lower()
        if key in seen:
            return
        seen.add(key)
        folders.append(folder)

    # Configured/source/install dirs: search inside them for install folders.
    for d in extra_dirs:
        if not d:
            continue
        add(d)
        for folder in _iter_engine_folders(d, 3):
            add(folder)

    # Known install dirs (already install-like).
    for d in detect_quake_directories():
        add(d)
    for d in steam_quake_folders():
        add(d)

    # Optional deep scan of whole drives.
    if deep:
        for root in (_drive_roots() or [Path.home()]):
            for folder in _iter_engine_folders(root, 3):
                add(folder)

    installs = []
    for folder in folders:
        engines = engines_in_folder(folder)
        names = [name for name, _ in engines]
        has_qw = any(cat == CATEGORY_QW for _, cat in engines)
        has_unezquake = "unezquake" in names
        installs.append({
            "folder": folder,
            "engines": names,
            "category": CATEGORY_QW if has_qw else CATEGORY_OTHER,
            "has_unezquake": has_unezquake,
            "has_qw": has_qw,
            "has_id1": (folder / "id1").is_dir(),
            "has_qw_dir": (folder / "qw").is_dir(),
            "has_rerelease": (folder / "rerelease").is_dir(),
        })

    def rank(info):
        if info["has_unezquake"]:
            return 0
        if info["has_qw"]:
            return 1
        return 2

    installs.sort(key=lambda i: (rank(i), str(i["folder"]).lower()))
    return installs




def _iter_binary_matches(root, max_depth: int):
    """Yield unezquake executable paths found under `root` up to `max_depth`."""
    root = Path(root)
    try:
        if not root.is_dir():
            return
    except OSError:
        return

    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth

        # Skip hidden / noisy / system directories and stop at the depth limit.
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d.lower() not in SKIP_DIR_NAMES
        ]
        if depth >= max_depth:
            dirnames[:] = []

        for name in filenames:
            low = name.lower()
            if low in BINARY_CANDIDATES or (low.startswith("unezquake") and "." not in low):
                yield current / name


def find_unezquake_binaries(extra_dirs=(), search_path: bool = True,
                            search_detected: bool = True,
                            max_depth: int = 3, deep: bool = False) -> list:
    """Return paths to every unezquake executable that can be found.

    Searches the supplied `extra_dirs`, the auto-detected Quake directories, and
    (shallowly) the entries on `PATH`. When `deep` is True it also scans each
    drive root (skipping system folders), which is slower.
    """
    root_specs = []
    for d in extra_dirs:
        if d:
            root_specs.append((Path(d), max_depth))
    if search_detected:
        for d in detect_quake_directories():
            root_specs.append((d, max_depth))
    if search_path:
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if entry:
                root_specs.append((Path(entry), 0))
    if deep:
        for root in (_drive_roots() or [Path.home()]):
            root_specs.append((root, max_depth))

    found = []
    seen = set()
    for root, depth in root_specs:
        for match in _iter_binary_matches(root, depth):
            try:
                key = str(match.resolve())
            except OSError:
                key = str(match)
            if os.name == "nt":
                key = key.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(match)
    return found


def find_unezquake_installs(extra_dirs=(), search_path: bool = True,
                            search_detected: bool = True,
                            max_depth: int = 3, deep: bool = False) -> list:
    """Return unique folders that contain a unezquake executable.

    Multiple Quake installs can exist on one machine, so this returns every
    distinct install directory found.
    """
    installs = []
    seen = set()
    for binary in find_unezquake_binaries(
        extra_dirs, search_path, search_detected, max_depth, deep
    ):
        folder = binary.parent
        try:
            key = str(folder.resolve())
        except OSError:
            key = str(folder)
        if os.name == "nt":
            key = key.lower()
        if key in seen:
            continue
        seen.add(key)
        installs.append(folder)
    return installs


def inspect_install(install_dir) -> dict:
    """Inspect an unezquake install folder and its Quake game-data library."""
    install_dir = Path(install_dir)
    info = {
        "install_dir": install_dir,
        "binaries": [],
        "engines": [name for name, _ in engines_in_folder(install_dir)],
        "data": {},
        "pak_files": [],
    }

    if install_dir.is_dir():
        try:
            entries = list(install_dir.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_file():
                continue
            low = entry.name.lower()
            if low in BINARY_CANDIDATES or (low.startswith("unezquake") and "." not in low):
                info["binaries"].append(entry)

    # Quake game-data library: the files needed to actually run.
    for sub in ("id1", "qw"):
        info["data"][sub] = (install_dir / sub / "pak0.pak").exists()

    if install_dir.is_dir():
        try:
            info["pak_files"] = sorted(install_dir.glob("*/*.pak"))
        except OSError:
            pass

    return info


def check_dependencies() -> dict:
    """Check if required system build tools are available."""
    result = {}
    for tool in BUILD_TOOLS:
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=5)
            result[tool] = True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            result[tool] = False
    return result


# ─── Version checking ─────────────────────────────────────────────────────────

# Markers embedded in the unezquake executable. `VersionStringFull()` compiles
# "UNEZQUAKE %s (<platform>)"; the version literal sits just before the format
# string, so we take the last semantic version found just ahead of the marker.
_VERSION_MARKERS = (b"UNEZQUAKE %s (", b"unezQuake %s")
_VERSION_RE = re.compile(rb"(\d+\.\d+(?:\.\d+)?(?:[-.][0-9A-Za-z]+)?)")
_SOURCE_VERSION_RE = re.compile(r'#define\s+VERSION_NUMBER\s+"([^"]+)"')


def latest_release_url(repo_url: str = REPO_URL):
    """Return the GitHub `releases/latest` API URL for a repository, or None."""
    url = (repo_url or "").strip()
    if url.endswith(".git"):
        url = url[:-4]
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def fetch_latest_release(repo_url: str = REPO_URL, timeout: int = 10) -> dict:
    """Fetch the latest GitHub release for a repository.

    Returns a dict with `tag`, `name`, `published_at`, `html_url` and `assets`
    (a list of `{name, size, url}`). Raises a RuntimeError with a human-readable
    message on any network/HTTP/JSON failure.
    """
    api = latest_release_url(repo_url)
    if not api:
        raise RuntimeError(f"Not a GitHub repository URL: {repo_url}")

    request = urllib.request.Request(
        api,
        headers={
            # GitHub rejects requests without a User-Agent.
            "User-Agent": "unezquake-installer",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError("No releases were found for this repository.")
        if e.code == 403:
            raise RuntimeError("GitHub API rate limit reached. Try again later.")
        raise RuntimeError(f"GitHub returned HTTP {e.code}.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach GitHub: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"Could not reach GitHub: {e}")
    except ValueError as e:
        raise RuntimeError(f"Invalid response from GitHub: {e}")

    assets = []
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        assets.append({
            "name": str(asset.get("name") or "").strip(),
            "size": int(asset.get("size") or 0),
            "url": str(asset.get("browser_download_url") or "").strip(),
        })

    return {
        "tag": str(payload.get("tag_name") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "published_at": str(payload.get("published_at") or "").strip(),
        "html_url": str(payload.get("html_url") or "").strip(),
        "assets": assets,
    }


def parse_version(text):
    """Parse a version string into a comparable tuple, or None if unparseable.

    Handles a leading `v`, tags with only two parts (`2.1` -> `(2, 1, 0)`) and
    pre-release suffixes (`2.1.1-dev` -> `(2, 1, 1)`).
    """
    if not text:
        return None
    value = str(text).strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    match = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part) if part is not None else 0 for part in match.groups())


def is_outdated(current, latest):
    """Return True/False if `current` is older than `latest`, or None if unknown."""
    parsed_current = parse_version(current)
    parsed_latest = parse_version(latest)
    if parsed_current is None or parsed_latest is None:
        return None
    return parsed_current < parsed_latest


def read_binary_version(path):
    """Extract the version embedded in a unezquake executable, or None."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024 * 1024)
    except OSError:
        return None

    for marker in _VERSION_MARKERS:
        index = data.find(marker)
        if index == -1:
            continue
        window = data[max(0, index - 128):index]
        matches = _VERSION_RE.findall(window)
        if matches:
            return matches[-1].decode("ascii", "ignore")
    return None


def read_source_version(game_dir):
    """Read VERSION_NUMBER from a checked-out repository's `src/version.h`."""
    if not game_dir:
        return None
    header = Path(game_dir) / "src" / "version.h"
    try:
        text = header.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = _SOURCE_VERSION_RE.search(text)
    return match.group(1) if match else None


def get_installed_version(install_dir=None, game_dir=None):
    """Best-effort version of the installed unezquake client, or None.

    Tries the binary in `install_dir` first, then the source header in
    `game_dir`, then any auto-detected unezquake install.
    """
    def scan(folder):
        for binary in find_unezquake_binaries(
            extra_dirs=[folder], search_path=False, search_detected=False, max_depth=1
        ):
            version = read_binary_version(binary)
            if version:
                return version
        return None

    if install_dir:
        version = scan(install_dir)
        if version:
            return version

    version = read_source_version(game_dir)
    if version:
        return version

    for folder in find_unezquake_installs(
        search_path=False, search_detected=True, max_depth=1
    ):
        version = scan(folder)
        if version:
            return version
    return None


# ─── Release install (prebuilt client from GitHub releases) ───────────────────

class InstallCancelled(Exception):
    """Raised internally when a release install is cancelled."""


def pick_platform_asset(assets, system=None, machine=None):
    """Return the release asset dict that matches this OS/arch, or None."""
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()

    if system.startswith("win"):
        os_tokens = ("windows", "win64", "win32", "-win", "_win")
        arch_tokens = ("x64", "x86_64", "amd64", "64")
    elif system == "darwin":
        os_tokens = ("macos", "osx", "darwin")
        arch_tokens = ("universal", "arm64", "x64", "64")
    elif system.startswith("linux"):
        os_tokens = ("linux",)
        arch_tokens = ("x86_64", "amd64", "64")
    else:
        return None

    fallback = None
    for asset in assets or []:
        name = (asset.get("name") or "").lower()
        if not name.endswith(".zip") or not asset.get("url"):
            continue
        if not any(token in name for token in os_tokens):
            continue
        if any(token in name for token in arch_tokens):
            return asset
        if fallback is None:
            fallback = asset
    return fallback


def download_asset(url, dest_path, progress_cb=None, timeout=60, cancel_check=None):
    """Download `url` to `dest_path`, reporting progress, and return bytes read."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "unezquake-installer"}
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Download failed: GitHub returned HTTP {e.code}.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not download the release: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"Could not download the release: {e}")

    total = int(response.headers.get("Content-Length") or 0)
    received = 0
    dest_path = Path(dest_path)
    try:
        with open(dest_path, "wb") as out:
            while True:
                if cancel_check and cancel_check():
                    raise InstallCancelled("Install cancelled by user.")
                chunk = response.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                if progress_cb:
                    progress_cb(received, total)
    finally:
        response.close()
    return received


def extract_release_client(archive, install_dir, system=None, log=None):
    """Extract the prebuilt client from a release archive into `install_dir`.

    Returns the path of the installed client. Handles the Windows `.exe`, the
    macOS double-zip (`unezQuake.app`) and the Linux AppImage.
    """
    system = (system or sys.platform).lower()
    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    def info(message):
        if log:
            log(message)

    archive = Path(archive)
    with zipfile.ZipFile(archive) as outer:
        members = outer.namelist()

        if system.startswith("win"):
            target = next((m for m in members if m.lower().endswith(".exe")), None)
            if target is None:
                raise RuntimeError("No .exe found in the Windows release archive.")
            dest = install_dir / "unezquake.exe"
            with outer.open(target) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            info(f"  ✓ Installed {dest.name}")
            return dest

        if system == "darwin":
            # The macOS asset is a zip nested inside a zip.
            inner_name = next((m for m in members if m.lower().endswith(".zip")), None)
            if inner_name is None:
                raise RuntimeError("No .zip found in the macOS release archive.")
            with outer.open(inner_name) as src:
                inner_bytes = src.read()
            with tempfile.TemporaryDirectory() as tmp:
                inner_path = Path(tmp) / "inner.zip"
                inner_path.write_bytes(inner_bytes)
                with zipfile.ZipFile(inner_path) as inner:
                    if not any(m.lower().startswith("unezquake.app/") for m in inner.namelist()):
                        raise RuntimeError("No unezQuake.app found in the macOS release archive.")
                    inner.extractall(install_dir)
            app = next(
                (p for p in install_dir.iterdir() if p.name.lower().endswith(".app")),
                install_dir,
            )
            info(f"  ✓ Installed {app.name}")
            return app

        # Linux: the release ships a self-contained AppImage.
        target = next((m for m in members if m.lower().endswith(".appimage")), None)
        if target is None:
            target = next((m for m in members if not m.endswith("/")), None)
        if target is None:
            raise RuntimeError("No client binary found in the release archive.")
        dest = install_dir / "unezQuake-x86_64.AppImage"
        with outer.open(target) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.chmod(dest, 0o755)
        info(f"  ✓ Installed {dest.name}")
        return dest


class ReleaseInstallWorker:
    """Downloads and installs a prebuilt unezquake client in a background thread.

    The `finished_callback` is called as `finished(success, message, info)` where
    `info` is a dict with `status` ("installed" / "uptodate" / "cancelled" /
    "error"), plus `tag` and `installed` where available.
    """

    def __init__(self, log_callback, progress_callback, status_callback,
                 finished_callback, install_dir: Path, repo_url: str = REPO_URL,
                 force: bool = False):
        self._log = log_callback
        self._progress = progress_callback
        self._status = status_callback
        self._finished = finished_callback
        self.install_dir = Path(install_dir)
        self.repo_url = repo_url
        self.force = force
        self._thread = None
        self._cancel = threading.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancel.set()

    def _check_cancel(self):
        if self._cancel.is_set():
            raise InstallCancelled("Install cancelled by user.")

    # ── Pipeline ─────────────────────────────────────────────────────────

    def _run(self):
        try:
            self._status("Checking latest release...")
            self._progress(5)
            self._log("Checking GitHub for the latest unezquake release...")
            release = fetch_latest_release(self.repo_url)
            tag = release.get("tag") or "unknown"
            self._log(f"  Latest release: {release.get('name') or tag} (tag {tag})")

            installed = get_installed_version(install_dir=self.install_dir)
            if not self.force and is_outdated(installed, tag) is False:
                self._log(f"  ✓ Already on the latest version ({installed}).")
                self._progress(100)
                self._status("✅ Up to date")
                self._finished(
                    True, f"Already up to date ({installed}).",
                    {"status": "uptodate", "tag": tag, "installed": installed},
                )
                return

            asset = pick_platform_asset(release.get("assets"))
            if asset is None:
                raise RuntimeError(
                    f"No prebuilt client for this platform in release {tag}."
                )
            self._log(f"  Downloading {asset['name']} ...")

            self._status(f"Downloading {tag}...")

            def on_progress(received, total):
                if total:
                    self._progress(min(70, 10 + int(received * 60 / total)))

            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / asset["name"]
                download_asset(
                    asset["url"], archive, progress_cb=on_progress,
                    cancel_check=self._cancel.is_set,
                )
                self._check_cancel()
                self._status("Installing...")
                self._progress(85)
                installed_path = extract_release_client(
                    archive, self.install_dir, log=self._log
                )

            self._check_cancel()
            new_version = get_installed_version(install_dir=self.install_dir)
            if new_version and parse_version(new_version) != parse_version(tag):
                self._log(
                    f"  ⚠ Installed binary reports {new_version} "
                    f"(release tag {tag})."
                )

            self._progress(100)
            self._status("✅ Complete!")
            self._log("")
            self._log("═══════════════════════════════════════════════")
            self._log(f"  ✅ Installed unezquake {tag}!")
            self._log(f"  Location: {installed_path}")
            self._log("═══════════════════════════════════════════════")
            self._finished(
                True, f"Installed unezquake {tag}.",
                {"status": "installed", "tag": tag, "installed": new_version,
                 "path": str(installed_path)},
            )
        except InstallCancelled as e:
            self._log("")
            self._log(f"Install cancelled: {e}")
            self._finished(False, str(e), {"status": "cancelled"})
        except PermissionError:
            message = (
                f"Could not write to {self.install_dir}. "
                "Is unezquake still running? Close it and try again."
            )
            self._log(f"❌ {message}")
            self._finished(False, message, {"status": "error"})
        except Exception as e:
            self._log("")
            self._log(f"❌ ERROR: {e}")
            self._finished(False, str(e), {"status": "error"})


# ─── Build Worker ─────────────────────────────────────────────────────────────

class BuildCancelled(Exception):
    """Raised internally when a running build is cancelled."""


class BuildWorker:
    """Runs the clone → build → install pipeline in a background thread."""

    def __init__(self, log_callback, progress_callback, status_callback,
                 finished_callback, game_dir: Path, install_dir: Path,
                 repo_url: str = REPO_URL):
        self._log = log_callback
        self._progress = progress_callback
        self._status = status_callback
        self._finished = finished_callback
        self.game_dir = game_dir
        self.install_dir = install_dir
        self.repo_url = repo_url
        self._thread = None
        self._proc = None
        self._cancel = threading.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self):
        """Launch the build pipeline in a daemon thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        """Return True if the worker thread is still alive."""
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        """Request cancellation and terminate any running child process."""
        self._cancel.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def _check_cancel(self):
        if self._cancel.is_set():
            raise BuildCancelled("Build cancelled by user.")

    # ── Pipeline ─────────────────────────────────────────────────────────

    def _run(self):
        try:
            if not build_supported():
                self._log("❌ Building unezquake is only supported on Linux.")
                self._finished(False, "Unsupported platform: unezquake builds on Linux only.")
                return

            self._step_clean()
            self._step_clone()
            self._step_submodules()
            self._step_build()
            self._step_install()
            self._step_done()
        except BuildCancelled as e:
            self._log("")
            self._log(f"Build cancelled: {e}")
            self._finished(False, str(e))
        except Exception as e:
            self._log("")
            self._log(f"❌ ERROR: {e}")
            self._finished(False, str(e))

    def _step_clean(self):
        self._check_cancel()
        self._status("Cleaning...")
        self._progress(5)
        self._log("Removing any existing unezquake source directory...")

        if not self.game_dir.exists():
            self._log("  (no existing directory to remove)")
            return

        self._assert_safe_to_delete(self.game_dir)
        shutil.rmtree(self.game_dir)
        self._log(f"  ✓ Removed {self.game_dir}")

    def _assert_safe_to_delete(self, path: Path):
        """Refuse to delete obviously dangerous or wrong directories.

        This protects against a misconfigured Source Directory wiping the user's
        home folder, a drive root, or the configured install directory.
        """
        target = path.resolve()
        home = Path.home().resolve()

        # Never delete a filesystem / drive root.
        if target.anchor and target == Path(target.anchor).resolve():
            raise RuntimeError(f"Refusing to delete filesystem root: {target}")

        # Never delete the home directory or any of its ancestors.
        if target == home or target in home.parents:
            raise RuntimeError(f"Refusing to delete home directory or its ancestor: {target}")

        # Never delete the install directory, or a directory that contains it.
        install = self.install_dir.resolve()
        if target == install or target in install.parents:
            raise RuntimeError(
                "Refusing to delete the source directory because it would also "
                f"remove the install directory: {self.install_dir}"
            )

        # Only delete something that looks like the cloned repository.
        if not (target / ".git").exists():
            raise RuntimeError(
                f"Refusing to delete {target}: it does not look like a git "
                "repository (no .git directory found). Delete it manually if "
                "this is intended."
            )

    def _step_clone(self):
        self._check_cancel()
        self._status("Cloning repository...")
        self._progress(15)
        self._log(f"Cloning {self.repo_url} ...")

        # git clone needs the destination's parent to exist.
        try:
            self.game_dir.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(
                f"Could not create source directory parent {self.game_dir.parent}: {e}"
            )

        try:
            result = subprocess.run(
                ["git", "clone", "--recurse-submodules", self.repo_url, str(self.game_dir)],
                capture_output=True, text=True, timeout=300
            )
        except FileNotFoundError:
            raise RuntimeError("git was not found. Install git and ensure it is on your PATH.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Git clone timed out after 300 seconds.")

        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed:\n{result.stderr}")
        self._log("  ✓ Repository cloned successfully")

    def _step_submodules(self):
        self._check_cancel()
        self._status("Updating submodules...")
        self._progress(35)
        self._log("Updating submodules to latest commits...")

        try:
            result = subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive", "--remote"],
                cwd=str(self.game_dir),
                capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Submodule update timed out after 120 seconds.")

        if result.returncode != 0:
            raise RuntimeError(f"Submodule update failed:\n{result.stderr}")
        self._log("  ✓ Submodules updated")

    def _step_build(self):
        self._check_cancel()
        self._status("Building unezquake...")
        self._progress(50)
        self._log("Starting build with build-linux.sh ...")
        self._log("  (this may take a few minutes)")

        build_script = self.game_dir / "build-linux.sh"
        if not build_script.exists():
            raise FileNotFoundError(f"Build script not found: {build_script}")

        proc = subprocess.Popen(
            ["bash", str(build_script)],
            cwd=str(self.game_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        self._proc = proc
        try:
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    self._log(f"  │ {stripped}")
                if self._cancel.is_set():
                    proc.kill()
                    break

            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise RuntimeError("Build timed out after 600 seconds.")
        finally:
            self._proc = None

        self._check_cancel()
        if proc.returncode != 0:
            raise RuntimeError(f"Build failed with exit code {proc.returncode}")
        self._log("  ✓ Build completed successfully")

    def _step_install(self):
        self._check_cancel()
        self._status("Installing binary...")
        self._progress(90)

        binary_path = self.game_dir / "build" / BINARY_NAME
        if not binary_path.exists():
            binary_path = self.game_dir / BINARY_NAME
        if not binary_path.exists():
            raise FileNotFoundError(
                f"Compiled binary not found. Expected at:\n"
                f"  {self.game_dir / 'build' / BINARY_NAME}\n"
                f"  or {self.game_dir / BINARY_NAME}"
            )

        dest_path = self.install_dir / BINARY_NAME
        self._log(f"Copying binary to {self.install_dir} ...")
        self.install_dir.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(str(binary_path), str(dest_path))
            os.chmod(str(dest_path), 0o755)
            self._log("  ✓ Binary copied (no elevation needed)")
            return
        except PermissionError:
            self._log("  → Requesting elevated privileges...")

        if not self._install_elevated(binary_path, dest_path):
            raise PermissionError(
                "Could not copy binary. Install manually or check permissions."
            )
        self._log(f"  ✓ Binary installed to {dest_path}")

    def _install_elevated(self, src: Path, dest: Path) -> bool:
        """Copy the binary with elevated privileges, preserving the exec bit.

        Uses `install -m 755` so the installed file is executable even though
        plain `cp` would drop the executable permission.
        """
        for tool in ("pkexec", "sudo"):
            try:
                result = subprocess.run(
                    [tool, "install", "-m", "755", str(src), str(dest)],
                    capture_output=True, text=True, timeout=60
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
            if result.returncode == 0:
                return True
            self._log(f"  {tool} failed: {result.stderr.strip()}")
        return False

    def _step_done(self):
        self._progress(100)
        self._status("✅ Complete!")
        self._log("")
        self._log("═══════════════════════════════════════════════")
        self._log("  ✅ Build and installation completed!")
        self._log(f"  Binary: {self.install_dir / BINARY_NAME}")
        self._log("═══════════════════════════════════════════════")
        self._finished(True, "Installation completed successfully!")
