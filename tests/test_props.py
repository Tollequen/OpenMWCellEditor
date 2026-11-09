"""Ownership, lock and trap of placed objects: read, changed and written in OpenMW's order."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import writer  # noqa: E402
from celleditor.esp import zstr  # noqa: E402

DATA = ("DATA", struct.pack("<6f", 1, 2, 3, 0, 0, 0))


def master_ref(subs):
    r = writer.ref("chest", 1, 2, 3)
    r["vanilla"] = (7, [("NAME", zstr("chest"))] + subs + [DATA])
    r["key"] = "c|vanilla|7"
    return r


class Props(unittest.TestCase):
    def test_read_from_a_master_reference(self):
        r = master_ref([("ANAM", zstr("fargoth")), ("FLTV", struct.pack("<i", 30)), ("KNAM", zstr("key_a"))])
        self.assertEqual(writer.props_of(r), {"owner": "fargoth", "lock": 30, "key": "key_a"})

    def test_override_puts_subrecords_in_order(self):
        r = master_ref([("UNAM", b"\0"), ("ANAM", zstr("fargoth"))])
        writer.apply_props(r, {"owner": None, "faction": "Thieves Guild", "rank": 2, "lock": 50, "trap": "fire"})
        names = [s for s, _ in writer._with_props(r["vanilla"][1], r["props"])]
        self.assertEqual(names, ["NAME", "UNAM", "CNAM", "INDX", "FLTV", "TNAM", "DATA"])

    def test_clearing_and_keys(self):
        r = master_ref([("CNAM", zstr("Mages Guild")), ("INDX", struct.pack("<i", 3))])
        writer.apply_props(r, {"faction": ""})
        self.assertEqual(r["props"], {})                       # the rank goes with the faction
        writer.apply_props(r, {"key": "key_a"})
        self.assertEqual(r["props"], {"key": "key_a", "lock": 0})  # a key alone locks it
        writer.apply_props(r, {"key": None, "lock": 0})
        self.assertEqual(r["props"], {})

    def test_edits_mark_a_master_reference_changed(self):
        r = master_ref([])
        edits = dict(writer.empty_edits(), props={"c|vanilla|7": {"owner": "fargoth"}})
        writer.apply_edits({}, {"c": [r]}, edits)
        self.assertTrue(r["changed"])
        self.assertIn(b"ANAM\x08\x00\x00\x00fargoth\x00", writer.encode_vanilla_override(r))

    def test_new_references_write_them_around_the_door(self):
        r = writer.ref("door", 0, 0, 0, dest=("Balmora", (1, 2, 3), 0.0))
        r["key"] = "added|u1"
        writer.apply_props(r, {"owner": "fargoth", "lock": 20, "trap": "fire"})
        entry = writer.encode_refs([r], writer.RefNums())[0]
        order = [entry.index(t) for t in (b"ANAM", b"DODT", b"DNAM", b"FLTV", b"TNAM", b"DATA")]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
