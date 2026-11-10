"""Room pieces: the walls, floors and doors the game itself lays out on a grid."""
import collections
import hashlib
import json
import math
import os
import re
import struct

from . import esp
from .models import cache_dir

VERSION = 1
PIECE_MESH = re.compile(r"(^|[\\/])[ixd][\\/]", re.I)
JAMB = re.compile(r"jamb|doorjam|djamb", re.I)
GRID = 64


def _quarter(rx, ry, rz):
    a = rz % (math.pi / 2)
    return abs(rx) < 0.01 and abs(ry) < 0.01 and min(a, math.pi / 2 - a) < 0.01


def _style(oid):
    return "_".join(oid.split("_")[:2])


def _on_grid(d):
    return abs(d / GRID - round(d / GRID)) < 0.02


def find(paths, objects):
    """Ids (lower case) of the load order's room pieces.

    A static whose model is in the i, x or d folder counts when the game places it turned by quarter turns and
    next to a piece of its style a whole number of 64-unit steps away, as rooms are built; whole buildings,
    rocks and beams it places freely. Doors with such a model always count."""
    by_cell = collections.defaultdict(list)
    for path in paths:
        interiors, _, _ = esp.cell_index(path)
        for cell in interiors:
            try:
                refs = esp.cell_refs(path, cell)[1]
            except KeyError:
                continue
            for _, subs in refs:
                d = dict(subs)
                if "NAME" not in d or len(d.get("DATA", b"")) < 24:
                    continue
                oid = esp.cstr(d["NAME"]).lower()
                kind, mesh = objects.get(oid, ("", ""))
                if kind != "STAT" or not oid.startswith(("in_", "ex_")) or not PIECE_MESH.search(mesh or ""):
                    continue
                by_cell[(path, cell)].append((oid,) + struct.unpack("<6f", d["DATA"][:24]))
    seen = collections.defaultdict(lambda: [0, 0, 0])            # id: [placed, turned by quarters, beside a piece]
    for refs in by_cell.values():
        styles = collections.defaultdict(list)
        for r in refs:
            styles[_style(r[0])].append(r)
        for r in refs:
            s = seen[r[0]]
            s[0] += 1
            s[1] += _quarter(*r[4:7])
            s[2] += any((abs(o[1] - r[1]) > 0.5 or abs(o[2] - r[2]) > 0.5) and abs(o[1] - r[1]) <= 1024
                        and abs(o[2] - r[2]) <= 1024 and _on_grid(o[1] - r[1]) and _on_grid(o[2] - r[2])
                        for o in styles[_style(r[0])] if o is not r)
    out = {oid for oid, (n, turned, beside) in seen.items()
           if turned >= 0.7 * n and (beside >= 0.4 * n or JAMB.search(oid))}
    out |= {oid for oid, (kind, mesh) in objects.items()
            if kind == "DOOR" and oid.startswith(("in_", "ex_")) and PIECE_MESH.search(mesh or "")}
    return sorted(out)


def cached(paths, objects):
    """find(), kept in the cache folder for this load order."""
    sig = ",".join("%s-%d-%d" % (os.path.basename(p).lower(), os.path.getsize(p), int(os.path.getmtime(p)))
                   for p in paths)
    key = hashlib.sha1(sig.encode()).hexdigest()[:12]
    path = os.path.join(cache_dir(), "pieces-%s.json" % key)
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("version") == VERSION and data.get("load") == sig:
            return data["pieces"]
    except (OSError, ValueError):
        pass
    pieces = find(paths, objects)
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": VERSION, "load": sig, "pieces": pieces}, f)
    except OSError:
        pass
    return pieces
