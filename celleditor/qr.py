"""QR codes for short texts: byte mode, level M, versions 1-6; laid out like Project Nayuki's QR Code generator."""

# Versions 1-6, level M: error correction codewords per block, and blocks.
ECC_PER_BLOCK = (None, 10, 16, 26, 18, 24, 16)
BLOCKS = (None, 1, 1, 1, 2, 2, 4)
FORMAT_M = 0          # level M's two format bits


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data, degree):
    """The Reed-Solomon error correction codewords of data."""
    divisor = _rs_divisor(degree)
    result = [0] * degree
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _raw_codewords(ver):
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        n -= (25 * align - 10) * align - 55
    return n // 8


def _data_codewords(ver):
    return _raw_codewords(ver) - ECC_PER_BLOCK[ver] * BLOCKS[ver]


def _codewords(data, ver):
    """The data bytes as the final codeword sequence, data and error correction interleaved."""
    bits = [0, 1, 0, 0]                                      # byte mode
    bits += [(len(data) >> i) & 1 for i in reversed(range(8))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    capacity = _data_codewords(ver) * 8
    bits += [0] * min(4, capacity - len(bits))              # terminator
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < _data_codewords(ver):
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    nblocks, ecc = BLOCKS[ver], ECC_PER_BLOCK[ver]
    raw = _raw_codewords(ver)
    short = nblocks - raw % nblocks
    short_len = raw // nblocks
    blocks, k = [], 0
    for i in range(nblocks):
        n = short_len - ecc + (0 if i < short else 1)
        d = words[k:k + n]
        k += n
        blocks.append((d, rs_remainder(d, ecc)))
    out = []
    for i in range(short_len - ecc + 1):
        for d, _ in blocks:
            if i < len(d):
                out.append(d[i])
    for i in range(ecc):
        for _, e in blocks:
            out.append(e[i])
    return out


def _alignment_positions(ver, size):
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    return list(reversed([size - 7 - i * step for i in range(n - 1)] + [6]))


MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Grid:
    def __init__(self, ver):
        self.size = size = ver * 4 + 17
        self.dark = [[False] * size for _ in range(size)]
        self.fixed = [[False] * size for _ in range(size)]
        for i in range(size):                               # timing patterns
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for x, y in ((3, 3), (size - 4, 3), (3, size - 4)):    # finder patterns
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    if 0 <= x + dx < size and 0 <= y + dy < size:
                        self.set(x + dx, y + dy, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _alignment_positions(ver, size)
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, len(pos) - 1), (len(pos) - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)                                      # reserves the format areas

    def set(self, x, y, dark):
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def format(self, mask):
        data = FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        size = self.size
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, size - 15 + i, bit(i))
        self.set(8, size - 8, True)

    def place(self, words):
        size, i = self.size, 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = size - 1 - vert if upward else vert
                    if not self.fixed[y][x] and i < len(words) * 8:
                        self.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def masked(self, mask):
        g = _Grid.__new__(_Grid)
        g.size, g.fixed = self.size, self.fixed
        g.dark = [[d != (not f and MASKS[mask](x, y)) for x, (d, f) in enumerate(zip(row, frow))]
                  for y, (row, frow) in enumerate(zip(self.dark, self.fixed))]
        g.format(mask)
        return g

    def penalty(self):
        size, dark, score = self.size, self.dark, 0
        lines = dark + [list(col) for col in zip(*dark)]
        for line in lines:
            run, prev = 0, None
            for d in line:
                run = run + 1 if d == prev else 1
                prev = d
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            s = "".join("1" if d else "0" for d in line)
            for pattern in ("10111010000", "00001011101"):
                start = s.find(pattern)
                while start != -1:
                    score += 40
                    start = s.find(pattern, start + 1)
        for y in range(size - 1):
            for x in range(size - 1):
                if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        total = size * size
        n = sum(map(sum, dark))
        score += abs(n * 20 - total * 10) // total * 10
        return score


def encode(text):
    """The QR code of text, as rows of booleans (True: dark)."""
    data = text.encode("utf-8")
    for ver in range(1, 7):
        if len(data) + 2 <= _data_codewords(ver):
            break
    else:
        raise ValueError("too long for a QR code here: %d bytes" % len(data))
    grid = _Grid(ver)
    grid.place(_codewords(data, ver))
    best = min((grid.masked(m) for m in range(8)), key=lambda g: g.penalty())
    return best.dark


def svg(text, quiet=4):
    """The QR code of text as an SVG image with a quiet zone."""
    rows = encode(text)
    n = len(rows) + 2 * quiet
    path = "".join("M%d %dh1v1h-1z" % (x + quiet, y + quiet)
                   for y, row in enumerate(rows) for x, d in enumerate(row) if d)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="%d" height="%d" fill="#fff"/><path d="%s" fill="#000"/></svg>' % (n, n, n, n, path))
