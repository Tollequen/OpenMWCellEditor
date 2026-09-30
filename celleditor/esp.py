"""TES3 (.esm/.esp/.omwaddon) record reading."""
import functools
import mmap
import os
import re
import struct


def sub(tag, data):
    return tag.encode("ascii") + struct.pack("<I", len(data)) + data


def zstr(s):
    return s.encode("latin1") + b"\0"


def record(tag, subrecords, flags=0):
    body = b"".join(subrecords)
    return tag.encode("ascii") + struct.pack("<III", len(body), 0, flags) + body


def esm_records(path, header_only=False):
    """Yield (tag, flags, [(subtag, bytes)]) for every record in a TES3 file, or only its header."""
    with open(path, "rb") as f:
        if header_only:
            head = f.read(16)
            d = head + f.read(struct.unpack_from("<I", head, 4)[0])
        else:
            d = f.read()
    # Stray bytes after the last record or at the end of a record are skipped, as OpenMW does.
    p = 0
    while p + 16 <= len(d):
        tag = d[p:p + 4].decode("latin1")
        size, _, flags = struct.unpack_from("<III", d, p + 4)
        body = d[p + 16:p + 16 + size]
        p += 16 + size
        subs, q = [], 0
        while q + 8 <= len(body):
            st = body[q:q + 4].decode("latin1")
            ss = struct.unpack_from("<I", body, q + 4)[0]
            subs.append((st, body[q + 8:q + 8 + ss]))
            q += 8 + ss
        yield tag, flags, subs


def _sig(path):
    """The key the caches use for a file, so a changed file is read again."""
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def cell_refs(path, cell):
    """A cell's references in a TES3 file: (header subrecords, [(refnum, subrecords)])."""
    return _cell_refs(path, _sig(path), cell)


@functools.lru_cache(maxsize=4096)
def _cell_refs(path, sig, cell):
    interiors, exteriors, _ = _cell_index(path, sig)
    grid = parse_exterior(cell)
    p = exteriors.get(grid) if grid else None
    if p is None:
        p = interiors.get(cell)
    if p is None:
        raise KeyError(cell)
    d = _data(path, sig)
    size = struct.unpack_from("<I", d, p + 4)[0]
    body = d[p + 16:p + 16 + size]
    subs, q = [], 0
    while q + 8 <= len(body):
        st = body[q:q + 4].decode("latin1")
        ss = struct.unpack_from("<I", body, q + 4)[0]
        subs.append((st, body[q + 8:q + 8 + ss]))
        q += 8 + ss
    return _split_refs(subs)


def _split_refs(subs):
    """Split a CELL record's subrecords into (header, [(refnum, reference subrecords)])."""
    head, refs, pending = [], [], []
    for st, v in subs:
        if st == "FRMR":
            refs.append((struct.unpack("<I", v)[0], pending))
            pending = []
        elif st in ("MVRF", "CNDT"):
            pending.append((st, v))
        elif st == "NAM0" or not refs:
            if st != "NAM0":                 # NAM0 (temporary reference count) isn't copied
                head.append((st, v))
        else:
            refs[-1][1].append((st, v))
    return head, refs


def moved_refs(path):
    """References a file moves into other exterior cells: {(x, y): [(refnum, subrecords)]}."""
    return _moved_refs(path, _sig(path))


@functools.lru_cache(maxsize=None)
def _moved_refs(path, sig):
    d = _data(path, sig)
    out = {}
    if d.find(b"MVRF") < 0:
        return out
    for tag, _, subs in esm_records(path):
        if tag != "CELL":
            continue
        for num, rsubs in _split_refs(subs)[1]:
            cndt = dict(rsubs).get("CNDT")
            if cndt:
                out.setdefault(struct.unpack("<ii", cndt), []).append((num, rsubs))
    return out


def cell_index(path):
    """Offsets of each CELL record: ({interior: offset}, {(x, y): offset}, {(x, y): name})."""
    return _cell_index(path, _sig(path))


@functools.lru_cache(maxsize=None)
def _cell_index(path, sig):
    d = _data(path, sig)
    interiors, exteriors, ext_names = {}, {}, {}
    p = 0
    while p + 16 <= len(d):
        size = struct.unpack_from("<I", d, p + 4)[0]
        if d[p:p + 4] == b"CELL":
            q, end, name, data, region = p + 16, min(len(d), p + 16 + size), None, None, b""
            while q + 8 <= end:
                st = d[q:q + 4]
                ss = struct.unpack_from("<I", d, q + 4)[0]
                v = d[q + 8:q + 8 + ss]
                if st == b"NAME":
                    name = cstr(v)
                elif st == b"DATA":
                    data = v
                elif st == b"RGNN":
                    region = v
                elif st == b"FRMR":
                    break
                q += 8 + ss
            if data is None or len(data) < 12:
                p += 16 + size
                continue
            flags = struct.unpack_from("<I", data)[0]
            if flags & 0x01:
                interiors[name] = p
            else:
                grid = struct.unpack_from("<ii", data, 4)
                exteriors[grid] = p
                ext_names[grid] = name or cstr(region)
        p += 16 + size
    return interiors, exteriors, ext_names


@functools.lru_cache(maxsize=None)
def _data(path, sig):
    """The file's bytes, memory-mapped."""
    with open(path, "rb") as f:
        if sig[0] == 0:
            return b""
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)


def land_index(path):
    """Offsets of a file's LAND records and its land textures: ({(x, y): offset}, {index: texture})."""
    return _land_index(path, _sig(path))


@functools.lru_cache(maxsize=None)
def _land_index(path, sig):
    d = _data(path, sig)
    lands, ltex = {}, {}
    p = 0
    while p + 16 <= len(d):
        size = struct.unpack_from("<I", d, p + 4)[0]
        tag = d[p:p + 4]
        if tag in (b"LAND", b"LTEX"):
            q, end, sub = p + 16, min(len(d), p + 16 + size), {}
            while q + 8 <= end:
                st = d[q:q + 4]
                ss = struct.unpack_from("<I", d, q + 4)[0]
                if st in (b"INTV", b"DATA"):
                    sub[st] = d[q + 8:q + 8 + ss]
                if tag == b"LAND" and st == b"INTV":
                    break
                q += 8 + ss
            if tag == b"LAND" and b"INTV" in sub:
                lands[struct.unpack("<ii", sub[b"INTV"][:8])] = p
            elif tag == b"LTEX" and b"INTV" in sub and b"DATA" in sub:
                ltex[struct.unpack("<i", sub[b"INTV"][:4])[0]] = cstr(sub[b"DATA"])
        p += 16 + size
    return lands, ltex


def record_at(path, offset):
    """{subrecord tag: bytes} of the record at offset."""
    d = _data(path, _sig(path))
    size = struct.unpack_from("<I", d, offset + 4)[0]
    out, q, end = {}, offset + 16, min(len(d), offset + 16 + size)
    while q + 8 <= end:
        ss = struct.unpack_from("<I", d, q + 4)[0]
        out[d[q:q + 4].decode("latin1")] = bytes(d[q + 8:q + 8 + ss])
        q += 8 + ss
    return out


UNNAMED = (b"CELL", b"DIAL", b"INFO", b"LAND", b"PGRD", b"TES3")


def named_records(path):
    """Offsets of each named record: {tag: {id (lower case): offset}}."""
    return _named_records(path, _sig(path))


@functools.lru_cache(maxsize=None)
def _named_records(path, sig):
    d = _data(path, sig)
    out = {}
    p = 0
    while p + 16 <= len(d):
        size = struct.unpack_from("<I", d, p + 4)[0]
        tag = d[p:p + 4]
        if tag not in UNNAMED and p + 24 <= len(d):
            st = d[p + 16:p + 20]
            ss = struct.unpack_from("<I", d, p + 20)[0]
            name = None
            if st == b"NAME" or (st == b"SCHD" and tag == b"SCPT"):
                name = cstr(bytes(d[p + 24:p + 24 + min(ss, 32 if st == b"SCHD" else ss)]))
            elif st == b"INDX" and tag == b"SKIL" and ss >= 4:
                name = "#%d" % struct.unpack_from("<i", d, p + 24)[0]
            if name:
                out.setdefault(tag.decode("latin1"), {})[name.lower()] = p
        p += 16 + size
    return out


def record_subs(path, offset):
    """(tag, flags, [(subtag, bytes)]) of the record at offset."""
    d = _data(path, _sig(path))
    size, _, flags = struct.unpack_from("<III", d, offset + 4)
    subs, q, end = [], offset + 16, min(len(d), offset + 16 + size)
    while q + 8 <= end:
        ss = struct.unpack_from("<I", d, q + 4)[0]
        subs.append((d[q:q + 4].decode("latin1"), bytes(d[q + 8:q + 8 + ss])))
        q += 8 + ss
    return d[offset:offset + 4].decode("latin1"), flags, subs


def release():
    """Clear the caches and close the memory maps; Windows can't replace a mapped file."""
    for cache in (_cell_refs, _moved_refs, _cell_index, _land_index, _named_records, _data):
        cache.cache_clear()
    from . import dialogue
    dialogue.release()


EXTERIOR = re.compile(r"\((-?\d+), (-?\d+)\)$")


def exterior_key(grid, name):
    """An exterior cell's editor name, e.g. "Moonmoth Legion Fort (-1, -3)"."""
    return "%s (%d, %d)" % (name, *grid)


def parse_exterior(key):
    m = EXTERIOR.search(key)
    return (int(m.group(1)), int(m.group(2))) if m else None


def cstr(b):
    return b.split(b"\0")[0].decode("latin1")


def find_records(path, ids):
    """Raw records for the given object ids (case-insensitive): {id: (tag, flags, subs)}."""
    want = {i.lower() for i in ids}
    found = {}
    for tag, flags, subs in esm_records(path):
        if tag in ("CELL", "DIAL", "INFO", "LAND", "PGRD") or not subs or subs[0][0] != "NAME":
            continue
        i = cstr(subs[0][1]).lower()
        if i in want and i not in found:
            found[i] = (tag, flags, subs)
    missing = want - set(found)
    if missing:
        raise KeyError("not in %s: %s" % (path, sorted(missing)))
    return found
