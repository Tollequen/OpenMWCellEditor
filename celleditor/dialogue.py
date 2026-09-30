"""Dialogue topics (DIAL) and responses (INFO) merged across the load order, and written back."""
import functools
import struct

from . import esp
from .esp import cstr, zstr

TYPES = ("Topic", "Voice", "Greeting", "Persuasion", "Journal")
TOPIC, VOICE, GREETING, PERSUASION, JOURNAL = range(5)
# Condition kinds by SCVR's second character; for "1" the next two are the function number.
KINDS = {"1": "function", "2": "global", "3": "local", "4": "journal", "5": "item", "6": "dead", "7": "notId",
         "8": "notFaction", "9": "notClass", "A": "notRace", "B": "notCell", "C": "notLocal"}
KIND_CODES = {"journal": "4JX", "item": "5IX", "dead": "6DX", "notId": "7XX", "notFaction": "8FX",
              "notClass": "9CX", "notRace": "ARX", "notCell": "BLX"}
FIELDS = ("text", "actor", "race", "class", "faction", "cell", "pcFaction", "sound", "disposition", "rank", "sex",
          "pcRank", "conditions", "result", "quest")
QUEST = {"QSTN": "name", "QSTF": "finished", "QSTR": "restart"}
HEAD, TAIL = "\0head", "\0tail"


# --- Reading ------------------------------------------------------------------------

def scan(path):
    """A file's topics in order: [(name, type, DIAL offset, [(id, PNAM, actor, offset, deleted)])]."""
    return _scan(path, esp._sig(path))


@functools.lru_cache(maxsize=None)
def _scan(path, sig):
    d = esp._data(path, sig)
    out, group = [], None
    p = 0
    while p + 16 <= len(d):
        size = struct.unpack_from("<I", d, p + 4)[0]
        tag = d[p:p + 4]
        if tag in (b"DIAL", b"INFO"):
            q, end, sub = p + 16, min(len(d), p + 16 + size), {}
            while q + 8 <= end:
                st = d[q:q + 4]
                ss = struct.unpack_from("<I", d, q + 4)[0]
                if st in (b"NAME", b"DATA", b"INAM", b"PNAM", b"ONAM", b"DELE") and st not in sub:
                    sub[st] = bytes(d[q + 8:q + 8 + ss])
                if tag == b"DIAL" and b"NAME" in sub and b"DATA" in sub:
                    break
                q += 8 + ss
            if tag == b"DIAL":
                data = sub.get(b"DATA", b"")
                group = (cstr(sub.get(b"NAME", b"")), data[0] if len(data) == 1 else -1, p, [])
                out.append(group)
            elif group is not None and b"INAM" in sub:
                group[3].append((cstr(sub[b"INAM"]), cstr(sub.get(b"PNAM", b"")),
                                 cstr(sub.get(b"ONAM", b"")).lower(), p, b"DELE" in sub))
        p += 16 + size
    return out


def release():
    _scan.cache_clear()


class Order:
    """A topic's responses in order, as OpenMW's InfoOrder puts them."""

    def __init__(self):
        self.next, self.prev = {HEAD: TAIL}, {TAIL: HEAD}
        self.nodes = {}

    def _unlink(self, i):
        p, n = self.prev.pop(i), self.next.pop(i)
        self.next[p], self.prev[n] = n, p

    def _link_after(self, a, i):
        n = self.next[a]
        self.next[a], self.prev[i], self.next[i], self.prev[n] = i, a, n, i

    def insert(self, i, pnam, rec, deleted):
        node = self.nodes.get(i)
        if node is not None and node["prev"] == pnam:
            node.update(rec=rec, deleted=deleted)
            node["files"].append(rec[0])
            return
        after = HEAD if not pnam else pnam if pnam in self.nodes else self.prev[TAIL]
        if node is None:
            self.nodes[i] = {"prev": pnam, "deleted": deleted, "rec": rec, "files": [rec[0]]}
            self._link_after(after, i)
            return
        node.update(prev=pnam, rec=rec, deleted=deleted)
        node["files"].append(rec[0])
        if after != i:
            self._unlink(i)
            self._link_after(after, i)

    def ids(self):
        out, i = [], self.next[HEAD]
        while i != TAIL:
            out.append(i)
            i = self.next[i]
        return out


class Topic:
    def __init__(self, name):
        self.name, self.type, self.dial, self.first = name, -1, None, None
        self.order = Order()

    def ids(self):
        """The responses in order, deleted ones left out."""
        return [i for i in self.order.ids() if not self.order.nodes[i]["deleted"]]


def parse_info(subs):
    """An INFO record's subrecords as fields."""
    d = {}
    for s, v in subs:
        d.setdefault(s, v)
    data = d.get("DATA", b"").ljust(12, b"\0")
    kind, disposition = struct.unpack_from("<ii", data)
    rank, sex, pc_rank = struct.unpack_from("<bbb", data, 8)
    f = {"id": cstr(d.get("INAM", b"")), "text": d.get("NAME", b"").decode("latin1"),
         "actor": cstr(d.get("ONAM", b"")), "race": cstr(d.get("RNAM", b"")), "class": cstr(d.get("CNAM", b"")),
         "faction": cstr(d.get("FNAM", b"")), "cell": cstr(d.get("ANAM", b"")), "pcFaction": cstr(d.get("DNAM", b"")),
         "sound": cstr(d.get("SNAM", b"")), "disposition": disposition, "rank": rank, "sex": sex, "pcRank": pc_rank,
         "result": d.get("BNAM", b"").decode("latin1"), "quest": None, "type": kind}
    for s, q in QUEST.items():
        if s in d:
            f["quest"] = q
    conds, last = [], None
    for s, v in subs:
        if s == "SCVR":
            last = _condition(v)
            conds.append(last)
        elif s in ("INTV", "FLTV") and last is not None and "value" not in last:
            last["value"] = struct.unpack("<i" if s == "INTV" else "<f", v[:4].ljust(4, b"\0"))[0]
            last["float"] = s == "FLTV"
    for c in conds:
        c.setdefault("value", 0)
        c.setdefault("float", False)
    f["conditions"] = conds
    return f


def _condition(v):
    """An SCVR as {index, kind, func, op, name, rule}."""
    rule = v.decode("latin1").rstrip("\0")
    c = {"rule": rule, "index": int(rule[0]) if rule[:1].isdigit() else 0, "kind": KINDS.get(rule[1:2], "?"),
         "op": rule[4:5] or "0", "name": rule[5:]}
    if c["kind"] == "function":
        c["func"] = int(rule[2:4]) if rule[2:4].isdigit() else -1
    return c


def _rule(c):
    """A condition's SCVR string."""
    if c.get("rule"):
        return c["rule"]
    k = c["kind"]
    if k == "function":
        mid = "1%02d" % int(c["func"])
    elif k in ("global", "local", "notLocal"):
        t = "f" if c.get("float") else "s" if -32768 <= int(c["value"]) <= 32767 else "l"
        mid = {"global": "2", "local": "3", "notLocal": "C"}[k] + t + "X"
    elif k in KIND_CODES:
        mid = KIND_CODES[k]
    else:
        raise ValueError("a condition of an unknown kind: %r" % k)
    op = str(c.get("op", "0"))
    if op not in "012345" or len(op) != 1:
        raise ValueError("a condition's comparison must be 0-5, not %r" % op)
    return "%d%s%s%s" % (int(c.get("index", 0)), mid, op, c.get("name", ""))


def _text(s):
    return (s or "").encode("latin1", "replace")


def encode_info(f, base=(), prev="", nxt="", kind=None):
    """An INFO's subrecords from fields, PNAM and NNAM, with the rest taken from base."""
    old = dict(base)
    was = old.get("DATA", b"").ljust(12, b"\0")
    out = [("INAM", zstr(f["id"])), ("PNAM", zstr(prev)), ("NNAM", zstr(nxt))]
    t = f.get("type") if kind is None else kind
    out.append(("DATA", struct.pack("<iibbb", int(t or 0), int(f["disposition"]), int(f["rank"]), int(f["sex"]),
                                    int(f["pcRank"])) + was[11:12]))
    for k, s in (("actor", "ONAM"), ("race", "RNAM"), ("class", "CNAM"), ("faction", "FNAM"), ("cell", "ANAM"),
                 ("pcFaction", "DNAM"), ("sound", "SNAM")):
        if f[k]:
            out.append((s, zstr(f[k])))
    if f["text"]:
        out.append(("NAME", _text(f["text"])))
    for i, c in enumerate(f["conditions"][:6]):
        c = dict(c, index=c.get("index", i))
        out.append(("SCVR", _rule(c).encode("latin1")))
        out.append(("FLTV", struct.pack("<f", float(c["value"]))) if c.get("float")
                   else ("INTV", struct.pack("<i", int(c["value"]))))
    if f["result"]:
        out.append(("BNAM", _text(f["result"])))
    for s, q in QUEST.items():
        if f.get("quest") == q:
            out.append((s, b"\1"))
    return out


class Dialogue:
    """The load order's dialogue, merged."""

    def __init__(self, load, usable=None):
        self.files = load.files
        self.usable = usable
        self._topics = None

    def topics(self):
        """{name (lower case): Topic}, and which topics each actor speaks in."""
        if self._topics is None:
            topics, actors = {}, {}
            for f in self.files:
                for name, kind, off, infos in scan(f.path):
                    t = topics.get(name.lower())
                    if t is None:
                        t = topics[name.lower()] = Topic(name)
                        t.first = f.name
                    t.type = kind if kind >= 0 else t.type
                    t.dial = (f, off)
                    for i, pnam, actor, ioff, deleted in infos:
                        t.order.insert(i, pnam, (f, ioff), deleted)
                        if actor:
                            actors.setdefault(actor, set()).add(name.lower())
            self._topics, self._actors = topics, actors
        return self._topics

    def names(self):
        """[{name, type}] of the topics other than journals."""
        return [{"name": t.name, "type": t.type} for k, t in sorted(self.topics().items())
                if t.type in (TOPIC, GREETING, PERSUASION, VOICE)]

    def base_fields(self, topic, i):
        n = topic.order.nodes[i]
        _, _, subs = esp.record_subs(n["rec"][0].path, n["rec"][1])
        return parse_info(subs), subs

    # --- The edits ----------------------------------------------------------------

    @staticmethod
    def by_topic(edits):
        out = {}
        for key, e in (edits or {}).items():
            topic, _, i = key.partition("|")
            out.setdefault(topic, {})[i] = e
        return out

    def arrange(self, topic, entries):
        """A topic's response ids in order after the edits, deleted ones included."""
        order = list(topic.order.ids()) if topic else []
        base_deleted = {i for i in order if topic.order.nodes[i]["deleted"]} if topic else set()
        order = [i for i in order if i not in base_deleted]
        pending = [i for i, e in sorted(entries.items()) if e.get("new") or ("after" in e and not e.get("deleted"))]
        order = [i for i in order if i not in pending]
        while pending:
            placed = False
            for i in list(pending):
                a = entries[i].get("after", "")
                if a == "":
                    order.insert(0, i)
                elif a in order:
                    order.insert(order.index(a) + 1, i)
                elif a in pending:
                    continue
                else:
                    order.append(i)                 # the response it followed is gone: at the end, as in OpenMW
                pending.remove(i)
                placed = True
            if not placed:
                order += pending
                break
        return order

    def fields_of(self, topic, i, e):
        """(the response's fields after the edit, the base's fields, its old subrecords)."""
        if e and e.get("new"):
            f = {k: e.get(k) for k in FIELDS}
            f.update(id=i, type=e.get("type", topic.type if topic else TOPIC))
            return f, None, ()
        base, subs = self.base_fields(topic, i)
        f = dict(base, **{k: v for k, v in (e or {}).items() if k in FIELDS})
        return f, base, subs

    def for_actor(self, actor, edits):
        """An NPC's dialogue with the unsaved edits applied, for the page."""
        actor = actor.lower()
        topics = self.topics()
        by = self.by_topic(edits)
        keys = set(self._actors.get(actor, ()))
        for k, entries in by.items():
            if any((e.get("actor") or "").lower() == actor for e in entries.values() if e.get("new")):
                keys.add(k)
        out = []
        for k in keys:
            t = topics.get(k)
            entries = by.get(k, {})
            order = self.arrange(t, entries)
            rows = []
            for n, i in enumerate(order):
                e = entries.get(i)
                if not (e and e.get("new")) and (t is None or i not in t.order.nodes):
                    continue
                f, base, _ = self.fields_of(t, i, e)
                if (f.get("actor") or "").lower() != actor:
                    continue
                rows.append({"key": k + "|" + i, "id": i, "fields": f, "base": base, "prev": order[n - 1] if n else "",
                             "file": None if base is None else t.order.nodes[i]["rec"][0].name,
                             "deleted": bool(e and e.get("deleted")), "isNew": bool(e and e.get("new"))})
            if not rows:
                continue
            first = next((e for e in entries.values() if e.get("new")), {})
            out.append({"key": k, "name": t.name if t else first.get("topic", k), "isNew": t is None,
                        "type": t.type if t else first.get("type", TOPIC), "responses": rows})
        return sorted(out, key=lambda g: ({GREETING: 0, TOPIC: 1, PERSUASION: 2, VOICE: 3}.get(g["type"], 4),
                                          g["name"].lower()))

    # --- Writing ------------------------------------------------------------------

    def records(self, edits, own=None):
        """The DIAL + INFO groups of the edited topics and the files they need; raises ValueError."""
        topics = self.topics()
        groups, need = {}, {}
        own = own.lower() if own else None
        for k, entries in sorted(self.by_topic(edits).items()):
            t = topics.get(k)
            if t is None:
                fresh = [e for e in entries.values() if e.get("new")]
                if not fresh or len(fresh) < len(entries):
                    raise ValueError("The topic %s isn't in the load order any more: reset its responses." % k)
                name, kind = fresh[0].get("topic") or k, fresh[0].get("type", TOPIC)
                if not name.strip():
                    raise ValueError("A topic needs a name.")
                dial = [("NAME", zstr(name)), ("DATA", bytes([kind]))]
            else:
                if self.usable is not None and t.first.lower() not in self.usable:
                    raise ValueError("The topic %s comes from %s, which this plugin can't use." % (t.name, t.first))
                _, _, dial = esp.record_subs(t.dial[0].path, t.dial[1])
                dial = [(s, v) for s, v in dial if s in ("NAME", "DATA")]
                kind = t.type
                need.setdefault(t.first, []).append("responses in %s" % t.name)
            for i, e in entries.items():
                if not e.get("new") and (t is None or i not in t.order.nodes):
                    raise ValueError("A response of %s isn't in the load order any more (reset it)." % k)
                if e.get("new") and t is not None and i in t.order.nodes:
                    raise ValueError("A new response of %s has the id of one that's there (%s)." % (k, i))
                if not e.get("new"):
                    f = t.order.nodes[i]["rec"][0].name
                    need.setdefault(f, []).append("a response in %s changed" % t.name)
            order = self.arrange(t, entries)
            files = lambda i: {x.name.lower() for x in t.order.nodes[i]["files"]} if t and i in t.order.nodes else set()   # noqa: E731
            mine = {i for i in order if own and own in files(i)}
            gone = {i for i, e in entries.items() if e.get("deleted") and i in mine and files(i) == {own}}
            order = [i for i in order if i not in gone]
            write = [i for i in order if i in entries or i in mine]
            infos = []
            for i in write:
                n = order.index(i)
                prev, nxt = (order[n - 1] if n else ""), (order[n + 1] if n + 1 < len(order) else "")
                e = entries.get(i)
                if e and e.get("deleted"):
                    infos.append(esp.record("INFO", [esp.sub("INAM", zstr(i)), esp.sub("PNAM", zstr(prev)),
                                                     esp.sub("NNAM", zstr(nxt)), esp.sub("DELE", b"\0\0\0\0")]))
                    continue
                f, _, subs = self.fields_of(t, i, e)
                flags = 0
                if t is not None and i in t.order.nodes:
                    flags = esp.record_subs(t.order.nodes[i]["rec"][0].path, t.order.nodes[i]["rec"][1])[1]
                infos.append(esp.record("INFO", [esp.sub(s, v) for s, v in encode_info(f, subs, prev, nxt, kind)],
                                        flags))
            flags = 0 if t is None else esp.record_subs(t.dial[0].path, t.dial[1])[1]
            groups[k] = esp.record("DIAL", [esp.sub(s, v) for s, v in dial], flags) + b"".join(infos)
        return groups, need
