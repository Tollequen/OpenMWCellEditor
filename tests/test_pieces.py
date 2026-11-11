import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import esp, pieces  # noqa: E402


def ref(num, oid, pos, turn=0.0):
    return (esp.sub("FRMR", struct.pack("<I", num)) + esp.sub("NAME", esp.zstr(oid))
            + esp.sub("DATA", struct.pack("<6f", *pos, 0, 0, turn)))


class Find(unittest.TestCase):
    def test_laid_out_on_a_grid(self):
        refs = [ref(1, "in_x_room_corner", (0, 0, 0)), ref(2, "in_x_room_side", (256, 0, 0), 1.5707964),
                ref(3, "in_x_shack", (37.5, 911.2, 4)), ref(4, "in_x_rock", (512, 0, 0), 0.3),
                ref(5, "in_x_djamb", (100, 3, 0)), ref(6, "furn_chair", (0, 128, 0))]
        cell = esp.record("CELL", [esp.sub("NAME", esp.zstr("Room")), esp.sub("DATA", struct.pack("<Iii", 1, 0, 0))] + refs)
        path = os.path.join(tempfile.mkdtemp(), "X.esp")
        with open(path, "wb") as f:
            f.write(esp.record("TES3", [esp.sub("HEDR", b"\0" * 300)]) + cell)
        stat = lambda m: ("STAT", m)   # noqa: E731
        objects = {"in_x_room_corner": stat("i\\a.nif"), "in_x_room_side": stat("i\\b.nif"), "in_x_shack": stat("i\\c.nif"),
                   "in_x_rock": stat("i\\d.nif"), "in_x_djamb": stat("i\\e.nif"), "furn_chair": stat("f\\f.nif"),
                   "in_x_door": ("DOOR", "d\\g.nif")}
        self.assertEqual(pieces.find([path], objects), ["in_x_djamb", "in_x_door", "in_x_room_corner", "in_x_room_side"])



class StartInGame(unittest.TestCase):
    def test_start_command(self):
        from celleditor import server
        self.assertEqual(server.start_command("My Room", [10, -20.26, 4]), 'player->positioncell 10.0 -20.3 4.0 0.0 "My Room"')
        self.assertEqual(server.start_command("Seyda Neen (-2, -9)", [-20000, 17000, 300], 90), "player->position -20000.0 17000.0 300.0 90.0")


if __name__ == "__main__":
    unittest.main()


class RoomSets(unittest.TestCase):
    def test_cleaned_and_kept(self):
        from celleditor import server
        old = server.SETTINGS
        server.SETTINGS = None
        try:
            got = server.room_sets([{"name": " Chapel ", "pieces": [{"id": "in_x_room_corner", "pos": [1.234, 2, 3], "rz": 1.5707964},
                                                                    {"id": "", "pos": [0, 0, 0]}]},
                                    {"name": "", "pieces": [{"id": "a", "pos": [0, 0, 0]}]},
                                    {"name": "Table", "room": False, "pieces": [
                                        {"id": "plate", "pos": [0, 0, 30], "rot": [0.1, 0, 2], "scale": 1.5}]}])
            self.assertEqual(got, [{"name": "Chapel",
                                    "pieces": [{"id": "in_x_room_corner", "pos": [1.23, 2.0, 3.0], "rz": 1.5708}]},
                                   {"name": "Table", "pieces": [
                                       {"id": "plate", "pos": [0.0, 0.0, 30.0], "rz": 0.0, "rot": [0.1, 0.0, 2.0], "scale": 1.5}]}])
            self.assertEqual(server.room_sets(), got)
        finally:
            server.SETTINGS = old
