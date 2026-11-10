"""Container records: their contents and respawn flag, and copies made for one placed container."""
import struct

from . import esp
from .esp import cstr, zstr

RESPAWN = 2                                     # FLAG bit (components/esm3/loadcont.hpp)
MAX_ID = 31


def parse(subs):
    """A container record's fields: id, name, model, flags, respawn, contents [[count, item id]]."""
    d = dict(subs)
    flags = struct.unpack("<i", d["FLAG"][:4])[0] if len(d.get("FLAG", b"")) >= 4 else 0
    return {"id": cstr(d.get("NAME", b"")), "name": cstr(d.get("FNAM", b"")), "model": cstr(d.get("MODL", b"")),
            "flags": flags, "respawn": bool(flags & RESPAWN),
            "contents": [[struct.unpack_from("<i", v)[0], cstr(v[4:])] for s, v in subs if s == "NPCO" and len(v) >= 4]}


def encode(subs, fields):
    """A container record's subrecords with the fields' id, respawn flag and contents (NPCO after SCRI)."""
    flags = (fields["flags"] & ~RESPAWN) | (RESPAWN if fields["respawn"] else 0)
    out = []
    for s, v in subs:
        if s == "NPCO":
            continue
        if s == "NAME":
            v = zstr(fields["id"])
        elif s == "FLAG":
            v = struct.pack("<i", flags)
        out.append((s, v))
    out += [("NPCO", struct.pack("<i", n) + iid.encode("latin1")[:32].ljust(32, b"\0")) for n, iid in fields["contents"]]
    return out


def blank(patch):
    """A container made from scratch: (subrecords, fields) from its entry's id, name, model and capacity."""
    subs = [("NAME", zstr(patch["id"])), ("MODL", zstr(patch.get("model") or ""))]
    if patch.get("name"):
        subs.append(("FNAM", zstr(patch["name"])))
    subs += [("CNDT", struct.pack("<f", float(patch.get("capacity", 100)))), ("FLAG", struct.pack("<i", 8))]
    return subs, apply(parse(subs), patch)


def apply(fields, patch):
    """A container's fields with the edits' changes."""
    return dict(fields, **{k: v for k, v in patch.items() if k in ("contents", "respawn")})


class Containers:
    """The load order's container records (index: an npc.Index of the same load order)."""

    def __init__(self, index):
        self.index = index

    def _record(self, oid):
        w = self.index.where("CONT").get(oid.lower())
        if w is None:
            return None
        _, flags, subs = esp.record_subs(w[0].path, w[1])
        if any(s == "DELE" for s, _ in subs):
            return None
        return w, flags, subs

    def get(self, oid, edits=None):
        """A container as the edits have it: fields, file, editable; None if there's no such container."""
        edits = edits or {}
        patch = edits.get(oid.lower())
        if patch and patch.get("new") and not patch.get("copy_of"):
            return dict(blank(patch)[1], file=None, editable=True)
        if patch and patch.get("new"):
            base = self._record(patch["copy_of"])
            if base is None:
                return None
            f = apply(dict(parse(base[2]), id=patch["id"]), patch)
            return dict(f, file=None, copy_of=patch["copy_of"], editable=True)
        found = self._record(oid)
        if found is None:
            return None
        w = found[0]
        return dict(apply(parse(found[2]), patch or {}), file=w[0].name, editable=self.index._ok(w[0].name))

    def free_id(self, base, taken=()):
        """An unused id for a copy of a container: base_01, base_02..."""
        taken = {t.lower() for t in taken}
        stem = base[:MAX_ID - 3]
        for n in range(1, 1000):
            oid = "%s_%02d" % (stem, n) if n < 100 else "%s_%d" % (base[:MAX_ID - 4], n)
            if oid.lower() not in taken and not self.index.find(oid):
                return oid
        raise ValueError("no free id for a copy of %s" % base)

    def records(self, edits):
        """The edited and copied containers' records and the files they need; raises ValueError."""
        out, need = [], {}
        items = {}
        for tag in ("WEAP", "ARMO", "CLOT", "MISC", "BOOK", "ALCH", "INGR", "APPA", "LOCK", "PROB", "REPA", "LIGH",
                    "LEVI"):
            items.update({k: v for k, v in self.index.where(tag).items() if k not in items})
        for key, patch in sorted(edits.items()):
            if patch.get("new"):
                if not patch["id"] or len(patch["id"]) > MAX_ID or patch["id"].lower() != key:
                    raise ValueError("A new container's id must be 1-%d letters: %r" % (MAX_ID, patch["id"]))
                taken = self.index.find(patch["id"])
                if taken:
                    raise ValueError("The new container %s has the id of %s in %s." % (patch["id"], *taken))
                if patch.get("copy_of"):
                    base = self._record(patch["copy_of"])
                    if base is None:
                        raise ValueError("The container %s that %s copies isn't in the load order." % (
                            patch["copy_of"], patch["id"]))
                    (w, flags, subs) = base
                    fields = apply(dict(parse(subs), id=patch["id"]), patch)      # a whole record: no master needed
                else:
                    if not patch.get("model"):
                        raise ValueError("The new container %s needs a model." % patch["id"])
                    flags = 0
                    subs, fields = blank(patch)
            else:
                found = self._record(key)
                if found is None:
                    raise ValueError("The container %s isn't in the load order any more: its contents can't "
                                     "be saved." % key)
                (w, flags, subs) = found
                if not self.index._ok(w[0].name):
                    raise ValueError("The container %s comes from %s, which this plugin can't use." % (key, w[0].name))
                fields = apply(parse(subs), patch)
                need.setdefault(w[0].name, []).append("%s's contents changed" % fields["id"])
            for _, iid in fields["contents"]:
                where = items.get(iid.lower())
                if where:
                    need.setdefault(where[2], []).append("%s holds %s" % (fields["id"], iid))
            rec = esp.record("CONT", [esp.sub(s, v) for s, v in encode(subs, fields)], flags)
            out.append((key, rec))
        return out, need
