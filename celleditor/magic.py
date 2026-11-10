"""Magic effects of enchantments, worded as the game's tooltips word them."""
import re
import struct

from .esp import cstr

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
