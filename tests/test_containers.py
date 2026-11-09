"""Container contents: read, changed, copied for one placed container, and written."""
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import containers, esp, loadorder, npc, writer  # noqa: E402
from celleditor.esp import zstr  # noqa: E402


def npco(n, iid):
    return esp.sub("NPCO", struct.pack("<i", n) + iid.encode().ljust(32, b"\0"))


class Contents(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        chest = esp.record("CONT", [esp.sub("NAME", zstr("chest_a")), esp.sub("MODL", zstr("o\\chest.nif")),
                                    esp.sub("FNAM", zstr("Chest")), esp.sub("CNDT", struct.pack("<f", 300)),
                                    esp.sub("FLAG", struct.pack("<i", 8)), npco(2, "gold_001")])
        gold = esp.record("MISC", [esp.sub("NAME", zstr("gold_001")), esp.sub("MODL", zstr("m\\gold.nif"))])
        self.esm = os.path.join(self.dir, "Base.esm")
        with open(self.esm, "wb") as f:
            f.write(writer.plugin_bytes([chest, gold], [], master=True))
        self.c = containers.Containers(npc.Index(loadorder.LoadOrder([self.esm])))

    def tearDown(self):
        esp.release()
        shutil.rmtree(self.dir)

    def test_read_and_change(self):
        c = self.c.get("Chest_A")
        self.assertEqual((c["contents"], c["respawn"], c["file"]), ([[2, "gold_001"]], False, "Base.esm"))
        c = self.c.get("chest_a", {"chest_a": {"contents": [[5, "gold_001"], [-1, "gold_001"]], "respawn": True}})
        self.assertEqual((c["contents"][1], c["respawn"]), ([-1, "gold_001"], True))

    def test_written_record(self):
        recs, need = self.c.records({"chest_a": {"contents": [[7, "gold_001"]], "respawn": True}})
        body = recs[0][1]
        self.assertIn(b"FLAG\x04\x00\x00\x00\x0a\x00\x00\x00", body)            # respawn added to the old 8
        self.assertIn(b"NPCO\x24\x00\x00\x00\x07\x00\x00\x00gold_001", body)
        self.assertEqual(body.count(b"NPCO"), 1)
        self.assertEqual(sorted(need), ["Base.esm"])

    def test_copy_for_one_container(self):
        new = self.c.free_id("chest_a")
        self.assertEqual(new, "chest_a_01")
        patch = {"new": True, "copy_of": "chest_a", "id": new, "contents": [[1, "gold_001"]]}
        self.assertEqual(self.c.get(new, {new: patch})["copy_of"], "chest_a")
        recs, _ = self.c.records({new: patch})
        self.assertIn(b"NAME\x0b\x00\x00\x00chest_a_01\x00", recs[0][1])
        with self.assertRaises(ValueError):
            self.c.records({"chest_a": dict(patch, id="chest_a")})        # a copy can't take a used id


if __name__ == "__main__":
    unittest.main()
