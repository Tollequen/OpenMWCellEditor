"""The MCP endpoint's protocol, the geometry under its tools, and assistant changes in the live session."""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import geometry, mcp  # noqa: E402
from celleditor.live import Live      # noqa: E402


def rpc(method, params=None, mid=1):
    code, out = mcp.handle_body(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method,
                                            "params": params or {}}).encode())
    return code, json.loads(out) if out else None


class Protocol(unittest.TestCase):
    def test_initialize(self):
        code, r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "claude-code", "version": "1"}})
        self.assertEqual(code, 200)
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(mcp.client["name"], "Claude")
        code, r = rpc("initialize", {"protocolVersion": "1999-01-01", "clientInfo": {"name": "x"}})
        self.assertIn(r["result"]["protocolVersion"], mcp.PROTOCOLS)

    def test_notification_gets_no_body(self):
        code, out = mcp.handle_body(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode())
        self.assertEqual((code, out), (202, None))

    def test_tools(self):
        _, r = rpc("tools/list")
        names = [t["name"] for t in r["result"]["tools"]]
        self.assertIn("place_objects", names)
        for t in r["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_errors(self):
        self.assertEqual(rpc("nope")[1]["error"]["code"], -32601)
        self.assertEqual(mcp.handle_body(b"{")[0], 400)
        _, r = rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertTrue(r["result"]["isError"])


class Geometry(unittest.TestCase):
    def box(self):
        """A 100-unit cube from z 0 to 100, as a Shape."""
        sh = geometry.Shape(None)
        sh.verts = [(x, y, z) for x in (-50, 50) for y in (-50, 50) for z in (0, 100)]
        quads = [(0, 2, 6, 4), (1, 3, 7, 5), (0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6)]
        sh.tris = [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]
        sh.lo, sh.hi = (-50, -50, 0), (50, 50, 100)
        return sh

    def test_rotation_is_clockwise(self):
        # a heading of 90 degrees turns the object's +y (its front) to the east
        p = geometry.to_world({"pos": (0, 0, 0), "rot": (0, 0, math.pi / 2)}, (0, 1, 0))
        self.assertAlmostEqual(p[0], 1.0)
        self.assertAlmostEqual(p[1], 0.0)

    def test_rotation_order_is_openmws(self):
        # OpenMW turns about z first, then x: front (+y), heading 90 then 90 about x, ends up east, not down
        p = geometry.to_world({"pos": (0, 0, 0), "rot": (math.pi / 2, 0, math.pi / 2)}, (0, 1, 0))
        self.assertAlmostEqual(p[0], 1.0)
        self.assertAlmostEqual(p[2], 0.0)

    def test_raycast(self):
        r = {"pos": (1000, 0, 0), "rot": (0, 0, 0.3), "scale": 2.0}
        h = geometry.raycast([(r, self.box())], (1000, 0, 500), (0, 0, -1))
        self.assertAlmostEqual(h["point"][2], 200.0, places=3)
        self.assertAlmostEqual(h["normal"][2], 1.0, places=3)
        self.assertIsNone(geometry.raycast([(r, self.box())], (0, 0, 500), (0, 0, -1)))

    def test_shape_root_keeps_its_transform(self):
        # OpenMW drops a root node's transform but keeps a root shape's: the crate is 32 below its origin
        from celleditor import nif
        from celleditor.gamedata import GameData
        try:
            data = GameData.from_cfg().read("meshes\\o\\contain_crate_01.nif")
        except FileNotFoundError:
            data = None
        if not data:
            self.skipTest("no game data")
        zs = [v for s in nif.shapes(data) for v in s["pos"][2::3]]
        self.assertEqual((round(min(zs)), round(max(zs))), (-32, 32))

    def test_terrain(self):
        h = geometry.terrain_hit(lambda x, y: x * 0.5, (0, 0, 100), (1, 0, 0))
        self.assertAlmostEqual(h["point"][0], 200.0, delta=0.1)


class AssistantChanges(unittest.TestCase):
    def test_undo_step_and_label_reach_pages(self):
        live = Live()
        live.path, live.ents = "/p.json", {}
        q, _ = live.join("page")
        self.assertTrue(live.apply("mcp", "/p.json", [{"id": "deleted|k", "v": True}],
                                   {"undo": True, "label": "Claude: x"}))
        ev = q.get_nowait()
        self.assertEqual((ev["type"], ev["from"], ev["undo"], ev["label"]), ("ops", "mcp", True, "Claude: x"))
        self.assertEqual(live.unsaved(), 1)

    def test_ask_and_answer(self):
        import threading
        live = Live()
        q, _ = live.join("page")
        live.where("page", {"cell": "c", "pos": [0, 0, 0]})
        self.assertEqual([p for p, _ in live.pages_here()], ["page"])

        def page():
            ev = q.get(timeout=5)
            live.answer(ev["req"], {"image": "data:image/jpeg;base64,AA=="})
        threading.Thread(target=page).start()
        self.assertEqual(live.ask("page", {"what": "view"}, 5)["image"][:10], "data:image")
        self.assertIsNone(live.ask("gone", {"what": "view"}, 0.1))


if __name__ == "__main__":
    unittest.main()
