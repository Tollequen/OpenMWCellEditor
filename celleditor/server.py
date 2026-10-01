"""The editor's local web server: pages, cells, meshes and textures, and saving edits."""
import hmac
import json
import os
import shutil
import struct
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import desktop, esp, launcher, models, nif, qr, writer
from .history import History, states
from .live import LIVE

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
LOCK = threading.Lock()
STRUCTURE_PREFIXES = ("in_", "ex_", "terrain_")

project = None
history = None
_models = _catalog = _land = None
_mesh_cache, _tex_cache = {}, {}
_disk_meshes = set()


def setup(p):
    """Switch to a project and reset the caches that depend on it."""
    global project, history, _models, _catalog, _land
    project = p
    history = History(p.file("history"))
    _models = _catalog = _land = None
    _disk_meshes.clear()
    LIVE.start(p.path, p.load_edits())
    if SETTINGS:
        SETTINGS.add_recent(p.path)
    threading.Thread(target=lambda: (model_index(), _land_index()), daemon=True).start()


# --- The start page: projects, setting one up, and opening it -------------------------------

GAME = None
SETTINGS = None
SERVER = None
AUTO_STOP = False
GUI = False


def _listdir(folder):
    """A folder's names, or none if it can't be read."""
    try:
        return os.listdir(folder)
    except OSError:
        return []


def home_info():
    """The start page's projects and the game setups a new one can start from."""
    from .gamedata import cfg_candidates
    from .settings import projects_dir
    infos = SETTINGS.get("project_info", {}) if SETTINGS else {}
    hidden = set(SETTINGS.get("hidden", [])) if SETTINGS else set()
    items, seen = [], set()

    def add(path, read):
        path = os.path.abspath(path)
        if path in seen or path in hidden:
            return
        info = infos.get(path)
        if info is None and read:
            try:
                info = launcher.summary(path)
            except (OSError, ValueError, KeyError):
                return
        if info is None:
            info = dict(launcher.summary(path, {}), kind=None, plugin="")
        seen.add(path)
        items.append(dict(info, open=bool(project and project.path == path), **thumb_info(path)))

    for p in (SETTINGS.recent() if SETTINGS else []):
        add(p, read=False)
    folder = projects_dir()
    for d in sorted(_listdir(folder)):
        sub = os.path.join(folder, d)
        for f in sorted(_listdir(sub)):
            if f.endswith(".json") and not f.startswith("layout_"):
                add(os.path.join(sub, f), read=True)
    cfg = cfg_candidates()
    return {"projects": items, "projectsDir": folder, "cfg": cfg[0] if cfg else None,
            "lastDataFiles": SETTINGS.get("last_data_files") if SETTINGS else None,
            "platform": sys.platform, "homeDir": os.path.expanduser("~"),
            "open": project.path if project else None}


def _remember(path, config):
    """Note a project in the recent list with what the start page shows about it."""
    if SETTINGS:
        SETTINGS.add_recent(path)
        infos = dict(SETTINGS.get("project_info", {}))
        infos[os.path.abspath(path)] = launcher.summary(os.path.abspath(path), config)
        SETTINGS.set("project_info", infos)
        if path in SETTINGS.get("hidden", []):
            SETTINGS.set("hidden", [h for h in SETTINGS.get("hidden", []) if h != path])


# --- Project pictures (the start page shows the cell each was last saved in) ------------

def _thumb_file(path, ext):
    """Paths of a project's picture and its note, next to the editor's settings."""
    import hashlib
    from .settings import Settings
    name = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode()).hexdigest()[:16]
    return os.path.join(os.path.dirname(Settings.default_path()), "thumbs", name + ext)


def save_thumb(data, cell, saved):
    """Store the page's picture of the open project, taken in cell."""
    import base64
    import time
    head, _, b64 = (data or "").partition(",")
    if head != "data:image/jpeg;base64" or len(b64) > 500000:
        raise ValueError("not a project picture")
    pic = _thumb_file(project.path, ".jpg")
    os.makedirs(os.path.dirname(pic), exist_ok=True)
    with open(pic, "wb") as f:
        f.write(base64.b64decode(b64))
    note = _thumb_note(project.path)
    note["cell"] = cell
    if saved:
        note["savedAt"] = int(time.time() * 1000)
    with open(_thumb_file(project.path, ".json"), "w") as f:
        json.dump(note, f)
    return {}


def _thumb_note(path):
    try:
        with open(_thumb_file(path, ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def thumb_info(path):
    """What the start page shows of a project's picture: {thumb, cell, savedAt}."""
    pic = _thumb_file(path, ".jpg")
    try:
        mtime = int(os.stat(pic).st_mtime)
    except OSError:
        return {}
    note = _thumb_note(path)
    return {"thumb": "/api/thumb?id=%s&v=%d" % (os.path.basename(pic)[:-4], mtime),
            "cell": note.get("cell"), "savedAt": note.get("savedAt")}


def _read_project(path):
    path = _clean_path(path)
    if os.path.isdir(path):
        found = [f for f in sorted(os.listdir(path)) if f.endswith(".json") and not f.startswith("layout_")
                 and _is_project(os.path.join(path, f))]
        if len(found) != 1:
            raise ValueError("%s is a folder%s. Choose the project file (.json) in it." % (
                path, " with several project files" if found else " without a project file"))
        path = os.path.join(path, found[0])
    if not os.path.exists(path):
        raise ValueError("There's no project file %s." % path)
    if not _is_project(path):
        raise ValueError("%s isn't a project file (a .json file with a \"plugin\")." % path)
    with open(path) as f:
        return path, json.load(f)


def project_page(path):
    """A project's setup for its page, and the folders it may not read."""
    path, config = _read_project(path)
    folder = os.path.dirname(path)
    blocked = launcher.blocked(launcher.folders_of(config, folder))
    plugins = []
    for p in config.get("load_order") or []:
        try:
            plugins.append(launcher.plugin_info(p))
        except PermissionError:
            plugins.append({"name": os.path.basename(p), "path": p, "folder": os.path.dirname(p), "masters": [],
                            "missing": "not allowed"})
        except ValueError:
            plugins.append({"name": os.path.basename(p), "path": p, "folder": os.path.dirname(p), "masters": [],
                            "missing": "not found"})
    if config.get("base_order") == "openmw":
        have = {p["name"].lower() for p in plugins}
        target = os.path.normcase(config["plugin"]) if config.get("base") else None
        at = next((i for i, p in enumerate(plugins) if os.path.normcase(p["path"]) == target), len(plugins))
        extra = [p for p in (launcher.openmw_load_order() or {"plugins": []})["plugins"]
                 if p["path"] and p["name"].lower() not in have]
        plugins[at:at] = extra
    folders = []
    for d in config.get("folders") or []:
        try:
            folders.append(launcher.folder_info(d))
        except (ValueError, PermissionError) as e:
            folders.append({"path": d, "name": os.path.basename(d), "assets": [],
                            "missing": "not allowed" if isinstance(e, PermissionError) else "not found"})
    setup_ = launcher.openmw_setup()
    info = launcher.summary(path, config)
    try:
        masters = launcher.masters_of(info["pluginPath"]) if os.path.isfile(info["pluginPath"]) else []
    except (OSError, ValueError):
        masters = []
    return dict(info, plugins=plugins, folderList=folders, blocked=launcher.areas(blocked), pluginMasters=masters,
                openmwCount=len(setup_[1]) if setup_ else 0,
                blockedText=launcher.denied_message(blocked) if blocked else "", deletable=_in_projects_folder(path),
                open=bool(project and project.path == path))


def save_project(path, data_files, load_order, folders=(), base_order=None, standalone=None):
    """Change a project's data folders, content files, base and standalone setting."""
    path, config = _read_project(path)
    if not config.get("data_files"):
        raise ValueError("This project uses OpenMW's settings for its game files.")
    data = launcher.data_files_info(data_files)
    plugins = [launcher.plugin_info(p) for p in load_order]
    if config.get("base") and not any(os.path.normcase(p["path"]) == os.path.normcase(config["plugin"])
                                      for p in plugins):
        plugins.append(launcher.plugin_info(config["plugin"]))
    plugins, _ = launcher.with_masters(plugins, data["path"], folders)
    config["data_files"], config["load_order"] = data["path"], [p["path"] for p in plugins]
    config["folders"] = [launcher.folder_info(d)["path"] for d in folders]
    if base_order in ("game", "openmw"):
        config["base_order"] = base_order
    if standalone is not None:
        config["standalone"] = bool(standalone)
    with open(path, "w") as f:
        json.dump(config, f, indent=1)
    _remember(path, config)
    if project is not None and project.path == path:
        _reload_project()
    return project_page(path)


def create_project(body):
    """Create a new project from the start page."""
    from . import project as projects
    from .settings import projects_dir
    data = launcher.data_files_info(body["dataFiles"])
    plugins = launcher.order([launcher.plugin_info(p) for p in body.get("loadOrder") or []])
    if body["mode"] == "edit":
        target = launcher.plugin_info(body["plugin"])
        if not any(os.path.normcase(p["path"]) == os.path.normcase(target["path"]) for p in plugins):
            plugins = plugins + [target]
        name = os.path.splitext(target["name"])[0]
    else:
        name = (body.get("newName") or "").strip()
        if not name or any(c in name for c in '/\\:*?"<>|') or name.startswith("."):
            raise ValueError("The content file needs a name that works as a file name (no / \\ : * ? \" < > |).")
        where = _clean_path(body.get("newFolder") or "")
        if not os.path.isdir(where):
            raise ValueError("Select the folder to save the content file in.")
        if launcher.can_read(where) is False:
            raise PermissionError(13, "not allowed", where)
        ext = body.get("newType") if body.get("newType") in (".omwaddon", ".esp", ".esm") else ".omwaddon"
        target_path = os.path.join(where, name + ext)
        if os.path.exists(target_path):
            raise ValueError("There's already a %s in that folder." % os.path.basename(target_path))
    folders = [launcher.folder_info(d)["path"] for d in body.get("folders") or []]
    plugins, missing = launcher.with_masters(plugins, data["path"], folders)
    if missing:
        raise ValueError("Needs %s, which wasn't found: add it as a resource first." % ", ".join(missing))
    base_order = body.get("baseOrder") if body.get("baseOrder") in ("game", "openmw") else "game"
    setup_ = {"data_files": data["path"], "load_order": [p["path"] for p in plugins], "name": name,
              "folders": folders, "base_order": base_order,
              "standalone": bool(body.get("standalone", base_order == "openmw"))}
    folder, n = os.path.join(projects_dir(), name), 2
    while os.path.exists(folder):
        folder, n = os.path.join(projects_dir(), "%s %d" % (name, n)), n + 1
    os.makedirs(folder, exist_ok=True)
    if body["mode"] == "edit":
        path = projects.create_in_place(folder, target["path"], setup_)
    else:
        path = projects.create_new(folder, target_path, setup_)
    if SETTINGS:
        SETTINGS.set("last_data_files", data["path"])
        if body["mode"] != "edit":
            SETTINGS.set("last_save_folder", where)
    with open(path) as f:
        _remember(path, json.load(f))
    if body["mode"] != "edit":
        projects.load(path, GAME).build()
    return {"path": path}


def open_project(path):
    from . import project as projects
    from .gamedata import GameData
    path, config = _read_project(path)
    blocked = launcher.blocked(launcher.folders_of(config, os.path.dirname(path)))
    if blocked:
        raise ValueError(launcher.denied_message(blocked) + " Open the project's page to allow it.")
    game = GAME
    if not config.get("data_files") and game is None:
        try:
            game = GameData.from_cfg()
        except FileNotFoundError:
            raise ValueError("This project uses OpenMW's settings (openmw.cfg), and there's none on this computer.")
    with LOCK:
        try:
            setup(projects.load(path, game))
        except FileNotFoundError as e:
            raise ValueError(str(e))
    _remember(path, config)
    return {"ok": True, "name": project.name}


def _in_projects_folder(path):
    """Whether a project lives in the editor's own projects folder."""
    from .settings import projects_dir
    root = os.path.realpath(projects_dir())
    folder = os.path.realpath(os.path.dirname(path))
    return os.path.dirname(folder) == root


def delete_project(path):
    """Delete a project made on the start page; its content file is left alone."""
    global project
    path, config = _read_project(path)
    if not _in_projects_folder(path):
        raise ValueError("This project's files aren't the editor's own: it can only be removed from the list.")
    plugin = os.path.normcase(os.path.realpath(os.path.join(os.path.dirname(path), config.get("plugin", ""))))
    folder = os.path.dirname(path)
    if plugin.startswith(os.path.normcase(os.path.realpath(folder)) + os.sep):
        raise ValueError("The content file is inside the project's folder, so the project isn't deleted.")
    with LOCK:
        if project is not None and project.path == path:
            project = None
        esp.release()                              # Windows can't delete a memory-mapped file
        shutil.rmtree(folder)
    forget_project(path)
    for ext in (".jpg", ".json"):
        try:
            os.remove(_thumb_file(path, ext))
        except OSError:
            pass
    if SETTINGS:
        infos = dict(SETTINGS.get("project_info", {}))
        infos.pop(path, None)
        SETTINGS.set("project_info", infos)
        SETTINGS.set("hidden", [h for h in SETTINGS.get("hidden", []) if h != path])
    return {}


def forget_project(path):
    """Take a project off the start page's list; its files stay."""
    if SETTINGS:
        path = os.path.abspath(path)
        SETTINGS.set("hidden", sorted(set(SETTINGS.get("hidden", [])) | {path}))
        SETTINGS.set("recent", [p for p in SETTINGS.get("recent", []) if p != path])
    return {}


def _reload_project():
    """Reload the open project after its setup changed."""
    from . import project as projects
    if project is not None:
        with LOCK:
            setup(projects.load(project.path, GAME))


def _is_project(path):
    try:
        with open(path) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(c, dict) and "plugin" in c


def _clean_path(path):
    """A typed or pasted path: unquoted, with ~ expanded, absolute."""
    path = (path or "").strip().strip('"\'')
    if not path:
        raise ValueError("Choose a file or folder first.")
    return os.path.abspath(os.path.expanduser(path))


def permission_message(e):
    """The message for a file the editor may not read or write."""
    where = e.filename or "a file"
    if sys.platform == "darwin":
        return ("The editor isn't allowed to use %s. Allow it in System Settings › Privacy & Security › "
                "Files and Folders, then restart the editor (on its start page)." % where)
    if sys.platform == "win32":
        return ("Windows didn't let the editor write %s. If Windows Security's Controlled folder access is on, "
                "allow Morrowind Cell Editor there (Virus & threat protection › Ransomware protection); otherwise "
                "check that the file isn't read-only or open in another program." % where)
    return "No permission to use %s." % where


def open_privacy_settings():
    """Open macOS System Settings at Privacy & Security > Files and Folders."""
    import subprocess
    if sys.platform != "darwin":
        raise ValueError("This is for macOS.")
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"])
    return {}


def restart():
    """Restart the editor in a new process on the same port."""
    import subprocess

    def again():
        SERVER.shutdown()
        SERVER.server_close()
        frozen = getattr(sys, "frozen", False)
        args = [a for a in sys.argv[1:] if a not in ("--no-browser", "--stop-when-closed")]
        cmd = [sys.executable] + ([] if frozen else [os.path.abspath(sys.argv[0])]) + args + ["--no-browser"]
        if AUTO_STOP:
            cmd.append("--stop-when-closed")
        log = open(os.path.join(os.path.dirname(SETTINGS.path), "editor.log"), "a") if SETTINGS else subprocess.DEVNULL
        subprocess.Popen(cmd, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    t = threading.Timer(0.3, again)
    t.daemon = False              # request threads are daemons; this timer must outlive the server
    t.start()
    return {}


def model_index():
    """The object index (id -> (type, mesh)) of the masters and the project, and the catalog."""
    global _models, _catalog
    if _models is None:
        m, c, _ = models.load(project.load.paths)
        usable = project.usable_files()
        if usable is not None:
            c = [o for o in c if o["file"].lower() in usable]
        _catalog = json.dumps(c).encode()
        _models = m
    extra = project.extra_models()
    _disk_meshes.update(v[1] for v in extra.values() if v[1] and os.path.isabs(v[1]))
    return dict(_models, **extra)


def _gather(extra=(), edits=None):
    """The project's cells with the saved edits, or with the given edits."""
    with LOCK:
        project.edits_override = None if edits is None else dict(writer.empty_edits(), **edits)
        try:
            cells, vanilla, keys = project.gather(extra)
        finally:
            project.edits_override = None
        return cells, vanilla, project.clones(), keys


def _entry(r, clones, index):
    src = clones.get(r["id"], r["id"].lower())
    m = index.get(src.lower())
    kind = "marker"
    if m and m[0] == "NPC_":
        kind = "npc"
    elif m and m[1] and not m[1].lower().endswith("editormarker.nif"):
        kind = "mesh"
    elif m and m[0] == "LIGH":
        kind = "light"
    t = project.tier(r["id"])
    structure = bool(m and m[0] == "STAT" and (src.startswith(STRUCTURE_PREFIXES) or src in project.structure_ids()))
    origin = "vanilla" if r.get("vanilla") else "added" if r.get("added") else "mod"
    pos, rot = [float(v) for v in r["pos"]], [float(v) for v in r["rot"]]
    orig_src = clones.get(r["orig_id"], r["orig_id"].lower()) if r.get("orig_id") else src
    orig = r.get("orig") or {"pos": pos, "rot": rot, "scale": r.get("scale")}
    orig = dict(orig, scale=float(orig.get("scale") or 1.0))
    return {"key": r.get("key", ""), "id": r["id"], "src": src, "origSrc": orig_src, "kind": kind,
            "structure": structure, "origin": origin, "mesh": m[1] if kind == "mesh" else None,
            "pos": pos, "rot": rot, "scale": r.get("scale") or 1.0, "editable": project.can_edit(r),
            "file": r.get("origin"), "changedBy": r.get("changed_by") or [],
            "isDoor": bool(m and m[0] == "DOOR"), "door": _door(r),
            "winsOver": [f for f in r.get("changed_by") or [] if f.lower() in project.loads_after],
            "nook": t[0] if t else None, "tier": t[1] if t else None, "only": bool(t and t[2]), "orig": orig}


def _door(r):
    """Where a door leads: {cell, interior, pos, heading}, or None."""
    if not r.get("dest"):
        return None
    cell, pos, heading = r["dest"]
    if not cell:
        g = writer.grid_of(pos)
        cell = esp.exterior_key(g, project.load.cells()[1].get(g, ""))
    return {"cell": cell, "interior": bool(r["dest"][0]), "pos": [float(v) for v in pos], "heading": float(heading)}


def all_cells():
    """The cell list: the project's own cells, then the load order's, interiors first."""
    interiors, exteriors = project.load.cells()
    known = {n.lower() for n in interiors}
    out = [{"name": n, "exterior": False} for n in project.own_cells
           if n.lower() not in known and not esp.parse_exterior(n)]
    out += [{"name": n, "exterior": False} for n in interiors]
    out += [{"name": esp.exterior_key(g, exteriors[g]), "exterior": True, "grid": list(g)}
            for g in sorted(exteriors, key=lambda g: (exteriors[g].lower(), g))]
    return out


def favorites():
    """The project's favorites: {"cells": [...], "objects": [...], "recent": [...]}; an older file is a list of cells."""
    path = project.file("favorites")
    f = {}
    if os.path.exists(path):
        with open(path) as fh:
            f = json.load(fh)
    if isinstance(f, list):
        f = {"cells": f}
    f.setdefault("cells", list(project.own_cells))
    f.setdefault("objects", [])
    f.setdefault("recent", [])
    return f


def info():
    """What the page shows about the project."""
    return {"name": project.name, "plugin": os.path.basename(project.plugin), "nooks": project.nooks,
            "masters": [os.path.basename(m) for m in project.masters], "fixedMasters": project.fixed_masters,
            "inPlace": project.in_place, "loadOrder": [f.name for f in project.load.files], "path": project.path,
            "standalone": bool(project.config.get("standalone")), "canEditNpcs": project.can_edit_npcs}


# --- NPCs -----------------------------------------------------------------------------

def npc_list():
    return {"npcs": project.npcs().npcs(), "canEdit": project.can_edit_npcs}


def npc_one(oid):
    n = project.npcs().npc(oid)
    if n is None:
        raise KeyError(oid)
    return n


def npc_dialogue(oid, edits):
    """An NPC's responses by topic, with the given dialogue edits."""
    with LOCK:
        return {"topics": project.dialogue().for_actor(oid, edits), "canEdit": project.can_edit_npcs}


def npc_id(oid):
    """Whether an id is free for a new NPC."""
    t = project.npcs().find(oid)
    return {"taken": list(t) if t else None}


def scene():
    """Everything the editor needs except the cells' contents."""
    cells, vanilla, clones, keys = _gather()
    nooks = {}
    for refs in cells.values():
        for r in refs:
            t = project.tier(r["id"])
            if t:
                nooks[t[0]] = max(nooks.get(t[0], 0), t[1])
    edits = project.load_edits()
    orphans = [k for k in list(edits["moved"]) + edits["deleted"] + list(edits["replaced"]) if k not in keys]
    fav = favorites()
    names = {c["name"] for c in all_cells()}
    start = project.config["start_cell"]
    start = start if start in names else next(iter(project.own_cells), None) or sorted(names)[0]
    return {"project": info(), "cells": all_cells(), "own": list(project.own_cells), "favorites": fav["cells"],
            "objectFavorites": fav["objects"], "recentObjects": fav["recent"], "startCell": start, "nooks": nooks,
            "edits": edits, "live": LIVE.state(), "orphans": orphans, "notice": _take_notice(),
            "hasThumb": os.path.exists(_thumb_file(project.path, ".jpg"))}


def _take_notice():
    """Take the project's notice, shown once."""
    n, project.notice = project.notice, None
    return n


def cell_data(name, edits=None):
    """One cell's contents after the edits, with camera start, water and terrain."""
    grid = esp.parse_exterior(name)
    others = _moved_in_from(grid, edits) - {name} if grid else set()
    cells, vanilla, clones, _ = _gather([name, *others], edits)
    index = model_index()
    placed = writer.view(cells, vanilla, name)
    for c in others:
        placed += [r for r in writer.view(cells, vanilla, c) if writer.grid_of(r["pos"]) == tuple(grid)]
    for k, v in ((edits or project.load_edits()).get("npcs") or {}).items():
        if v.get("new"):
            index[k] = ("NPC_", v.get("model") or "")
    refs = [_entry(r, clones, index) for r in placed]
    try:
        water = project.water(name)
    except KeyError:
        water = None
        try:
            head = dict(project.load.cell_head(name))
            flags = struct.unpack_from("<I", head["DATA"])[0]
            if grid:
                water = 0.0 if flags & 0x02 else None
            elif flags & 0x02:
                water = struct.unpack("<f", head["WHGT"])[0] if "WHGT" in head else float(
                    struct.unpack("<i", head["INTV"])[0]) if "INTV" in head else None
        except KeyError:
            pass
    start = project.start(name)
    if start:
        (x, y, z), heading = start
        start = {"pos": [x, y, z + 90.0], "yaw": heading}
    elif grid:
        cx, cy = grid[0] * 8192 + 4096, grid[1] * 8192 + 4096
        start = {"pos": [cx, cy - 2500, terrain_height(grid, cx, cy - 2500) + 900], "yaw": 0.0, "pitch": -0.35}
    elif refs:
        xs, ys, zs = (sorted(r["pos"][i] for r in refs) for i in range(3))
        mid = len(refs) // 2
        start = {"pos": [xs[mid], ys[mid], zs[mid] + 60], "yaw": 0.0}
    else:
        start = {"pos": [0, 0, 100], "yaw": 0.0}
    can_add = project.can_add(name)
    return {"name": name, "refs": refs, "start": start, "water": water, "grid": list(grid) if grid else None,
            "canAdd": can_add}


def _moved_in_from(grid, edits=None):
    """Exterior cells whose edited objects now stand in grid."""
    edits = dict(writer.empty_edits(), **edits) if edits else project.load_edits()
    out = set()
    for k, m in edits["moved"].items():
        cell = k.split("|")[0]
        if not k.startswith("added|") and esp.parse_exterior(cell) and writer.grid_of(m["pos"]) == tuple(grid):
            out.add(cell)
    for a in edits["added"]:
        pos = edits["moved"].get("added|" + a["uid"], a)["pos"]
        if esp.parse_exterior(a["cell"]) and writer.grid_of(pos) == tuple(grid):
            out.add(a["cell"])
    return out


# --- Terrain (exterior cells) ---------------------------------------------

def _land_index():
    """The LAND records by grid and the land textures by file."""
    global _land
    if _land is None:
        _land = project.load.land()
    return _land


def _heights(d):
    v = d["VHGT"]
    offset = struct.unpack_from("<f", v, 0)[0]
    delta = struct.unpack_from("<4225b", v, 4)
    out, start = [], offset
    for j in range(65):
        row = delta[j * 65:j * 65 + 65]
        start += row[0]                              # VHGT: a row's first delta is from the previous row's start
        h = start
        out.append(h * 8)
        for dh in row[1:]:
            h += dh
            out.append(h * 8)
    return out


def terrain_height(grid, x, y):
    d = (_land_index()[0].get(tuple(grid)) or (None,))[0]
    if not d or "VHGT" not in d:
        return 0.0
    h = _heights(d)
    i = min(64, max(0, int(round((x - grid[0] * 8192) / 128))))
    j = min(64, max(0, int(round((y - grid[1] * 8192) / 128))))
    return float(h[j * 65 + i])


def terrain(x, y):
    """Heights, vertex colours and the 16 x 16 texture grid of an exterior cell."""
    lands, ltexes = _land_index()
    d, fi = lands.get((x, y)) or (None, None)
    ltex = ltexes.get(fi, {})               # VTEX indices refer to the LTEX of the LAND's own file
    if not d or "VHGT" not in d:
        return {"grid": [x, y], "heights": None}
    colors = None
    if "VCLR" in d:
        colors = [round(c / 255.0, 3) for c in d["VCLR"][:65 * 65 * 3]]
    tex = [0] * 256
    if "VTEX" in d:
        raw = struct.unpack("<256H", d["VTEX"][:512])
        k = 0
        for y1 in range(4):
            for x1 in range(4):
                for y2 in range(4):
                    for x2 in range(4):
                        tex[(y1 * 4 + y2) * 16 + (x1 * 4 + x2)] = raw[k]
                        k += 1
    names = {0: "_land_default.tga"}
    for t in set(tex):
        if t:
            names[t] = ltex.get(t - 1, "_land_default.tga")
    return {"grid": [x, y], "heights": [round(h, 1) for h in _heights(d)], "colors": colors,
            "tex": tex, "textures": {str(k): v for k, v in names.items()}}


# --- Meshes and textures ---------------------------------------------------------

def mesh(path):
    """A mesh's shapes as JSON."""
    if path not in _mesh_cache:
        if os.path.isabs(path):
            if path not in _disk_meshes:
                raise KeyError(path)
            with open(path, "rb") as f:
                data = f.read()
        else:
            data = project.game.read("meshes\\" + path)
            if data is None:
                raise KeyError(path)
        out = []
        try:
            shapes = nif.shapes(data)
        except Exception as e:
            print("Couldn't read the mesh %s (%s: %s); it's shown as a box." % (path, type(e).__name__, e), flush=True)
            shapes = []
        for s in shapes:
            col = s["color"]
            out.append({
                "pos": [round(v, 3) for v in s["pos"]],
                "normal": None if s["normal"] is None else [round(v, 4) for v in s["normal"]],
                "uv": None if s["uv"] is None else [round(v, 5) for v in s["uv"]],
                "color": None if col is None else [round(col[k], 3) for k in range(len(col)) if k % 4 != 3],
                "index": list(s["index"]),
                "texture": s["texture"], "blend": s["blend"], "alphaTest": s["alpha_test"],
                "doubleSided": s["double_sided"], "diffuse": list(s["diffuse"]),
                "emissive": list(s["emissive"]), "alpha": s["alpha"], "count": len(s["pos"]) // 3,
            })
        _mesh_cache[path] = json.dumps(out).encode()
    return _mesh_cache[path]


def texture(name):
    """A texture's file, found like OpenMW: under textures\\ with a .dds of the name first, then the bare name."""
    key = name.lower()
    if key not in _tex_cache:
        path = key.replace("/", "\\").lstrip("\\")
        if not path.startswith("textures\\"):
            cut = path.find("\\textures\\")
            path = path[cut + 1:] if cut >= 0 else "textures\\" + path
        stem, ext = os.path.splitext(path)
        base = "textures\\" + os.path.basename(stem.replace("\\", "/"))
        data = None
        for p in (stem + ".dds", stem + (ext or ".tga"), base + ".dds", base + (ext or ".tga"), base + ".tga", base + ".bmp"):
            data = project.game.read(p)
            if data is not None:
                break
        if data is None:
            return None
        _tex_cache[key] = data
    return _tex_cache[key]


# --- Saving -------------------------------------------------------------------------

def clean_edits(edits):
    """Edits as they're stored: rounded, sorted, added-then-deleted objects dropped."""
    deleted = set(edits.get("deleted", []))
    gone = {"added|" + a["uid"] for a in edits.get("added", []) if "added|" + a["uid"] in deleted}
    return {"moved": {k: dict({"pos": [round(v, 2) for v in m["pos"]], "rot": [round(v, 5) for v in m["rot"]]},
                              **({"scale": round(min(2.0, max(0.5, m["scale"])), 3)}
                                 if m.get("scale") is not None else {}))
                      for k, m in sorted(edits.get("moved", {}).items()) if k not in gone},
            "deleted": sorted(deleted - gone),
            "replaced": {k: v for k, v in sorted(edits.get("replaced", {}).items()) if k not in gone},
            "added": [{"uid": a["uid"], "cell": a["cell"], "id": a["id"],
                       "pos": [round(v, 2) for v in a["pos"]], "rot": [round(v, 5) for v in a["rot"]],
                       "scale": a.get("scale"), "tier": a.get("tier")}
                      for a in edits.get("added", []) if "added|" + a["uid"] not in gone],
            "attached": {k: v for k, v in sorted(edits.get("attached", {}).items())
                         if k not in gone and v not in gone},
            "doors": {k: {"cell": d["cell"], "pos": [round(v, 2) for v in d["pos"]],
                          "rot": [round(v, 5) for v in d["rot"]]}
                      for k, d in sorted(edits.get("doors", {}).items()) if k not in gone},
            "groups": {g: sorted(keys) for g, keys in sorted(
                (g, [k for k in ks if k not in gone]) for g, ks in edits.get("groups", {}).items()) if len(keys) > 1},
            "npcs": {k: v for k, v in sorted((edits.get("npcs") or {}).items()) if v},
            "dialogue": {k: v for k, v in sorted((edits.get("dialogue") or {}).items()) if v}}


def _base_ids(edits):
    """Make added objects in an upgrade tier name the object they copy; new NPCs have no tier to copy them for."""
    clones = {k.lower(): v for k, v in project.clones().items()}
    new = {k.lower() for k, v in (edits.get("npcs") or {}).items() if v and v.get("new")}
    for a in edits.get("added") or []:
        if a.get("tier") and a["id"].lower() in new:
            a["tier"] = None
        elif a.get("tier") and a["id"].lower() in clones:
            a["id"] = clones[a["id"].lower()]
    return edits


def save(edits, label=""):
    clean = clean_edits(_base_ids(edits))
    path = project.file("edits")
    with LOCK:
        if (clean["npcs"] or clean["dialogue"]) and project.can_edit_npcs:
            project.edits_override = clean
            try:
                project.records_and_needs()
            finally:
                project.edits_override = None
        if not history.versions() and os.path.exists(path):
            with open(path) as f:
                history.snapshot(json.load(f), "before-history")
        with open(path, "w") as f:
            json.dump(clean, f, indent=1)
        history.snapshot(clean, label)
        message = project.build()
    LIVE.was_saved(clean)
    return {"ok": True, "message": message, "moved": len(clean["moved"]),
            "deleted": len(clean["deleted"]), "added": len(clean["added"]), "replaced": len(clean["replaced"]),
            "doors": len(clean["doors"]), "npcs": len(clean["npcs"]), "responses": len(clean["dialogue"]),
            "edits": clean,
            "newMasters": [{"file": n, "why": w} for n, w in project.new_masters]}


def revert(name, key=None):
    """Restore the layout from a saved version: all of it, or one object."""
    target = history.load(name) if name else writer.empty_edits()
    if key is None:
        return save(target, label="restored")
    cur = project.load_edits()
    if key.startswith("npcs|"):
        oid = key[len("npcs|"):]
        placed = sorted({a["cell"] for a in cur["added"] if a["id"].lower() == oid})
        if (cur["npcs"].get(oid) or {}).get("new") and oid not in target.get("npcs", {}) and placed:
            raise ValueError("%s is placed in %s: delete it there first, so no cell is left with an NPC that "
                             "isn't there." % (cur["npcs"][oid].get("id", oid), ", ".join(placed)))
        cur["npcs"].pop(oid, None)
        if oid in target.get("npcs", {}):
            cur["npcs"][oid] = target["npcs"][oid]
        return save(cur, label="reverted")
    if key.startswith("dialogue|"):
        k = key[len("dialogue|"):]
        cur["dialogue"].pop(k, None)
        if k in target.get("dialogue", {}):
            cur["dialogue"][k] = target["dialogue"][k]
        return save(cur, label="reverted")
    st = states(target).get(key) or {}
    cur["moved"].pop(key, None)
    if "moved" in st:
        cur["moved"][key] = st["moved"]
    cur["deleted"] = [k for k in cur["deleted"] if k != key] + ([key] if st.get("deleted") else [])
    cur["replaced"].pop(key, None)
    if "replaced" in st:
        cur["replaced"][key] = st["replaced"]
    cur.setdefault("attached", {}).pop(key, None)
    if "attached" in st:
        cur["attached"][key] = st["attached"]
    cur.setdefault("doors", {}).pop(key, None)
    if "door" in st:
        cur["doors"][key] = st["door"]
    groups = cur.setdefault("groups", {})
    for g in list(groups):
        groups[g] = [k for k in groups[g] if k != key]
    if "group" in st:
        groups.setdefault(st["group"], []).append(key)
    cur["groups"] = {g: ks for g, ks in groups.items() if len(ks) > 1}
    if key.startswith("added|"):
        uid = key[len("added|"):]
        cur["added"] = [a for a in cur["added"] if a["uid"] != uid] + ([st["added"]] if "added" in st else [])
    return save(cur, label="reverted")


RECENT = 20


def save_favorites(body):
    fav = favorites()
    if "favorites" in body:
        fav["cells"] = body["favorites"]
    if "objects" in body:
        fav["objects"] = body["objects"]
    if "recent" in body:
        fav["recent"] = body["recent"][:RECENT]
    with open(project.file("favorites"), "w") as f:
        json.dump(fav, f, indent=1)


# --- HTTP ---------------------------------------------------------------------------

_warned_blocked = False
ACCESS_CODE = None
LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
TRIES, LOCKOUT = 10, 900
_wrong_codes = {}
CODE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Cell Editor</title>
<style>body{font:16px system-ui,sans-serif;background:#101014;color:#ddd;display:flex;justify-content:center;
padding-top:18vh}form{background:#18181f;border:1px solid #333;border-radius:10px;padding:20px;max-width:320px}
input{font-size:22px;letter-spacing:.2em;width:9em;text-transform:uppercase;padding:6px;margin:10px 0}
button{font-size:16px;padding:8px 16px}p{color:#999;font-size:14px}.bad{color:#e88}</style></head><body>
<form method="get" action="/"><b>Morrowind Cell Editor</b><p>Enter the code the editor shows on the computer
it runs on.</p>%s<input name="code" autocomplete="off" autofocus><br><button>Open</button></form></body></html>"""
FIREWALL_APP = (os.path.abspath(os.path.join(sys.executable, "..", "..", ".."))
                if getattr(sys, "frozen", False) and sys.platform == "darwin"
                else os.path.join(sys.base_prefix, "Resources", "Python.app"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def handle(self):
        try:
            super().handle()
        except OSError as e:
            # ENOTCONN on macOS: the application firewall blocked this Python; warn once
            global _warned_blocked
            if e.errno != 57:
                raise
            if not _warned_blocked:
                _warned_blocked = True
                print("A connection from %s was cut off by macOS before it arrived. Most likely the "
                      "firewall: allow %s in System Settings > Network > Firewall > Options (see "
                      "README.md)." % (self.client_address[0], FIREWALL_APP), flush=True)

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        # "/" is the start page or the editor, so it is never cached
        if self.command == "GET" and not getattr(self, "_replying", False):
            page = urlparse(self.path).path
            self.send_header("Cache-Control", "no-store" if page == "/" or page.endswith(".html") else "no-cache")
        super().end_headers()

    def reply(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        page = ctype == "application/json" or ctype.startswith("text/html")
        self.send_header("Cache-Control", "no-store" if page else "max-age=3600")
        self._replying = True
        self.end_headers()
        self._replying = False
        self.wfile.write(body)

    def here(self):
        """Whether the request comes from this computer."""
        return this_computer(self.client_address[0])

    def stream(self, page):
        """The page's live events as server-sent events."""
        import queue
        q, hello = LIVE.join(page, self.here())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self._replying = True
        self.end_headers()
        self._replying = False

        def send(event):
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()
        try:
            send(hello)
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
                    continue
                if event is None:
                    break
                send(event)
        except OSError:
            pass
        finally:
            LIVE.leave(page, q)

    def allowed(self):
        """Whether the request may be served: this computer, or a device with the access code."""
        if not LAN or self.here():
            return True
        from http.cookies import SimpleCookie
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return "ce_code" in c and self.try_code(c["ce_code"].value)

    def locked_out(self):
        import time
        t = _wrong_codes.get(self.client_address[0])
        if t and time.time() - t[1] > LOCKOUT:
            _wrong_codes.pop(self.client_address[0], None)
            return False
        return bool(t) and t[0] >= TRIES

    def try_code(self, code):
        """Check an access code, locking a device out after TRIES wrong ones."""
        import time
        if self.locked_out():
            return False
        if hmac.compare_digest(code.strip().upper().encode(), ACCESS_CODE.encode()):
            _wrong_codes.pop(self.client_address[0], None)
            return True
        t = _wrong_codes.setdefault(self.client_address[0], [0, time.time()])
        t[0] += 1
        return False

    def refuse(self, path, q):
        """Handle a device without the access code."""
        code = (q.get("code") or "").strip().upper()
        if code and self.try_code(code):
            self.send_response(302)
            self.send_header("Set-Cookie", "ce_code=%s; Path=/; Max-Age=%d; SameSite=Lax" % (code, 180 * 86400))
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.startswith("/api/"):
            return self.reply(b'{"error": "access code needed"}', code=403)
        note = ("Too many wrong codes. Try again in %d minutes." % (LOCKOUT // 60) if self.locked_out()
                else "That code isn't right." if code else "")
        return self.reply((CODE_PAGE % ('<p class="bad">%s</p>' % note if note else "")).encode(),
                          "text/html; charset=utf-8", 403 if note else 200)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/favicon.ico", "/apple-touch-icon-precomposed.png"):
            with open(os.path.join(WEB, "favicon.png" if u.path == "/favicon.ico" else "apple-touch-icon.png"), "rb") as f:
                return self.reply(f.read(), "image/png")
        if not self.allowed():
            return self.refuse(u.path, q)
        if u.path == "/api/ping":
            return self.reply(json.dumps({"app": "OpenMW Cell Editor", "project": project and project.name}).encode())
        if u.path == "/api/phone":
            return self.reply(json.dumps(phone_info(self.here())).encode())
        if u.path == "/api/thumb":
            import re
            name, data = q.get("id", ""), b""
            if re.fullmatch(r"[0-9a-f]{16}", name):
                try:
                    with open(os.path.join(os.path.dirname(_thumb_file("x", "")), name + ".jpg"), "rb") as f:
                        data = f.read()
                except OSError:
                    pass
            return self.reply(data, "image/jpeg") if data else self.reply(b"{}", code=404)
        if u.path == "/api/home":
            if not self.here():
                return self.reply(json.dumps({"remote": True, "project": project and project.name}).encode())
            try:
                return self.reply(json.dumps(home_info()).encode())
            except Exception:
                traceback.print_exc()
                return self.reply(json.dumps({"error": traceback.format_exc()}).encode(), code=500)
        if project is None and u.path in ("/", "/index.html"):
            self.path = "/home.html"
        elif project is None and u.path.startswith("/api/"):
            return self.reply(b'{"error": "no project open"}', code=409)
        try:
            if u.path == "/api/live":
                return self.stream(q.get("page") or "")
            if u.path == "/api/scene":
                return self.reply(json.dumps(dict(scene(), here=self.here())).encode())
            if u.path == "/api/cell":
                return self.reply(json.dumps(cell_data(q["name"])).encode())
            if u.path == "/api/terrain":
                return self.reply(json.dumps(terrain(int(q["x"]), int(q["y"]))).encode())
            if u.path == "/api/history":
                return self.reply(json.dumps(history.summary()).encode())
            if u.path == "/api/history/version":
                return self.reply(json.dumps(history.version_diff(q["name"])).encode())
            if u.path == "/api/history/object":
                return self.reply(json.dumps(history.object_history(q["key"])).encode())
            if u.path == "/api/catalog":
                model_index()
                return self.reply(_catalog)
            if u.path == "/api/npcs":
                return self.reply(json.dumps(npc_list()).encode())
            if u.path == "/api/npc":
                try:
                    return self.reply(json.dumps(npc_one(q["id"])).encode())
                except KeyError:
                    return self.reply(b'{"error": "no such NPC"}', code=404)
            if u.path == "/api/npc/lists":
                return self.reply(json.dumps(project.npcs().lists()).encode())
            if u.path == "/api/npc/id":
                return self.reply(json.dumps(npc_id(q["id"])).encode())
            if u.path == "/api/dialogue/topics":
                return self.reply(json.dumps(project.dialogue().names()).encode())
            if u.path == "/api/mesh":
                try:
                    return self.reply(mesh(q["path"]))
                except KeyError:
                    return self.reply(b"[]", code=404)
            if u.path == "/api/tex":
                data = texture(q["name"])
                return self.reply(data, "application/octet-stream") if data else self.reply(b"{}", code=404)
        except Exception:
            traceback.print_exc()
            return self.reply(json.dumps({"error": traceback.format_exc()}).encode(), code=500)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        if not self.allowed():
            return self.reply(b'{"ok": false, "message": "access code needed"}', code=403)
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if u.path == "/api/save":
                try:
                    return self.reply(json.dumps(save(LIVE.edits() if body.get("live") else body)).encode())
                except ValueError as e:
                    return self.reply(json.dumps({"ok": False, "message": str(e)}).encode(), code=400)
                except PermissionError as e:
                    return self.reply(json.dumps({"ok": False, "message": permission_message(e)}).encode(), code=403)
            if u.path == "/api/revert":
                try:
                    return self.reply(json.dumps(revert(body["name"], body.get("key"))).encode())
                except ValueError as e:
                    return self.reply(json.dumps({"ok": False, "message": str(e)}).encode(), code=400)
            if u.path == "/api/favorites":
                save_favorites(body)
                return self.reply(b'{"ok": true}')
            if u.path == "/api/alive":
                stops = alive(body.get("id"), body.get("closing"), self.here())
                return self.reply(json.dumps({"ok": True, "stopsIn": stops}).encode())
            if u.path == "/api/phone":
                if not self.here():
                    return self.reply(b'{"ok": false, "message": "only on the computer the editor runs on"}',
                                      code=403)
                done = new_code() if body.get("newCode") else set_phone(body.get("on"))
                return self.reply(json.dumps(dict({"ok": True}, **done)).encode())
            if u.path == "/api/cell":
                return self.reply(json.dumps(cell_data(body["name"], body.get("edits"))).encode())
            if u.path == "/api/npc/dialogue":
                return self.reply(json.dumps(npc_dialogue(body["id"], body.get("edits") or {})).encode())
            if u.path == "/api/live/ops":
                if not LIVE.apply(body.get("page"), body.get("path"), body.get("ops") or []):
                    return self.reply(b'{"ok": false, "message": "another project is open"}', code=409)
                return self.reply(b'{"ok": true}')
            if u.path == "/api/live/where":
                LIVE.where(body.get("page"), body)
                return self.reply(b'{"ok": true}')
            if u.path == "/api/thumb":
                return self.reply(json.dumps(dict({"ok": True}, **save_thumb(body.get("data"), body.get("cell"),
                                                                             body.get("saved")))).encode())
            if u.path == "/api/live/bye":
                LIVE.leave(body.get("page"))
                return self.reply(b'{"ok": true}')
            if u.path == "/api/live/draft":
                LIVE.drop_draft()
                return self.reply(b'{"ok": true}')
            home = {"/api/home/open": lambda: open_project(body["path"]),
                    "/api/home/create": lambda: create_project(body),
                    "/api/home/project": lambda: project_page(body["path"]),
                    "/api/home/save-project": lambda: save_project(body["path"], body["dataFiles"], body["loadOrder"],
                                                                   body.get("folders") or [], body.get("baseOrder"),
                                                                   body.get("standalone")),
                    "/api/home/defaults": lambda: launcher.defaults(SETTINGS),
                    "/api/home/folder": lambda: launcher.folder_info(body["path"]),
                    "/api/home/resolve": lambda: launcher.resolve(_clean_path(body["path"]), body.get("have") or [],
                                                                  body["dataFiles"], body.get("folders") or []),
                    "/api/home/forget": lambda: forget_project(body["path"]),
                    "/api/home/delete": lambda: delete_project(body["path"]),
                    "/api/home/data": lambda: launcher.data_files_info(body["folder"]),
                    "/api/home/plugin": lambda: launcher.plugin_info(_clean_path(body["path"])),
                    "/api/home/openmw": lambda: launcher.openmw_load_order() or {"cfg": None, "plugins": []},
                    "/api/home/browse": lambda: launcher.browse(body.get("path"), body.get("want")),
                    "/api/home/privacy": open_privacy_settings,
                    "/api/home/restart": restart}
            if (u.path in home or u.path == "/api/quit") and not self.here():
                return self.reply(b'{"ok": false, "message": "Only on the host computer."}', code=403)
            if u.path in home:
                try:
                    return self.reply(json.dumps(dict({"ok": True}, **home[u.path]())).encode())
                except ValueError as e:
                    return self.reply(json.dumps({"ok": False, "message": str(e)}).encode(), code=400)
                except PermissionError as e:
                    return self.reply(json.dumps({"ok": False, "message": permission_message(e)}).encode(), code=403)
            if u.path in ("/api/launcher/editor", "/api/launcher/show"):
                if not (self.here() and GUI):
                    return self.reply(b'{"ok": false}')
                if u.path == "/api/launcher/editor":
                    done = open_editor(body.get("switched"))
                else:
                    done = {"shown": desktop.show(body.get("screen") or "projects", body.get("path"))}
                return self.reply(json.dumps(dict({"ok": True}, **done)).encode())
            if u.path == "/api/quit":
                self.reply(b'{"ok": true}')
                threading.Thread(target=SERVER.shutdown, daemon=True).start()
                return
            return self.reply(b"{}", code=404)
        except Exception:
            traceback.print_exc()
            return self.reply(json.dumps({"ok": False, "message": traceback.format_exc()}).encode(), code=500)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind looks up the host's DNS name, which can hang on macOS
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


_address = [None, 0.0]


def lan_address():
    """This machine's address on the local network."""
    import socket
    import time
    if time.time() - _address[1] < 30:
        return _address[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        found = s.getsockname()[0]
    except OSError:
        found = None
    finally:
        s.close()
    _address[:] = [found, time.time()]
    return found


def this_computer(address):
    return address in LOCAL or address == lan_address()


# --- Phones and tablets ----------------------------------------------------------------

LAN = False
PORT = None
_rebind = []


def phone_info(here):
    """What the Open on another device window shows."""
    if not here:
        return {"here": False}
    ip = lan_address()
    address = "http://%s:%d" % (ip, PORT) if ip else None
    url = address and "%s/?code=%s" % (address, ACCESS_CODE)
    return {"here": True, "on": LAN, "address": address, "code": ACCESS_CODE, "url": url,
            "qr": qr.svg(url) if url and LAN else None, "system": sys.platform,
            "blocked": _warned_blocked and FIREWALL_APP, "grace": PHONE_GRACE // 60}


def set_phone(on):
    """Turn phone access on or off and listen again on the same port."""
    on = bool(on)
    if SETTINGS:
        SETTINGS.set("phone_access", on)
    if on != LAN:
        _rebind[:] = [on]
        t = threading.Timer(0.2, SERVER.shutdown)
        t.daemon = True
        t.start()
    return {}


def new_code():
    """Make a new access code; devices using the old one must enter it again."""
    from .settings import new_code as make
    global ACCESS_CODE
    ACCESS_CODE = SETTINGS.lan_code(new=True) if SETTINGS else make(exclude=ACCESS_CODE)
    _wrong_codes.clear()
    LIVE.end_remote()
    return {}


def _listen(lan, port):
    return Server(("0.0.0.0" if lan else "127.0.0.1", port), Handler)


# --- Stopping when the last tab closes ---------------------------------------------
# Pages report every 30 s; browsers throttle timers in hidden tabs to once a minute

CLOSE_GRACE = 20
PHONE_GRACE = 180
FIRST = 90
STALE = 600
_pages = {}
_last_here = [0.0]
_started = [0.0]


def _grace():
    return PHONE_GRACE if any(not here for _, here in _pages.values()) else CLOSE_GRACE


def _stops_in(now):
    """Seconds until the editor stops by itself, or None while a page here keeps it running."""
    if not AUTO_STOP or any(here for _, here in _pages.values()):
        return None
    if _last_here[0]:
        return max(0, int(_last_here[0] + _grace() - now))
    return max(0, int(_started[0] + max(FIRST, _grace()) - now))


def alive(page, closing=False, here=True):
    """Note that a page is there or closing."""
    import time
    now = time.time()
    if here:
        _last_here[0] = now
    if page:
        if closing:
            _pages.pop(page, None)
        else:
            _pages[page] = [now, here]
    return None if here else _stops_in(now)


def _watch():
    """Stop the server once no page has been open on this computer for a while."""
    import time
    _started[0] = last = time.time()
    while True:
        time.sleep(5)
        now = time.time()
        if now - last > 30:
            # The computer slept and the clock jumped: give pages time to report again
            for seen in _pages.values():
                seen[0] = now
            _last_here[0] = now if _last_here[0] else 0.0
            _started[0] = now
        last = now
        for page, (seen, _) in list(_pages.items()):
            if now - seen > STALE:
                _pages.pop(page, None)
        if _stops_in(now) == 0:
            print("No editor page is open on this computer any more: stopping.", flush=True)
            _rebind.clear()
            SERVER.shutdown()
            return


def open_editor(switched=False):
    """Open the editor in the browser after the launcher opened a project."""
    import webbrowser
    with LIVE.lock:
        here = set(LIVE.pages) - LIVE.remote
    if switched and here:
        return {"opened": False}
    webbrowser.open("http://localhost:%d" % PORT)
    return {"opened": True}


def _show_running(port):
    """Bring the launcher of the editor running on port to the front."""
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/launcher/show" % port, data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.load(r).get("shown"))
    except (OSError, ValueError):
        return False


def already_running(port):
    """Whether the editor already serves this port."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=2) as r:
            return json.load(r).get("app") == "OpenMW Cell Editor"
    except (OSError, ValueError):
        return False


def run(p=None, port=8765, lan=False, browser=True, code=None, game=None, settings=None, auto_stop=False,
        gui=False):
    """Serve the editor for project p, or the start page when p is None."""
    import webbrowser
    global ACCESS_CODE, AUTO_STOP, GAME, GUI, SETTINGS, SERVER, LAN, PORT
    AUTO_STOP = auto_stop
    GAME, SETTINGS = game, settings
    if p:
        setup(p)
    import secrets
    ACCESS_CODE = (code or secrets.token_hex(4)).upper()
    server = None
    for p_ in range(port, port + 10):
        try:
            server = _listen(lan, p_)
            port = p_
            break
        except OSError:
            if already_running(p_):
                print("The editor is already running on http://localhost:%d; opening it." % p_, flush=True)
                if browser and not _show_running(p_):
                    webbrowser.open("http://localhost:%d" % p_)
                return
    if server is None:
        raise OSError("ports %d-%d are all in use" % (port, port + 9))
    url = "http://localhost:%d" % port
    SERVER, LAN, PORT = server, lan, port
    print("Morrowind Cell Editor%s on %s  (Ctrl+C to stop)" % (": " + p.name if p else "", url), flush=True)
    if lan:
        address = "http://%s:%d" % (lan_address() or "<this computer's IP>", port)
        print("Other devices on your network: %s/?code=%s  (or open %s and enter the code %s)"
              % (address, ACCESS_CODE, address, ACCESS_CODE), flush=True)
    if gui and desktop.available():
        GUI, AUTO_STOP = True, False
        print("It runs until you close its window.", flush=True)
        serving = threading.Thread(target=_serve, args=(port,), name="server")
        serving.start()
        if browser and p:
            threading.Timer(1.0, webbrowser.open, [url]).start()
        from .settings import config_dir
        try:
            desktop.run(url + "/home.html?launcher", serving,
                        os.path.dirname(SETTINGS.path) if SETTINGS else config_dir())
        except Exception as e:
            print("The launcher window couldn't open (%s): the start page opens in the browser." % e, flush=True)
            GUI, AUTO_STOP = False, True
            if not (browser and p):
                webbrowser.open(url)
            threading.Thread(target=_watch, daemon=True).start()
            serving.join()
        finally:
            _rebind.clear()
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
            serving.join(10)
            LIVE.close()
        return
    if browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    if auto_stop:
        print("It stops by itself when you close its last tab.", flush=True)
        threading.Thread(target=_watch, daemon=True).start()
    try:
        _serve(port)
    finally:
        LIVE.close()


def _serve(port):
    global SERVER, LAN
    while True:
        try:
            SERVER.serve_forever()
        except KeyboardInterrupt:
            print("Stopped.")
            return
        if not _rebind:
            return
        lan = _rebind.pop()
        SERVER.server_close()
        try:
            SERVER = _listen(lan, port)
        except OSError as e:
            print("Couldn't switch phone access (%s): it stays as it was." % e, flush=True)
            lan = not lan
            SERVER = _listen(lan, port)
        LAN = lan
        if lan:
            print("Other devices on your network: %s/?code=%s"
                  % ("http://%s:%d" % (lan_address() or "<this computer's IP>", port), ACCESS_CODE), flush=True)
        else:
            LIVE.end_remote()
            print("Only this computer can connect now.", flush=True)

