"""New interior cells: their settings in the edits and their CELL headers."""
import struct

from .esp import EXTERIOR, cstr, zstr

MAX_NAME = 63
INTERIOR, WATER, NO_SLEEP, LIKE_EXTERIOR = 0x01, 0x02, 0x04, 0x80
DEFAULTS = {"ambient": [62, 50, 38], "sun": [81, 40, 0], "fog": [107, 56, 35], "fog_density": 1.0, "water": None,
            "no_sleep": False, "like_exterior": False}


def _colour(v, default):
    try:
        return [max(0, min(255, int(c))) for c in list(v)[:3]] if len(v) >= 3 else list(default)
    except (TypeError, ValueError):
        return list(default)


def clean(c):
    """A new cell's entry as it's stored."""
    out = {"new": True, "name": str(c.get("name") or "").strip()}
    for k in ("ambient", "sun", "fog"):
        out[k] = _colour(c.get(k) or (), DEFAULTS[k])
    try:
        out["fog_density"] = round(max(0.0, min(1.0, float(c.get("fog_density", 1.0)))), 3)
    except (TypeError, ValueError):
        out["fog_density"] = 1.0
    try:
        out["water"] = None if c.get("water") is None else round(float(c["water"]), 2)
    except (TypeError, ValueError):
        out["water"] = None
    out["no_sleep"] = bool(c.get("no_sleep"))
    out["like_exterior"] = bool(c.get("like_exterior"))
    return out


def new_cells(edits):
    """{name: entry} of the edits' new cells."""
    return {c["name"]: c for c in (edits.get("cells") or {}).values() if c and c.get("new") and c.get("name")}


def name_error(name, interiors=()):
    """Why a new interior can't have this name, or None."""
    if not name:
        return "The cell needs a name."
    if len(name) > MAX_NAME:
        return "A cell's name can be %d letters at most." % MAX_NAME
    if "|" in name or EXTERIOR.search(name):
        return "A cell's name can't have | in it or end like an exterior's, in (x, y)."
    try:
        name.encode("latin1")
    except UnicodeEncodeError:
        return "A cell's name can only have letters Morrowind's files can hold (Latin-1)."
    if name.lower() in {n.lower() for n in interiors}:
        return "There's a cell named %s already." % name
    return None


def head(c):
    """A new cell's header subrecords, in the order OpenMW writes them."""
    c = dict(DEFAULTS, **c)
    flags = INTERIOR | (WATER if c["water"] is not None else 0) | (NO_SLEEP if c["no_sleep"] else 0) | (
        LIKE_EXTERIOR if c["like_exterior"] else 0)
    out = [("NAME", zstr(c["name"])), ("DATA", struct.pack("<Iii", flags, 0, 0))]
    if c["water"] is not None:
        out.append(("WHGT", struct.pack("<f", c["water"])))
    if not c["like_exterior"]:
        out.append(("AMBI", b"".join(bytes(c[k][:3]) + b"\0" for k in ("ambient", "sun", "fog"))
                    + struct.pack("<f", c["fog_density"])))
    return out


def settings(subs):
    """An interior's settings from its header subrecords, as a new cell's entry has them."""
    d = dict(subs)
    flags = struct.unpack_from("<I", d.get("DATA", b"").ljust(4, b"\0"))[0]
    out = dict(DEFAULTS, name=cstr(d.get("NAME", b"")), no_sleep=bool(flags & NO_SLEEP),
               like_exterior=bool(flags & LIKE_EXTERIOR))
    a = d.get("AMBI", b"")
    if len(a) >= 16:
        out.update(ambient=list(a[0:3]), sun=list(a[4:7]), fog=list(a[8:11]),
                   fog_density=round(struct.unpack_from("<f", a, 12)[0], 3))
    if flags & WATER:
        out["water"] = (round(struct.unpack("<f", d["WHGT"])[0], 2) if len(d.get("WHGT", b"")) == 4
                        else float(struct.unpack("<i", d["INTV"])[0]) if len(d.get("INTV", b"")) == 4 else 0.0)
    return out
