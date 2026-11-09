"""NPC bodies as OpenMW puts them together: race parts, head, hair and worn clothing and armour on the skeleton."""
import struct

from . import esp, nif
from .esp import cstr

# Attach bone of each part slot (ESM::PartReferenceType; apps/openmw/mwrender/npcanimation.cpp)
PART_BONES = ("Head", "Head", "Neck", "Chest", "Groin", "Groin", "Right Hand", "Left Hand", "Right Wrist",
              "Left Wrist", "Shield Bone", "Right Forearm", "Left Forearm", "Right Upper Arm", "Left Upper Arm",
              "Right Foot", "Left Foot", "Right Ankle", "Left Ankle", "Right Knee", "Left Knee", "Right Upper Leg",
              "Left Upper Leg", "Right Clavicle", "Left Clavicle", "Weapon Bone", "Tail")
HEAD, HAIR, SKIRT, SHIELD, WEAPON = 0, 1, 5, 10, 25

# A race's skin part (BYDT part) -> the slots it fills
RACE_SLOTS = {2: (2,), 3: (3,), 4: (4,), 5: (6, 7), 6: (8, 9), 7: (11, 12), 8: (13, 14), 9: (15, 16),
              10: (17, 18), 11: (19, 20), 12: (21, 22), 14: (26,)}

# Equipment slots, in the order OpenMW adds their parts, with their base priority
SLOT_ORDER = (("robe", 11), ("skirt", 3), ("helmet", 0), ("cuirass", 0), ("greaves", 0), ("lpauldron", 0),
              ("rpauldron", 0), ("boots", 0), ("lgauntlet", 0), ("rgauntlet", 0), ("shirt", 0), ("pants", 0),
              ("carriedleft", 0))
ARMOR_SLOTS = ("helmet", "cuirass", "lpauldron", "rpauldron", "greaves", "boots", "lgauntlet", "rgauntlet",
               "carriedleft", "lgauntlet", "rgauntlet")
CLOTHING_SLOTS = (("pants",), ("boots",), ("shirt",), ("belt",), ("robe",), ("rgauntlet",), ("lgauntlet",),
                  ("skirt",), ("lring", "rring"), ("amulet",))
ROBE_HIDES = (4, 5, 21, 22, 13, 14, 19, 20, 11, 12, 3)
SKIRT_HIDES = (4, 21, 22)
BEAST = 2                                                     # RADT flag
BEAST_CANT = (0, 15, 16)                                      # head and feet (mwclass/armor.cpp canBeEquipped)

SKELETONS = {"male": "base_anim.nif", "female": "base_anim_female.nif", "beast": "base_animkna.nif"}


class Bodies:
    """The load order's body parts, races, clothing and armour, read once."""

    def __init__(self, index):
        self.index = index
        self._body = self._race = self._armor = self._clothing = None
        self._nifs, self._bones = {}, {}

    def _records(self, tag):
        for oid, (f, off, _) in self.index.where(tag).items():
            _, _, subs = esp.record_subs(f.path, off)
            if not any(s == "DELE" for s, _ in subs):
                yield oid, subs

    @staticmethod
    def _parts(subs):
        """[(slot, male part id, female part id)] of a clothing or armour record."""
        out = []
        for s, v in subs:
            if s == "INDX":
                out.append([v[0], "", ""])
            elif s in ("BNAM", "CNAM") and out:
                out[-1][1 if s == "BNAM" else 2] = cstr(v).lower()
        return [tuple(p) for p in out]

    def body(self):
        """{id: (model, part, flags, type, race)} (lower case ids)."""
        if self._body is None:
            self._body = {}
            for oid, subs in self._records("BODY"):
                d = dict(subs)
                b = d.get("BYDT", b"").ljust(4, b"\0")
                self._body[oid] = (cstr(d.get("MODL", b"")), b[0], b[2], b[3], cstr(d.get("FNAM", b"")).lower())
        return self._body

    def race(self, rid):
        """(flags, (male height, female height), (male weight, female weight)) of a race, or None."""
        if self._race is None:
            self._race = {}
            for oid, subs in self._records("RACE"):
                radt = dict(subs).get("RADT", b"").ljust(140, b"\0")
                h = struct.unpack_from("<2f", radt, 120)
                w = struct.unpack_from("<2f", radt, 128)
                self._race[oid] = (struct.unpack_from("<i", radt, 136)[0], h, w)
        return self._race.get((rid or "").lower())

    def armor(self):
        """{id: (type, rating, parts)}."""
        if self._armor is None:
            self._armor = {}
            for oid, subs in self._records("ARMO"):
                a = dict(subs).get("AODT", b"").ljust(24, b"\0")
                t, _, _, _, _, rating = struct.unpack_from("<ifiiii", a)
                self._armor[oid] = (t, rating, self._parts(subs))
        return self._armor

    def clothing(self):
        """{id: (type, value, parts)}."""
        if self._clothing is None:
            self._clothing = {}
            for oid, subs in self._records("CLOT"):
                c = dict(subs).get("CTDT", b"").ljust(12, b"\0")
                t, _, value = struct.unpack_from("<ifH", c)
                self._clothing[oid] = (t, value, self._parts(subs))
        return self._clothing

    # --- Putting an NPC together ------------------------------------------------------------

    def race_parts(self, race, female):
        """{slot: model} of a race's skin parts (female falls back to male, as in getBodyParts)."""
        race = (race or "").lower()
        out, fallback = {}, {}
        for oid, (model, part, flags, kind, r) in self.body().items():
            if kind != 0 or r != race or flags & 2 or part not in RACE_SLOTS or oid.endswith("1st"):
                continue
            target = out if bool(flags & 1) == female else fallback if female else None
            if target is None:
                continue
            for slot in RACE_SLOTS[part]:
                target.setdefault(slot, model)
        fallback.update(out)
        return fallback

    def equipped(self, items, beast):
        """{slot: ("armor"|"clothing", record)} worn from an inventory, like InventoryStore::autoEquipArmor
        (armour by its base rating, not the wearer's skills); beasts wear nothing with a head or foot part."""
        armor, clothing = self.armor(), self.clothing()
        slots = {}
        for _, iid in items:
            iid = iid.lower()
            if iid in armor:
                kind, rec = "armor", armor[iid]
                t = rec[0]
                if t < 0 or t >= len(ARMOR_SLOTS):
                    continue
                cands = (ARMOR_SLOTS[t],)
            elif iid in clothing:
                kind, rec = "clothing", clothing[iid]
                t = rec[0]
                if t < 0 or t >= len(CLOTHING_SLOTS):
                    continue
                cands = CLOTHING_SLOTS[t]
            else:
                continue
            if beast and any(p[0] in BEAST_CANT for p in rec[2]):    # closed helmets, boots and shoes
                continue
            for slot in cands:
                old = slots.get(slot)
                if old:
                    if kind == "clothing":
                        if old[0] != "clothing" or rec[1] <= old[1][1]:
                            continue
                    elif old[0] == "armor":
                        if old[1][0] == rec[0]:
                            if rec[1] <= old[1][1]:
                                continue
                        elif old[1][0] < rec[0]:
                            continue
                slots[slot] = (kind, rec)
                break
        return slots

    def parts(self, npc):
        """{slot: model} an NPC shows (npc: the NPC page's fields), as NpcAnimation::updateParts adds them."""
        body = self.body()
        race = self.race(npc.get("race"))
        beast = bool(race and race[0] & BEAST)
        female = bool(npc.get("female"))
        prio, model = [0] * len(PART_BONES), [None] * len(PART_BONES)

        def add(slot, p, m):
            if p > prio[slot]:
                prio[slot], model[slot] = p, m

        def reserve(slot, p):
            if p > prio[slot]:
                prio[slot], model[slot] = p, None

        worn = self.equipped(npc.get("items") or [], beast)
        for slot, base in SLOT_ORDER:
            item = worn.get(slot)
            if not item:
                continue
            if slot == "helmet":
                prio[HAIR], model[HAIR] = 0, None
            kind, rec = item
            p = ((base + 1) << 1) + (1 if kind == "armor" else 0)
            for part, male, fem in rec[2]:
                if part >= len(PART_BONES):
                    continue
                bp = body.get(fem) if female and fem else None
                bp = bp or (body.get(male) if male else None)
                if bp:
                    add(part, p, bp[0])
                else:
                    reserve(part, p)
            for hide in ROBE_HIDES if slot == "robe" else SKIRT_HIDES if slot == "skirt" else ():
                reserve(hide, p)
        head = body.get((npc.get("head") or "").lower())
        hair = body.get((npc.get("hair") or "").lower())
        if prio[HEAD] < 1 and head:
            add(HEAD, 1, head[0])
        if prio[HAIR] < 1 and prio[HEAD] <= 1 and hair:
            add(HAIR, 1, hair[0])
        for slot, m in self.race_parts(npc.get("race"), female).items():
            if prio[slot] < 1:
                add(slot, 1, m)
        return {k: m for k, m in enumerate(model) if m and k != WEAPON}

    def shapes(self, npc, read):
        """An NPC's shapes, its feet at the origin, scaled by its race; read(mesh path) -> bytes or None."""
        race = self.race(npc.get("race"))
        female = bool(npc.get("female"))
        kind = "beast" if race and race[0] & BEAST else "female" if female else "male"
        if kind not in self._bones:
            data = read(SKELETONS[kind])
            self._bones[kind] = nif.skeleton(data) if data is not None else None
        bones = self._bones[kind]
        if bones is None:
            return []
        out = []
        for slot, path in sorted(self.parts(npc).items()):
            try:
                key = path.lower()
                if key not in self._nifs:
                    if len(self._nifs) > 400:
                        self._nifs.clear()
                    d = read(path)
                    self._nifs[key] = nif.parse(d) if d is not None else None
                if self._nifs[key] is None:
                    continue
                out += nif.part_shapes(self._nifs[key], bones, PART_BONES[slot],
                                       "hair" if slot == HAIR else PART_BONES[slot])
            except Exception as e:                          # one unreadable part doesn't hide the NPC
                print("Couldn't read the body part %s (%s: %s)." % (path, type(e).__name__, e), flush=True)
        if race:
            h, w = race[1][1 if female else 0], race[2][1 if female else 0]
            if (h, w) != (1.0, 1.0) and h > 0 and w > 0:
                for sh in out:
                    p = sh["pos"]
                    sh["pos"] = [v * (h if k % 3 == 2 else w) for k, v in enumerate(p)]
        return out
