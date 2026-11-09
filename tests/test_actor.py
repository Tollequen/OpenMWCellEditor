"""NPC bodies: which parts an NPC shows, and parts placed on a skeleton."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import actor, nif  # noqa: E402


def z(s):
    return s.encode() + b"\0"


def body(oid, model, part, race, female=False, kind=0):
    return oid, [("NAME", z(oid)), ("MODL", z(model)), ("FNAM", z(race)),
                 ("BYDT", bytes([part, 0, 1 if female else 0, kind]))]


def race(oid, beast=False, height=(1.0, 1.0), weight=(1.0, 1.0)):
    radt = bytes(120) + struct.pack("<4fi", height[0], height[1], weight[0], weight[1], 2 if beast else 1)
    return oid, [("NAME", z(oid)), ("RADT", radt)]


def item(oid, tag_data, parts):
    subs = [("NAME", z(oid)), tag_data]
    for slot, male, female in parts:
        subs.append(("INDX", bytes([slot])))
        if male:
            subs.append(("BNAM", z(male)))
        if female:
            subs.append(("CNAM", z(female)))
    return oid, subs


def armor(oid, kind, rating, parts):
    return item(oid, ("AODT", struct.pack("<ifiiii", kind, 1.0, 10, 100, 0, rating)), parts)


def clothing(oid, kind, value, parts):
    return item(oid, ("CTDT", struct.pack("<ifHH", kind, 1.0, value, 0)), parts)


class FakeBodies(actor.Bodies):
    def __init__(self, records):
        super().__init__(None)
        self.records = records

    def _records(self, tag):
        return iter(self.records.get(tag, []))


RECORDS = {
    "BODY": [body("b_m_chest", "b\\m_chest.nif", 3, "dark elf"),
             body("b_m_foot", "b\\m_foot.nif", 9, "dark elf"),
             body("b_m_upperleg", "b\\m_leg.nif", 12, "dark elf"),
             body("b_f_chest", "b\\f_chest.nif", 3, "dark elf", female=True),
             body("b_m_hand.1st", "b\\m_hand.1st.nif", 5, "dark elf"),
             body("b_head", "b\\head.nif", 0, "dark elf"),
             body("b_hair", "b\\hair.nif", 1, "dark elf"),
             body("c_robe", "c\\robe.nif", 3, "", kind=1),
             body("a_helm", "a\\helm.nif", 0, "", kind=2),
             body("a_boot", "a\\boot.nif", 9, "", kind=2),
             body("c_shirt", "c\\shirt.nif", 3, "", kind=1),
             body("c_shirt2", "c\\shirt2.nif", 3, "", kind=1)],
    "RACE": [race("dark elf"), race("khajiit", beast=True), race("nord", height=(1.06, 1.0), weight=(1.25, 1.0))],
    "CLOT": [clothing("robe", 4, 10, [(3, "c_robe", "")]),
             clothing("cheap shirt", 2, 5, [(3, "c_shirt", "")]),
             clothing("fine shirt", 2, 50, [(3, "c_shirt2", "")])],
    "ARMO": [armor("helm", 0, 10, [(0, "a_helm", ""), (1, "", "")]),
             armor("open helm", 0, 5, [(1, "a_helm", "")]),
             armor("boots", 5, 10, [(15, "a_boot", ""), (16, "a_boot", "")])],
}

NPC = {"race": "Dark Elf", "female": False, "head": "b_head", "hair": "b_hair", "items": []}


class Parts(unittest.TestCase):
    def setUp(self):
        self.b = FakeBodies(RECORDS)

    def parts(self, **kw):
        return {actor.PART_BONES[k] + (" (hair)" if k == actor.HAIR else ""): m
                for k, m in self.b.parts(dict(NPC, **kw)).items()}

    def test_race_parts_head_and_hair(self):
        p = self.parts()
        self.assertEqual(p["Chest"], "b\\m_chest.nif")
        self.assertEqual((p["Right Foot"], p["Left Foot"]), ("b\\m_foot.nif", "b\\m_foot.nif"))
        self.assertEqual((p["Head"], p["Head (hair)"]), ("b\\head.nif", "b\\hair.nif"))
        self.assertNotIn("Right Hand", p)                     # first-person parts aren't used

    def test_female_falls_back_to_male_parts(self):
        p = self.parts(female=True)
        self.assertEqual(p["Chest"], "b\\f_chest.nif")
        self.assertEqual(p["Right Foot"], "b\\m_foot.nif")

    def test_robe_hides_legs_and_helmet_hides_hair(self):
        p = self.parts(items=[[1, "robe"], [1, "helm"]])
        self.assertEqual(p["Chest"], "c\\robe.nif")
        self.assertNotIn("Right Upper Leg", p)
        self.assertEqual(p["Head"], "a\\helm.nif")
        self.assertNotIn("Head (hair)", p)

    def test_better_clothing_wins(self):
        self.assertEqual(self.parts(items=[[1, "cheap shirt"], [1, "fine shirt"]])["Chest"], "c\\shirt2.nif")
        self.assertEqual(self.parts(items=[[1, "fine shirt"], [1, "cheap shirt"]])["Chest"], "c\\shirt2.nif")

    def test_beasts_wear_no_boots(self):
        self.assertEqual(self.parts(items=[[1, "boots"]])["Right Foot"], "a\\boot.nif")
        self.assertNotIn("Right Foot", self.parts(race="khajiit", items=[[1, "boots"]]))

    def test_outfit_says_why_items_are_not_worn(self):
        o = self.b.outfit(dict(NPC, race="khajiit", items=[[1, "boots"], [1, "cheap shirt"], [1, "fine shirt"]]))
        self.assertEqual(o["slots"], {"shirt": "fine shirt"})
        self.assertEqual(o["notWorn"], {"boots": {"beast": "feet"}, "cheap shirt": {"instead": "fine shirt"}})

    def test_beasts_wear_open_helmets_only(self):
        self.assertEqual(self.parts(race="khajiit", items=[[1, "open helm"]])["Head (hair)"], "a\\helm.nif")
        self.assertEqual(self.parts(race="khajiit", items=[[1, "helm"]])["Head (hair)"], "b\\hair.nif")


def node(name, children=(), t=(0.0, 0.0, 0.0)):
    return {"type": b"NiNode", "name": name, "flags": 0, "t": t, "R": nif.I3, "s": 1.0, "props": [],
            "children": list(children)}


class Placing(unittest.TestCase):
    def test_skeleton_bones_in_its_space(self):
        blocks = {0: node(b"base_anim.nif", [1], t=(5.0, 5.0, 5.0)), 1: node(b"Bip01", [2], t=(0.0, 0.0, 10.0)),
                  2: node(b"Left Foot", t=(3.0, 0.0, 0.0))}
        bones = nif.skeleton(blocks)
        self.assertEqual(bones["left foot"][1], (3.0, 0.0, 10.0))  # the root's own transform is dropped

    def test_rigid_part_hangs_on_its_bone_mirrored_on_the_left(self):
        bones = {"left foot": (nif.I3, (3.0, 0.0, 10.0))}
        blocks = {0: node(b"foot", [1]),
                  1: {"type": b"NiTriShape", "name": b"Tri foot", "flags": 0, "t": (0.0, 0.0, 0.0), "R": nif.I3,
                      "s": 1.0, "props": [], "data": 2, "skin": -1},
                  2: {"type": b"NiTriShapeData", "verts": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
                      "normals": None, "colors": None, "uv": None, "tris": (0, 1, 2)}}
        sh = nif.part_shapes(blocks, bones, "Left Foot", "left foot")[0]
        self.assertEqual(sh["pos"][:3], [2.0, 0.0, 10.0])
        self.assertEqual(list(sh["index"]), [0, 2, 1])


if __name__ == "__main__":
    unittest.main()
