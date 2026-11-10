"""Items: read and written again unchanged, edited, and made from scratch."""
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import esp, items, loadorder, npc, writer  # noqa: E402
from celleditor.esp import zstr  # noqa: E402

SWORD = [("NAME", zstr("iron_sword")), ("MODL", zstr("w\\iron.nif")), ("FNAM", zstr("Iron Sword")),
         ("WPDT", struct.pack("<fihHffHBBBBBBi", 20.0, 15, 1, 400, 1.25, 1.0, 50, 1, 8, 2, 9, 1, 3, 0)),
         ("ITEX", zstr("w\\tx_iron.tga"))]
SHIRT = [("NAME", zstr("shirt_a")), ("MODL", zstr("c\\shirt.nif")), ("FNAM", zstr("Shirt")),
         ("CTDT", struct.pack("<ifHH", 2, 1.0, 5, 10)), ("ITEX", zstr("c\\tx_shirt.tga")),
         ("INDX", bytes([3])), ("BNAM", b"c_m_shirt"), ("CNAM", b"c_f_shirt")]


class Items(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        recs = [esp.record("WEAP", [esp.sub(s, v) for s, v in SWORD]),
                esp.record("CLOT", [esp.sub(s, v) for s, v in SHIRT]),
                esp.record("SCPT", [esp.sub("SCHD", b"myscript".ljust(52, b"\0"))]),
                esp.record("BODY", [esp.sub("NAME", zstr("c_m_shirt")), esp.sub("BYDT", bytes([3, 0, 0, 1]))])]
        self.esm = os.path.join(self.dir, "Base.esm")
        with open(self.esm, "wb") as f:
            f.write(writer.plugin_bytes(recs, [], master=True))
        self.it = items.Items(npc.Index(loadorder.LoadOrder([self.esm])))

    def tearDown(self):
        esp.release()
        shutil.rmtree(self.dir)

    def test_other_kinds_are_written_and_read_back(self):
        potion = {"new": True, "kind": "ALCH", "id": "my_potion", "name": "My Potion", "model": "m\\p.nif",
                  "icon": "m\\p.tga", "weight": 0.5, "value": 20, "auto": False,
                  "effects": [{"effect": 75, "skill": -1, "attribute": -1, "range": 0, "area": 0, "duration": 5,
                               "min": 2, "max": 4}]}
        light = {"new": True, "kind": "LIGH", "id": "my_lamp", "name": "My Lamp", "model": "l\\l.nif", "radius": 200,
                 "color": [10, 20, 30], "lflags": 3, "time": 600}
        edits = {"my_potion": potion, "my_lamp": light,
                 "my_rock": {"new": True, "kind": "STAT", "id": "my_rock", "model": "x\\rock.nif"},
                 "my_door": {"new": True, "kind": "DOOR", "id": "my_door", "name": "Door", "model": "d\\d.nif"},
                 "my_root": {"new": True, "kind": "INGR", "id": "my_root", "name": "Root", "model": "n\\r.nif",
                             "effects": [{"effect": 75, "skill": -1, "attribute": -1}]}}
        recs, _ = self.it.records(edits)
        self.assertEqual([k for k, _ in recs], [("DOOR", "my_door"), ("LIGH", "my_lamp"), ("ALCH", "my_potion"),
                                                ("STAT", "my_rock"), ("INGR", "my_root")])
        out = os.path.join(self.dir, "Out.esp")
        with open(out, "wb") as f:
            f.write(writer.plugin_bytes([rec for _, rec in recs], [self.esm]))
        read = [(tag, subs) for tag, _, subs in esp.esm_records(out) if tag in items.KINDS]
        for ((kind, key), _), (tag, subs) in zip(recs, read):
            self.assertEqual(tag, kind)
            back = items.parse(kind, [(s_, bytes(v)) for s_, v in subs])
            for k, v in edits[key].items():
                if k != "new":
                    self.assertEqual(back[k], v, (key, k))
        self.assertEqual(items.encode(items.parse("STAT", [("NAME", zstr("a")), ("MODL", zstr("b.nif"))])),
                         [("NAME", zstr("a")), ("MODL", zstr("b.nif"))])
        with self.assertRaises(ValueError):
            self.it.records({"p": {"new": True, "kind": "ALCH", "id": "p", "model": "m.nif", "effects": []}})

    def test_unchanged_records_come_back_byte_for_byte(self):
        for kind, subs in (("WEAP", SWORD), ("CLOT", SHIRT)):
            self.assertEqual(items.encode(items.parse(kind, subs)), subs)

    def test_read_and_edit(self):
        sword = self.it.get("Iron_Sword")
        self.assertEqual((sword["kind"], sword["slash_max"], sword["speed"]), ("WEAP", 9, 1.25))
        recs, need = self.it.records({"iron_sword": {"name": "Rusty Sword", "value": 3}})
        self.assertIn(b"FNAM\x0c\x00\x00\x00Rusty Sword\x00", recs[0][1])
        self.assertEqual(sorted(need), ["Base.esm"])
        self.assertEqual(self.it.get("shirt_a")["parts"], [[3, "c_m_shirt", "c_f_shirt"]])

    def test_new_item(self):
        oid = self.it.free_id("iron_sword")
        self.assertEqual(oid, "iron_sword_01")
        patch = {"new": True, "kind": "MISC", "id": "gem_key", "name": "Gem Key", "model": "m\\key.nif",
                 "mflags": 1, "script": "myscript"}
        recs, need = self.it.records({"gem_key": patch})
        (tag, key), rec = recs[0]
        self.assertEqual((tag, key), ("MISC", "gem_key"))
        self.assertIn(b"MCDT\x0c\x00\x00\x00", rec)
        self.assertIn(b"SCRI\x09\x00\x00\x00myscript\x00", rec)
        self.assertEqual(list(need), ["Base.esm"])                   # for the script
        with self.assertRaises(ValueError):
            self.it.records({"gem_key": dict(patch, model="")})
        with self.assertRaises(ValueError):
            self.it.records({"iron_sword": dict(patch, id="iron_sword")})   # the id is taken


if __name__ == "__main__":
    unittest.main()
