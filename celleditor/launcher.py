"""The start page's backend: a project's game files and plugins, the folder browser, unreadable folders."""
import json
import os
import sys

from .gamedata import GameData, cfg_candidates, read_cfg
from .loadorder import TES3_EXTENSIONS, masters_of

OFFICIAL = ("Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm")
DENIED = set()            # folders macOS refused this session (listing raises PermissionError; stat works)


# --- Folders the editor may not read ---------------------------------------------------

def can_read(folder):
    """True if the folder can be listed, False if that's not allowed, None if it isn't there."""
    try:
        os.listdir(folder)
        return True
    except PermissionError:
        DENIED.add(folder)
        return False
    except OSError:
        return None


def blocked(folders):
    """The folders, or the nearest existing folder above each, that can't be read."""
    out = []
    for folder in folders:
        while folder and not os.path.exists(folder) and os.path.dirname(folder) != folder:
            folder = os.path.dirname(folder)
        if folder and can_read(folder) is False and folder not in out:
            out.append(folder)
    return out


def area_of(folder):
    """A protected place by the name macOS's settings give it, or the folder."""
    home = os.path.expanduser("~")
    for sub, label in (("Documents", "Documents"), ("Downloads", "Downloads"), ("Desktop", "Desktop"),
                       (os.path.join("Library", "Mobile Documents"), "iCloud Drive")):
        base = os.path.join(home, sub)
        if folder == base or folder.startswith(base + os.sep):
            return label
    if folder.startswith("/Volumes/"):
        return "Removable Volumes"
    return folder


def areas(folders):
    out = []
    for f in folders:
        a = area_of(f)
        if a not in out:
            out.append(a)
    return out


def denied_message(folders):
    """What to say when folders can't be read."""
    names = areas(folders)
    if sys.platform == "darwin" and all(not n.startswith("/") for n in names):
        return "OpenMW Cell Editor needs permission to read your %s folder%s." % (
            " and ".join(names), "s" if len(names) > 1 else "")
    return "The editor can't read %s." % ", ".join(names)


# --- Plugins -----------------------------------------------------------------------------

def plugin_info(path):
    """{name, path, folder, masters} of a plugin file; ValueError if it isn't one."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ValueError("There's no content file %s." % path)
    if not path.lower().endswith(TES3_EXTENSIONS):
        raise ValueError("%s isn't a content file (.esm, .esp or .omwaddon)." % os.path.basename(path))
    with open(path, "rb") as f:
        if f.read(4) != b"TES3":
            raise ValueError("%s isn't a Morrowind content file." % os.path.basename(path))
    return {"name": os.path.basename(path), "path": path, "folder": os.path.dirname(path),
            "masters": masters_of(path)}


def data_files_info(folder):
    """The Data Files folder's official plugins; ValueError if it has no Morrowind.esm."""
    folder = os.path.abspath(os.path.expanduser(folder.strip().strip('"\'')))
    if can_read(folder) is False:
        raise PermissionError(13, "not allowed", folder)
    names = {n.lower(): n for n in os.listdir(folder)} if os.path.isdir(folder) else {}
    if "morrowind.esm" not in names:
        raise ValueError("Morrowind.esm was not found in %s. Please select the Data Files folder containing "
                         "Morrowind.esm." % folder)
    return {"path": folder, "official": [plugin_info(os.path.join(folder, names[n.lower()]))
                                         for n in OFFICIAL if n.lower() in names]}


def order(plugins):
    """Plugins in an order that loads each after its masters, otherwise as given."""
    out, placed = [], set()
    by_name = {p["name"].lower(): p for p in plugins}

    def place(p, seen=()):
        if p["name"].lower() in placed or p["name"].lower() in seen:
            return
        for m in p["masters"]:
            if m.lower() in by_name:
                place(by_name[m.lower()], seen + (p["name"].lower(),))
        placed.add(p["name"].lower())
        out.append(p)

    for p in plugins:
        place(p)
    return out


def folder_info(path):
    """{path, name, assets} of a mod folder; ValueError if it isn't a folder."""
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"\'')))
    if not os.path.isdir(path):
        raise ValueError("There's no folder %s." % path)
    if can_read(path) is False:
        raise PermissionError(13, "not allowed", path)
    names = {n.lower() for n in os.listdir(path)}
    assets = [n for n in ("meshes", "textures", "icons") if n in names] + (
        ["archives"] if any(n.endswith(".bsa") for n in names) else [])
    if not assets:
        raise ValueError("%s has no meshes or textures folder (or .bsa archive) in it. Please select a folder "
                         "containing mod assets." % os.path.basename(path))
    return {"path": path, "name": os.path.basename(path), "assets": assets}


def cfg_data_dirs():
    """The data folders in the first openmw.cfg found, or []."""
    found = cfg_candidates()
    if not found:
        return []
    base = os.path.dirname(found[0])
    return [d if os.path.isabs(d) else os.path.join(base, d) for d in read_cfg(found[0]).get("data", [])]


def cfg_archives():
    """The archives openmw.cfg names (fallback-archive=), or []."""
    found = cfg_candidates()
    return read_cfg(found[0]).get("fallback-archive", []) if found else []


def _find_in(name, folders, listings):
    """A file by name, any case, in the first of the folders that has it."""
    for d in folders:
        if d not in listings:
            try:
                listings[d] = {n.lower(): n for n in os.listdir(d)}
            except OSError:
                listings[d] = {}
        n = listings[d].get(name.lower())
        if n:
            return os.path.join(d, n)
    return None


def with_masters(plugins, data_files, folders=()):
    """Plugins plus the masters they need, in load order, and the names of masters found nowhere."""
    out = list(plugins)
    names = {p["name"].lower() for p in out}
    missing, listings, todo = [], {}, list(out)
    cfg = None
    while todo:
        p = todo.pop(0)
        for m in p["masters"]:
            if m.lower() in names:
                continue
            near = [p["folder"], data_files] + [q["folder"] for q in out] + list(folders)
            path = _find_in(m, near, listings)
            if path is None:
                if cfg is None:
                    cfg = cfg_data_dirs()
                path = _find_in(m, reversed(cfg), listings)       # a later data folder wins
            names.add(m.lower())
            if path is None:
                missing.append(m)
                continue
            info = plugin_info(path)
            out.append(info)
            todo.append(info)
    return order(out), missing


def resolve(path, have, data_files, folders=()):
    """What adding a content file adds: {add: its missing masters then it, missing: masters found nowhere}."""
    target = plugin_info(path)
    current = []
    for h in have:
        try:
            current.append(plugin_info(h))
        except (OSError, ValueError):
            continue
    if any(os.path.normcase(c["path"]) == os.path.normcase(target["path"]) for c in current):
        return {"add": [], "missing": []}
    full, missing = with_masters(current + [target], data_files, folders)
    known = {os.path.normcase(c["path"]) for c in current}
    return {"add": [p for p in full if os.path.normcase(p["path"]) not in known], "missing": missing}


def openmw_load_order():
    """The plugins in the first openmw.cfg found, for picking from, or None without one."""
    found = cfg_candidates()
    if not found:
        return None
    cfg = read_cfg(found[0])
    base = os.path.dirname(found[0])
    dirs = [d if os.path.isabs(d) else os.path.join(base, d) for d in cfg.get("data", [])]
    listing = {}
    denied = []
    for d in dirs:
        ok = can_read(d)
        if ok is False:
            denied.append(d)
        listing[d] = {n.lower(): n for n in os.listdir(d)} if ok else {}
    folders = []
    for d in dirs:
        names = set(listing[d])
        has_assets = {"meshes", "textures"} & names or any(n.endswith(".bsa") for n in names)
        if has_assets and not any(n.endswith(TES3_EXTENSIONS) for n in names):
            folders.append({"path": d, "name": os.path.basename(d)})
    out = []
    for name in cfg.get("content", []):
        if not name.lower().endswith(TES3_EXTENSIONS):
            continue
        where = next((d for d in reversed(dirs) if name.lower() in listing[d]), None)
        if where:
            info = plugin_info(os.path.join(where, listing[where][name.lower()]))
            out.append(dict(info, denied=False))
        else:
            out.append({"name": name, "path": None, "folder": None, "masters": [], "denied": bool(denied)})
    return {"cfg": found[0], "plugins": out, "folders": folders, "denied": denied,
            "deniedText": denied_message(denied) if denied else ""}


# --- A project's game files --------------------------------------------------------------

def openmw_setup():
    """(data folders, TES3 content file names, archive names) from openmw.cfg, or None without one."""
    found = cfg_candidates()
    if not found:
        return None
    cfg = read_cfg(found[0])
    base = os.path.dirname(found[0])
    dirs = [d if os.path.isabs(d) else os.path.join(base, d) for d in cfg.get("data", [])]
    content = [c for c in cfg.get("content", []) if c.lower().endswith(TES3_EXTENSIONS)]
    return dirs, content, cfg.get("fallback-archive", [])


def game_for(config):
    """The GameData of a project with "data_files", or None without."""
    data = config.get("data_files")
    if not data:
        return None
    paths = [p for p in config.get("load_order") or [] if p]
    if config.get("base_order") == "openmw" and openmw_setup():
        cfg_dirs, cfg_content, cfg_arch = openmw_setup()
        dirs = ([data] if data not in cfg_dirs else []) + list(cfg_dirs)
        for d in [os.path.dirname(p) for p in paths] + list(config.get("folders") or []):
            if d not in dirs:
                dirs.append(d)
        names = list(cfg_content)
        for p in paths:
            if os.path.basename(p).lower() not in {n.lower() for n in names}:
                names.append(os.path.basename(p))
        game = GameData(dirs, list(cfg_arch), names)
        game.wanted_dirs = dirs
        return game
    dirs = [data]
    for p in paths:
        d = os.path.dirname(p)
        if d not in dirs:
            dirs.append(d)
    for d in config.get("folders") or []:
        if d not in dirs:
            dirs.append(d)
    archives = [a for a in ("Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa") if os.path.exists(os.path.join(data, a))]

    def add(names):
        for n in names:
            if n.lower() not in {a.lower() for a in archives}:
                archives.append(n)

    def bsas(d):
        try:
            return sorted(n for n in os.listdir(d) if n.lower().endswith(".bsa"))
        except OSError:
            return []

    for p in paths:
        d = os.path.dirname(p)
        own = os.path.splitext(os.path.basename(p))[0].lower() + ".bsa"
        add([n for n in bsas(d) if d != data or n.lower() == own])
    for d in config.get("folders") or []:
        add(bsas(d))
    in_dirs = {n.lower() for d in dirs for n in bsas(d)}
    add([n for n in cfg_archives() if n.lower() in in_dirs])
    game = GameData(dirs, archives, [os.path.basename(p) for p in paths])
    game.wanted_dirs = dirs
    return game


def defaults(settings):
    """What a new project starts with: its Data Files folder, save location and load order size."""
    data = settings.get("last_data_files") if settings else None
    setup = openmw_setup()
    if not data and setup:
        for d in setup[0]:
            if can_read(d) and any(n.lower() == "morrowind.esm" for n in os.listdir(d)):
                data = d
                break
    return {"dataFiles": data, "saveFolder": settings.get("last_save_folder") if settings else None,
            "openmwCount": len(setup[1]) if setup else 0}


def folders_of(config, project_dir):
    """Every folder a project reads or writes."""
    out = [project_dir]
    openmw = openmw_setup()[0] if config.get("base_order") == "openmw" and openmw_setup() else []
    for f in ([config.get("data_files")] + [os.path.dirname(p) for p in config.get("load_order") or []]
              + list(config.get("folders") or []) + list(openmw)):
        if f and f not in out:
            out.append(f)
    plugin = config.get("plugin")
    if plugin:
        d = os.path.dirname(os.path.join(project_dir, plugin))
        if d not in out:
            out.append(d)
    return out


def summary(path, config=None):
    """What the start page shows about a project."""
    if config is None:
        with open(path) as f:
            config = json.load(f)
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.lower() in ("celleditor", "project"):
        stem = os.path.basename(os.path.dirname(path))
    folder = os.path.dirname(path)
    return {"path": path, "name": config.get("name") or stem, "plugin": os.path.basename(config.get("plugin", "")),
            "pluginPath": os.path.join(folder, config.get("plugin", "")),
            "kind": "in place" if config.get("base") else "generator" if config.get("generator") else "new",
            "dataFiles": config.get("data_files"), "loadOrder": config.get("load_order"),
            "folders": config.get("folders") or [],
            "baseOrder": config.get("base_order") or "game", "standalone": bool(config.get("standalone")),
            "own": bool(config.get("data_files"))}


# --- The folder browser ------------------------------------------------------------------

def places():
    home = os.path.expanduser("~")
    out = [("Home", home)] + [(n, os.path.join(home, n)) for n in ("Documents", "Desktop", "Downloads")]
    if sys.platform == "win32":
        out += [("%s:" % d, "%s:\\" % d) for d in "CDEFGH" if os.path.exists("%s:\\" % d)]
        out += [("Steam", os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\"), "Steam", "steamapps", "common"))]
    elif sys.platform == "darwin":
        out += [("Applications", "/Applications"), ("Volumes", "/Volumes")]
    else:
        out += [("/", "/"), ("Steam", os.path.join(home, ".local", "share", "Steam", "steamapps", "common"))]
    return [{"name": n, "path": p} for n, p in out if os.path.isdir(p) and p not in DENIED]


def browse(path, want):
    """A folder's subfolders and the files that fit want ("folder", "plugin" or "project")."""
    home = os.path.expanduser("~")
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"\''))) if path and path.strip() else home
    while not os.path.isdir(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    ext = {"plugin": TES3_EXTENSIONS, "project": (".json",)}.get(want, ())
    parent = os.path.dirname(path)
    out = {"path": path, "parent": parent if parent != path else None, "dirs": [], "files": [],
           "places": places(), "sep": os.sep, "hasMorrowind": False, "denied": False}
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except PermissionError:
        DENIED.add(path)
        out["places"] = places()
        return dict(out, denied=True, deniedText=denied_message([path]))
    except OSError as e:
        raise ValueError("Can't open %s: %s" % (path, e.strerror))
    for n in names:
        if n.startswith("."):
            continue
        full = os.path.join(path, n)
        if os.path.isdir(full):
            if full not in DENIED:
                out["dirs"].append(n)
        elif ext and n.lower().endswith(ext) and not n.startswith("layout_"):
            out["files"].append(n)
    low = {n.lower() for n in names}
    out["hasMorrowind"] = "morrowind.esm" in low
    out["hasAssets"] = bool({"meshes", "textures", "icons"} & low) or any(n.endswith(".bsa") for n in low)
    out["hasContent"] = any(n.endswith(TES3_EXTENSIONS) for n in low)
    hidden = sorted(d for d in DENIED if os.path.dirname(d) == path)
    if hidden:
        out["hidden"] = [os.path.basename(d) for d in hidden]
        out["deniedText"] = denied_message(hidden)
    return out
