"""Object sizes and ray hits in a cell, from the meshes (for the MCP tools; stdlib only)."""
import math

from . import nif

_cache = {}


def rot_matrix(rot):
    """A reference's rotation as rows of a 3x3 matrix: clockwise, turned about z first, then y, then x, as
    OpenMW does (Misc::Convert::makeOsgQuat)."""
    rx, ry, rz = rot
    c, s = math.cos, math.sin
    Rx = ((1, 0, 0), (0, c(rx), s(rx)), (0, -s(rx), c(rx)))
    Ry = ((c(ry), 0, -s(ry)), (0, 1, 0), (s(ry), 0, c(ry)))
    Rz = ((c(rz), s(rz), 0), (-s(rz), c(rz), 0), (0, 0, 1))

    def mul(A, B):
        return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return mul(mul(Rx, Ry), Rz)


def to_world(r, v):
    """A point in an object's own frame -> world."""
    M, s, p = rot_matrix(r["rot"]), r.get("scale") or 1.0, r["pos"]
    return tuple(p[i] + s * (M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2]) for i in range(3))


class Shape:
    """A mesh's triangles in its own frame and its extent."""

    def __init__(self, data):
        self.verts, self.tris = [], []
        for sh in nif.shapes(data) if data else []:
            base = len(self.verts)
            pos = sh["pos"]
            self.verts += [(pos[k], pos[k + 1], pos[k + 2]) for k in range(0, len(pos), 3)]
            idx = sh["index"]
            self.tris += [(base + idx[k], base + idx[k + 1], base + idx[k + 2]) for k in range(0, len(idx) - 2, 3)]
        if self.verts:
            self.lo = tuple(min(v[i] for v in self.verts) for i in range(3))
            self.hi = tuple(max(v[i] for v in self.verts) for i in range(3))
        else:
            self.lo = self.hi = None


def clear():
    _cache.clear()


def shape(path, read):
    """The Shape of a mesh path; read(path) gives its bytes (or None)."""
    key = path.lower()
    if key not in _cache:
        try:
            _cache[key] = Shape(read(path))
        except Exception:
            _cache[key] = Shape(None)
    return _cache[key]


def world_box(r, sh):
    """(min, max) of an object's box in the world (the corners of its own box, turned)."""
    if sh.lo is None:
        p = r["pos"]
        return tuple(v - 8 for v in p), tuple(v + 8 for v in p)
    corners = [to_world(r, (x, y, z)) for x in (sh.lo[0], sh.hi[0]) for y in (sh.lo[1], sh.hi[1])
               for z in (sh.lo[2], sh.hi[2])]
    return tuple(min(c[i] for c in corners) for i in range(3)), tuple(max(c[i] for c in corners) for i in range(3))


def _box_hit(o, d, lo, hi):
    """Distance along the ray to where it enters the box, or None."""
    t0, t1 = 0.0, math.inf
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if o[i] < lo[i] or o[i] > hi[i]:
                return None
            continue
        a, b = (lo[i] - o[i]) / d[i], (hi[i] - o[i]) / d[i]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return None
    return t0


def _tri_hits(sh, o, d, best):
    """The nearest (t, triangle) of a shape along a ray in its own frame, if nearer than best."""
    V = sh.verts
    ox, oy, oz = o
    dx, dy, dz = d
    found = None
    for tri in sh.tris:
        a, b, c = V[tri[0]], V[tri[1]], V[tri[2]]
        e1x, e1y, e1z = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        e2x, e2y, e2z = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        hx, hy, hz = dy * e2z - dz * e2y, dz * e2x - dx * e2z, dx * e2y - dy * e2x
        det = e1x * hx + e1y * hy + e1z * hz
        if -1e-9 < det < 1e-9:
            continue
        f = 1.0 / det
        sx, sy, sz = ox - a[0], oy - a[1], oz - a[2]
        u = f * (sx * hx + sy * hy + sz * hz)
        if u < 0 or u > 1:
            continue
        qx, qy, qz = sy * e1z - sz * e1y, sz * e1x - sx * e1z, sx * e1y - sy * e1x
        v = f * (dx * qx + dy * qy + dz * qz)
        if v < 0 or u + v > 1:
            continue
        t = f * (e2x * qx + e2y * qy + e2z * qz)
        if 1e-3 < t < best:
            best, found = t, (e1x, e1y, e1z, e2x, e2y, e2z)
    return best, found


def raycast(objects, o, d, max_dist=20000.0):
    """The first object surface hit: {t, point, normal, ref}, or None.

    objects: [(ref, Shape)] with ref pos/rot/scale. The ray starts at o, along d."""
    n = math.sqrt(sum(v * v for v in d)) or 1.0
    d = tuple(v / n for v in d)
    cands = []
    for r, sh in objects:
        if sh.lo is None:
            continue
        lo, hi = world_box(r, sh)
        t = _box_hit(o, d, lo, hi)
        if t is not None and t < max_dist:
            cands.append((t, r, sh))
    cands.sort(key=lambda c: c[0])
    best, hit = max_dist, None
    for t0, r, sh in cands:
        if t0 > best:
            break
        M, s, p = rot_matrix(r["rot"]), r.get("scale") or 1.0, r["pos"]
        rel = tuple(o[i] - p[i] for i in range(3))
        # into the object's frame: M is orthonormal, so its transpose undoes it; scale keeps distances in t
        lo_ = tuple(sum(M[k][i] * rel[k] for k in range(3)) / s for i in range(3))
        ld = tuple(sum(M[k][i] * d[k] for k in range(3)) / s for i in range(3))
        t, tri = _tri_hits(sh, lo_, ld, best)
        if tri:
            best = t
            e1, e2 = tri[:3], tri[3:]
            nl = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            nw = tuple(sum(M[i][k] * nl[k] for k in range(3)) for i in range(3))
            ln = math.sqrt(sum(v * v for v in nw)) or 1.0
            nw = tuple(v / ln for v in nw)
            if sum(nw[i] * d[i] for i in range(3)) > 0:       # facing the ray
                nw = tuple(-v for v in nw)
            hit = {"t": t, "point": tuple(o[i] + t * d[i] for i in range(3)), "normal": nw, "ref": r}
    return hit


def terrain_hit(height_at, o, d, max_dist=20000.0, step=32.0):
    """Where a ray first goes below the terrain: {t, point}, or None. height_at(x, y) -> z."""
    n = math.sqrt(sum(v * v for v in d)) or 1.0
    d = tuple(v / n for v in d)

    def below(t):
        p = tuple(o[i] + t * d[i] for i in range(3))
        return p[2] < height_at(p[0], p[1])
    if below(0.0):
        return None
    t = 0.0
    while t < max_dist:
        t2 = t + step
        if below(t2):
            a, b = t, t2
            for _ in range(12):
                m = (a + b) / 2
                a, b = (a, m) if below(m) else (m, b)
            return {"t": b, "point": tuple(o[i] + b * d[i] for i in range(3)), "normal": (0.0, 0.0, 1.0), "ref": None}
        t = t2
    return None
