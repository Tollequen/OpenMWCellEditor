"""Magic effects of enchantments, worded as the game's tooltips word them."""
import re
import struct

from .esp import cstr, zstr

# Effect index -> GMST id (after "sEffect") and hardcoded flags (components/esm3/loadmgef.cpp, .hpp)
EFFECTS = (
    "WaterBreathing SwiftSwim WaterWalking Shield FireShield LightningShield FrostShield Burden Feather Jump "
    "Levitate SlowFall Lock Open FireDamage ShockDamage FrostDamage DrainAttribute DrainHealth DrainSpellpoints "
    "DrainFatigue DrainSkill DamageAttribute DamageHealth DamageMagicka DamageFatigue DamageSkill Poison "
    "WeaknesstoFire WeaknesstoFrost WeaknesstoShock WeaknesstoMagicka WeaknesstoCommonDisease "
    "WeaknesstoBlightDisease WeaknesstoCorprusDisease WeaknesstoPoison WeaknesstoNormalWeapons DisintegrateWeapon "
    "DisintegrateArmor Invisibility Chameleon Light Sanctuary NightEye Charm Paralyze Silence Blind Sound "
    "CalmHumanoid CalmCreature FrenzyHumanoid FrenzyCreature DemoralizeHumanoid DemoralizeCreature RallyHumanoid "
    "RallyCreature Dispel Soultrap Telekinesis Mark Recall DivineIntervention AlmsiviIntervention DetectAnimal "
    "DetectEnchantment DetectKey SpellAbsorption Reflect CureCommonDisease CureBlightDisease CureCorprusDisease "
    "CurePoison CureParalyzation RestoreAttribute RestoreHealth RestoreSpellPoints RestoreFatigue RestoreSkill "
    "FortifyAttribute FortifyHealth FortifySpellpoints FortifyFatigue FortifySkill FortifyMagickaMultiplier "
    "AbsorbAttribute AbsorbHealth AbsorbSpellPoints AbsorbFatigue AbsorbSkill ResistFire ResistFrost ResistShock "
    "ResistMagicka ResistCommonDisease ResistBlightDisease ResistCorprusDisease ResistPoison ResistNormalWeapons "
    "ResistParalysis RemoveCurse TurnUndead SummonScamp SummonClannfear SummonDaedroth SummonDremora "
    "SummonAncestralGhost SummonSkeletalMinion SummonLeastBonewalker SummonGreaterBonewalker SummonBonelord "
    "SummonWingedTwilight SummonHunger SummonGoldenSaint SummonFlameAtronach SummonFrostAtronach "
    "SummonStormAtronach FortifyAttackBonus CommandCreatures CommandHumanoids BoundDagger BoundLongsword BoundMace "
    "BoundBattleAxe BoundSpear BoundLongbow ExtraSpell BoundCuirass BoundHelm BoundBoots BoundShield BoundGloves "
    "Corpus Vampirism SummonCenturionSphere SunDamage StuntedMagicka SummonFabricant SummonCreature01 "
    "SummonCreature02 SummonCreature03 SummonCreature04 SummonCreature05").split()
FLAGS = (
    4552, 4544, 4552, 4576, 4576, 4576, 4576, 4560, 4544, 4544, 4576, 4544, 70020, 70020, 496, 496, 496, 4562, 4592,
    4560, 4560, 4561, 466, 496, 464, 464, 465, 496, 4560, 4560, 4560, 4560, 4560, 4560, 4560, 4560, 4560, 464, 464,
    4552, 12736, 4544, 4544, 4544, 4480, 4568, 4568, 4560, 4560, 70016, 70016, 70016, 70016, 70016, 70016, 70016,
    70016, 4548, 70072, 4160, 4172, 4172, 4172, 4172, 4160, 4160, 4160, 4544, 4544, 460, 460, 460, 460, 460, 450, 448,
    448, 448, 449, 4546, 4544, 4544, 4544, 4545, 4544, 135570, 131472, 131472, 131472, 135569, 4544, 4544, 4544, 4544,
    4544, 4544, 4544, 4544, 4544, 4544, 448, 70032, 36936, 36936, 36936, 36936, 36936, 36936, 36936, 36936, 36936,
    36936, 36936, 36936, 36936, 36936, 36936, 4544, 4480, 4480, 20552, 20552, 20552, 20552, 20552, 20552, 4488, 20552,
    20552, 20552, 20552, 20552, 4168, 4172, 4168, 64, 4552, 4168, 4168, 4168, 4168, 4168, 4168)
TARGET_SKILL, TARGET_ATTRIBUTE, NO_DURATION, NO_MAGNITUDE, APPLIED_ONCE = 1, 2, 4, 8, 0x1000
VERBS = {"Absorb": "sAbsorb", "Damage": "sDamage", "Drain": "sDrain", "Fortify": "sFortify", "Restore": "sRestore"}
PERCENT = set(range(28, 37)) | set(range(90, 100)) | {40, 47, 57, 68}
FEET = {59, 64, 65, 66}
LEVELS = {118, 119}
TIMES_INT = 84
WORDS = {"spoint": "pt", "spoints": "pts", "spercent": "%", "sfeet": "feet", "sLevel": "Level", "sLevels": "Levels",
         "sTo": "to", "ssecond": "sec", "sseconds": "secs", "sXTimesINT": "x INT", "sfor": "for", "sin": "in",
         "sfootarea": "ft", "sonword": "on", "sRangeSelf": "Self", "sRangeTouch": "Touch", "sRangeTarget": "Target",
         "sAbsorb": "Absorb", "sDamage": "Damage", "sDrain": "Drain", "sFortify": "Fortify", "sRestore": "Restore"}
RANGES = ("sRangeSelf", "sRangeTouch", "sRangeTarget")


class Wording:
    """Effect lines in the load order's own words (text: a game setting's string, or None)."""

    def __init__(self, text, attributes, skills):
        self.text, self.attributes, self.skills = text, attributes, skills
        self._cache = {}

    def word(self, gmst, default=None):
        if gmst not in self._cache:
            self._cache[gmst] = self.text(gmst) or default or WORDS.get(gmst, "")
        return self._cache[gmst]

    def name(self, index, skill, attribute):
        """An effect's name, with the skill or attribute it works on."""
        key = EFFECTS[index]
        flags = FLAGS[index]
        target = (self.skills[skill] if flags & TARGET_SKILL and 0 <= skill < len(self.skills) else
                  self.attributes[attribute] if flags & TARGET_ATTRIBUTE and 0 <= attribute < len(self.attributes)
                  else None)
        if target:
            verb = next((g for v, g in VERBS.items() if key.startswith(v)), None)
            if verb:
                return "%s %s" % (self.word(verb), target)
        base = self.word("sEffect" + key, re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", key))
        return "%s %s" % (base, target) if target else base

    def line(self, enam, constant=False):
        """One ENAM subrecord as the tooltip's line (MWSpellEffect::updateWidgets)."""
        index, skill, attribute, rng, area, duration, low, high = struct.unpack("<hbbiiiii", enam[:24].ljust(24, b"\0"))
        if not 0 <= index < len(EFFECTS):
            return "?"
        flags = FLAGS[index]
        w = self.word
        out = self.name(index, skill, attribute)
        if (low or high) and not flags & NO_MAGNITUDE:
            if index == TIMES_INT:
                out += " %.1f" % (low / 10.0) + ("" if low == high else " %s %.1f" % (w("sTo"), high / 10.0))
                out += w("sXTimesINT")
            else:
                out += " %d" % low + ("" if low == high else " %s %d" % (w("sTo"), high))
                one = low == high and abs(low) == 1
                out += (w("spercent") if index in PERCENT else " " + w("sfeet") if index in FEET
                        else " " + w("sLevel" if one else "sLevels") if index in LEVELS
                        else " " + w("spoint" if one else "spoints"))
        if not constant:
            if not flags & APPLIED_ONCE:
                duration = max(1, duration)
            if duration > 0 and not flags & NO_DURATION:
                out += " %s %d %s" % (w("sfor"), duration, w("ssecond" if duration == 1 else "sseconds"))
            if area > 0:
                out += " %s %d %s" % (w("sin"), area, w("sfootarea"))
            if 0 <= rng < len(RANGES):
                out += " %s %s" % (w("sonword"), w(RANGES[rng]))
        return out


def enchantment(subs, wording):
    """An ENCH record for the lists: its type index, effect lines and (if set by hand) charge."""
    d = dict(subs)
    kind, _, charge, flags = struct.unpack("<iiii", d.get("ENDT", b"")[:16].ljust(16, b"\0"))
    out = {"id": cstr(d.get("NAME", b"")), "kind": kind,
           "effects": [wording.line(v, constant=kind == 3) for s, v in subs if s == "ENAM"]}
    if kind in (1, 2) and not flags & 1:
        out["charge"] = charge
    return out


# --- New enchantments and spells ---------------------------------------------------

ENCHANT_TYPES = ("Cast once", "Cast when strikes", "Cast when used", "Constant effect")
SPELL_TYPES = ("Spell", "Ability", "Blight", "Disease", "Curse", "Power")
RANGE_FLAGS = (0x40, 0x80, 0x100)                   # CastSelf, CastTouch, CastTarget (loadmgef.hpp)
MAX_EFFECTS = 8
MAX_ID = 31
EFFECT_FIELDS = ("effect", "skill", "attribute", "range", "area", "duration", "min", "max")


def effects_info(wording):
    """The effects to choose from: index, name and what they allow."""
    out = []
    for i, key in enumerate(EFFECTS):
        f = FLAGS[i]
        out.append({"index": i, "name": wording.word("sEffect" + key, re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", key)),
                    "skill": bool(f & TARGET_SKILL), "attribute": bool(f & TARGET_ATTRIBUTE),
                    "duration": not f & NO_DURATION, "magnitude": not f & NO_MAGNITUDE,
                    "ranges": [r for r, bit in enumerate(RANGE_FLAGS) if f & bit]})
    return out


def parse_effects(subs):
    """A record's effects as fields."""
    out = []
    for s, v in subs:
        if s == "ENAM" and len(v) >= 24:
            out.append(dict(zip(EFFECT_FIELDS, struct.unpack("<hbbiiiii", v[:24]))))
    return out


def encode_effect(e):
    i = int(e["effect"])
    f = FLAGS[i]
    return struct.pack("<hbbiiiii", i, int(e.get("skill", -1)) if f & TARGET_SKILL else -1,
                       int(e.get("attribute", -1)) if f & TARGET_ATTRIBUTE else -1, int(e.get("range", 0)),
                       max(0, int(e.get("area", 0))), max(0, int(e.get("duration", 0))),
                       max(0, int(e.get("min", 0))), max(0, int(e.get("max", 0))))


def lines(kind, type_, effects, wording):
    """How the game words a new enchantment's or spell's effects."""
    constant = (kind == "ENCH" and type_ == 3) or (kind == "SPEL" and type_ == 1)
    out = []
    for e in effects:
        try:
            out.append(wording.line(encode_effect(e), constant=constant))
        except (KeyError, ValueError, IndexError, struct.error):
            out.append("?")
    return out


def check(m, taken=()):
    """Raise ValueError if a new enchantment or spell can't be written."""
    kind, oid = m.get("kind"), m.get("id") or ""
    what = "enchantment" if kind == "ENCH" else "spell"
    if kind not in ("ENCH", "SPEL"):
        raise ValueError("%s is neither an enchantment nor a spell." % oid)
    if not oid or len(oid) > MAX_ID:
        raise ValueError("A new %s's id must be 1-%d letters: %r" % (what, MAX_ID, oid))
    effects = m.get("effects") or []
    if not 1 <= len(effects) <= MAX_EFFECTS:
        raise ValueError("The %s %s needs 1-%d effects." % (what, oid, MAX_EFFECTS))
    for e in effects:
        i = int(e.get("effect", -1))
        if not 0 <= i < len(EFFECTS):
            raise ValueError("The %s %s has an effect the game doesn't know." % (what, oid))
        constant = (kind == "ENCH" and m.get("type") == 3) or (kind == "SPEL" and m.get("type") == 1)
        if not constant and not FLAGS[i] & RANGE_FLAGS[int(e.get("range", 0))]:
            raise ValueError("In %s, %s can't be cast on that range." % (oid, EFFECTS[i]))
        if int(e.get("min", 0)) > int(e.get("max", 0)):
            raise ValueError("In %s, an effect's least magnitude is more than its most." % oid)
    types = ENCHANT_TYPES if kind == "ENCH" else SPELL_TYPES
    if not 0 <= int(m.get("type", 0)) < len(types):
        raise ValueError("The %s %s has no type." % (what, oid))


def encode(m):
    """A new enchantment's or spell's subrecords."""
    fx = [("ENAM", encode_effect(e)) for e in m["effects"]]
    auto = 1 if m.get("auto", True) else 0
    if m["kind"] == "ENCH":
        return [("NAME", zstr(m["id"])), ("ENDT", struct.pack("<iiii", int(m.get("type", 0)), int(m.get("cost", 0)),
                                                                  int(m.get("charge", 0)), auto))] + fx
    flags = auto | (4 if m.get("always") else 0)
    out = [("NAME", zstr(m["id"]))]
    if m.get("name"):
        out.append(("FNAM", zstr(m["name"])))
    return out + [("SPDT", struct.pack("<iii", int(m.get("type", 0)), int(m.get("cost", 0)), flags))] + fx


def fields(tag, subs):
    """An enchantment's or spell's fields, to start a new one from."""
    d = dict(subs)
    if tag == "ENCH":
        t, cost, charge, flags = struct.unpack("<iiii", d.get("ENDT", b"")[:16].ljust(16, b"\0"))
        return {"kind": "ENCH", "id": cstr(d.get("NAME", b"")), "type": t, "cost": cost, "charge": charge,
                "auto": bool(flags & 1), "effects": parse_effects(subs)}
    t, cost, flags = struct.unpack("<iii", d.get("SPDT", b"")[:12].ljust(12, b"\0"))
    return {"kind": "SPEL", "id": cstr(d.get("NAME", b"")), "name": cstr(d.get("FNAM", b"")), "type": t, "cost": cost,
            "auto": bool(flags & 1), "always": bool(flags & 4), "effects": parse_effects(subs)}
