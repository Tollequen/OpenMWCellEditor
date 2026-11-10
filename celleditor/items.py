"""Item and object records (weapons, armour, clothing, misc items, books, potions, ingredients, lights, statics,
activators, doors): read, changed, created and written."""
import struct

from . import esp, magic
from .esp import cstr, zstr

MAX_ID = 31
KINDS = {"WEAP": "Weapon", "ARMO": "Armor", "CLOT": "Clothing", "MISC": "Misc", "BOOK": "Book", "ALCH": "Potion",
         "INGR": "Ingredient", "LIGH": "Light", "STAT": "Static", "ACTI": "Activator", "DOOR": "Door"}
CARRIED = ("WEAP", "ARMO", "CLOT", "MISC", "BOOK", "ALCH", "INGR", "LIGH")       # kinds an inventory can hold

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

# The other kinds: their fields, and what a new one starts with (components/esm3/loadalch, loadingr, loadligh,
# loadstat, loadacti, loaddoor). A light's flags: 1 dynamic, 2 carried, 4 negative, 8 flicker, 16 fire, 32 off by
# default, 64 slow flicker, 128 pulse, 256 slow pulse. An ingredient has up to 4 effects {effect, skill, attribute}.
OTHER = {
    "ALCH": (("id", "name", "model", "icon", "script", "weight", "value", "auto", "effects"),
             {"weight": 1.0, "value": 1, "auto": True, "effects": []}),
    "INGR": (("id", "name", "model", "icon", "script", "weight", "value", "effects"),
             {"weight": 0.1, "value": 1, "effects": []}),
    "LIGH": (("id", "name", "model", "icon", "script", "sound", "weight", "value", "time", "radius", "color", "lflags"),
             {"weight": 1.0, "value": 1, "time": -1, "radius": 128, "color": [255, 200, 120], "lflags": 1}),
    "STAT": (("id", "model"), {}),
    "ACTI": (("id", "name", "model", "script"), {}),
    "DOOR": (("id", "name", "model", "script", "open_sound", "close_sound"), {}),
}
TEXTS = ("name", "model", "icon", "script", "sound", "open_sound", "close_sound")


def fields_of(kind):
    """The fields an item of a kind has."""
    if kind in OTHER:
        return set(OTHER[kind][0])
    return set(COMMON) | set(DATA[kind][2]) | ({"parts"} if kind in WEARABLE else set()) | (
        {"text"} if kind == "BOOK" else set())


def parse(kind, subs):
    """An item record's fields."""
    d = dict(subs)
    if kind in OTHER:
        return _parse_other(kind, subs, d)
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
    if kind in OTHER:
        names, start = OTHER[kind]
        f = {k: "" for k in names if k in TEXTS}
        f.update(kind=kind, id=oid, **{k: (list(v) if isinstance(v, list) else v) for k, v in start.items()})
        return f
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
    if kind in OTHER:
        return _encode_other(kind, f)
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


def _parse_other(kind, subs, d):
    text = lambda s_: cstr(d.get(s_, b""))                                      # noqa: E731
    f = {"kind": kind, "id": text("NAME"), "model": text("MODL")}
    if kind != "STAT":
        f.update(name=text("FNAM"), script=text("SCRI"))
    if kind == "DOOR":
        f.update(open_sound=text("SNAM"), close_sound=text("ANAM"))
    elif kind == "LIGH":
        raw = d.get("LHDT", b"").ljust(24, b"\0")[:24]
        weight, value, time, radius = struct.unpack_from("<fiii", raw)
        f.update(icon=text("ITEX"), sound=text("SNAM"), weight=round(weight, 4), value=value, time=time, radius=radius,
                 color=list(raw[16:19]), lflags=struct.unpack_from("<i", raw, 20)[0])
    elif kind == "ALCH":
        weight, value, flags = struct.unpack("<fii", d.get("ALDT", b"").ljust(12, b"\0")[:12])
        f.update(icon=text("TEXT"), weight=round(weight, 4), value=value, auto=bool(flags & 1),
                 effects=magic.parse_effects(subs))
    elif kind == "INGR":
        raw = struct.unpack("<fi12i", d.get("IRDT", b"").ljust(56, b"\0")[:56])
        f.update(icon=text("ITEX"), weight=round(raw[0], 4), value=raw[1],
                 effects=[{"effect": raw[2 + i], "skill": raw[6 + i], "attribute": raw[10 + i]}
                          for i in range(4) if raw[2 + i] >= 0])
    return f


def _encode_other(kind, f):
    opt = lambda s_, k: [(s_, zstr(f[k]))] if f.get(k) else []                    # noqa: E731
    out = [("NAME", zstr(f["id"])), ("MODL", zstr(f["model"]))]
    if kind == "STAT":
        return out
    if kind == "ACTI":
        return out + opt("FNAM", "name") + opt("SCRI", "script")
    if kind == "DOOR":
        return out + opt("FNAM", "name") + opt("SCRI", "script") + opt("SNAM", "open_sound") + opt("ANAM", "close_sound")
    if kind == "LIGH":
        r, g, b = ([max(0, min(255, int(c))) for c in f.get("color") or ()] + [0, 0, 0])[:3]
        data = struct.pack("<fiii4Bi", float(f.get("weight", 0)), int(f.get("value", 0)), int(f.get("time", 0)),
                           int(f.get("radius", 0)), r, g, b, 0, int(f.get("lflags", 0)))
        return out + opt("FNAM", "name") + opt("ITEX", "icon") + [("LHDT", data)] + opt("SCRI", "script") + opt(
            "SNAM", "sound")
    if kind == "ALCH":
        data = struct.pack("<fii", float(f.get("weight", 0)), int(f.get("value", 0)), 1 if f.get("auto") else 0)
        return out + opt("TEXT", "icon") + opt("SCRI", "script") + opt("FNAM", "name") + [("ALDT", data)] + [
            ("ENAM", magic.encode_effect(e)) for e in f.get("effects") or []]
    fx = list(f.get("effects") or [])[:4]
    col = lambda k: [int(e.get(k, -1)) for e in fx] + [-1] * (4 - len(fx))      # noqa: E731
    data = struct.pack("<fi12i", float(f.get("weight", 0)), int(f.get("value", 0)), *col("effect"), *col("skill"),
                       *col("attribute"))
    return out + opt("FNAM", "name") + [("IRDT", data)] + opt("SCRI", "script") + opt("ITEX", "icon")


def _check_other(f):
    """Raise ValueError if a potion's or ingredient's effects can't be written."""
    kind, fx = f["kind"], f.get("effects") or []
    if kind == "ALCH" and not 1 <= len(fx) <= magic.MAX_EFFECTS:
        raise ValueError("The potion %s needs 1-%d effects." % (f["id"], magic.MAX_EFFECTS))
    if kind == "INGR" and len(fx) > 4:
        raise ValueError("The ingredient %s can have 4 effects at most." % f["id"])
    for e in fx if kind in ("ALCH", "INGR") else ():
        if not 0 <= int(e.get("effect", -1)) < len(magic.EFFECTS):
            raise ValueError("%s has an effect the game doesn't know." % f["id"])
        if kind == "ALCH" and int(e.get("min", 0)) > int(e.get("max", 0)):
            raise ValueError("In %s, an effect's least magnitude is more than its most." % f["id"])


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
            _check_other(f)
            for k in ("sound", "open_sound", "close_sound"):
                uses(f.get(k), "SOUN", "%s's sound" % f["id"])
            uses(f.get("script"), "SCPT", "%s's script" % f["id"])
            uses(f.get("enchant"), "ENCH", "%s's enchantment" % f["id"])
            for _, male, female in f.get("parts") or []:
                for b in (male, female):
                    uses(b, "BODY", "%s's body parts" % f["id"])
            rec = esp.record(kind, [esp.sub(s, v) for s, v in encode(f)], flags)
            out.append(((kind, key), rec))
        return out, need
