"""Plugin writing: references, layout edits and the plugin file."""
import json
import math
import os
import struct

from .esp import _split_refs, cell_refs, cstr, parse_exterior, record, sub, zstr

CELL_SIZE = 8192

EDIT_KINDS = ("moved", "deleted", "replaced", "added", "attached", "doors", "groups", "npcs", "dialogue")


def ref(obj_id, x, y, z, rot=0.0, dest=None, scale=None, lock=None, rot_x=0.0, owner=None, rot_y=0.0,
        lock_key=None):
    """A placed reference; rotations are clockwise, in radians."""
    return {"id": obj_id, "pos": [x, y, z], "rot": [rot_x, rot_y, rot],
            "dest": dest, "scale": scale, "lock": lock, "owner": owner, "lock_key": lock_key}


# --- Reference numbers -----------------------------------------------------------

class RefNums:
    """Reference numbers (FRMR) that stay the same between builds; removed numbers aren't reused."""

    def __init__(self, path=None):
        self.path, self.refs, self.next, self.changed = path, {}, 1, False
        if path and os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            self.refs, self.next = d["refs"], d["next"]

    def get(self, key):
        n = self.refs.get(key)
        if n is None:
            n = self.refs[key] = self.next
            self.next += 1
            self.changed = True
        return n

    def save(self):
        if self.path and self.changed:
            _write_text(self.path, json.dumps({"next": self.next, "refs": dict(sorted(self.refs.items()))}, indent=1))
            self.changed = False


def encode_refs(refs, refnums):
    """The subrecords of new references."""
    out = []
    for r in refs:
        subs = [sub("FRMR", struct.pack("<I", refnums.get(r["key"]))), sub("NAME", zstr(r["id"]))]
        if r["scale"] is not None:
            subs.append(sub("XSCL", struct.pack("<f", r["scale"])))
        if r.get("owner"):
            subs.append(sub("ANAM", zstr(r["owner"])))
        if r["dest"] is not None:
            cell, (dx, dy, dz), heading = r["dest"]
            subs.append(sub("DODT", struct.pack("<6f", dx, dy, dz, 0.0, 0.0, heading)))
            if cell:                          # no DNAM: a door to the exterior world
                subs.append(sub("DNAM", zstr(cell)))
        if r["lock"] is not None:
            subs.append(sub("FLTV", struct.pack("<i", r["lock"])))
        if r.get("lock_key"):
            subs.append(sub("KNAM", zstr(r["lock_key"])))
        subs.append(sub("DATA", struct.pack("<6f", *r["pos"], *r["rot"])))
        out.append(b"".join(subs))
    return out


# --- Layout edits ------------------------------------------------------------------

def empty_edits():
    return {"moved": {}, "deleted": [], "replaced": {}, "added": [], "attached": {}, "doors": {}, "groups": {},
            "npcs": {}, "dialogue": {}}


def dest_of(subs):
    """A door reference's destination (cell or "", (x, y, z), heading), or None."""
    d = dict(subs)
    if "DODT" not in d:
        return None
    x, y, z, _, _, heading = struct.unpack("<6f", d["DODT"])
    return (cstr(d["DNAM"]) if "DNAM" in d else "", (x, y, z), heading)


def load_edits(path):
    edits = empty_edits()
    if path and os.path.exists(path):
        with open(path) as f:
            edits.update(json.load(f))
    return edits


def ref_key(cell, r):
    """A generated reference's stable key: its cell, object and position."""
    return "%s|%s|%d,%d,%d" % (cell, r["id"], *[round(v) for v in r["pos"]])


def edited_cells(edits):
    """The cells the layout edits touch."""
    cells = {k.split("|")[0] for k in list(edits["moved"]) + edits["deleted"] + list(edits["replaced"])
             + list(edits.get("doors", {})) if "|vanilla|" in k}
    return cells | {a["cell"] for a in edits["added"]}


def vanilla_refs(master, cell):
    """A master file's references of a cell, as refs the edits can change."""
    out = []
    for num, subs in cell_refs(master, cell)[1]:
        d = dict(subs)
        x, y, z, rx, ry, rz = struct.unpack("<6f", d["DATA"])
        r = ref(cstr(d["NAME"]), x, y, z, rz, rot_x=rx, rot_y=ry,
                scale=struct.unpack("<f", d["XSCL"])[0] if "XSCL" in d else None, dest=dest_of(subs))
        r["vanilla"] = (num, subs)
        r["key"] = "%s|vanilla|%d" % (cell, num)
        out.append(r)
    return out


def apply_edits(cells, vanilla, edits, added_id=None, replaced_id=None):
    """Add objects, give every reference a key, and apply replacements, moves and deletions."""
    deleted = set(edits["deleted"])
    keys = set()
    for a in edits["added"]:
        if a["cell"] in cells:
            r = ref(added_id(a) if added_id else a["id"], *a["pos"], a["rot"][2],
                    rot_x=a["rot"][0], rot_y=a["rot"][1], scale=a.get("scale"))
            r["added"] = a["uid"]
            cells[a["cell"]].append(r)
    lists = [(c, refs, False) for c, refs in cells.items()] + [(c, refs, True) for c, refs in (vanilla or {}).items()]
    for cell, refs, from_master in lists:
        seen = {}
        for r in refs:
            if r.get("added"):
                r["key"] = "added|" + r["added"]
            elif not r.get("vanilla"):
                k = ref_key(cell, r)
                seen[k] = seen.get(k, 0) + 1
                r["key"] = k if seen[k] == 1 else "%s#%d" % (k, seen[k])
            keys.add(r["key"])
            new = edits["replaced"].get(r["key"])
            if new:
                r["orig_id"] = r["id"]
                r["id"] = new if r.get("vanilla") or not replaced_id else replaced_id(r["id"], new)
            door = edits.get("doors", {}).get(r["key"])
            if door:
                r["dest"] = (door["cell"], tuple(door["pos"]), door["rot"][2])
                r["dest_edited"] = True
            m = edits["moved"].get(r["key"])
            if m:
                r["orig"] = {"pos": list(r["pos"]), "rot": list(r["rot"]), "scale": r.get("scale")}
                r["pos"] = list(m["pos"])
                r["rot"] = list(m["rot"])
                if m.get("scale") is not None:
                    r["scale"] = m["scale"]
            if r.get("vanilla"):
                r["changed"] = bool(new or m or door or r["key"] in deleted)
                r["deleted"] = r["key"] in deleted
        if not from_master:
            refs[:] = [r for r in refs if r["key"] not in deleted]
    return keys


def gather(generated, edits, master, extra_cells=(), added_id=None, replaced_id=None):
    """A project's cells with the edits applied: ({cell: refs}, {cell: master refs}, keys)."""
    refs_of = master if callable(master) else (lambda c: vanilla_refs(master, c))
    cells = generated
    vanilla = {}
    for c in set(cells) | edited_cells(edits) | set(extra_cells):
        try:
            vanilla[c] = refs_of(c)
        except KeyError:
            continue
        cells.setdefault(c, [])
    keys = apply_edits(cells, vanilla, edits, added_id, replaced_id)
    return cells, vanilla, keys


def view(cells, vanilla, cell):
    """What a cell contains after the edits: the project's refs and the kept master ones."""
    return cells.get(cell, []) + [r for r in vanilla.get(cell, []) if not r["deleted"]]


def encode_vanilla_override(r, master_index=0):
    """A plugin reference overriding a master's: FRMR (master index + 1) << 24 | refnum; DELE deletes; MVRF moves."""
    num, subs = r["vanilla"]
    frmr = struct.pack("<I", ((master_index + 1) << 24) | (num & 0xffffff))
    out = [sub("FRMR", frmr)]
    if r.get("moved_to"):
        out[:0] = [sub("MVRF", frmr), sub("CNDT", struct.pack("<ii", *r["moved_to"]))]
    subs = [(s_, v) for s_, v in subs if s_ not in ("MVRF", "CNDT")]
    if r.get("dest_edited"):
        subs = _with_dest(subs, r["dest"])
    # XSCL goes right after NAME and UNAM, as the game writes it.
    scale = None if r.get("scale") in (None, 1.0) else sub("XSCL", struct.pack("<f", r["scale"]))
    for s_, v in subs:
        if s_ == "XSCL":
            continue
        if scale and s_ not in ("NAME", "UNAM"):
            out.append(scale)
            scale = None
        if s_ == "NAME":
            v = zstr(r["id"])
        elif s_ == "DATA":
            v = struct.pack("<6f", *r["pos"], *r["rot"])
        out.append(sub(s_, v))
    if scale:
        out.append(scale)
    if r["deleted"]:
        out.append(sub("DELE", struct.pack("<i", 0)))
    return b"".join(out)


def _with_dest(subs, dest):
    """Subrecords with the door destination (DODT, DNAM) replaced."""
    cell, (x, y, z), heading = dest
    new = [("DODT", struct.pack("<6f", x, y, z, 0.0, 0.0, heading))] + ([("DNAM", zstr(cell))] if cell else [])
    out, done = [], False
    for s_, v in subs:
        if s_ in ("DODT", "DNAM"):
            if not done:
                out += new
                done = True
            continue
        if s_ == "DATA" and not done:
            out += new
            done = True
        out.append((s_, v))
    return out


def grid_of(pos):
    """The exterior cell a position is in."""
    return math.floor(pos[0] / CELL_SIZE), math.floor(pos[1] / CELL_SIZE)


def rehome_exterior_refs(cells, vanilla, key_of):
    """Move references edited out of their exterior cell into the cell they're in now."""
    for cell in list(cells):
        g = parse_exterior(cell)
        if not g:
            continue
        stay = []
        for r in cells[cell]:
            t = grid_of(r["pos"])
            if t == g:
                stay.append(r)
            else:
                cells.setdefault(key_of(t), []).append(r)
        cells[cell][:] = stay
    for cell, refs in vanilla.items():
        g = parse_exterior(cell)
        for r in refs if g else ():
            t = grid_of(r["pos"])
            r["moved_to"] = t if r["changed"] and not r["deleted"] and t != g else None


def exterior_head(grid):
    """The header of an exterior cell no master has."""
    return [("NAME", b"\0"), ("DATA", struct.pack("<Iii", 0, *grid))]


# --- Plugin files --------------------------------------------------------------------

def plugin_bytes(records, masters, description="", author=""):
    """A whole plugin: the TES3 header, then the records."""
    header = struct.pack("<fI", 1.3, 0)
    header += author.encode("latin1")[:31].ljust(32, b"\0")
    header += description.encode("latin1")[:255].ljust(256, b"\0")
    header += struct.pack("<I", len(records))
    subs = [sub("HEDR", header)]
    for m in masters:
        subs += [sub("MAST", zstr(os.path.basename(m))), sub("DATA", struct.pack("<Q", os.path.getsize(m)))]
    return record("TES3", subs) + b"".join(records)


def edited_cell_records(cells, vanilla, master, refnums, names=None, head_of=None, master_index=None):
    """CELL records for the master's cells: header, new references and overrides."""
    records, count = [], 0
    for name in (sorted(cells) if names is None else names):
        refs = cells.get(name, [])
        overrides = [encode_vanilla_override(r, master_index(r) if master_index else 0)
                     for r in vanilla.get(name, []) if r["changed"]]
        if not refs and not overrides:
            continue
        head = [sub(s_, v) for s_, v in (head_of(name) if head_of else cell_refs(master, name)[0])]
        records.append(record("CELL", head + encode_refs(refs, refnums) + overrides))
        count += len(refs)
    return records, count


def _raw_records(data):
    """(tag, flags, record bytes, subrecords) of every record in a file's bytes."""
    p = 0
    while p + 16 <= len(data):
        tag = data[p:p + 4].decode("latin1")
        size, _, flags = struct.unpack_from("<III", data, p + 4)
        body, subs, q = data[p + 16:p + 16 + size], [], 0
        while q + 8 <= len(body):
            ss = struct.unpack_from("<I", body, q + 4)[0]
            subs.append((body[q:q + 4].decode("latin1"), body[q + 8:q + 8 + ss]))
            q += 8 + ss
        yield tag, flags, data[p:p + 16 + size], subs
        p += 16 + size


def _entry_bytes(num, subs):
    """A reference's bytes as they were."""
    lead = [x for x in subs if x[0] in ("MVRF", "CNDT")]
    rest = [x for x in subs if x[0] not in ("MVRF", "CNDT")]
    return b"".join(sub(s_, v) for s_, v in lead) + sub("FRMR", struct.pack("<I", num)) + \
        b"".join(sub(s_, v) for s_, v in rest)


def rewrite_plugin(base, cells, vanilla, refnums, masters, cell_key, key_of, head_of, master_index, objects=None,
                   dialogue=None):
    """An existing plugin with the edits written into it; other records stay as they were."""
    with open(base, "rb") as f:
        data = f.read()
    records = list(_raw_records(data))
    old_masters = [cstr(v).lower() for s_, v in records[0][3] if s_ == "MAST"]
    own = os.path.basename(base).lower()

    changed = {}
    home = {}
    for cell, refs in vanilla.items():
        for r in refs:
            if r["changed"]:
                k = (r["origin"].lower(), r["vanilla"][0] & 0xffffff)
                changed[k], home[k] = r, cell
    adds = {}

    def grid(cell):
        return parse_exterior(cell)

    def encode(r, num, subs, index, in_grid):
        r = dict(r, vanilla=(num, subs))
        t = grid_of(r["pos"])
        r["moved_to"] = t if in_grid and not r["deleted"] and t != in_grid else None
        return encode_vanilla_override(r, index)

    top, found = 0, set()
    plan = []
    objects = objects or {}
    key = lambda subs: cstr(subs[0][1]).lower() if subs and subs[0][0] == "NAME" else None   # noqa: E731
    present = {(tag, key(subs)) for tag, _, _, subs in records[1:]} & set(objects)
    fresh = [v for k, v in objects.items() if k not in present]
    dialogue = dict(dialogue or {})
    skipping = False
    for tag, flags, raw, subs in records[1:]:
        if tag == "INFO" and skipping:
            continue
        skipping = False
        if tag == "DIAL":
            k = key(subs)
            if k in dialogue:
                plan.append(dialogue.pop(k))
                skipping = True
                continue
        if tag != "CELL":
            k = (tag, key(subs))
            plan.append(objects[k] if k in present else raw)
            continue
        if fresh:
            plan.extend(fresh)
            fresh = []
        head, entries = _split_refs(subs)
        cell = cell_key(head)
        g = grid(cell)
        out, touched = [], False
        for num, rsubs in entries:
            local = num >> 24
            origin = own if local == 0 else (old_masters[local - 1] if local <= len(old_masters) else None)
            if local == 0:
                top = max(top, num)
            k = (origin, num & 0xffffff)
            r = changed.get(k)
            if r is None:
                out.append(_entry_bytes(num, rsubs))
                continue
            touched = True
            found.add(k)
            if origin == own:
                if r["deleted"]:
                    continue
                t = grid_of(r["pos"])
                rsubs = [x for x in rsubs if x[0] not in ("MVRF", "CNDT")]
                if g and t != g:
                    adds.setdefault(key_of(t), []).append(encode(r, num, rsubs, -1, None))
                else:
                    out.append(encode(r, num, rsubs, -1, None))
            else:
                out.append(encode(r, num & 0xffffff, rsubs, master_index(r), g))
        plan.append((cell, flags, raw, head, out, touched))

    plan.extend(fresh)
    plan.extend(dialogue.values())

    for k, r in changed.items():
        if k not in found and k[0] != own:
            cell = home[k]
            adds.setdefault(cell, []).append(encode(r, k[1], r["vanilla"][1], master_index(r), grid(cell)))
    refnums.next = max(refnums.next, top + 1)
    count = 0
    for cell, refs in cells.items():
        if refs:
            adds.setdefault(cell, []).extend(encode_refs(refs, refnums))
            count += len(refs)

    body, written, done = [], 0, set()
    by_lower = {c.lower(): c for c in adds}
    for item in plan:
        if isinstance(item, bytes):
            body.append(item)
            continue
        cell, flags, raw, head, out, touched = item
        extra = adds.get(by_lower.get(cell.lower()), []) if cell.lower() not in done else []
        if not touched and not extra:
            body.append(raw)
            continue
        done.add(cell.lower())
        written += 1
        body.append(record("CELL", [sub(s_, v) for s_, v in head] + out + extra, flags))
    for cell, refs in adds.items():
        if cell.lower() not in done and refs:
            written += 1
            body.append(record("CELL", [sub(s_, v) for s_, v in head_of(cell)] + refs))

    # The header: HEDR's record count at offset 296, and a MAST + DATA (file size) per master.
    hedr = dict(records[0][3])["HEDR"]
    subs = [sub("HEDR", hedr[:296] + struct.pack("<I", len(body)) + hedr[300:])]
    for m in masters:
        subs += [sub("MAST", zstr(os.path.basename(m))), sub("DATA", struct.pack("<Q", os.path.getsize(m)))]
    subs += [sub(s_, v) for s_, v in records[0][3] if s_ not in ("HEDR", "MAST", "DATA")]
    return record("TES3", subs, records[0][1]) + b"".join(body), written, count


def write_file(path, data):
    """Write a file atomically."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _write_text(path, text):
    write_file(path, text.encode("utf-8"))
