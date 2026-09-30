"""Saved versions of a project's layout edits: one JSON file per save, in order."""
import datetime
import json
import os

from .writer import empty_edits


def states(e):
    """{key: state} of an edits file."""
    out = {}
    for k, m in e["moved"].items():
        out.setdefault(k, {})["moved"] = m
    for k in e["deleted"]:
        out.setdefault(k, {})["deleted"] = True
    for k, v in e["replaced"].items():
        out.setdefault(k, {})["replaced"] = v
    for a in e["added"]:
        out.setdefault("added|" + a["uid"], {})["added"] = a
    for k, parent in e.get("attached", {}).items():
        out.setdefault(k, {})["attached"] = parent
    for k, d in e.get("doors", {}).items():
        out.setdefault(k, {})["door"] = d
    for g, keys in e.get("groups", {}).items():
        for k in keys:
            out.setdefault(k, {})["group"] = g
    for k, v in e.get("npcs", {}).items():
        out["npcs|" + k] = {"npc": v}
    for k, v in e.get("dialogue", {}).items():
        out["dialogue|" + k] = {"response": v}
    return out


def _label(key, state=None):
    """A readable name for an edit key: its cell and object."""
    if key.startswith("added|"):
        a = (state or {}).get("added") or {}
        return a.get("cell", "?"), a.get("id", "added object")
    if key.startswith("npcs|"):
        n = (state or {}).get("npc") or {}
        return "NPCs", n.get("id") or key[len("npcs|"):]
    if key.startswith("dialogue|"):
        r = (state or {}).get("response") or {}
        topic = r.get("topic") or key.split("|")[1]
        return "Dialogue", "%s%s" % (topic, " (%s)" % r["actor"] if r.get("actor") else "")
    parts = key.split("|")
    return parts[0], parts[1] if parts[1] != "vanilla" else "vanilla #" + parts[2]


def diff(old, new):
    """Per-object differences between two edits files."""
    a, b = states(old), states(new)
    out = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            cell, obj = _label(k, b.get(k) or a.get(k))
            out.append({"key": k, "cell": cell, "object": obj, "before": a.get(k), "after": b.get(k)})
    return out


class History:
    def __init__(self, folder):
        self.folder = folder

    def versions(self):
        if not os.path.isdir(self.folder):
            return []
        names = [n for n in os.listdir(self.folder) if n.endswith(".json")]
        return sorted(names, key=lambda n: (n[:19], int(n[20:23]) if n[20:23].isdigit() else 0))

    def load(self, name):
        if "/" in name or "\\" in name or not name.endswith(".json"):
            raise ValueError("bad version name")
        e = empty_edits()
        with open(os.path.join(self.folder, name)) as f:
            e.update(json.load(f))
        return e

    def snapshot(self, edits, label=""):
        """Keep a copy of a saved layout unless it's the same as the last one."""
        os.makedirs(self.folder, exist_ok=True)
        versions = self.versions()
        if versions and self.load(versions[-1]) == dict(empty_edits(), **edits):
            return versions[-1]
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = "%s_%03d%s.json" % (stamp, len(versions) + 1, "_" + label if label else "")
        with open(os.path.join(self.folder, name), "w") as f:
            json.dump(edits, f, indent=1)
        return name

    def summary(self):
        """Saved versions, newest first, each with what changed from the one before."""
        out, prev = [], empty_edits()
        for n in self.versions():
            e = self.load(n)
            d = diff(prev, e)
            out.append({"name": n, "changes": len(d), "objects": [x["object"] for x in d[:6]],
                        "counts": {k: len(e[k]) for k in ("moved", "added", "replaced", "deleted")}})
            prev = e
        return out[::-1]

    def version_diff(self, name):
        """What changed in a version from the one before it."""
        names = self.versions()
        i = names.index(name)
        before = self.load(names[i - 1]) if i else empty_edits()
        return {"name": name, "changes": diff(before, self.load(name))}

    def object_history(self, key):
        """The saved states of one object, oldest first, only where it changed."""
        out, last = [], "unset"
        for n in self.versions():
            st = states(self.load(n)).get(key)
            if st != last:
                out.append({"name": n, "state": st})
                last = st
        return out
