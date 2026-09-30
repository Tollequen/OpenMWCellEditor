"""Files inside TES3 BSA archives."""
import struct


class Archive:
    """One BSA archive; names are case-insensitive and use backslashes."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            head = f.read(12)
            _, hash_offset, n = struct.unpack("<III", head)
            table = f.read(hash_offset)             # size/offset pairs, name offsets, names
        records = [struct.unpack_from("<II", table, 8 * i) for i in range(n)]
        name_offsets = struct.unpack_from("<%dI" % n, table, 8 * n)
        names_base = 12 * n
        data_start = 12 + hash_offset + 8 * n
        self.files = {}
        for (size, offset), no in zip(records, name_offsets):
            s = names_base + no
            name = table[s:table.index(b"\0", s)].decode("latin1").lower()
            self.files[name] = (data_start + offset, size)

    def has(self, name):
        return _norm(name) in self.files

    def read(self, name):
        start, size = self.files[_norm(name)]
        with open(self.path, "rb") as f:
            f.seek(start)
            return f.read(size)


def _norm(name):
    return name.lower().replace("/", "\\")
