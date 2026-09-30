"""NPC_ records as editable fields, and written back."""
import struct

from . import esp
from .esp import cstr, zstr

ATTRIBUTES = ("Strength", "Intelligence", "Willpower", "Agility", "Speed", "Endurance", "Personality", "Luck")
SKILLS = ("Block", "Armorer", "Medium Armor", "Heavy Armor", "Blunt Weapon", "Long Blade", "Axe", "Spear",
          "Athletics", "Enchant", "Destruction", "Alteration", "Illusion", "Conjuration", "Mysticism",
          "Restoration", "Alchemy", "Unarmored", "Security", "Sneak", "Acrobatics", "Light Armor",
          "Short Blade", "Marksman", "Mercantile", "Speechcraft", "Hand-to-hand")
# Morrowind.esm's skill data (governing attribute, specialization), used when no SKIL is loaded.
SKILL_DATA = ((5, 0), (0, 0), (5, 0), (5, 0), (5, 0), (0, 0), (0, 0), (5, 0), (4, 2), (1, 1), (2, 1),
              (2, 1), (1, 1), (1, 1), (2, 1), (2, 1), (1, 1), (4, 2), (1, 2), (3, 2), (0, 2), (3, 2),
              (4, 2), (3, 2), (6, 2), (6, 2), (4, 2))
FEMALE, ESSENTIAL, RESPAWN, AUTOCALC = 0x01, 0x02, 0x04, 0x10
# Record types that share OpenMW's object id space.
OBJECT_TAGS = {"ACTI": "an activator", "ALCH": "a potion", "APPA": "an apparatus", "ARMO": "an armor",
               "BODY": "a body part", "BOOK": "a book", "CLOT": "a clothing item", "CONT": "a container",
               "CREA": "a creature", "DOOR": "a door", "INGR": "an ingredient", "LEVC": "a leveled creature list",
               "LEVI": "a leveled item list", "LIGH": "a light", "LOCK": "a lockpick", "MISC": "a misc item",
               "NPC_": "an NPC", "PROB": "a probe", "REPA": "a repair item", "STAT": "a static", "WEAP": "a weapon"}
ITEM_TAGS = {"WEAP": "Weapon", "ARMO": "Armor", "CLOT": "Clothing", "MISC": "Misc", "BOOK": "Book",
             "ALCH": "Potion", "INGR": "Ingredient", "APPA": "Apparatus", "LOCK": "Lockpick", "PROB": "Probe",
             "REPA": "Repair", "LIGH": "Light", "LEVI": "Leveled list"}
SPELL_TYPES = ("Spell", "Ability", "Blight", "Disease", "Curse", "Power")
FIELDS = ("id", "name", "model", "race", "class", "faction", "head", "hair", "script", "level", "autocalc",
          "attributes", "skills", "health", "magicka", "fatigue", "disposition", "reputation", "rank", "gold",
          "female", "essential", "respawn", "blood", "items", "spells", "hello", "fight", "flee", "alarm",
          "services", "wander")
TAIL = ("DODT", "DNAM", "AI_W", "AI_T", "AI_F", "AI_E", "AI_A", "CNDT")
PACKAGE_NAMES = {"AI_T": "Travel", "AI_F": "Follow", "AI_E": "Escort", "AI_A": "Activate"}
MAX_ID = 31                      # the Construction Set's limit; the record itself has none


def parse(subs):
    """An NPC_ record's subrecords as fields."""
    d = {}
    for s, v in subs:
        d.setdefault(s, v)
    f = {"id": cstr(d.get("NAME", b"")), "name": cstr(d.get("FNAM", b"")), "model": cstr(d.get("MODL", b""))}
    for k, s in (("race", "RNAM"), ("class", "CNAM"), ("faction", "ANAM"), ("head", "BNAM"), ("hair", "KNAM"),
                 ("script", "SCRI")):
        f[k] = cstr(d.get(s, b""))
    npdt = d.get("NPDT", b"\0" * 12)
    if len(npdt) >= 52:
        f.update(level=struct.unpack_from("<h", npdt)[0], autocalc=False, attributes=list(npdt[2:10]),
                 skills=list(npdt[10:37]))
        f["health"], f["magicka"], f["fatigue"] = struct.unpack_from("<3H", npdt, 38)
        f["disposition"], f["reputation"], f["rank"] = npdt[44], npdt[45], npdt[46]
        f["gold"] = struct.unpack_from("<i", npdt, 48)[0]
    else:
        npdt = npdt.ljust(12, b"\0")
        f.update(level=struct.unpack_from("<h", npdt)[0], autocalc=True, attributes=[0] * 8, skills=[0] * 27,
                 health=0, magicka=0, fatigue=0, disposition=npdt[2], reputation=npdt[3], rank=npdt[4],
                 gold=struct.unpack_from("<i", npdt, 8)[0])
    flags = struct.unpack("<i", d["FLAG"][:4])[0] if len(d.get("FLAG", b"")) >= 4 else 0
    f.update(female=bool(flags & FEMALE), essential=bool(flags & ESSENTIAL), respawn=bool(flags & RESPAWN),
             blood=(flags >> 10) & 0x3f)
    f["items"] = [[struct.unpack_from("<i", v)[0], cstr(v[4:])] for s, v in subs if s == "NPCO" and len(v) >= 4]
    f["spells"] = [cstr(v) for s, v in subs if s == "NPCS"]
    aidt = d.get("AIDT", b"").ljust(12, b"\0")
    f["hello"] = struct.unpack_from("<H", aidt)[0]
    f["fight"], f["flee"], f["alarm"] = aidt[2], aidt[3], aidt[4]
    f["services"] = struct.unpack_from("<i", aidt, 8)[0]
    w = d.get("AI_W")
    f["wander"] = None if w is None else {
        "distance": struct.unpack_from("<h", w.ljust(14, b"\0"))[0],
        "duration": struct.unpack_from("<h", w.ljust(14, b"\0"), 2)[0],
        "time": w.ljust(14, b"\0")[4], "idle": list(w.ljust(14, b"\0")[5:13]), "repeat": bool(w.ljust(14, b"\0")[13])}
    return f


def extras(subs):
    """What the page shows but doesn't edit: travel destinations and other AI packages."""
    return {"travel": sum(1 for s, _ in subs if s == "DODT"),
            "packages": [PACKAGE_NAMES[s] for s, _ in subs if s in PACKAGE_NAMES]}


def _clamp(v, lo, hi, what):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ValueError("%s: %r isn't a whole number" % (what, v))
    return min(hi, max(lo, v))


def _fixed(s, what):
    b = s.encode("latin1")
    if len(b) > 32:
        raise ValueError("%s: %s is longer than 32 letters" % (what, s))
    return b.ljust(32, b"\0")


def encode(f, base=(), base_flags=None):
    """The subrecords of an NPC with fields f, keeping what the fields don't cover from base."""
    who = f["id"]
    old = dict(base)
    out = [("NAME", zstr(who))]
    if f["model"]:
        out.append(("MODL", zstr(f["model"])))
    if f["name"]:
        out.append(("FNAM", zstr(f["name"])))
    for k, s in (("race", "RNAM"), ("class", "CNAM"), ("faction", "ANAM"), ("head", "BNAM"), ("hair", "KNAM")):
        out.append((s, zstr(f[k] or "")))
    if f["script"]:
        out.append(("SCRI", zstr(f["script"])))
    level = _clamp(f["level"], 0, 32767, who + " level")
    byte = lambda k: _clamp(f[k], 0, 255, "%s %s" % (who, k))          # noqa: E731
    gold = _clamp(f["gold"], -2 ** 31, 2 ** 31 - 1, who + " gold")
    was = old.get("NPDT", b"")                     # NPDT padding is kept: the Construction Set leaves bytes in it
    if f["autocalc"]:
        pad = was[5:8] if len(was) == 12 else b"\0\0\0"
        npdt = struct.pack("<hBBB3si", level, byte("disposition"), byte("reputation"), byte("rank"), pad, gold)
    else:
        attrs = [_clamp(v, 0, 255, who + " " + ATTRIBUTES[i]) for i, v in enumerate(f["attributes"])]
        skills = [_clamp(v, 0, 255, who + " " + SKILLS[i]) for i, v in enumerate(f["skills"])]
        if len(attrs) != 8 or len(skills) != 27:
            raise ValueError("%s: 8 attributes and 27 skills are needed" % who)
        pads = (was[37:38], was[47:48]) if len(was) == 52 else (b"\0", b"\0")
        npdt = struct.pack("<h8B27Bc3HBBBci", level, *attrs, *skills, pads[0],
                           *[_clamp(f[k], 0, 65535, "%s %s" % (who, k)) for k in ("health", "magicka", "fatigue")],
                           byte("disposition"), byte("reputation"), byte("rank"), pads[1], gold)
    out.append(("NPDT", npdt))
    flags = struct.unpack("<i", old["FLAG"][:4])[0] if len(old.get("FLAG", b"")) >= 4 else 0x08
    flags &= 0x3ff & ~(FEMALE | ESSENTIAL | RESPAWN | AUTOCALC)
    flags |= (FEMALE if f["female"] else 0) | (ESSENTIAL if f["essential"] else 0) | \
        (RESPAWN if f["respawn"] else 0) | (AUTOCALC if f["autocalc"] else 0)
    out.append(("FLAG", struct.pack("<i", flags | (_clamp(f["blood"], 0, 63, who + " blood") << 10))))
    for count, item in f["items"]:
        out.append(("NPCO", struct.pack("<i", _clamp(count, -2 ** 31, 2 ** 31 - 1, who + " item count"))
                    + _fixed(item, who + " item")))
    for spell in f["spells"]:
        out.append(("NPCS", _fixed(spell, who + " spell")))
    pad = old.get("AIDT", b"\0" * 12).ljust(12, b"\0")[5:8]
    out.append(("AIDT", struct.pack("<HBBB3si", _clamp(f["hello"], 0, 65535, who + " hello"),
                                    byte("fight"), byte("flee"), byte("alarm"), pad,
                                    _clamp(f["services"], -2 ** 31, 2 ** 31 - 1, who + " services"))))
    w = f["wander"]
    wander = None if w is None else ("AI_W", struct.pack(
        "<hhB8BB", _clamp(w["distance"], -32768, 32767, who + " wander distance"),
        _clamp(w["duration"], -32768, 32767, who + " wander duration"),
        _clamp(w["time"], 0, 255, who + " wander time"),
        *[_clamp(v, 0, 255, who + " idle") for v in (list(w["idle"]) + [0] * 8)[:8]], 1 if w.get("repeat") else 0))
    done = False
    for s, v in base:
        if s not in TAIL:
            continue
        if s == "AI_W" and not done:
            done = True
            if wander:
                out.append(wander)
            continue
        out.append((s, v))
    if wander and not done:
        out.append(wander)
    return out


def apply(fields, patch):
    """An NPC's fields with the edits' changes."""
    return dict(fields, **{k: v for k, v in patch.items() if k in FIELDS and k != "id"})


def new_fields(patch):
    """A new NPC's fields."""
    missing = [k for k in FIELDS if k not in patch]
    if missing:
        raise ValueError("the new NPC %s has no %s" % (patch.get("id"), ", ".join(missing)))
    return {k: patch[k] for k in FIELDS}


class Index:
    """The load order's NPCs and the lists their fields choose from."""

    def __init__(self, load, usable=None):
        self.files = load.files
        self.usable = usable
        self._where, self._list, self._lists = {}, None, None

    def where(self, tag):
        """{id (lower case): (last file, offset, first file's name)}."""
        if tag not in self._where:
            out = {}
            for f in self.files:
                for i, off in esp.named_records(f.path).get(tag, {}).items():
                    out[i] = (f, off, out[i][2] if i in out else f.name)
            self._where[tag] = out
        return self._where[tag]

    def _subs(self, tag, oid):
        w = self.where(tag).get(oid.lower())
        return None if w is None else esp.record_subs(w[0].path, w[1])

    def _ok(self, name):
        return self.usable is None or name.lower() in self.usable

    def find(self, oid):
        """(what it is, e.g. "an NPC", file) of an object with this id, or None."""
        for tag, what in OBJECT_TAGS.items():
            w = self.where(tag).get(oid.lower())
            if w:
                return what, w[0].name
        return None

    def npcs(self):
        """The list: [{id, name, race, class, file, editable}]."""
        if self._list is None:
            out = []
            for i, (f, off, first) in self.where("NPC_").items():
                _, _, subs = esp.record_subs(f.path, off)
                d = dict(subs)
                if "DELE" in d:
                    continue
                out.append({"id": cstr(d.get("NAME", b"")), "name": cstr(d.get("FNAM", b"")),
                            "race": cstr(d.get("RNAM", b"")), "class": cstr(d.get("CNAM", b"")),
                            "file": f.name, "editable": self._ok(f.name)})
            self._list = sorted(out, key=lambda n: ((n["name"] or n["id"]).lower(), n["id"].lower()))
        return self._list

    def npc(self, oid):
        """One NPC as the load order has it, or None."""
        w = self.where("NPC_").get(oid.lower())
        if w is None:
            return None
        tag, flags, subs = esp.record_subs(w[0].path, w[1])
        if any(s == "DELE" for s, _ in subs):
            return None
        return dict(extras(subs), fields=parse(subs), file=w[0].name, origin=w[2], editable=self._ok(w[0].name))

    def lists(self):
        """What the NPC page chooses from: races, classes, factions, body parts, spells, items and more."""
        if self._lists is not None:
            return self._lists

        def each(tag):
            for i, (f, off, first) in sorted(self.where(tag).items()):
                if not self._ok(first):
                    continue
                _, _, subs = esp.record_subs(f.path, off)
                d = {}
                for s, v in subs:
                    d.setdefault(s, v)
                if "DELE" not in d:
                    yield d, subs

        races = []
        for d, _ in each("RACE"):
            radt = d.get("RADT", b"").ljust(140, b"\0")
            bonus = [list(struct.unpack_from("<ii", radt, 8 * k)) for k in range(7)]
            races.append({"id": cstr(d["NAME"]), "name": cstr(d.get("FNAM", b"")),
                          "attrs": list(struct.unpack_from("<16i", radt, 56)), "bonus": bonus,
                          "flags": struct.unpack_from("<i", radt, 136)[0]})
        classes = []
        for d, _ in each("CLAS"):
            c = d.get("CLDT", b"").ljust(60, b"\0")
            v = struct.unpack_from("<15i", c)
            classes.append({"id": cstr(d["NAME"]), "name": cstr(d.get("FNAM", b"")), "attrs": list(v[:2]),
                            "spec": v[2], "skills": [list(v[3 + 2 * k:5 + 2 * k]) for k in range(5)],
                            "services": v[14]})
        factions = []
        for d, subs in each("FACT"):
            factions.append({"id": cstr(d["NAME"]), "name": cstr(d.get("FNAM", b"")),
                             "ranks": [cstr(v) for s, v in subs if s == "RNAM"]})
        parts = []
        for d, _ in each("BODY"):
            b = d.get("BYDT", b"").ljust(4, b"\0")
            if b[3] == 0 and b[0] in (0, 1):                  # BYDT: a skin part that is a head (0) or hair (1)
                parts.append({"id": cstr(d["NAME"]), "race": cstr(d.get("FNAM", b"")), "part": b[0],
                              "vampire": bool(b[1]), "female": bool(b[2] & 1)})
        spells = []
        for d, _ in each("SPEL"):
            t = struct.unpack_from("<i", d.get("SPDT", b"").ljust(4, b"\0"))[0]
            spells.append({"id": cstr(d["NAME"]), "name": cstr(d.get("FNAM", b"")),
                           "type": SPELL_TYPES[t] if 0 <= t < len(SPELL_TYPES) else "?"})
        items = []
        for tag, kind in ITEM_TAGS.items():
            for d, _ in each(tag):
                items.append({"id": cstr(d["NAME"]), "name": cstr(d.get("FNAM", b"")), "type": kind})
        items.sort(key=lambda o: o["id"].lower())
        scripts = sorted((cstr(d["SCHD"][:32]) for d, _ in each("SCPT") if "SCHD" in d), key=str.lower)
        skills = [list(v) for v in SKILL_DATA]
        for d, _ in each("SKIL"):
            k = struct.unpack_from("<i", d["INDX"])[0] if len(d.get("INDX", b"")) >= 4 else -1
            if 0 <= k < 27 and len(d.get("SKDT", b"")) >= 8:
                skills[k] = list(struct.unpack_from("<ii", d["SKDT"]))
        mult = 2.0
        g = self._subs("GMST", "fNPCbaseMagickaMult")
        if g:
            fl = dict(g[2]).get("FLTV")
            mult = struct.unpack("<f", fl)[0] if fl and len(fl) == 4 else mult
        self._lists = {"races": races, "classes": classes, "factions": factions, "parts": parts, "spells": spells,
                       "items": items, "scripts": scripts, "skills": skills, "magickaMult": mult,
                       "attributeNames": ATTRIBUTES, "skillNames": SKILLS}
        return self._lists

    # --- Writing ------------------------------------------------------------------

    def records(self, edits):
        """The NPC_ records of the edits and the files they need; raises ValueError."""
        out, need = [], {}

        def uses(oid, tag, why):
            w = self.where(tag).get(oid.lower()) if oid else None
            if w:
                need.setdefault(w[2], []).append(why)

        for key, patch in sorted(edits.items()):
            if patch.get("new"):
                f = new_fields(patch)
                if f["id"].lower() != key or not f["id"] or len(f["id"]) > MAX_ID:
                    raise ValueError("A new NPC's id must be 1-%d letters: %r" % (MAX_ID, f["id"]))
                taken = self.find(f["id"])
                if taken:
                    raise ValueError("The new NPC %s has the id of %s in %s: give it another id." % (
                        f["id"], taken[0], taken[1]))
                subs, flags = [], 0
            else:
                w = self.where("NPC_").get(key)
                if w is None:
                    raise ValueError("The NPC %s isn't in the load order any more: its changes can't be saved "
                                     "(reset it in the NPC editor)." % key)
                if not self._ok(w[0].name):
                    raise ValueError("The NPC %s comes from %s, which this plugin can't use." % (key, w[0].name))
                _, flags, subs = esp.record_subs(w[0].path, w[1])
                f = apply(parse(subs), patch)
                need.setdefault(w[0].name, []).append("%s changed" % f["id"])
            for k, tag in (("race", "RACE"), ("class", "CLAS")):
                if not self.where(tag).get((f[k] or "").lower()):
                    raise ValueError("The NPC %s needs a %s: %r isn't one." % (f["id"], k, f[k]))
            for k, tag in (("race", "RACE"), ("class", "CLAS"), ("faction", "FACT"), ("head", "BODY"),
                           ("hair", "BODY"), ("script", "SCPT")):
                uses(f[k], tag, "%s's %s" % (f["id"], k))
            for _, item in f["items"]:
                for tag in ITEM_TAGS:
                    if self.where(tag).get(item.lower()):
                        uses(item, tag, "%s carries %s" % (f["id"], item))
                        break
            for spell in f["spells"]:
                uses(spell, "SPEL", "%s knows %s" % (f["id"], spell))
            rec = esp.record("NPC_", [esp.sub(s, v) for s, v in encode(f, subs)], flags)
            out.append((key, rec))
        return out, need
