"""A project's own panel: calls from its page reach Project.api, with the page's edits."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celleditor import project, server  # noqa: E402


class Panel(project.Project):
    panel = {"title": "Stages", "script": "panel.js"}

    def __init__(self):
        pass

    def api(self, name, args, cells):
        if name == "count":
            return {"cells": len(cells()), "x": args.get("x")}
        if name == "bad":
            raise ValueError("not like that")
        raise KeyError(name)


class ProjectCalls(unittest.TestCase):
    def setUp(self):
        self.keep = server.project, server._gather
        self.edits = []
        server.project = Panel()
        server._gather = lambda extra=(), edits=None: (self.edits.append(edits) or {"a": [], "b": []}, {}, {}, set())

    def tearDown(self):
        server.project, server._gather = self.keep

    def call(self, body):
        out, code = server.project_call(body)
        return code, json.loads(out)

    def test_call_gets_args_and_the_pages_edits(self):
        code, out = self.call({"name": "count", "args": {"x": 1}, "edits": {"moved": {"k": {}}}})
        self.assertEqual((code, out), (200, {"cells": 2, "x": 1}))
        self.assertEqual(self.edits, [{"moved": {"k": {}}}])

    def test_errors(self):
        self.assertEqual(self.call({"name": "nope"})[0], 404)
        code, out = self.call({"name": "bad"})
        self.assertEqual((code, out), (400, {"ok": False, "message": "not like that"}))

    def test_defaults(self):
        p = project.Project.__new__(project.Project)
        self.assertIsNone(p.panel)
        self.assertIsNone(p.tag("x"))
        self.assertTrue(p.shown("x", {}))
        self.assertEqual(p.migrate({"added": []}), {"added": []})
        with self.assertRaises(KeyError):
            p.api("x", {}, lambda: {})


if __name__ == "__main__":
    unittest.main()
