"""The game's content files merged in load order as OpenMW does, the last file winning."""
import os
import struct

from . import esp
from .writer import dest_of, ref

TES3_EXTENSIONS = (".esm", ".esp", ".omwaddon", ".omwgame")


def masters_of(path):
    """The master file names in a plugin's header."""
    tag, _, subs = next(esp.esm_records(path, header_only=True))
    return [esp.cstr(v) for s, v in subs if s == "MAST"]


class ContentFile:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.masters = masters_of(path)


class LoadOrder:
    def __init__(self, paths):
        self.files = [ContentFile(p) for p in paths]
        self._index = {f.name.lower(): i for i, f in enumerate(self.files)}
        self._cells = None

    @property
    def paths(self):
        return [f.path for f in self.files]

    def index(self, name):
        """A file's position in the load order, or None if it isn't loaded."""
        return self._index.get(name.lower())

    def file(self, name):
        i = self.index(name)
        return None if i is None else self.files[i]

    # --- Cells --------------------------------------------------------------------

    def cells(self):
        """(interior names, {grid: name}) of every file; an exterior is named by the first file."""
        if self._cells is None:
            interiors, exteriors = {}, {}
            for f in self.files:
                ins, exs, names = esp.cell_index(f.path)
                for n in ins:
                    interiors.setdefault(n.lower(), n)
                for g in exs:
                    if not exteriors.get(g):
                        exteriors[g] = names.get(g, "")
            self._cells = (sorted(interiors.values(), key=str.lower), exteriors)
        return self._cells

    def has_cell(self, cell, among=None):
        return bool(self.defining(cell, among))

    def defining(self, cell, among=None):
        """The files, in load order, that have a record for a cell."""
        want = None if among is None else {n.lower() for n in among}
        out = []
        for f in self.files:
            if want is not None and f.name.lower() not in want:
                continue
            ins, exs, _ = esp.cell_index(f.path)
            grid = esp.parse_exterior(cell)
            if (grid in exs) if grid else (cell in ins):
                out.append(f)
        return out

    def cell_head(self, cell, among=None):
        """A cell's header subrecords from the last file that has it; KeyError if none has it."""
        files = self.defining(cell, among)
        if not files:
            raise KeyError(cell)
        return esp.cell_refs(files[-1].path, cell)[0]

    def references(self, cell):
        """[(origin file, number, subrecords)] of a cell with later changes, deletions and moves applied."""
        grid = esp.parse_exterior(cell)
        table, touched = {}, {}
        found = False
        for fi, f in enumerate(self.files):
            entries = []
            try:
                entries += esp.cell_refs(f.path, cell)[1]
                found = True
            except KeyError:
                pass
            if grid:
                moved_in = esp.moved_refs(f.path).get(grid, [])
                found = found or bool(moved_in)
                entries += moved_in
            for raw, subs in entries:
                local, num = raw >> 24, raw & 0xffffff
                if local and local <= len(f.masters):
                    origin = self.index(f.masters[local - 1])
                    if origin is None:
                        continue
                else:
                    origin = fi
                key = (origin, num)
                d = dict(subs)
                target = struct.unpack("<ii", d["CNDT"]) if "CNDT" in d else None
                if "DELE" in d or (target is not None and target != grid):
                    table.pop(key, None)
                else:
                    table[key] = subs
                if fi != origin:
                    touched.setdefault(key, []).append(f.name)
        if not found:
            raise KeyError(cell)
        self.changed_by = {(self.files[o].name, n): names for (o, n), names in touched.items()}
        return [(self.files[o].name, n, subs) for (o, n), subs in table.items()]

    def master_refs(self, cell, first_master="Morrowind.esm"):
        """A cell's references as refs the edits can change, keyed by cell, origin and number."""
        out = []
        for origin, num, subs in self.references(cell):
            d = dict(subs)
            if "DATA" not in d or "NAME" not in d:
                continue
            x, y, z, rx, ry, rz = struct.unpack("<6f", d["DATA"])
            r = ref(esp.cstr(d["NAME"]), x, y, z, rz, rot_x=rx, rot_y=ry,
                    scale=struct.unpack("<f", d["XSCL"])[0] if "XSCL" in d else None, dest=dest_of(subs))
            r["vanilla"] = (num, subs)
            r["origin"] = origin
            r["changed_by"] = self.changed_by.get((origin, num), [])
            tag = str(num) if origin.lower() == first_master.lower() else "%s:%d" % (origin, num)
            r["key"] = "%s|vanilla|%s" % (cell, tag)
            out.append(r)
        return out

    # --- Terrain ------------------------------------------------------------------

    def land(self):
        """The last file's LAND of each grid and each file's land textures."""
        lands, ltex = {}, {}
        for fi, f in enumerate(self.files):
            where, textures = esp.land_index(f.path)
            for grid, offset in where.items():
                lands[grid] = (_Record(f.path, offset), fi)
            if textures:
                ltex[fi] = textures
        return lands, ltex


class _Record:
    """A record's subrecords ({tag: bytes}), read on first use."""

    def __init__(self, path, offset):
        self.path, self.offset, self._d = path, offset, None

    def _subs(self):
        if self._d is None:
            self._d = esp.record_at(self.path, self.offset)
        return self._d

    def __contains__(self, k):
        return k in self._subs()

    def __getitem__(self, k):
        return self._subs()[k]

    def get(self, k, default=None):
        return self._subs().get(k, default)


def from_game(game, content=None, exclude=(), replace=None):
    """The load order of TES3 files from the content list, found in the data folders."""
    skip = {e.lower() for e in exclude}
    swap = {k.lower(): v for k, v in (replace or {}).items()}
    paths, missing, used = [], [], set()
    for name in content if content is not None else game.content:
        low = name.lower()
        if not low.endswith(TES3_EXTENSIONS) or low in skip:
            continue
        if low in swap:
            paths.append(swap[low])
            used.add(low)
            continue
        p = game.find(name)
        (paths if p else missing).append(p or name)
    paths += [v for k, v in swap.items() if k not in used]
    if missing:
        print("Not found in the data folders, skipped:", ", ".join(missing))
    return LoadOrder(paths)
