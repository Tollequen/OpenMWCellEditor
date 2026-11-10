import struct
import unittest

from celleditor import magic
from celleditor.npc import ATTRIBUTES, SKILLS


def enam(effect, skill=-1, attribute=-1, rng=0, area=0, duration=0, low=0, high=0):
    return struct.pack("<hbbiiiii", effect, skill, attribute, rng, area, duration, low, high)


class EffectLines(unittest.TestCase):
    def setUp(self):
        self.w = magic.Wording(lambda name: None, ATTRIBUTES, SKILLS)

    def test_damage_with_range_area_and_time(self):
        self.assertEqual(self.w.line(enam(14, rng=2, area=3, duration=5, low=5, high=15)),
                         "Fire Damage 5 to 15 pts for 5 secs in 3 ft on Target")

    def test_skill_and_attribute_targets(self):
        self.assertEqual(self.w.line(enam(83, skill=5, low=5, high=5), constant=True), "Fortify Long Blade 5 pts")
        self.assertEqual(self.w.line(enam(74, attribute=0, rng=0, duration=1, low=1, high=1)),
                         "Restore Strength 1 pt for 1 sec on Self")

    def test_percent_and_no_magnitude(self):
        self.assertEqual(self.w.line(enam(90, duration=10, low=20, high=40)), "Resist Fire 20 to 40% for 10 secs on Self")
        self.assertEqual(self.w.line(enam(39, duration=60, low=1, high=1)), "Invisibility for 60 secs on Self")

    def test_game_settings_win(self):
        w = magic.Wording({"sEffectFireDamage": "Feuerschaden", "spoints": "Pkt"}.get, ATTRIBUTES, SKILLS)
        self.assertEqual(w.line(enam(14, low=2, high=2), constant=True), "Feuerschaden 2 Pkt")

    def test_enchantment(self):
        subs = [("NAME", b"x_en\0"), ("ENDT", struct.pack("<iiii", 1, 5, 340, 0)), ("ENAM", enam(14, rng=1, low=1, high=1))]
        self.assertEqual(magic.enchantment(subs, self.w),
                         {"id": "x_en", "kind": 1, "charge": 340, "effects": ["Fire Damage 1 pt for 1 sec on Touch"]})


if __name__ == "__main__":
    unittest.main()


class NewMagic(unittest.TestCase):
    def setUp(self):
        self.w = magic.Wording(lambda name: None, ATTRIBUTES, SKILLS)

    def test_round_trip(self):
        m = {"kind": "SPEL", "id": "x_spark", "name": "Spark", "type": 0, "cost": 5, "auto": False, "always": True,
             "effects": [{"effect": 15, "skill": -1, "attribute": -1, "range": 2, "area": 5, "duration": 1, "min": 2, "max": 9}]}
        magic.check(m)
        got = magic.fields("SPEL", magic.encode(m))
        self.assertEqual(got, dict(m, kind="SPEL"))
        self.assertEqual(magic.lines("SPEL", 0, m["effects"], self.w), ["Shock Damage 2 to 9 pts for 1 sec in 5 ft on Target"])

    def test_constant_enchantment(self):
        m = {"kind": "ENCH", "id": "x_en", "type": 3, "auto": True,
             "effects": [{"effect": 83, "skill": 5, "attribute": -1, "range": 0, "min": 5, "max": 5}]}
        magic.check(m)
        self.assertEqual(magic.lines("ENCH", 3, m["effects"], self.w), ["Fortify Long Blade 5 pts"])
        self.assertEqual(magic.fields("ENCH", magic.encode(m))["effects"][0]["skill"], 5)

    def test_refused(self):
        good = {"kind": "SPEL", "id": "x", "type": 0, "effects": [{"effect": 14, "range": 2, "min": 1, "max": 2}]}
        for bad in ({"id": ""}, {"effects": []}, {"effects": [{"effect": 999}]},
                    {"effects": [{"effect": 14, "range": 2, "min": 5, "max": 2}]},
                    {"effects": [{"effect": 60, "range": 2}]}, {"kind": "X"}):
            with self.assertRaises(ValueError, msg=bad):
                magic.check(dict(good, **bad))
        magic.check(good)
