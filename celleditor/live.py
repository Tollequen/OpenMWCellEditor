"""Shared unsaved edits for pages on several devices, streamed as entries, with a draft file."""
import hashlib
import json
import os
import itertools
import queue
import threading
import time

from .settings import Settings

SECTIONS = ("moved", "replaced", "attached", "doors", "groups", "npcs", "dialogue")


def entries(edits):
    """The entries of edits: {id: value}."""
    out = {}
    for section in SECTIONS:
        for k, v in (edits.get(section) or {}).items():
            out[section + "|" + k] = v
    for k in edits.get("deleted") or []:
        out["deleted|" + k] = True
    for a in edits.get("added") or []:
        out["added|" + a["uid"]] = a
    return out


def edits_of(ents):
    """Entries back into edits."""
    e = {"moved": {}, "deleted": [], "replaced": {}, "added": [], "attached": {}, "doors": {}, "groups": {},
         "npcs": {}, "dialogue": {}}
    for i, v in ents.items():
        section, key = i.split("|", 1)
        if section == "deleted":
            e["deleted"].append(key)
        elif section == "added":
            e["added"].append(v)
        elif section in SECTIONS:
            e[section][key] = v
    return e


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _fingerprint(edits):
    return hashlib.sha1(json.dumps(entries(edits), sort_keys=True).encode()).hexdigest()


class Live:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = None
        self.ents = {}
        self.saved = {}
        self.version = 0
        self.pages = {}
        self.remote = set()
        self.presence = {}
        self.asks = {}
        self.seen = {}
        self._ask_ids = itertools.count(1)
        self._timer = None

    # --- The project ---------------------------------------------------------------

    def start(self, path, saved):
        """A project was opened; the same one again keeps the unsaved edits."""
        with self.lock:
            same = self.path is not None and os.path.normcase(self.path) == os.path.normcase(path)
            self._write_draft()
            self.saved = entries(saved)
            if not same:
                self.path, self.ents, self.presence = path, dict(self.saved), {}
            self.version += 1
            self._send({"type": "project", "path": path})

    def edits(self):
        with self.lock:
            return edits_of(self.ents)

    def unsaved(self):
        """How many entries differ from the saved edits."""
        with self.lock:
            return sum(1 for i in set(self.ents) | set(self.saved) if not _same(self.ents.get(i), self.saved.get(i)))

    def state(self):
        """What a page starts with: the edits now, and a draft to offer back if nothing has changed."""
        with self.lock:
            draft = None
            if _same(self.ents, self.saved):
                d = self._read_draft()
                if d and d.get("base") == _fingerprint(edits_of(self.saved)) and not _same(entries(d["edits"]), self.saved):
                    draft = {"edits": d["edits"], "at": d.get("at")}
            return {"edits": edits_of(self.ents), "version": self.version, "draft": draft}

    # --- Changes -------------------------------------------------------------------

    def apply(self, page, path, ops, extra=None):
        """A page's changes; False if the page shows another project.

        extra goes into the event: {"undo": True, "label": ...} makes the pages offer the change as one undo
        step (changes from an assistant, which has no undo of its own)."""
        with self.lock:
            if not self.path or os.path.normcase(path or "") != os.path.normcase(self.path):
                return False
            for op in ops:
                i = op["id"]
                if op.get("v") is None:
                    self.ents.pop(i, None)
                else:
                    self.ents[i] = op["v"]
            self.version += 1
            self._send(dict(extra or {}, type="ops", ops=ops, version=self.version, **{"from": page}))
            self._draft_later()
            return True

    def was_saved(self, clean):
        """The edits were saved: every page takes them."""
        with self.lock:
            self.saved = entries(clean)
            self.ents = dict(self.saved)
            self.version += 1
            self._send({"type": "saved", "edits": clean, "version": self.version})
            self._drop_draft()

    def drop_draft(self):
        with self.lock:
            self._drop_draft()

    # --- Pages ---------------------------------------------------------------------

    def join(self, page, here=True):
        """A page's stream: (its queue, the first event with everything as it is now)."""
        q = queue.Queue()
        with self.lock:
            old = self.pages.get(page)
            if old:
                old.put(None)
            self.pages[page] = q
            if not here:
                self.remote.add(page)
            hello = {"type": "hello", "edits": edits_of(self.ents), "version": self.version, "path": self.path,
                     "others": [dict(p, page=k) for k, p in self.presence.items() if k != page]}
        return q, hello

    def leave(self, page, q=None):
        """A page's stream ended, or the page said it's closing."""
        with self.lock:
            if page in self.pages and (q is None or self.pages[page] is q):
                if q is None:
                    self.pages[page].put(None)
                del self.pages[page]
                self.remote.discard(page)
                self.seen.pop(page, None)
                if self.presence.pop(page, None) is not None:
                    self._send({"type": "gone", "page": page})

    def end_remote(self):
        """Phone access was turned off: the streams of other devices end."""
        with self.lock:
            for page in list(self.remote):
                if page in self.pages:
                    self.pages.pop(page).put(None)
                if self.presence.pop(page, None) is not None:
                    self._send({"type": "gone", "page": page})
            self.remote.clear()

    def where(self, page, info):
        """Where a page is and what it has selected."""
        with self.lock:
            if page not in self.pages:
                return
            info = {k: info.get(k) for k in ("label", "cell", "pos", "yaw", "pitch", "sel", "tiers")}
            self.presence[page] = info
            self.seen[page] = time.time()
            self._send(dict(info, type="presence", page=page), skip=page)

    def pages_here(self):
        """[(page, presence)] of the pages on this computer showing a cell, the last one to move first."""
        with self.lock:
            out = [(k, dict(p)) for k, p in self.presence.items()
                   if k in self.pages and k not in self.remote and p.get("cell")]
        return sorted(out, key=lambda kp: -self.seen.get(kp[0], 0))

    def ask(self, page, event, timeout=20.0):
        """Ask one page something (e.g. a picture); its answer, or None if it doesn't answer in time."""
        box = {"done": threading.Event(), "answer": None}
        with self.lock:
            q = self.pages.get(page)
            if q is None:
                return None
            n = next(self._ask_ids)
            self.asks[n] = box
            q.put(dict(event, type="ask", req=n))
        try:
            box["done"].wait(timeout)
        finally:
            with self.lock:
                self.asks.pop(n, None)
        return box["answer"]

    def answer(self, n, data):
        with self.lock:
            box = self.asks.get(n)
            if box:
                box["answer"] = data
                box["done"].set()

    def _send(self, event, skip=None):
        for page, q in self.pages.items():
            if page != skip:
                q.put(event)

    def close(self):
        """The editor stops: the streams end and the draft is written."""
        with self.lock:
            for q in self.pages.values():
                q.put(None)
            self.pages.clear()
            self._write_draft()

    # --- The draft file ------------------------------------------------------------

    def _draft_path(self):
        name = hashlib.sha1(os.path.normcase(os.path.abspath(self.path)).encode()).hexdigest()[:16]
        return os.path.join(os.path.dirname(Settings.default_path()), "unsaved", name + ".json")

    def _read_draft(self):
        try:
            with open(self._draft_path()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _draft_later(self):
        if self._timer is None:
            self._timer = threading.Timer(1.0, self._draft_now)
            self._timer.daemon = True
            self._timer.start()

    def _draft_now(self):
        with self.lock:
            self._timer = None
            self._write_draft(changed=True)

    def _write_draft(self, changed=False):
        """Write the unsaved edits to the draft file."""
        if self._timer is not None and not changed:
            self._timer.cancel()
            self._timer = None
        if not self.path:
            return
        if _same(self.ents, self.saved):
            if changed:
                self._drop_draft()
            return
        path = self._draft_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"project": self.path, "base": _fingerprint(edits_of(self.saved)),
                           "edits": edits_of(self.ents), "at": int(time.time() * 1000)}, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def _drop_draft(self):
        if self.path:
            try:
                os.remove(self._draft_path())
            except OSError:
                pass


LIVE = Live()
