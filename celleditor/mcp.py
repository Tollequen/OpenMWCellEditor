"""An MCP server (Model Context Protocol, over HTTP at /mcp) for AI assistants working next to the user.

The assistant runs in the user's own AI app (e.g. Claude Code) and calls these tools. Its edits go into the
live session like another device's: the user sees them appear unsaved, and each tool call is one step their
Undo takes back. Only requests from this computer are served, and only when the settings file has
"assistant_mcp": true (not a released feature: no UI, not in the README)."""
import json
import math
import os
import random
import re
import string
import time

from . import geometry, writer
from .live import LIVE

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PAGE = "mcp"
TIER = re.compile(r"^([a-z]+)(\d)(o?)$")
client = {"name": "Assistant"}

INSTRUCTIONS = """Tools for the OpenMW Cell Editor that the user has open: look at a Morrowind cell, take
pictures from the user's editor and place, move or delete objects.
Coordinates are game units: +x east, +y north, +z up (a Hlaalu wall tile is 256 wide, a door about 200
tall). Rotations are degrees, clockwise seen from above; z is the heading (0 = facing north).
Edits appear in the user's editor right away, unsaved. Each call is one step the user can undo, and the
note you give is shown to them. Don't save unless the user asks. Objects are named by key (from
list_objects or editor_context); place_objects takes object ids (search with find_object_ids).
Projects with upgrade tiers (nooks) hide objects by tier: an object's "tier" is e.g. "ic1" (shown from tier
1 of nook ic up) or "ic0o" (only at tier 0)."""


# --- Helpers ---------------------------------------------------------------------------------

class ToolError(Exception):
    pass


def _srv():
    from . import server
    if server.project is None:
        raise ToolError("No project is open in the editor (it shows its start page).")
    return server


def _r(v, n=1):
    return [round(float(x), n) for x in v]


def _deg(rot):
    return [round(math.degrees(a) % 360.0, 1) if i == 2 else round(math.degrees(a), 1) for i, a in enumerate(rot)]


def _rad_rot(v, default=(0.0, 0.0, 0.0)):
    """Degrees (a number for the heading, or [x, y, z]) -> radians [x, y, z]."""
    if v is None:
        return list(default)
    if isinstance(v, (int, float)):
        return [default[0], default[1], math.radians(v)]
    if len(v) != 3:
        raise ToolError("rot is degrees: a number (the heading) or [x, y, z]")
    return [math.radians(a) for a in v]


def _vec(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ToolError("%s must be [x, y, z]" % name)
    return [float(a) for a in v]


def _tier_name(r):
    if not r.get("nook"):
        return None
    return "%s%d%s" % (r["nook"], r["tier"], "o" if r.get("only") else "")


def _shown(r, tiers):
    if not r.get("nook"):
        return True
    t = tiers.get(r["nook"], 0)
    return t == r["tier"] if r.get("only") else t >= r["tier"]


def _page():
    """(page id, presence) of the user's editor page on this computer, or (None, {})."""
    pages = LIVE.pages_here()
    return pages[0] if pages else (None, {})


def _cell_name(args):
    cell = args.get("cell") or _page()[1].get("cell")
    if not cell:
        raise ToolError("Give a cell: the editor isn't showing one.")
    return cell


class Cell:
    """A cell as the editor shows it now (with the unsaved edits)."""

    def __init__(self, name, tiers=None):
        S = _srv()
        self.S = S
        self.edits = LIVE.edits()
        try:
            self.data = S.cell_data(name, self.edits)
        except KeyError:
            raise ToolError("There's no cell named %r." % name)
        self.name = self.data["name"]
        deleted = set(self.edits.get("deleted") or [])
        self.refs = [r for r in self.data["refs"] if r["key"] not in deleted]
        top = {}
        for r in self.refs:
            if r.get("nook"):
                top[r["nook"]] = max(top.get(r["nook"], 0), r["tier"])
        shown = _page()[1]
        self.tiers = dict(top)
        if shown.get("cell") == self.name:
            self.tiers.update(shown.get("tiers") or {})
        self.tiers.update(tiers or {})
        self.by_key = {r["key"]: r for r in self.refs}

    def shape(self, r):
        if r.get("kind") != "mesh" or not r.get("mesh"):
            return geometry.Shape(None)
        return geometry.shape(r["mesh"], self.S.mesh_bytes)

    def solid(self, skip=()):
        return [(r, self.shape(r)) for r in self.refs
                if r["kind"] == "mesh" and _shown(r, self.tiers) and r["key"] not in skip]

    def describe(self, r):
        lo, hi = geometry.world_box(r, self.shape(r))
        out = {"key": r["key"], "id": r["id"], "pos": _r(r["pos"]), "rot": _deg(r["rot"]),
               "box": [_r(lo, 0), _r(hi, 0)]}
        if (r.get("scale") or 1.0) != 1.0:
            out["scale"] = round(r["scale"], 3)
        if r["src"].lower() != r["id"].lower():
            out["copy_of"] = r["src"]
        t = _tier_name(r)
        if t:
            out["tier"] = t
            if not _shown(r, self.tiers):
                out["hidden_at_these_tiers"] = True
        if r["origin"] != "mod":
            out["origin"] = r["origin"]
        if r.get("structure"):
            out["structure"] = True
        if not r.get("editable", True):
            out["read_only"] = True
        if r.get("door"):
            out["door_to"] = r["door"]["cell"]
        if r["kind"] != "mesh":
            out["kind"] = r["kind"]
        return out

    def hit(self, o, d, skip=(), max_dist=20000.0):
        h = geometry.raycast(self.solid(skip), o, d, max_dist)
        grid = self.data.get("grid")
        if grid:
            S = self.S
            t = geometry.terrain_hit(lambda x, y: S.terrain_height(writer.grid_of((x, y, 0)), x, y), o, d,
                                     h["t"] if h else max_dist)
            if t:
                h = t
        return h


def _send(ops, note):
    S = _srv()
    label = "%s: %s" % (client["name"], note) if note else "%s changed %d thing(s)" % (client["name"], len(ops))
    if not LIVE.apply(PAGE, S.project.path, ops, {"undo": True, "label": label}):
        raise ToolError("The editor has another project open.")


def _uid():
    t, n = int(time.time() * 1000), ""
    while t:
        t, d = divmod(t, 36)
        n = (string.digits + string.ascii_lowercase)[d] + n
    return n + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))


def _drop_z(cell, r, sh, skip):
    """z for an object so its bottom rests on the first surface below its position; None if none."""
    lo, hi = geometry.world_box(r, sh)
    h = cell.hit((r["pos"][0], r["pos"][1], r["pos"][2] + 1.0), (0.0, 0.0, -1.0), skip)
    if not h:
        return None
    return r["pos"][2] + h["point"][2] - lo[2]


def _tier_ok(cell, tier):
    if tier is None:
        return None
    m = TIER.match(str(tier))
    nooks = set(getattr(cell.S.project, "nooks", {}) or {}) | {r["nook"] for r in cell.refs if r.get("nook")}
    if not m or m.group(1) not in nooks:
        raise ToolError("tier %r: give e.g. %r (nooks: %s)" % (tier, (sorted(nooks) or ["x"])[0] + "1",
                                                           ", ".join(sorted(nooks)) or "none in this project"))
    return tier


# --- Tools ---------------------------------------------------------------------------------------

def t_context(args):
    S = _srv()
    pages = []
    for page, p in LIVE.pages_here():
        info = {"cell": p["cell"], "camera": {"pos": _r(p.get("pos") or [0, 0, 0], 0),
                                              "yaw": round(math.degrees(p.get("yaw") or 0) % 360, 1),
                                              "pitch": round(math.degrees(p.get("pitch") or 0), 1)}}
        if p.get("tiers"):
            info["tiers"] = p["tiers"]
        if p.get("sel"):
            try:
                cell = Cell(p["cell"])
                info["selected"] = [cell.describe(cell.by_key[k]) for k in p["sel"] if k in cell.by_key]
            except ToolError:
                info["selected"] = p["sel"]
        pages.append(info)
    nooks = getattr(S.project, "nooks", {}) or {}
    out = {"project": S.project.name, "plugin": os.path.basename(S.project.plugin), "unsaved_changes": LIVE.unsaved(),
           "editor_pages": pages or "No editor page is open on this computer."}
    if nooks:
        out["nooks"] = nooks
    return json.dumps(out)


def t_list(args):
    cell = Cell(_cell_name(args), args.get("tiers"))
    near = _vec(args["near"], "near") if args.get("near") else None
    radius = float(args.get("radius") or 0)
    match = (args.get("match") or "").lower()
    box = args.get("box")
    refs = cell.refs
    if match:
        refs = [r for r in refs if match in r["id"].lower() or match in r["src"].lower() or match in r["key"].lower()]
    if box:
        lo, hi = _vec(box[0], "box min"), _vec(box[1], "box max")
        refs = [r for r in refs if all(lo[i] <= r["pos"][i] <= hi[i] for i in range(3))]
    if not args.get("include_hidden"):
        refs = [r for r in refs if _shown(r, cell.tiers)]
    if near:
        dist = {r["key"]: math.sqrt(sum((a - b) ** 2 for a, b in zip(near, r["pos"]))) for r in refs}
        if radius:
            refs = [r for r in refs if dist[r["key"]] <= radius]
        refs.sort(key=lambda r: dist[r["key"]])
    limit = int(args.get("limit") or 60)
    out = {"cell": cell.name, "tiers": cell.tiers, "count": len(refs),
           "objects": [cell.describe(r) for r in refs[:limit]]}
    if len(refs) > limit:
        out["more"] = "%d more; narrow with near/radius, box or match" % (len(refs) - limit)
    return json.dumps(out)


def t_raycast(args):
    cell = Cell(_cell_name(args), args.get("tiers"))
    o = _vec(args["from"], "from")
    d = _vec(args.get("direction") or [0, 0, -1], "direction")
    h = cell.hit(o, d, set(args.get("ignore") or []), float(args.get("max_distance") or 20000))
    if not h:
        return json.dumps({"hit": None})
    out = {"hit": _r(h["point"]), "distance": round(h["t"], 1), "normal": _r(h["normal"], 3)}
    out["object"] = cell.describe(h["ref"]) if h["ref"] else "terrain"
    return json.dumps(out)


def t_find_ids(args):
    S = _srv()
    S.model_index()
    words = (args.get("query") or "").lower().split()
    if not words:
        raise ToolError("Give a query, e.g. 'candle' or 'altar imp'.")
    kind = (args.get("type") or "").lower()
    found = []
    for o in json.loads(S._catalog):
        text = (o["id"] + " " + (o.get("name") or "")).lower()
        if all(w in text for w in words) and (not kind or o["type"].lower() == kind):
            found.append({"id": o["id"], "type": o["type"], "name": o.get("name") or "", "mesh": o.get("mesh") or ""})
    limit = int(args.get("limit") or 40)
    return json.dumps({"count": len(found), "objects": found[:limit]})


def t_place(args):
    cell = Cell(_cell_name(args))
    S = cell.S
    if not cell.data.get("canAdd", True):
        raise ToolError("Objects can't be added to %s in this project." % cell.name)
    index = S.model_index()
    ops, placed, notes = [], [], []
    for i, o in enumerate(args.get("objects") or []):
        oid = o.get("id") or ""
        m = index.get(oid.lower())
        if not m:
            raise ToolError("objects[%d]: no object %r (find_object_ids searches)" % (i, oid))
        oid = next((c["id"] for c in json.loads(S._catalog) if c["id"].lower() == oid.lower()), oid)
        tier = _tier_ok(cell, o.get("tier"))
        uid = _uid()
        r = {"key": "added|" + uid, "id": oid, "src": oid, "kind": "mesh" if m[1] and m[0] != "NPC_" else "npc",
             "mesh": m[1], "pos": _vec(o.get("pos"), "objects[%d].pos" % i), "rot": _rad_rot(o.get("rot")),
             "scale": min(2.0, max(0.5, float(o.get("scale") or 1.0))), "origin": "added"}
        if tier:
            tm = TIER.match(tier)
            r.update(nook=tm.group(1), tier=int(tm.group(2)), only=bool(tm.group(3)))
        if o.get("drop"):
            z = _drop_z(cell, r, cell.shape(r), ())
            if z is None:
                notes.append("%s: nothing below it to drop onto; left at z %.1f" % (oid, r["pos"][2]))
            else:
                r["pos"][2] = z
        entry = {"uid": uid, "cell": cell.name, "id": oid, "pos": r["pos"], "rot": r["rot"],
                 "scale": r["scale"], "tier": tier}
        ops.append({"id": "added|" + uid, "v": entry})
        cell.refs.append(r)
        cell.by_key[r["key"]] = r
        placed.append(cell.describe(r))
    if not ops:
        raise ToolError("Give objects to place.")
    _send(ops, args.get("note") or "added %d object(s)" % len(ops))
    return json.dumps({"placed": placed, "notes": notes} if notes else {"placed": placed})


def _cell_of_key(key, edits):
    if key.startswith("added|"):
        a = next((a for a in edits.get("added") or [] if "added|" + a["uid"] == key), None)
        if not a:
            raise ToolError("No added object %r." % key)
        return a["cell"]
    return key.split("|", 1)[0]


def t_move(args):
    edits = LIVE.edits()
    cells, ops, moved, notes = {}, [], [], []
    for i, mv in enumerate(args.get("moves") or []):
        key = mv.get("key") or ""
        name = _cell_of_key(key, edits)
        cell = cells.get(name) or cells.setdefault(name, Cell(name))
        r = cell.by_key.get(key)
        if not r:
            raise ToolError("moves[%d]: no object %r in %s" % (i, key, name))
        if not r.get("editable", True):
            raise ToolError("moves[%d]: %s can't be edited in this project" % (i, key))
        r = dict(r)
        if mv.get("pos") is not None:
            r["pos"] = _vec(mv["pos"], "pos")
        if mv.get("offset") is not None:
            r["pos"] = [a + b for a, b in zip(r["pos"], _vec(mv["offset"], "offset"))]
        if mv.get("rot") is not None:
            r["rot"] = _rad_rot(mv["rot"], r["rot"])
        if mv.get("turn") is not None:
            r["rot"] = [r["rot"][0], r["rot"][1], (r["rot"][2] + math.radians(float(mv["turn"]))) % (2 * math.pi)]
        if mv.get("scale") is not None:
            r["scale"] = min(2.0, max(0.5, float(mv["scale"])))
        if mv.get("drop"):
            z = _drop_z(cell, r, cell.shape(r), {key})
            if z is None:
                notes.append("%s: nothing below it to drop onto" % key)
            else:
                r["pos"] = [r["pos"][0], r["pos"][1], z]
        v = {"pos": [float(a) for a in r["pos"]], "rot": [float(a) for a in r["rot"]]}
        if (r.get("scale") or 1.0) != (r.get("orig") or {}).get("scale", 1.0):
            v["scale"] = r["scale"]
        ops.append({"id": "moved|" + key, "v": v})
        cell.by_key[key].update(pos=v["pos"], rot=v["rot"], scale=r["scale"])
        moved.append(cell.describe(cell.by_key[key]))
    if not ops:
        raise ToolError("Give moves.")
    _send(ops, args.get("note") or "moved %d object(s)" % len(ops))
    return json.dumps({"moved": moved, "notes": notes} if notes else {"moved": moved})


def t_delete(args):
    edits = LIVE.edits()
    ops = []
    for key in args.get("keys") or []:
        name = _cell_of_key(key, edits)
        cell = Cell(name)
        r = cell.by_key.get(key)
        if not r:
            raise ToolError("No object %r in %s." % (key, name))
        if not r.get("editable", True):
            raise ToolError("%s can't be edited in this project." % key)
        if key.startswith("added|"):
            ops.append({"id": key, "v": None})
            for sec in ("moved", "attached"):
                if key in (edits.get(sec) or {}):
                    ops.append({"id": sec + "|" + key, "v": None})
        else:
            ops.append({"id": "deleted|" + key, "v": True})
    if not ops:
        raise ToolError("Give keys.")
    _send(ops, args.get("note") or "deleted %d object(s)" % len(args["keys"]))
    return json.dumps({"deleted": args["keys"]})


def t_set_tier(args):
    key = args.get("key") or ""
    edits = LIVE.edits()
    a = next((a for a in edits.get("added") or [] if "added|" + a["uid"] == key), None)
    if not a:
        raise ToolError("Only added objects (keys 'added|...') can change tier.")
    cell = Cell(a["cell"])
    a = dict(a, tier=_tier_ok(cell, args.get("tier")))
    _send([{"id": key, "v": a}], args.get("note") or "%s now in tier %s" % (a["id"], a["tier"] or "always"))
    return json.dumps({"key": key, "tier": a["tier"]})


def t_view(args):
    page, p = _page()
    if not page:
        raise ToolError("No editor page is open on this computer to take the picture.")
    ask = {"what": "view", "width": int(min(1600, max(320, args.get("width") or 1024)))}
    if args.get("cell") and args["cell"] != p.get("cell"):
        raise ToolError("The editor shows %s, not %s; ask the user to open it (pictures come from their editor)."
                        % (p.get("cell"), args["cell"]))
    pos = _vec(args["pos"], "pos") if args.get("pos") else None
    if pos:
        ask["pos"] = pos
    if args.get("look_at"):
        t = _vec(args["look_at"], "look_at")
        src = pos or p.get("pos") or [0, 0, 0]
        dx, dy, dz = (t[i] - src[i] for i in range(3))
        ask["yaw"] = math.atan2(dx, dy)
        ask["pitch"] = math.atan2(dz, math.hypot(dx, dy))
    else:
        if args.get("yaw") is not None:
            ask["yaw"] = math.radians(float(args["yaw"]))
        if args.get("pitch") is not None:
            ask["pitch"] = math.radians(float(args["pitch"]))
    if args.get("tiers"):
        ask["tiers"] = args["tiers"]
    ans = LIVE.ask(page, ask)
    if ans is None:
        raise ToolError("The editor page didn't answer (is it open and not frozen?).")
    if ans.get("error"):
        raise ToolError(ans["error"])
    data = ans.get("image") or ""
    mime, _, b64 = data.partition(";base64,")
    cam = ans.get("camera") or {}
    text = "%s, camera %s, heading %s, pitch %s" % (p.get("cell"), cam.get("pos"), cam.get("yaw"), cam.get("pitch"))
    return [{"type": "image", "data": b64, "mimeType": mime[5:] or "image/jpeg"}, {"type": "text", "text": text}]


def t_save(args):
    S = _srv()
    out = S.save(LIVE.edits(), args.get("label") or "")
    return json.dumps({"message": out.get("message"), "moved": out["moved"], "added": out["added"],
                       "deleted": out["deleted"]})


V3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
ROT = {"description": "degrees: a number (the heading, clockwise from north) or [x, y, z]",
       "anyOf": [{"type": "number"}, V3]}
TIERS = {"type": "object", "additionalProperties": {"type": "integer"},
         "description": "tier per nook to assume, e.g. {\"hal\": 1}; default: what the user's editor shows"}
NOTE = {"type": "string", "description": "a few words shown to the user, e.g. 'candles on the altar'"}
CELL = {"type": "string", "description": "cell name; default: the one the user's editor shows"}
READ = {"readOnlyHint": True, "openWorldHint": False}
EDIT = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

TOOLS = [
    ("editor_context", "Where the user is: the open project, each editor page's cell, camera, upgrade tiers "
     "and selected objects, and how many changes are unsaved.", {}, [], READ, t_context),
    ("list_objects", "Objects in a cell as the editor shows them (with unsaved edits): key, id, position, "
     "rotation (degrees), world box [min, max], tier. Nearest first with near.",
     {"cell": CELL, "near": dict(V3, description="sort by distance from this point"),
      "radius": {"type": "number", "description": "with near: only this close"},
      "box": {"type": "array", "items": V3, "minItems": 2, "maxItems": 2, "description": "[min, max] of positions"},
      "match": {"type": "string", "description": "part of the id or key"},
      "tiers": TIERS, "include_hidden": {"type": "boolean", "description": "also objects hidden at these tiers"},
      "limit": {"type": "integer", "description": "default 60"}}, [], READ, t_list),
    ("raycast", "The first surface a ray hits (object meshes, and terrain outside): point, distance, surface "
     "normal and the object. Straight down by default, e.g. to find a floor or table top.",
     {"cell": CELL, "from": V3, "direction": dict(V3, description="default [0, 0, -1]"),
      "ignore": {"type": "array", "items": {"type": "string"}, "description": "object keys to look through"},
      "max_distance": {"type": "number"}, "tiers": TIERS}, ["from"], READ, t_raycast),
    ("find_object_ids", "Search the placeable objects (ids, names) of the project's content files.",
     {"query": {"type": "string", "description": "words that must all appear in the id or name"},
      "type": {"type": "string", "description": "e.g. Static, Light, Misc, Container, Activator, Door"},
      "limit": {"type": "integer", "description": "default 40"}}, ["query"], READ, t_find_ids),
    ("view", "A picture from the user's editor, in the cell it shows. Without pos/yaw/pitch/look_at it's what "
     "the user sees; with them, a camera there (the user's own view doesn't move). Selected objects have "
     "yellow boxes.",
     {"pos": dict(V3, description="camera position"), "look_at": dict(V3, description="aim the camera here"),
      "yaw": {"type": "number", "description": "degrees clockwise from north"},
      "pitch": {"type": "number", "description": "degrees up (negative: down)"}, "tiers": TIERS,
      "width": {"type": "integer", "description": "pixels, default 1024"},
      "cell": {"type": "string", "description": "check that the editor shows this cell"}}, [], READ, t_view),
    ("place_objects", "Add objects (one undo step for the user). drop: lower each onto the first surface "
     "below its pos, so pos can be a little above a table (objects placed earlier in the call count).",
     {"cell": CELL, "objects": {"type": "array", "items": {"type": "object", "properties": {
         "id": {"type": "string"}, "pos": V3, "rot": ROT, "scale": {"type": "number"},
         "tier": {"type": "string", "description": "e.g. 'ic1'; default: always there"},
         "drop": {"type": "boolean"}}, "required": ["id", "pos"]}}, "note": NOTE},
     ["objects"], EDIT, t_place),
    ("move_objects", "Move, turn or scale objects by key (one undo step). pos/rot set; offset/turn add; "
     "drop lowers it onto the first surface below its (new) position. Attached objects don't follow.",
     {"moves": {"type": "array", "items": {"type": "object", "properties": {
         "key": {"type": "string"}, "pos": V3, "offset": V3, "rot": ROT,
         "turn": {"type": "number", "description": "degrees added to the heading"},
         "scale": {"type": "number"}, "drop": {"type": "boolean"}}, "required": ["key"]}}, "note": NOTE},
     ["moves"], EDIT, t_move),
    ("delete_objects", "Delete objects by key (one undo step).",
     {"keys": {"type": "array", "items": {"type": "string"}}, "note": NOTE}, ["keys"],
     dict(EDIT, destructiveHint=True), t_delete),
    ("set_tier", "Put an added object in an upgrade tier, or null for always there (one undo step).",
     {"key": {"type": "string"}, "tier": {"type": ["string", "null"]}, "note": NOTE}, ["key", "tier"],
     EDIT, t_set_tier),
    ("save", "Save the edits and build the plugin, as the user's Save button does. Only when the user asks.",
     {"label": {"type": "string", "description": "a name for the saved version"}}, [],
     dict(EDIT, destructiveHint=True), t_save),
]
BY_NAME = {t[0]: t for t in TOOLS}


def tool_list():
    return [{"name": n, "description": d, "annotations": a,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for n, d, props, req, a, _ in TOOLS]


def call(name, args):
    """MCP tools/call result."""
    t = BY_NAME.get(name)
    if not t:
        return {"content": [{"type": "text", "text": "No tool %r." % name}], "isError": True}
    try:
        out = t[5](args or {})
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except (KeyError, ValueError, TypeError) as e:
        return {"content": [{"type": "text", "text": "Bad arguments: %s: %s" % (type(e).__name__, e)}], "isError": True}
    content = out if isinstance(out, list) else [{"type": "text", "text": out}]
    return {"content": content, "isError": False}


def handle(msg):
    """One JSON-RPC message -> its response, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        info = params.get("clientInfo") or {}
        name = info.get("title") or info.get("name") or "Assistant"
        client["name"] = "Claude" if "claude" in name.lower() else name
        want = params.get("protocolVersion")
        result = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[1],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "openmw-cell-editor", "title": "OpenMW Cell Editor", "version": "0.1"},
                  "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        result = call(params.get("name"), params.get("arguments"))
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def handle_body(raw):
    """(status, response bytes or None) for a POST body."""
    try:
        msg = json.loads(raw)
    except ValueError:
        return 400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}).encode()
    if isinstance(msg, list):
        out = [r for r in (handle(m) for m in msg) if r is not None]
        return (200, json.dumps(out).encode()) if out else (202, None)
    r = handle(msg)
    return (200, json.dumps(r).encode()) if r is not None else (202, None)

