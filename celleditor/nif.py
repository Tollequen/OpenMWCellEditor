"""Renderable geometry and material bits of a Morrowind NIF (4.0.0.2)."""
import re
import struct

NODE_TYPES = {b'NiNode', b'NiBSAnimationNode', b'NiBSParticleNode', b'AvoidNode', b'NiBillboardNode', b'NiSwitchNode'}
GEOM_TYPES = {b'NiTriShape', b'NiTriStrips'}
FIELDLESS = {b'NiAlphaAccumulator', b'NiClusterAccumulator'}        # blocks with no fields after their type name


class R:
    """Little-endian cursor over a byte string."""
    def __init__(s, d, p): s.d = d; s.p = p
    def u16(s): v = struct.unpack_from('<H', s.d, s.p)[0]; s.p += 2; return v
    def u32(s): v = struct.unpack_from('<I', s.d, s.p)[0]; s.p += 4; return v
    def i32(s): v = struct.unpack_from('<i', s.d, s.p)[0]; s.p += 4; return v
    def f(s, n=1):
        v = struct.unpack_from('<%df' % n, s.d, s.p); s.p += 4 * n; return v
    def str(s): n = s.u32(); v = s.d[s.p:s.p + n]; s.p += n; return v


def block_starts(d):
    """Block offsets and types: NIF 4.0.0.2 has no block size table, so find the type names."""
    hp = d.index(b'\n') + 1
    count = struct.unpack_from('<I', d, hp + 4)[0]
    found, p = [], hp + 8
    for m in re.finditer(rb'(?:Ni|RootCollisionNode|AvoidNode|BS)', d[p:]):
        s = p + m.start()
        ln = struct.unpack_from('<I', d, s - 4)[0]
        if 3 <= ln <= 40 and d[s:s + ln].isalpha():
            found.append((s - 4, d[s:s + ln]))
    if len(found) <= count:
        return found
    # Extra matches are object names that look like types; a name directly follows its block's type
    starts = []
    for pos, t in found:
        prev = starts[-1] if starts else None
        if prev and pos == prev[0] + 4 + len(prev[1]) and prev[1] not in FIELDLESS:
            continue
        starts.append((pos, t))
    return starts


I3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _mm(A, B):
    """3x3 matrices as row-major 9-tuples: A @ B."""
    return tuple(A[i * 3] * B[j] + A[i * 3 + 1] * B[3 + j] + A[i * 3 + 2] * B[6 + j] for i in range(3) for j in range(3))


def _mv(A, v):
    return (A[0] * v[0] + A[1] * v[1] + A[2] * v[2], A[3] * v[0] + A[4] * v[1] + A[5] * v[2],
            A[6] * v[0] + A[7] * v[1] + A[8] * v[2])


def _xform(flat, M, s=1.0, t=(0.0, 0.0, 0.0)):
    """s * (M @ v) + t for every xyz of a flat list, flat out."""
    a, b, c, d, e, f, g, h, i = (m * s for m in M)
    tx, ty, tz = t
    out = []
    for k in range(0, len(flat), 3):
        x, y, z = flat[k], flat[k + 1], flat[k + 2]
        out += (a * x + b * y + c * z + tx, d * x + e * y + f * z + ty, g * x + h * y + i * z + tz)
    return out


def _avobject(r):
    """Reads NiObjectNET + NiAVObject fields; returns flags, transform, property refs."""
    name = r.str(); r.i32(); r.i32()
    flags = r.u16()
    t = r.f(3); M = r.f(9); s = r.f()[0]
    r.f(3)
    props = [r.i32() for _ in range(r.u32())]
    if r.u32():
        r.u32(); r.f(3); r.f(9); r.f(3)
    return name, flags, t, M, s, props


def _parse(d):
    hp = d.index(b'\n') + 1
    _, nb = struct.unpack_from('<II', d, hp)
    starts = block_starts(d)
    if len(starts) != nb:
        raise ValueError('block count mismatch %d vs %d' % (len(starts), nb))
    blocks = {}
    for i, (p, t) in enumerate(starts):
        r = R(d, p + 4 + len(t))
        b = {'type': t}
        try:
            if t in NODE_TYPES or t in GEOM_TYPES or t == b'RootCollisionNode':
                b['name'], b['flags'], b['t'], b['R'], b['s'], b['props'] = _avobject(r)
                if t in GEOM_TYPES:
                    b['data'] = r.i32()
                else:
                    b['children'] = [r.i32() for _ in range(r.u32())]
                    if t == b'NiSwitchNode':             # then effect refs and the index of the child shown first
                        [r.i32() for _ in range(r.u32())]
                        b['initial'] = r.u32()
            elif t in (b'NiTriShapeData', b'NiTriStripsData'):
                nv = r.u16()
                b['verts'] = r.f(3 * nv) if r.u32() else ()
                b['normals'] = r.f(3 * nv) if r.u32() else None
                r.f(4)
                b['colors'] = r.f(4 * nv) if r.u32() else None
                nuv = r.u16()
                has_uv = r.u32()
                uvs = [r.f(2 * nv) for _ in range(nuv)] if has_uv else []
                b['uv'] = uvs[0] if uvs else None
                if t == b'NiTriShapeData':
                    nt = r.u16(); r.u32()
                    b['tris'] = struct.unpack_from('<%dH' % (3 * nt), d, r.p) if nt else ()
                else:
                    r.u16(); ns = r.u16(); lens = [r.u16() for _ in range(ns)]
                    tl = []
                    for L in lens:
                        st = struct.unpack_from('<%dH' % L, d, r.p); r.p += 2 * L
                        for k in range(L - 2):
                            a, b_, c = st[k], st[k + 1], st[k + 2]
                            if a != b_ and b_ != c and a != c:
                                tl += (a, b_, c) if k % 2 == 0 else (a, c, b_)
                    b['tris'] = tl
            elif t == b'NiTexturingProperty':
                r.str(); r.i32(); r.i32(); r.u16()
                r.u32(); r.u32()                     # apply mode, texture count
                b['base'] = r.i32() if r.u32() else -1
            elif t == b'NiSourceTexture':
                r.str(); r.i32(); r.i32()
                external = r.d[r.p]; r.p += 1
                b['file'] = r.str().decode('latin1') if external else None
            elif t == b'NiAlphaProperty':
                r.str(); r.i32(); r.i32()
                b['aflags'] = r.u16(); b['threshold'] = r.d[r.p]
            elif t == b'NiMaterialProperty':
                r.str(); r.i32(); r.i32(); r.u16()
                r.f(3); b['diffuse'] = r.f(3); r.f(3); b['emissive'] = r.f(3); r.f(); b['alpha'] = r.f()[0]
            elif t == b'NiStencilProperty':
                r.str(); r.i32(); r.i32(); r.u16()
                r.p += 1 + 4 * 6
                b['draw_mode'] = r.u32()
        except (struct.error, IndexError):
            pass
        blocks[i] = b
    return blocks


def _source_file(blocks, ref):
    return blocks.get(ref, {}).get('file')


def attach_light(d):
    """Where a light's mesh has its AttachLight node (OpenMW puts the light there): (x, y, z), or None."""
    blocks = _parse(d)
    root = blocks.get(0)
    if not root or 'children' not in root:
        return None

    def find(i, M, t, s):
        b = blocks.get(i)
        if b is None or 't' not in b:
            return None
        M2 = _mm(M, b['R']); t2 = tuple(t[k] + s * v for k, v in enumerate(_mv(M, b['t']))); s2 = s * b['s']
        if b.get('name', b'').lower() == b'attachlight':
            return t2
        for c in b.get('children', []):
            found = find(c, M2, t2, s2) if c >= 0 else None
            if found:
                return found
        return None

    # the root's own transform is dropped, as in shapes()
    M, t, s = (root['R'], root['t'], root['s']) if root.get('name', b'').lower() == b'bip01' \
        else (I3, (0.0, 0.0, 0.0), 1.0)
    for c in root['children']:
        found = find(c, M, t, s) if c >= 0 else None
        if found:
            return found
    return None


def shapes(d):
    """The shapes in a NIF file's bytes: dicts of flat vertex lists, texture and material values."""
    blocks = _parse(d)
    out = []

    def walk(i, M, t, s, props):
        b = blocks.get(i)
        if b is None or 't' not in b or b['type'] == b'RootCollisionNode' or (b['flags'] & 1):
            return
        M2 = _mm(M, b['R']); t2 = tuple(t[k] + s * v for k, v in enumerate(_mv(M, b['t']))); s2 = s * b['s']
        p2 = dict(props)
        for pr in b['props']:
            pb = blocks.get(pr)
            if pb:
                p2[pb['type']] = pb
        if 'children' in b:
            kids = b['children']
            if b['type'] == b'NiSwitchNode':        # a switch node shows one child: the initial one
                k = b.get('initial', 0)
                kids = kids[k:k + 1] if 0 <= k < len(kids) else kids[:1]
            for c in kids:
                if c >= 0:
                    walk(c, M2, t2, s2, p2)
            return
        dd = blocks.get(b.get('data', -1))
        if not dd or len(dd.get('tris', [])) == 0 or len(dd['verts']) == 0:
            return
        tex = p2.get(b'NiTexturingProperty')
        texture = _source_file(blocks, tex['base']) if tex and tex.get('base', -1) >= 0 else None
        al = p2.get(b'NiAlphaProperty')
        mat = p2.get(b'NiMaterialProperty')
        st = p2.get(b'NiStencilProperty')
        aflags = al['aflags'] if al and 'aflags' in al else 0
        out.append({
            'pos': _xform(dd['verts'], M2, s2, t2),
            'normal': None if dd['normals'] is None else _xform(dd['normals'], M2),
            'uv': dd['uv'], 'color': dd['colors'], 'index': dd['tris'],
            'texture': texture,
            'blend': bool(aflags & 1),
            'alpha_test': (al['threshold'] / 255.0) if (aflags & 0x200) else None,
            'double_sided': bool(st and st.get('draw_mode') == 3),
            'diffuse': tuple(mat['diffuse']) if mat and 'diffuse' in mat else (1.0, 1.0, 1.0),
            'emissive': tuple(mat['emissive']) if mat and 'emissive' in mat else (0.0, 0.0, 0.0),
            'alpha': mat['alpha'] if mat and 'alpha' in mat else 1.0,
        })

    root = blocks[0]
    if root.get('type') == b'RootCollisionNode':
        return out
    props = {}
    for pr in root.get('props', []):
        if blocks.get(pr):
            props[blocks[pr]['type']] = blocks[pr]
    if 'children' in root:
        # OpenMW drops a root node's own transform, except Bip01's (components/nif/node.cpp, NiNode::read)
        M, t, s = (root['R'], root['t'], root['s']) if root.get('name', b'').lower() == b'bip01' \
            else (I3, (0.0, 0.0, 0.0), 1.0)
        for c in root['children']:
            if c >= 0:
                walk(c, M, t, s, props)
    elif 'data' in root:
        # a mesh that is only a shape keeps its transform (e.g. contain_crate_01, 32 below its origin)
        walk(0, I3, (0.0, 0.0, 0.0), 1.0, {})
    return out
