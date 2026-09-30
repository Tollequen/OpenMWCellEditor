"""Plugin tests on the game's files (openmw.cfg or CELLEDITOR_DATA): python3 -m unittest discover tests"""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import esp, models, project, writer  # noqa: E402
from celleditor.gamedata import GameData             # noqa: E402

CELL = "Seyda Neen, Arrille's Tradehouse"


def game():
    if os.environ.get("CELLEDITOR_DATA"):
        return GameData([os.environ["CELLEDITOR_DATA"]])
    try:
        return GameData.from_cfg()
    except FileNotFoundError:
        return None


def refs_of(plugin, cell):
    """The (FRMR, subrecords) pairs of a cell's references in a plugin."""
    grid = esp.parse_exterior(cell)
    for tag, _, subs in esp.esm_records(plugin):
        if tag != "CELL":
            continue
        d = dict(esp._split_refs(subs)[0])
        if grid:
            flags, x, y = struct.unpack_from("<Iii", d["DATA"])
            if flags & 1 or (x, y) != grid:
                continue
        elif esp.cstr(subs[0][1]) != cell:
            continue
        return [(n, dict(r)) for n, r in esp._split_refs(subs)[1]]
    return None


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class NewProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Test.json")
        project.create(self.path)
        self.p = project.load(self.path, game())
        self.vanilla = writer.vanilla_refs(self.p.master, CELL)

    def save_edits(self, edits):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits, f)

    def test_move_add_delete_scale(self):
        moved, gone, scaled = self.vanilla[0], self.vanilla[1], self.vanilla[2]
        edits = writer.empty_edits()
        edits["moved"][moved["key"]] = {"pos": [1.0, 2.0, 3.0], "rot": [0.0, 0.0, 1.5]}
        edits["moved"][scaled["key"]] = {"pos": scaled["pos"], "rot": scaled["rot"], "scale": 1.5}
        edits["deleted"].append(gone["key"])
        edits["added"] = [{"uid": "a1", "cell": CELL, "id": "barrel_01", "pos": [10.0, 20.0, 30.0],
                           "rot": [0.0, 0.0, 0.5], "scale": None, "tier": None},
                          {"uid": "a2", "cell": CELL, "id": "chest_small_01", "pos": [0.0, 0.0, 0.0],
                           "rot": [0.0, 0.0, 0.0], "scale": None, "tier": None}]
        self.save_edits(edits)
        self.p.build()

        tes3 = next(esp.esm_records(self.p.plugin))
        self.assertEqual(tes3[0], "TES3")
        head = dict(tes3[2])
        self.assertEqual(esp.cstr(head["MAST"]), "Morrowind.esm")
        self.assertEqual(struct.unpack("<Q", head["DATA"])[0], os.path.getsize(self.p.master))

        refs = dict(refs_of(self.p.plugin, CELL))
        master_ref = lambda r: (1 << 24) | r["vanilla"][0]     # noqa: E731
        self.assertEqual(struct.unpack("<6f", refs[master_ref(moved)]["DATA"])[:3], (1.0, 2.0, 3.0))
        self.assertIn("DELE", refs[master_ref(gone)])
        self.assertAlmostEqual(struct.unpack("<f", refs[master_ref(scaled)]["XSCL"])[0], 1.5)
        self.assertEqual(esp.cstr(refs[1]["NAME"]), "barrel_01")
        self.assertEqual(esp.cstr(refs[2]["NAME"]), "chest_small_01")
        self.assertEqual(len(refs), 5)
        self.assertFalse([n for n, r in refs.items() if n < (1 << 24) and "KNAM" in r])

        edits["deleted"].append("added|a1")
        self.save_edits(edits)
        self.p.build()
        refs = dict(refs_of(self.p.plugin, CELL))
        self.assertNotIn(1, refs)
        self.assertEqual(esp.cstr(refs[2]["NAME"]), "chest_small_01")
        edits["added"].append({"uid": "a3", "cell": CELL, "id": "barrel_01", "pos": [5.0, 5.0, 5.0],
                               "rot": [0.0, 0.0, 0.0], "scale": None, "tier": None})
        self.save_edits(edits)
        self.p.build()
        refs = dict(refs_of(self.p.plugin, CELL))
        self.assertEqual(esp.cstr(refs[3]["NAME"]), "barrel_01")

    def test_lock_key(self):
        """A generated door's lock key is written as KNAM, not the edit key."""
        refs = {"Test cell": [writer.ref("in_hlaalu_door", 0, 0, 0, lock=50, lock_key="my_key"),
                              writer.ref("barrel_01", 1, 0, 0)]}
        writer.apply_edits(refs, {}, writer.empty_edits())
        encoded = writer.encode_refs(refs["Test cell"], writer.RefNums())
        self.assertIn(b"KNAM\x07\x00\x00\x00my_key\x00", encoded[0])
        self.assertNotIn(b"KNAM", encoded[1])

    def test_moves_across_cell_borders(self):
        """Objects moved or added across an exterior border are written into their new cells."""
        _, exteriors = self.p.load.cells()
        src = esp.exterior_key((-2, -9), exteriors[(-2, -9)])
        dst = esp.exterior_key((-2, -10), exteriors[(-2, -10)])
        moved = next(r for r in self.p.master_refs(src) if r["origin"] == "Morrowind.esm")
        edits = writer.empty_edits()
        south = [moved["pos"][0], -10 * 8192 + 4096.0, moved["pos"][2]]
        edits["moved"][moved["key"]] = {"pos": south, "rot": moved["rot"]}
        west = [-3 * 8192 + 100.0, -9 * 8192 + 100.0, 0.0]
        edits["added"] = [{"uid": "x1", "cell": src, "id": "barrel_01", "pos": west, "rot": [0.0, 0.0, 0.0],
                           "scale": None, "tier": None}]
        self.save_edits(edits)
        self.p.build()
        refs = refs_of(self.p.plugin, src)
        frmr = (1 << 24) | moved["vanilla"][0]
        self.assertEqual(struct.unpack("<ii", dict(refs)[frmr]["CNDT"]), (-2, -10))
        self.assertIn(1, dict(refs_of(self.p.plugin, esp.exterior_key((-3, -9), exteriors[(-3, -9)]))))

        from celleditor.loadorder import LoadOrder
        lo = LoadOrder([self.p.master, self.p.plugin])
        keys = lambda cell: {(o, n) for o, n, _ in lo.references(cell)}             # noqa: E731
        self.assertIn(("Morrowind.esm", moved["vanilla"][0]), keys(dst))
        self.assertNotIn(("Morrowind.esm", moved["vanilla"][0]), keys(src))
        self.assertIn((os.path.basename(self.p.plugin), 1), keys(esp.exterior_key((-3, -9), "")))

    def test_door_destination(self):
        """A vanilla load door's new destination is written as DODT, with DNAM for an interior."""
        door = next(r for r in self.vanilla if r["dest"])
        edits = writer.empty_edits()
        edits["doors"][door["key"]] = {"cell": "Seyda Neen, Census and Excise Office", "pos": [1.0, 2.0, 3.0],
                                      "rot": [0.0, 0.0, 1.5]}
        self.save_edits(edits)
        self.p.build()
        r = dict(refs_of(self.p.plugin, CELL))[(1 << 24) | door["vanilla"][0]]
        self.assertEqual(struct.unpack("<6f", r["DODT"]), (1.0, 2.0, 3.0, 0.0, 0.0, 1.5))
        self.assertEqual(esp.cstr(r["DNAM"]), "Seyda Neen, Census and Excise Office")

        edits["doors"][door["key"]] = {"cell": "", "pos": [-15000.0, -70000.0, 100.0], "rot": [0.0, 0.0, 0.0]}
        self.save_edits(edits)
        self.p.build()
        r = dict(refs_of(self.p.plugin, CELL))[(1 << 24) | door["vanilla"][0]]
        self.assertNotIn("DNAM", r)
        self.assertEqual(struct.unpack("<6f", r["DODT"])[:3], (-15000.0, -70000.0, 100.0))

    def test_no_edits_no_cells(self):
        self.p.build()
        records = list(esp.esm_records(self.p.plugin))
        self.assertEqual([r[0] for r in records], ["TES3"])


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class Conflicts(unittest.TestCase):
    def test_other_plugin_changes_the_same_object(self):
        """Another plugin moving the same object is detected, with its load order."""
        dir = tempfile.mkdtemp()
        data = os.path.dirname(game().master("Morrowind.esm"))
        project.create(os.path.join(dir, "Other.json"))
        other = project.load(os.path.join(dir, "Other.json"), GameData([data], content=["Morrowind.esm"]))
        target = writer.vanilla_refs(other.master, CELL)[0]
        edits = writer.empty_edits()
        edits["moved"][target["key"]] = {"pos": [7.0, 7.0, 7.0], "rot": [0.0, 0.0, 0.0]}
        with open(other.file("edits"), "w") as f:
            json.dump(edits, f)
        other.build()

        for order, wins in ((["Morrowind.esm", "Mine.omwaddon", "Other.omwaddon"], True),
                            (["Morrowind.esm", "Other.omwaddon", "Mine.omwaddon"], False)):
            path = os.path.join(dir, "Mine.json")
            project.create(path)
            mine = project.load(path, GameData([data, dir], content=order))
            r = next(x for x in mine.master_refs(CELL) if x["key"] == target["key"])
            self.assertEqual(r["changed_by"], ["Other.omwaddon"])
            self.assertEqual("other.omwaddon" in mine.loads_after, wins)
            self.assertEqual(r["pos"], [7.0, 7.0, 7.0])


def has_expansions(g):
    return g is not None and g.find("Tribunal.esm") and g.find("Bloodmoon.esm")


@unittest.skipIf(not has_expansions(game()), "needs Tribunal.esm and Bloodmoon.esm")
class LoadOrder(unittest.TestCase):
    """Tribunal and Bloodmoon objects are shown, and editing them makes those files masters."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Test.json")
        project.create(self.path)
        with open(self.path) as f:
            config = json.load(f)
        config["content"] = ["Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm"]
        with open(self.path, "w") as f:
            json.dump(config, f)
        self.p = project.load(self.path, game())
        interiors, _ = self.p.load.cells()
        only = lambda name: [c for c in interiors if [f.name for f in self.p.load.defining(c)] == [name]]  # noqa: E731
        self.tribunal_cell = only("Tribunal.esm")[0]
        self.both = [c for c in interiors
                     if [f.name for f in self.p.load.defining(c)] == ["Morrowind.esm", "Tribunal.esm"]]
        self.bloodmoon_object = next(o for o in models.load(self.p.load.paths)[1] if o["file"] == "Bloodmoon.esm")

    def build(self, edits):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits, f)
        self.p._origins = None
        self.p.build()
        tes3 = next(esp.esm_records(self.p.plugin))
        return [esp.cstr(v) for s, v in tes3[2] if s == "MAST"]

    def test_masters_follow_the_edits(self):
        mw = self.p.master_refs(CELL)[0]
        edits = writer.empty_edits()
        edits["moved"][mw["key"]] = {"pos": [1.0, 2.0, 3.0], "rot": [0.0, 0.0, 0.0]}
        self.assertEqual(self.build(edits), ["Morrowind.esm"])

        # FRMR of a master's reference: (master index + 1) << 24 | refnum
        tr = self.p.master_refs(self.tribunal_cell)[0]
        self.assertEqual(tr["origin"], "Tribunal.esm")
        self.assertIn("|vanilla|Tribunal.esm:", tr["key"])
        edits["moved"][tr["key"]] = {"pos": [5.0, 5.0, 5.0], "rot": [0.0, 0.0, 0.0]}
        edits["added"] = [{"uid": "b1", "cell": CELL, "id": self.bloodmoon_object["id"], "pos": [0.0, 0.0, 0.0],
                           "rot": [0.0, 0.0, 0.0], "scale": None, "tier": None}]
        self.assertEqual(self.build(edits), ["Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm"])
        refs = dict(refs_of(self.p.plugin, self.tribunal_cell))
        self.assertIn((2 << 24) | tr["vanilla"][0], refs)
        self.assertEqual(struct.unpack("<6f", refs[(2 << 24) | tr["vanilla"][0]]["DATA"])[:3], (5.0, 5.0, 5.0))
        refs = dict(refs_of(self.p.plugin, CELL))
        self.assertEqual(esp.cstr(refs[1]["NAME"]).lower(), self.bloodmoon_object["id"].lower())

    def test_merged_cells(self):
        """A cell in both Morrowind.esm and Tribunal.esm shows both files' objects."""
        if not self.both:
            self.skipTest("no cell in both files")
        tribunal = self.p.load.file("Tribunal.esm").path
        cells = [c for c in self.both if esp.cell_refs(tribunal, c)[1]]
        if not cells:
            self.skipTest("Tribunal adds objects to no Morrowind.esm cell")
        cell = cells[0]
        merged = self.p.master_refs(cell)
        each = [len(esp.cell_refs(f.path, cell)[1]) for f in self.p.load.defining(cell)]
        self.assertEqual(len(merged), sum(each))
        self.assertEqual({r["origin"] for r in merged}, {"Morrowind.esm", "Tribunal.esm"})


def ref_bytes(num, obj_id, pos, extra=()):
    return (esp.sub("FRMR", struct.pack("<I", num)) + esp.sub("NAME", esp.zstr(obj_id))
            + b"".join(esp.sub(t, v) for t, v in extra) + esp.sub("DATA", struct.pack("<6f", *pos, 0, 0, 0)))


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class InPlace(unittest.TestCase):
    """Editing a plugin in place changes only the edited cells and keeps the rest."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        g = game()
        mw = g.master("Morrowind.esm")
        self.mw_refs = esp.cell_refs(mw, CELL)[1]
        head = esp.cell_refs(mw, CELL)[0]
        self.static = esp.record("STAT", [esp.sub("NAME", esp.zstr("x_test_barrel")),
                                          esp.sub("MODL", esp.zstr("o\\contain_barrel_01.nif"))])
        tradehouse = esp.record("CELL", [esp.sub(t, v) for t, v in head] + [
            ref_bytes(1, "x_test_barrel", (1, 2, 3)),
            ref_bytes((1 << 24) | self.mw_refs[0][0], esp.cstr(dict(self.mw_refs[0][1])["NAME"]), (4, 5, 6))])
        room = esp.record("CELL", [esp.sub("NAME", esp.zstr("X Test Room")),
                                   esp.sub("DATA", struct.pack("<Iii", 1, 0, 0)),
                                   ref_bytes(2, "barrel_01", (0, 0, 0)), ref_bytes(3, "barrel_01", (50, 0, 0))])
        self.cells = [tradehouse, room]
        self.plugin = os.path.join(self.dir, "X.esp")
        with open(self.plugin, "wb") as f:
            f.write(writer.plugin_bytes([self.static] + self.cells, [mw], "a test", "someone"))
        self.path = project.create_in_place(os.path.join(self.dir, "proj"), self.plugin)
        self.p = self.load()

    def load(self):
        return project.load(self.path, game())

    def build(self, edits):
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits, f)
        self.p.build()
        with open(self.plugin, "rb") as f:
            return f.read()

    def key(self, cell, num, file="X.esp"):
        return "%s|vanilla|%s:%d" % (cell, file, num)

    def test_no_edits_same_file(self):
        with open(self.plugin, "rb") as f:
            before = f.read()
        self.assertEqual(self.build(writer.empty_edits()), before)

    def test_edits(self):
        refs = {r["key"]: r for r in self.p.master_refs(CELL)}
        self.assertIn(self.key(CELL, 1), refs)
        self.assertTrue(self.p.can_edit(refs[self.key(CELL, 1)]))
        mw_moved = "%s|vanilla|%d" % (CELL, self.mw_refs[0][0])
        mw_gone = "%s|vanilla|%d" % (CELL, self.mw_refs[1][0])
        self.assertEqual(refs[mw_moved]["pos"], [4, 5, 6])
        edits = writer.empty_edits()
        edits["moved"][self.key(CELL, 1)] = {"pos": [10.0, 20.0, 30.0], "rot": [0.0, 0.0, 1.0], "scale": 1.5}
        edits["moved"][mw_moved] = {"pos": [7.0, 8.0, 9.0], "rot": [0.0, 0.0, 0.0]}
        edits["deleted"] += [mw_gone, self.key("X Test Room", 2)]
        edits["added"] = [{"uid": "n1", "cell": "X Test Room", "id": "chest_small_01", "pos": [5.0, 5.0, 5.0],
                           "rot": [0.0, 0.0, 0.0], "scale": None, "tier": None}]
        data = self.build(edits)
        self.assertIn(self.static, data)
        records = [t for t, _, _ in esp.esm_records(self.plugin)]
        self.assertEqual(records, ["TES3", "STAT", "CELL", "CELL"])
        hedr = dict(next(esp.esm_records(self.plugin))[2])["HEDR"]
        self.assertEqual(struct.unpack_from("<I", hedr, 296)[0], 3)
        self.assertEqual(esp.cstr(hedr[40:296]), "a test")

        th = dict(refs_of(self.plugin, CELL))
        self.assertEqual(struct.unpack("<6f", th[1]["DATA"])[:3], (10.0, 20.0, 30.0))
        self.assertAlmostEqual(struct.unpack("<f", th[1]["XSCL"])[0], 1.5)
        self.assertEqual(struct.unpack("<6f", th[(1 << 24) | self.mw_refs[0][0]]["DATA"])[:3], (7.0, 8.0, 9.0))
        self.assertIn("DELE", th[(1 << 24) | self.mw_refs[1][0]])
        room = dict(refs_of(self.plugin, "X Test Room"))
        self.assertEqual(sorted(room), [3, 4])
        self.assertEqual(esp.cstr(room[4]["NAME"]), "chest_small_01")

    def test_changed_outside(self):
        """A plugin changed elsewhere (OpenMW-CS) is reloaded from the file."""
        edits = writer.empty_edits()
        edits["moved"][self.key(CELL, 1)] = {"pos": [10.0, 20.0, 30.0], "rot": [0.0, 0.0, 0.0]}
        self.build(edits)
        self.assertIsNone(self.load().notice)
        with open(self.plugin, "ab") as f:
            f.write(esp.record("STAT", [esp.sub("NAME", esp.zstr("x_other")), esp.sub("MODL", esp.zstr("a.nif"))]))
        p = self.load()
        self.assertIn("modified outside", p.notice)
        self.assertEqual(p.load_edits()["moved"], {})
        refs = {r["key"]: r for r in p.master_refs(CELL)}
        self.assertEqual(refs[self.key(CELL, 1)]["pos"], [10.0, 20.0, 30.0])

    def test_official_files_refused(self):
        with self.assertRaises(ValueError):
            project.create_in_place(os.path.join(self.dir, "mw"), game().master("Morrowind.esm"))


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class Npcs(unittest.TestCase):
    """NPC edits: whole records under their ids, new NPCs, masters."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Test.json")
        project.create(self.path)
        self.p = project.load(self.path, game())

    def npcs_in(self, plugin):
        return {esp.cstr(subs[0][1]).lower(): (flags, subs) for tag, flags, subs in esp.esm_records(plugin)
                if tag == "NPC_"}

    def test_round_trip(self):
        from celleditor import npc
        mw = game().master("Morrowind.esm")
        for tag, flags, subs in esp.esm_records(mw):
            if tag == "NPC_" and esp.cstr(subs[0][1]) != "player":
                self.assertEqual(npc.encode(npc.parse(subs), subs), subs, esp.cstr(subs[0][1]))

    def test_change_and_new(self):
        from celleditor import npc
        index = self.p.npcs()
        fargoth = index.npc("fargoth")
        self.assertEqual((fargoth["file"], fargoth["fields"]["race"]), ("Morrowind.esm", "Wood Elf"))
        self.assertTrue(fargoth["fields"]["autocalc"])
        new = dict(fargoth["fields"], id="x_test_twin", name="Fargoth's Twin", new=True, autocalc=False,
                   attributes=[40] * 8, skills=[30] * 27, health=50, magicka=60, fatigue=70, items=[[3, "Gold_001"]])
        edits = writer.empty_edits()
        edits["npcs"] = {"fargoth": {"level": 7, "essential": True, "spells": ["hearth heal"]},
                         "x_test_twin": new}
        tribunal = [n for n in index.npcs() if n["file"] == "Tribunal.esm"]
        if tribunal:
            edits["npcs"][tribunal[0]["id"].lower()] = {"gold": 123}
        with open(self.p.file("edits"), "w") as f:
            json.dump(edits, f)
        self.assertIn("NPC", self.p.build())
        got = self.npcs_in(self.p.plugin)
        f = npc.parse(got["fargoth"][1])
        self.assertEqual((f["level"], f["essential"], f["spells"], f["name"]), (7, True, ["hearth heal"], "Fargoth"))
        self.assertTrue(f["autocalc"])
        self.assertEqual(len(dict(got["fargoth"][1])["NPDT"]), 12)
        t = npc.parse(got["x_test_twin"][1])
        self.assertEqual((t["name"], t["skills"][5], t["magicka"], t["items"], t["autocalc"]),
                         ("Fargoth's Twin", 30, 60, [[3, "Gold_001"]], False))
        self.assertEqual(len(dict(got["x_test_twin"][1])["NPDT"]), 52)
        masters = [m.lower() for m in __import__("celleditor.loadorder").loadorder.masters_of(self.p.plugin)]
        self.assertIn("morrowind.esm", masters)
        if tribunal:
            self.assertIn("tribunal.esm", masters)
            self.assertEqual(npc.parse(got[tribunal[0]["id"].lower()][1])["gold"], 123)

    def test_refused(self):
        edits = writer.empty_edits()
        fargoth = self.p.npcs().npc("fargoth")["fields"]
        for bad in ({"fargoth": {"race": "No Such Race"}},
                    {"caius cosades": dict(fargoth, id="caius cosades", new=True)},
                    {"x_test_gone": {"level": 3}}):
            edits["npcs"] = bad
            with open(self.p.file("edits"), "w") as f:
                json.dump(edits, f)
            with self.assertRaises(ValueError):
                self.p.write_plugin()

    def test_in_place(self):
        """A plugin's own NPC is replaced in place; a new one goes before its first cell."""
        from celleditor import npc
        g = game()
        mw = g.master("Morrowind.esm")
        _, flags, subs = esp.record_subs(mw, esp.named_records(mw)["NPC_"]["fargoth"])
        own = dict(npc.parse(subs), id="x_test_own", name="Own One")
        own_rec = esp.record("NPC_", [esp.sub(s_, v) for s_, v in npc.encode(own, subs)], 0x400)
        static = esp.record("STAT", [esp.sub("NAME", esp.zstr("x_test_barrel")),
                                     esp.sub("MODL", esp.zstr("o\\contain_barrel_01.nif"))])
        room = esp.record("CELL", [esp.sub("NAME", esp.zstr("X Test Room")),
                                   esp.sub("DATA", struct.pack("<Iii", 1, 0, 0)), ref_bytes(1, "x_test_own", (0, 0, 0))])
        late = dict(own, id="x_test_late", name="After the cell")
        late_rec = esp.record("NPC_", [esp.sub(s_, v) for s_, v in npc.encode(late, subs)])
        plugin = os.path.join(self.dir, "X.esp")
        with open(plugin, "wb") as f:
            f.write(writer.plugin_bytes([own_rec, static, room, late_rec], [mw]))
        p = project.load(project.create_in_place(os.path.join(self.dir, "proj"), plugin), g)
        self.assertEqual(p.npcs().npc("x_test_own")["file"], "X.esp")
        edits = writer.empty_edits()
        edits["npcs"] = {"x_test_own": {"name": "Renamed"}, "x_test_late": {"level": 9},
                         "x_test_new": dict(own, id="x_test_new", name="New One", new=True)}
        with open(p.file("edits"), "w") as f:
            json.dump(edits, f)
        p.build()
        records = [(t, fl, esp.cstr(s_[0][1])) for t, fl, s_ in esp.esm_records(plugin)]
        self.assertEqual([r[0] for r in records], ["TES3", "NPC_", "STAT", "NPC_", "CELL", "NPC_"])
        self.assertEqual(records[1][1:], (0x400, "x_test_own"))
        self.assertEqual((records[3][2], records[5][2]), ("x_test_new", "x_test_late"))
        got = self.npcs_in(plugin)
        self.assertEqual(npc.parse(got["x_test_own"][1])["name"], "Renamed")
        self.assertEqual(npc.parse(got["x_test_late"][1])["level"], 9)
        hedr = dict(next(esp.esm_records(plugin))[2])["HEDR"]
        self.assertEqual(struct.unpack_from("<I", hedr, 296)[0], 5)


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class Dialogue(unittest.TestCase):
    """Changed, added, moved and deleted responses load in the order the editor showed."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Test.json")
        project.create(self.path)
        self.p = project.load(self.path, game())

    def test_round_trip(self):
        from celleditor import dialogue
        for tag, _, subs in esp.esm_records(game().master("Morrowind.esm")):
            if tag == "INFO":
                d = dict(subs)
                out = dialogue.encode_info(dialogue.parse_info(subs), subs, esp.cstr(d["PNAM"]), esp.cstr(d["NNAM"]))
                self.assertEqual(out, subs, esp.cstr(d["INAM"]))

    def reload(self, plugin, masters):
        from celleditor import dialogue, loadorder
        esp.release()
        return dialogue.Dialogue(loadorder.LoadOrder(masters + [plugin])).topics()

    def test_edits(self):
        dl = self.p.dialogue()
        mine = {t["name"]: t for t in dl.for_actor("fargoth", {})}
        ring = [r["id"] for r in mine["ring"]["responses"]]
        hiding = [r["id"] for r in mine["Fargoth's hiding place"]["responses"]]
        edits = {"ring|" + ring[0]: {"text": "Changed."},
                 "ring|x1": {"new": True, "topic": "ring", "type": 0, "after": ring[-1], "actor": "fargoth",
                             "text": "A new one.", "race": "", "class": "", "faction": "", "cell": "", "pcFaction": "",
                             "sound": "", "disposition": 0, "rank": -1, "sex": -1, "pcRank": -1, "result": "",
                             "quest": None, "conditions": [{"kind": "journal", "name": "MS_Lookout", "op": "3",
                                                            "value": 10, "index": 0}]},
                 "fargoth's hiding place|" + hiding[1]: {"after": ""},
                 "fargoth's hiding place|" + hiding[0]: {"deleted": True},
                 "x test topic|x2": {"new": True, "topic": "X Test Topic", "type": 0, "after": "", "actor": "fargoth",
                                     "text": "Brand new.", "race": "", "class": "", "faction": "", "cell": "",
                                     "pcFaction": "", "sound": "", "disposition": 30, "rank": -1, "sex": -1,
                                     "pcRank": -1, "result": 'AddTopic "ring"', "quest": None, "conditions": []}}
        expected = {k: [i for i in dl.arrange(dl.topics().get(k), dl.by_topic(edits)[k])
                        if not dl.by_topic(edits)[k].get(i, {}).get("deleted")]
                    for k in ("ring", "fargoth's hiding place")}
        e = writer.empty_edits()
        e["dialogue"] = edits
        with open(self.p.file("edits"), "w") as f:
            json.dump(e, f)
        self.assertIn("topic", self.p.build())
        topics = self.reload(self.p.plugin, [game().master("Morrowind.esm")])
        for k, ids in expected.items():
            self.assertEqual(topics[k].ids(), ids, k)
        self.assertEqual(topics["ring"].ids().index("x1"), topics["ring"].ids().index(ring[-1]) + 1)
        self.assertNotIn(hiding[0], topics["fargoth's hiding place"].ids())
        self.assertEqual(topics["fargoth's hiding place"].ids()[0], hiding[1])
        self.assertEqual((topics["x test topic"].ids(), topics["x test topic"].type), (["x2"], 0))
        from celleditor import dialogue
        infos = {esp.cstr(dict(s_)["INAM"]): dialogue.parse_info(s_) for t_, _, s_ in esp.esm_records(self.p.plugin)
                 if t_ == "INFO" and "DELE" not in dict(s_)}
        self.assertEqual(infos[ring[0]]["text"], "Changed.")
        c = infos["x1"]["conditions"][0]
        self.assertEqual((c["rule"], c["value"]), ("04JX3MS_Lookout", 10))
        self.assertEqual(infos["x2"]["result"], 'AddTopic "ring"')

    def test_refused(self):
        e = writer.empty_edits()
        for bad in ({"ring|nope": {"text": "x"}}, {"no such topic|1": {"text": "x"}}):
            e["dialogue"] = bad
            with open(self.p.file("edits"), "w") as f:
                json.dump(e, f)
            with self.assertRaises(ValueError):
                self.p.write_plugin()

    def test_in_place(self):
        """A plugin's own topic is rewritten in place; its other responses stay in order."""
        from celleditor import dialogue
        g = game()
        mw = g.master("Morrowind.esm")

        def info(i, prev, nxt, text):
            f = {"id": i, "text": text, "actor": "fargoth", "race": "", "class": "", "faction": "", "cell": "",
                 "pcFaction": "", "sound": "", "disposition": 0, "rank": -1, "sex": -1, "pcRank": -1,
                 "conditions": [], "result": "", "quest": None, "type": 0}
            return esp.record("INFO", [esp.sub(s_, v) for s_, v in dialogue.encode_info(f, (), prev, nxt)])
        group = esp.record("DIAL", [esp.sub("NAME", esp.zstr("X Own Topic")), esp.sub("DATA", b"\0")]) + \
            info("a", "", "b", "First.") + info("b", "a", "", "Second.")
        static = esp.record("STAT", [esp.sub("NAME", esp.zstr("x_test_barrel")),
                                     esp.sub("MODL", esp.zstr("o\\contain_barrel_01.nif"))])
        plugin = os.path.join(self.dir, "X.esp")
        with open(plugin, "wb") as f:
            f.write(writer.plugin_bytes([group, static], [mw]))
        p = project.load(project.create_in_place(os.path.join(self.dir, "proj"), plugin), g)
        e = writer.empty_edits()
        e["dialogue"] = {"x own topic|a": {"text": "First, changed."},
                         "x own topic|n": {"new": True, "topic": "X Own Topic", "type": 0, "after": "a",
                                           "actor": "fargoth", "text": "Between.", "race": "", "class": "",
                                           "faction": "", "cell": "", "pcFaction": "", "sound": "", "disposition": 0,
                                           "rank": -1, "sex": -1, "pcRank": -1, "result": "", "quest": None,
                                           "conditions": []},
                         "x own topic|b": {"deleted": True}}
        with open(p.file("edits"), "w") as f:
            json.dump(e, f)
        p.build()
        tags = [t_ for t_, _, _ in esp.esm_records(plugin)]
        self.assertEqual(tags, ["TES3", "DIAL", "INFO", "INFO", "STAT"])
        topics = self.reload(plugin, [mw])
        self.assertEqual(topics["x own topic"].ids(), ["a", "n"])


GENERATOR = """from celleditor import dialogue, esp, npc, writer
from celleditor.loadorder import LoadOrder
from celleditor.project import Project as Base


class Project(Base):
    fixed_masters = True

    def build_base(self, path):
        mw = self.game.master("Morrowind.esm")
        w = npc.Index(LoadOrder([mw])).where("NPC_")["fargoth"]
        _, flags, subs = esp.record_subs(w[0].path, w[1])
        own = esp.record("NPC_", [esp.sub("NAME", esp.zstr("x_gen_npc"))] + [esp.sub(s, v) for s, v in subs[1:]])
        f = {"id": "x_gen_0", "text": "Generated.", "actor": "x_gen_npc", "race": "", "class": "", "faction": "",
             "cell": "", "pcFaction": "", "sound": "", "disposition": 0, "rank": -1, "sex": -1, "pcRank": -1,
             "conditions": [], "result": "", "quest": None, "type": 0}
        topic = esp.record("DIAL", [esp.sub("NAME", esp.zstr("X Gen Topic")), esp.sub("DATA", b"\\0")])
        info = esp.record("INFO", [esp.sub(s, v) for s, v in dialogue.encode_info(f, (), "", "")])
        writer.write_file(path, writer.plugin_bytes([own, topic, info], [mw]))
"""


class Generator(unittest.TestCase):
    """A generator script that builds the plugin: the editor writes NPC and dialogue edits into it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "gen.py"), "w") as f:
            f.write(GENERATOR)
        self.path = os.path.join(self.dir, "Gen.json")
        with open(self.path, "w") as f:
            json.dump({"plugin": "Gen.omwaddon", "generator": "gen.py"}, f)
        self.p = project.load(self.path, game())

    def test_no_edits_as_built(self):
        self.assertTrue(self.p.can_edit_npcs)
        self.p.build()
        with open(self.p.plugin, "rb") as a, open(self.p.generated_plugin, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_edits(self):
        from celleditor import dialogue, loadorder, npc
        index = self.p.npcs()
        self.assertTrue(index.npc("x_gen_npc")["editable"])
        tribunal = [n for n in index.npcs() if n["file"] == "Tribunal.esm"]
        if tribunal:
            self.assertFalse(tribunal[0]["editable"])
        e = writer.empty_edits()
        e["npcs"] = {"x_gen_npc": {"gold": 77}, "fargoth": {"level": 9}}
        e["dialogue"] = {"x gen topic|x_gen_0": {"text": "Changed."}}
        with open(self.p.file("edits"), "w") as f:
            json.dump(e, f)
        self.assertIn("2 NPCs, 1 topic", self.p.build())
        mw = game().master("Morrowind.esm")
        load = loadorder.LoadOrder([mw, self.p.plugin])
        got = npc.Index(load)
        self.assertEqual((got.npc("x_gen_npc")["fields"]["gold"], got.npc("fargoth")["fields"]["level"]), (77, 9))
        topic = [t for t in dialogue.Dialogue(load).for_actor("x_gen_npc", {}) if t["key"] == "x gen topic"][0]
        self.assertEqual([r["fields"]["text"] for r in topic["responses"]], ["Changed."])
        self.assertEqual(loadorder.masters_of(self.p.plugin), ["Morrowind.esm"])

class Cfg(unittest.TestCase):
    """Adding a new plugin to openmw.cfg."""

    def test_add_to_cfg(self):
        from celleditor.gamedata import add_to_cfg, read_cfg
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "openmw.cfg")
        with open(cfg, "w") as f:
            f.write('fallback=x,y\ndata="/games/Data Files"\ncontent=Morrowind.esm\nencoding=win1252\n')
        folder = os.path.join(d, 'My "House" & co')
        self.assertTrue(add_to_cfg(cfg, folder, "My House.omwaddon"))
        with open(cfg) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[2], 'data="%s"' % folder.replace("&", "&&").replace('"', '&"'))
        self.assertEqual(lines[-1], "content=My House.omwaddon")
        self.assertEqual(read_cfg(cfg)["data"], ["/games/Data Files", folder])
        self.assertFalse(add_to_cfg(cfg, folder, "My House.omwaddon"))
        self.assertTrue(os.path.exists(cfg + ".celleditor-backup"))


@unittest.skipIf(game() is None, "no game data (openmw.cfg or CELLEDITOR_DATA)")
class Launcher(unittest.TestCase):
    """Projects set up on the start page: their own Data Files and plugins."""

    def setUp(self):
        from celleditor import server, settings
        self.dir = tempfile.mkdtemp()
        os.environ["CELLEDITOR_PROJECTS"] = os.path.join(self.dir, "projects")
        server.SETTINGS = settings.Settings(os.path.join(self.dir, "settings.json"))
        self.server = server
        self.data = os.path.dirname(game().master("Morrowind.esm"))
        self.official = [os.path.join(self.data, n) for n in ("Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm")
                         if os.path.exists(os.path.join(self.data, n))]

    def tearDown(self):
        os.environ.pop("CELLEDITOR_PROJECTS", None)

    def test_order(self):
        from celleditor import launcher
        p = lambda n, *m: {"name": n, "masters": list(m)}          # noqa: E731
        got = launcher.order([p("B.esp", "A.esm"), p("Morrowind.esm"), p("A.esm", "Morrowind.esm")])
        self.assertEqual([x["name"] for x in got], ["Morrowind.esm", "A.esm", "B.esp"])

    def test_new_plugin(self):
        out = os.path.join(self.dir, "mods")
        os.makedirs(out)
        made = self.server.create_project({"dataFiles": self.data, "mode": "new", "newName": "My Test",
                                           "newFolder": out, "loadOrder": self.official})
        self.server.open_project(made["path"])
        p = self.server.project
        self.assertTrue(os.path.exists(os.path.join(out, "My Test.omwaddon")))
        self.assertEqual([f.name for f in p.load.files], [os.path.basename(x) for x in self.official])
        self.assertTrue(p.path.startswith(os.path.join(self.dir, "projects")))
        self.assertEqual(self.server.SETTINGS.get("last_data_files"), self.data)

    def test_edit_plugin(self):
        t = InPlace("test_edits")
        t.setUp()
        made = self.server.create_project({"dataFiles": self.data, "mode": "edit", "plugin": t.plugin, "loadOrder": []})
        self.server.open_project(made["path"])
        p = self.server.project
        self.assertTrue(p.in_place)
        self.assertEqual([f.name for f in p.load.files], ["Morrowind.esm", "X.esp"])
        refs = {r["key"] for r in p.master_refs(CELL)}
        self.assertIn(CELL + "|vanilla|X.esp:1", refs)
        page = self.server.project_page(p.path)
        self.assertEqual([x["name"] for x in page["plugins"]], ["Morrowind.esm", "X.esp"])
        self.assertEqual(page["blocked"], [])

    def test_delete_project(self):
        """Deleting a project removes the editor's folder for it, never the content file."""
        out = os.path.join(self.dir, "mods")
        os.makedirs(out)
        made = self.server.create_project({"dataFiles": self.data, "mode": "new", "newName": "Gone",
                                           "newFolder": out, "loadOrder": self.official})
        self.server.open_project(made["path"])
        plugin = os.path.join(out, "Gone.omwaddon")
        self.assertTrue(self.server.project_page(made["path"])["deletable"])
        self.server.delete_project(made["path"])
        self.assertFalse(os.path.exists(os.path.dirname(made["path"])))
        self.assertTrue(os.path.exists(plugin))
        self.assertIsNone(self.server.project)
        self.assertNotIn(made["path"], [p["path"] for p in self.server.home_info()["projects"]])
        mine = os.path.join(self.dir, "mymod", "celleditor.json")
        project.create(mine)
        with self.assertRaises(ValueError):
            self.server.delete_project(mine)
        self.assertTrue(os.path.exists(mine))

    def test_masters_elsewhere(self):
        """Adding TR_Mainland.esm finds Tamriel_Data.esm in another folder and loads the archives."""
        from celleditor import launcher
        mw = self.official[0]
        td_dir, tr_dir = os.path.join(self.dir, "Tamriel_Data"), os.path.join(self.dir, "TR")
        os.makedirs(td_dir)
        os.makedirs(tr_dir)
        td = os.path.join(td_dir, "Tamriel_Data.esm")
        tr = os.path.join(tr_dir, "TR_Mainland.esm")
        writer.write_file(td, writer.plugin_bytes([], [mw]))
        writer.write_file(tr, writer.plugin_bytes([], [mw, td]))
        for n in ("Tamriel_Data.bsa", "PT_Data.bsa"):
            open(os.path.join(td_dir, n), "wb").close()
        real = launcher.cfg_data_dirs
        try:
            launcher.cfg_data_dirs = lambda: []
            r = launcher.resolve(tr, self.official, self.data)
            self.assertEqual([p["name"] for p in r["add"]], ["TR_Mainland.esm"])
            self.assertEqual(r["missing"], ["Tamriel_Data.esm"])
            launcher.cfg_data_dirs = lambda: [self.data, td_dir, tr_dir]
            r = launcher.resolve(tr, self.official, self.data)
            self.assertEqual([p["name"] for p in r["add"]], ["Tamriel_Data.esm", "TR_Mainland.esm"])
            self.assertEqual(r["missing"], [])
        finally:
            launcher.cfg_data_dirs = real
        game = launcher.game_for({"data_files": self.data, "load_order": self.official + [td, tr]})
        self.assertIn("Tamriel_Data.bsa", game.archive_names)
        self.assertIn("PT_Data.bsa", game.archive_names)
        self.assertEqual(game.content[-2:], ["Tamriel_Data.esm", "TR_Mainland.esm"])

    def test_standalone_and_new_masters(self):
        """A mod is read-only in a standalone project; otherwise editing it makes it a master."""
        from celleditor import launcher
        t = InPlace("test_edits")
        t.setUp()
        out = os.path.join(self.dir, "mods")
        os.makedirs(out)
        made = self.server.create_project({"dataFiles": self.data, "mode": "new", "newName": "Alone", "newFolder": out,
                                           "loadOrder": self.official + [t.plugin], "standalone": True})
        p = project.load(made["path"], game())
        barrel = next(r for r in p.master_refs(CELL) if r["origin"] == "X.esp")
        self.assertFalse(p.can_edit(barrel))
        self.assertNotIn("x.esp", p.usable_files())
        self.server.save_project(made["path"], self.data, self.official + [t.plugin], standalone=False)
        p = project.load(made["path"], game())
        self.assertTrue(p.can_edit(barrel))
        edits = writer.empty_edits()
        edits["moved"][barrel["key"]] = {"pos": [9.0, 9.0, 9.0], "rot": [0.0, 0.0, 0.0]}
        with open(p.file("edits"), "w") as f:
            json.dump(edits, f)
        message = p.build()
        self.assertIn("Now it also needs X.esp.", message)
        self.assertNotIn("x_test_barrel", message)
        self.assertEqual(p.new_masters[0][0], "X.esp")
        self.assertIn("x_test_barrel changed in " + CELL, p.new_masters[0][1])

    def test_openmw_base_order(self):
        """A project on OpenMW's load order shows its content files and folders as they are now."""
        from celleditor import launcher
        mod = os.path.join(self.dir, "SomeMod")
        os.makedirs(mod)
        writer.write_file(os.path.join(mod, "Some.esp"), writer.plugin_bytes([], [self.official[0]]))
        real = launcher.openmw_setup
        try:
            launcher.openmw_setup = lambda: ([self.data, mod], [os.path.basename(x) for x in self.official] + ["Some.esp"],
                                             ["Morrowind.bsa"])
            game_ = launcher.game_for({"data_files": self.data, "load_order": self.official, "base_order": "openmw"})
            self.assertEqual(game_.content[-1], "Some.esp")
            self.assertIn(mod, game_.data_dirs)
            self.assertIn(mod, launcher.folders_of({"data_files": self.data, "base_order": "openmw"}, self.dir))
        finally:
            launcher.openmw_setup = real

    def test_mod_folder(self):
        """A mod folder adds only its meshes, textures and archives."""
        from celleditor import launcher
        mod = os.path.join(self.dir, "Better Barrels")
        os.makedirs(os.path.join(mod, "meshes", "o"))
        with open(os.path.join(mod, "meshes", "o", "contain_barrel_01.nif"), "wb") as f:
            f.write(b"x")
        with self.assertRaises(ValueError):
            launcher.folder_info(self.dir)
        game = launcher.game_for({"data_files": self.data, "load_order": self.official, "folders": [mod]})
        self.assertEqual(game.data_dirs[-1], mod)
        self.assertEqual(game.read("meshes\\o\\contain_barrel_01.nif"), b"x")
        self.assertEqual(game.content, [os.path.basename(x) for x in self.official])

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "only where chmod 0 refuses reading")
    def test_refused_folder(self):
        from celleditor import launcher
        locked = os.path.join(self.dir, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0)
        try:
            self.assertTrue(launcher.browse(locked, "folder")["denied"])
            parent = launcher.browse(self.dir, "folder")
            self.assertNotIn("locked", parent["dirs"])
            self.assertEqual(parent["hidden"], ["locked"])
            self.assertEqual(launcher.blocked([os.path.join(locked, "x", "y")]), [locked])
        finally:
            os.chmod(locked, 0o755)
            launcher.DENIED.discard(locked)


class Phone(unittest.TestCase):
    """Phone access: the QR code, the access code's limit, and what keeps the editor running."""

    def test_qr(self):
        from celleditor import qr
        # Error correction codewords of the QR standard's 1-M "HELLO WORLD" example
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.rs_remainder(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])
        self.assertEqual(len(qr.encode("http://192.168.100.100:65535/?code=ABCDEF")), 29)
        self.assertIn("<svg", qr.svg("x"))
        with self.assertRaises(ValueError):
            qr.encode("x" * 200)

    def test_code_tries(self):
        from celleditor import server
        server.LAN, server.ACCESS_CODE = True, "ABCDEF"
        h = server.Handler.__new__(server.Handler)
        h.client_address = ("10.1.2.3", 5000)
        server._wrong_codes.clear()
        self.assertTrue(h.try_code("abcdef"))
        for _ in range(server.TRIES):
            self.assertFalse(h.try_code("XXXXXX"))
        self.assertFalse(h.try_code("ABCDEF"))
        self.assertTrue(h.locked_out())
        server._wrong_codes["10.1.2.3"][1] -= server.LOCKOUT + 1
        self.assertTrue(h.try_code("ABCDEF"))
        server._wrong_codes.clear()
        server.SETTINGS = None
        server.new_code()
        self.assertNotEqual(server.ACCESS_CODE, "ABCDEF")
        self.assertFalse(h.try_code("ABCDEF"))
        self.assertTrue(h.try_code(server.ACCESS_CODE))
        server._wrong_codes.clear()

    def test_phones_dont_keep_it_running(self):
        import time
        from celleditor import server
        server.AUTO_STOP = True
        server._pages.clear()
        server._started[0] = time.time()
        server._last_here[0] = 0.0
        server.alive("computer", here=True)
        self.assertIsNone(server.alive("phone", here=False))
        server.alive("computer", closing=True, here=True)
        left = server.alive("phone", here=False)
        self.assertTrue(server.PHONE_GRACE - 2 <= left <= server.PHONE_GRACE)
        server.alive("phone", closing=True, here=False)
        self.assertEqual(server._grace(), server.CLOSE_GRACE)
        server._pages.clear()
        server.AUTO_STOP = False


class Live(unittest.TestCase):
    """Editing on several devices: the editor's edits, pages' changes, drafts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CELLEDITOR_SETTINGS"] = os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        del os.environ["CELLEDITOR_SETTINGS"]

    def test_entries(self):
        from celleditor import live
        e = {"moved": {"c|a|1": {"pos": [1, 2, 3], "rot": [0, 0, 1]}}, "deleted": ["c|b|2"], "replaced": {"c|d|3": "x"},
             "added": [{"uid": "u1", "cell": "c", "id": "y", "pos": [0, 0, 0], "rot": [0, 0, 0]}],
             "attached": {"added|u1": "c|d|3"}, "doors": {}, "groups": {"g1": ["c|a|1", "added|u1"]},
             "npcs": {"fargoth": {"level": 5}}, "dialogue": {"ring|123": {"text": "Hello"}}}
        self.assertEqual(live.edits_of(live.entries(e)), e)
        self.assertIn("npcs|fargoth", live.entries(e))
        self.assertIn("dialogue|ring|123", live.entries(e))
        self.assertIn("moved|c|a|1", live.entries(e))

    def test_pages_and_draft(self):
        from celleditor import live
        path = os.path.join(self.tmp, "p.json")
        saved = {"moved": {}, "deleted": ["c|b|2"], "replaced": {}, "added": [], "attached": {}, "doors": {}, "groups": {}}
        lv = live.Live()
        lv.start(path, saved)
        qa, hello = lv.join("a")
        qb, _ = lv.join("b", here=False)
        self.assertEqual(hello["edits"]["deleted"], ["c|b|2"])
        self.assertFalse(lv.apply("a", "other.json", []))
        self.assertTrue(lv.apply("a", path, [{"id": "moved|c|a|1", "v": {"pos": [1, 2, 3], "rot": [0, 0, 0]}},
                                             {"id": "deleted|c|b|2", "v": None}]))
        ev = qb.get_nowait()
        self.assertEqual((ev["type"], ev["from"]), ("ops", "a"))
        self.assertEqual(qa.get_nowait()["type"], "ops")
        e = lv.edits()
        self.assertEqual((list(e["moved"]), e["deleted"]), (["c|a|1"], []))
        lv.where("b", {"label": "iPhone", "cell": "c", "pos": [0, 0, 0]})
        self.assertEqual(qa.get_nowait()["label"], "iPhone")
        lv.end_remote()
        self.assertIsNone(qb.get_nowait())
        self.assertEqual(qa.get_nowait()["type"], "gone")
        lv.close()
        lv2 = live.Live()
        lv2.start(path, saved)
        self.assertEqual(list(lv2.state()["draft"]["edits"]["moved"]), ["c|a|1"])
        lv2.apply("x", path, [{"id": "deleted|c|z|9", "v": True}])
        self.assertIsNone(lv2.state()["draft"])
        lv2.was_saved(lv2.edits())
        self.assertIsNone(lv2._read_draft())


class Desktop(unittest.TestCase):
    def test_launcher_opens_the_editor(self):
        import webbrowser
        from celleditor import server
        from celleditor.live import LIVE
        opened = []
        old = server.PORT, webbrowser.open, dict(LIVE.pages), set(LIVE.remote)

        def restore():
            server.PORT, webbrowser.open = old[0], old[1]
            LIVE.pages.clear()
            LIVE.pages.update(old[2])
            LIVE.remote.clear()
            LIVE.remote.update(old[3])
        self.addCleanup(restore)
        server.PORT = 1
        webbrowser.open = opened.append
        LIVE.pages.clear()
        LIVE.remote.clear()
        self.assertTrue(server.open_editor(switched=True)["opened"])
        LIVE.pages["phone"] = None
        LIVE.remote.add("phone")
        self.assertTrue(server.open_editor(switched=True)["opened"])
        LIVE.pages["tab"] = None
        self.assertFalse(server.open_editor(switched=True)["opened"])
        self.assertTrue(server.open_editor(switched=False)["opened"])
        self.assertEqual(len(opened), 3)
        self.assertFalse(server.desktop.show())


class StrayBytes(unittest.TestCase):
    """Content files with stray trailing bytes are read as OpenMW reads them."""

    def test_read(self):
        def sub(tag, data):
            return tag.encode() + struct.pack("<I", len(data)) + data

        def rec(tag, body):
            return tag.encode() + struct.pack("<III", len(body), 0, 0) + body
        head = rec("TES3", sub("HEDR", struct.pack("<fi", 1.3, 0) + b"\0" * 288 + struct.pack("<i", 2)))
        cell = rec("CELL", sub("NAME", b"Stray Room\0") + sub("DATA", struct.pack("<Iii", 1, 0, 0)))
        npc = rec("NPC_", sub("NAME", b"someone\0") + b"\0" * 6)
        path = os.path.join(tempfile.mkdtemp(), "Stray.esp")
        with open(path, "wb") as f:
            f.write(head + cell + npc + b"\0" * 4)
        tags = [(t, [s_ for s_, _ in subs]) for t, _, subs in esp.esm_records(path)]
        self.assertEqual(tags, [("TES3", ["HEDR"]), ("CELL", ["NAME", "DATA"]), ("NPC_", ["NAME"])])
        self.assertIn("Stray Room", esp.cell_index(path)[0])
        esp.release()


if __name__ == "__main__":
    unittest.main()
