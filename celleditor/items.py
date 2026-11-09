"""Item records (weapons, armour, clothing, misc items, books): read, changed, created and written."""
import struct

from . import esp
from .esp import cstr, zstr

MAX_ID = 31
KINDS = {"WEAP": "Weapon", "ARMO": "Armor", "CLOT": "Clothing", "MISC": "Misc", "BOOK": "Book"}

# Each kind's data subrecord: (name, struct format, field names) (components/esm3/load*.hpp)
DATA = {
    "WEAP": ("WPDT", "<fihHffHBBBBBBi", ("weight", "value", "wtype", "health", "speed", "reach", "enchant_pts",
                                         "chop_min", "chop_max", "slash_min", "slash_max", "thrust_min",
                                         "thrust_max", "wflags")),
    "ARMO": ("AODT", "<ifiiii", ("atype", "weight", "value", "health", "enchant_pts", "rating")),
    "CLOT": ("CTDT", "<ifHH", ("ctype", "weight", "value", "enchant_pts")),
    "MISC": ("MCDT", "<fii", ("weight", "value", "mflags")),
    "BOOK": ("BKDT", "<fiiii", ("weight", "value", "scroll", "skill", "enchant_pts")),
}
DEFAULTS = {
    "WEAP": {"wtype": 0, "health": 100, "speed": 1.0, "reach": 1.0, "chop_min": 1, "chop_max": 5, "slash_min": 1,
             "slash_max": 5, "thrust_min": 1, "thrust_max": 5, "wflags": 0},
    "ARMO": {"atype": 1, "health": 100, "rating": 5},
    "CLOT": {"ctype": 2},
    "MISC": {"mflags": 0},
    "BOOK": {"scroll": 0, "skill": -1, "text": ""},
}
COMMON = ("id", "name", "model", "icon", "script", "enchant", "weight", "value", "enchant_pts")
WEARABLE = ("ARMO", "CLOT")


def fields_of(kind):
    """The fields an item of a kind has."""
    return set(COMMON) | set(DATA[kind][2]) | ({"parts"} if kind in WEARABLE else set()) | (
        {"text"} if kind == "BOOK" else set())


def parse(kind, subs):
    """An item record's fields."""
    d = dict(subs)
    data_name, fmt, names = DATA[kind]
    raw = d.get(data_name, b"").ljust(struct.calcsize(fmt), b"\0")[:struct.calcsize(fmt)]
    f = dict(zip(names, struct.unpack(fmt, raw)))
    f.update(kind=kind, id=cstr(d.get("NAME", b"")), name=cstr(d.get("FNAM", b"")), model=cstr(d.get("MODL", b"")),
             icon=cstr(d.get("ITEX", b"")), script=cstr(d.get("SCRI", b"")), enchant=cstr(d.get("ENAM", b"")))
    if kind == "BOOK":
        f["text"] = d.get("TEXT", b"").decode("latin1").rstrip("\0")
    if kind in WEARABLE:
        parts = []
        for s, v in subs:
            if s == "INDX":
                parts.append([v[0], "", ""])
            elif s in ("BNAM", "CNAM") and parts:
                parts[-1][1 if s == "BNAM" else 2] = cstr(v)
        f["parts"] = parts
    for k in ("weight", "speed", "reach"):
        if k in f:
            f[k] = round(f[k], 4)
    return f


def new_fields(kind, oid):
    """A new item's fields: the kind's defaults."""
    f = {k: "" for k in ("name", "model", "icon", "script", "enchant")}
    f.update(kind=kind, id=oid, weight=1.0, value=1, enchant_pts=0, **DEFAULTS[kind])
    if kind in WEARABLE:
        f["parts"] = []
    return f


def apply(fields, patch):
    """An item's fields with the edits' changes."""
    allowed = fields_of(fields["kind"]) - {"id"}
    return dict(fields, **{k: v for k, v in patch.items() if k in allowed})


def encode(f):
    """An item's subrecords in the order OpenMW writes them."""
    kind = f["kind"]
    data_name, fmt, names = DATA[kind]
    vals = []
    for n, c in zip(names, fmt[1:]):
        v = f.get(n, 0)
        vals.append(float(v) if c == "f" else int(v))
    data = (data_name, struct.pack(fmt, *vals))
    out = [("NAME", zstr(f["id"])), ("MODL", zstr(f["model"]))]
    if f.get("name"):
        out.append(("FNAM", zstr(f["name"])))
    script = [("SCRI", zstr(f["script"]))] if f.get("script") else []
    out += script + [data] if kind == "ARMO" else [data] + script
    if f.get("icon"):
        out.append(("ITEX", zstr(f["icon"])))
    for part, male, female in f.get("parts") or []:          # BNAM and CNAM have no closing NUL
        out.append(("INDX", bytes([int(part)])))
        if male:
            out.append(("BNAM", male.encode("latin1")))
        if female:
            out.append(("CNAM", female.encode("latin1")))
    if kind == "BOOK" and f.get("text"):
        out.append(("TEXT", f["text"].encode("latin1", "replace")))
    if f.get("enchant") and kind != "MISC":
        out.append(("ENAM", zstr(f["enchant"])))
    return out


class Items:
    """The load order's item records (index: an npc.Index of the same load order)."""

    def __init__(self, index):
        self.index = index

    def _record(self, oid):
        for kind in KINDS:
            w = self.index.where(kind).get(oid.lower())
            if w:
                _, flags, subs = esp.record_subs(w[0].path, w[1])
                if any(s == "DELE" for s, _ in subs):
                    return None
                return kind, w, flags, subs
        return None

    def get(self, oid, edits=None):
        """An item as the edits have it: fields, file, editable; None if there's no such item."""
        patch = (edits or {}).get(oid.lower())
        if patch and patch.get("new"):
            return dict(patch, file=None, editable=True)
        found = self._record(oid)
        if found is None:
            return None
        kind, w, _, subs = found
        return dict(apply(parse(kind, subs), patch or {}), file=w[0].name, editable=self.index._ok(w[0].name))

    def free_id(self, base, taken=()):
        """An unused id: base itself if it's free, else base_01, base_02..."""
        taken = {t.lower() for t in taken}
        base = base[:MAX_ID]
        if base.lower() not in taken and not self.index.find(base):
            return base
        for n in range(1, 1000):
            oid = "%s_%02d" % (base[:MAX_ID - 3], n) if n < 100 else "%s_%d" % (base[:MAX_ID - 4], n)
            if oid.lower() not in taken and not self.index.find(oid):
                return oid
        raise ValueError("no free id like %s" % base)

    def records(self, edits):
        """The edited and new items' records ((tag, id), record) and the files they need; raises ValueError."""
        out, need = [], {}

        def uses(oid, tag, why):
            w = self.index.where(tag).get(oid.lower()) if oid else None
            if w:
                need.setdefault(w[2], []).append(why)

        for key, patch in sorted(edits.items()):
            if patch.get("new"):
                kind = patch.get("kind")
                if kind not in KINDS:
                    raise ValueError("The new item %s has no kind." % patch.get("id"))
                f = apply(new_fields(kind, patch["id"]), patch)
                if not f["id"] or len(f["id"]) > MAX_ID or f["id"].lower() != key:
                    raise ValueError("A new item's id must be 1-%d letters: %r" % (MAX_ID, f["id"]))
                taken = self.index.find(f["id"])
                if taken:
                    raise ValueError("The new item %s has the id of %s in %s: give it another id." % (f["id"], *taken))
                if not f["model"]:
                    raise ValueError("The new item %s needs a model." % f["id"])
                flags = 0
            else:
                found = self._record(key)
                if found is None:
                    raise ValueError("The item %s isn't in the load order any more: its changes can't be saved." % key)
                kind, w, flags, subs = found
                if not self.index._ok(w[0].name):
                    raise ValueError("The item %s comes from %s, which this plugin can't use." % (key, w[0].name))
                f = apply(parse(kind, subs), patch)
                need.setdefault(w[0].name, []).append("%s changed" % f["id"])
            uses(f.get("script"), "SCPT", "%s's script" % f["id"])
            uses(f.get("enchant"), "ENCH", "%s's enchantment" % f["id"])
            for _, male, female in f.get("parts") or []:
                for b in (male, female):
                    uses(b, "BODY", "%s's body parts" % f["id"])
            rec = esp.record(kind, [esp.sub(s, v) for s, v in encode(f)], flags)
            out.append(((kind, key), rec))
        return out, need
