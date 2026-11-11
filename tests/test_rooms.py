import json
import os
import re
import unittest

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "celleditor", "web", "rooms.js")


class Rooms(unittest.TestCase):
    def test_ready_made_rooms(self):
        with open(PATH) as f:
            text = f.read()
        body = text[text.index("[", text.index("ROOMS")):text.rindex("]") + 1]
        body = re.sub(r",(\s*\])", r"\1", re.sub(r"(\w+):", r'"\1":', body))
        rooms = json.loads(body)
        self.assertEqual(len({r["name"] for r in rooms}), len(rooms))
        for r in rooms:
            self.assertRegex(r["style"], r"^(in|ex)_[a-z]+$")
            self.assertTrue(any("door" in p[0] for p in r["pieces"]), r["name"])
            for p in r["pieces"]:
                self.assertEqual(len(p), 5)
                self.assertEqual(p[0], p[0].lower())
                self.assertEqual(p[4] % 90, 0)


if __name__ == "__main__":
    unittest.main()
