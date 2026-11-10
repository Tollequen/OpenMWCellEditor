"""New cells in the three kinds of project: python3 -m unittest discover tests"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import cells, esp, loadorder, project, writer   # noqa: E402
from test_plugin import GENERATOR, game, ref_bytes, refs_of      # noqa: E402

ESMTOOL = "/Applications/OpenMW.app/Contents/MacOS/esmtool"
ROOM = {"new": True, "name": "X New Room", "ambient": [10, 20, 30], "sun": [40, 50, 60], "fog": [70, 80, 90],
        "fog_density": 0.5, "water": -12.5, "no_sleep": True, "like_exterior": False}


def edits_with_room(objects=1):
    e = writer.empty_edits()
    e["cells"] = {"x new room": dict(ROOM)}
    e["added"] = [{"uid": "u%d" % i, "cell": "X New Room", "id": "barrel_01", "pos": [i * 50.0, 0.0, 0.0],
                   "rot": [0.0, 0.0, 0.0]} for i in range(objects)]
    return e


def head_of(plugin, name):
    return esp.cell_refs(plugin, name)[0]


class Settings(unittest.TestCase):
    def test_head_round_trip(self):
        head = cells.head(ROOM)
        self.assertEqual([s for s, _ in head], ["NAME", "DATA", "WHGT", "AMBI"])
        self.assertEqual(struct.unpack("<Iii", dict(head)["DATA"]), (1 | 2 | 4, 0, 0))
        self.assertEqual(dict(cells.settings(head), new=True), ROOM)

    def test_like_exterior_has_no_ambient(self):
        head = cells.head(dict(ROOM, like_exterior=True, water=None))
        self.assertEqual([s for s, _ in head], ["NAME", "DATA"])
        self.assertEqual(struct.unpack_from("<I", dict(head)["DATA"])[0], 1 | 4 | 0x80)

    def test_clean(self):
        c = cells.clean({"name": " A ", "ambient": [300, -1, "7"], "fog_density": 9, "water": "x"})
        self.assertEqual((c["name"], c["ambient"], c["sun"], c["fog_density"], c["water"]),
                         ("A", [255, 0, 7], [81, 40, 0], 1.0, None))

    def test_names(self):
        self.assertIsNone(cells.name_error("A Room", ["Other"]))
        for bad in ("", "x" * 64, "A|B", "Somewhere (1, 2)", "A Room"):
            self.assertIsNotNone(cells.name_error(bad, ["a room"]), bad)


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class NewProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Test.json")
        project.create(self.path)
        self.p = project.load(self.path, game())

    def build(self, edits):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits, f)
        return self.p.build()

    def test_cell_with_objects(self):
        self.build(edits_with_room(2))
        self.assertEqual(dict(cells.settings(head_of(self.p.plugin, "X New Room")), new=True), ROOM)
        refs = refs_of(self.p.plugin, "X New Room")
        self.assertEqual([esp.cstr(r["NAME"]) for _, r in refs], ["barrel_01", "barrel_01"])
        self.assertTrue(self.p.can_add("X New Room"))
        if os.path.exists(ESMTOOL):
            out = subprocess.run([ESMTOOL, "dump", "-C", self.p.plugin], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("X New Room", out.stdout)

    def test_empty_cell_is_written(self):
        self.build(edits_with_room(0))
        self.assertEqual(refs_of(self.p.plugin, "X New Room"), [])

    def test_same_numbers_next_build(self):
        self.build(edits_with_room(2))
        first = [n for n, _ in refs_of(self.p.plugin, "X New Room")]
        e = edits_with_room(2)
        e["added"].insert(0, dict(e["added"][0], uid="early"))
        self.build(e)
        self.assertEqual([n for n, _ in refs_of(self.p.plugin, "X New Room")][1:], first)

    def test_refused(self):
        p = self.p
        for change in ({"name": "Seyda Neen, Arrille's Tradehouse"}, {"name": "Other Name"}, {"new": False}):
            e = edits_with_room(0)
            e["cells"]["x new room"].update(change)
            p.edits_override = e
            with self.assertRaises(ValueError, msg=change):
                p.check_new_cells()
        p.edits_override = edits_with_room(0)
        p.check_new_cells()

    def test_shown_with_edits(self):
        self.p.edits_override = edits_with_room(1)
        got, _, keys = self.p.gather_all()
        self.assertEqual([r["key"] for r in got["X New Room"]], ["added|u0"])
        self.assertIn("added|u0", keys)


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class InPlace(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        mw = game().master("Morrowind.esm")
        room = esp.record("CELL", [esp.sub("NAME", esp.zstr("X Test Room")),
                                   esp.sub("DATA", struct.pack("<Iii", 1, 0, 0)), ref_bytes(2, "barrel_01", (0, 0, 0))])
        self.plugin = os.path.join(self.dir, "X.esp")
        with open(self.plugin, "wb") as f:
            f.write(writer.plugin_bytes([room], [mw]))
        self.p = project.load(project.create_in_place(os.path.join(self.dir, "proj"), self.plugin), game())

    def test_new_cell_beside_the_old(self):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits_with_room(1), f)
        self.p.build()
        self.assertEqual([n for n, _ in refs_of(self.plugin, "X Test Room")], [2])
        new = refs_of(self.plugin, "X New Room")
        self.assertEqual(len(new), 1)
        self.assertGreater(new[0][0], 2)
        self.assertEqual(cells.settings(head_of(self.plugin, "X New Room"))["water"], -12.5)
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits_with_room(0), f)
        self.p.build()
        self.assertEqual(refs_of(self.plugin, "X New Room"), [])


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class Generator(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "gen.py"), "w") as f:
            f.write(GENERATOR)
        self.path = os.path.join(self.dir, "Gen.json")
        with open(self.path, "w") as f:
            json.dump({"plugin": "Gen.omwaddon", "generator": "gen.py"}, f)
        self.p = project.load(self.path, game())

    def test_new_cell_after_the_generated_records(self):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits_with_room(1), f)
        self.assertIn("1 new cell", self.p.build())
        self.assertEqual(len(refs_of(self.p.plugin, "X New Room")), 1)
        self.assertEqual(loadorder.masters_of(self.p.plugin), ["Morrowind.esm"])


if __name__ == "__main__":
    unittest.main()
