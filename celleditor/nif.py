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


def _transform(r):
    """NiTransform (rotation, translation, scale) as an affine (3x3 with the scale in it, translation)."""
    M = r.f(9); t = r.f(3); s = r.f()[0]
    return tuple(m * s for m in M), t


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
                    b['skin'] = r.i32()
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
            elif t == b'NiSkinInstance':
                b['skin_data'] = r.i32(); r.i32()
                b['bones'] = [r.i32() for _ in range(r.u32())]
            elif t == b'NiSkinData':
                b['xform'] = _transform(r)
                nb = r.u32(); r.i32()                   # bone count, partition ref
                b['bone_info'] = []
                for _ in range(nb):
                    xf = _transform(r); r.f(4)          # bounding sphere
                    nw = r.u16()
                    w = struct.unpack_from('<' + 'Hf' * nw, d, r.p) if nw else ()
                    r.p += 6 * nw
                    b['bone_info'].append((xf, w))
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


def parse(d):
    """A NIF's blocks, to pass to skeleton() or part_shapes() more than once."""
    return _parse(d)


def _shapes(blocks):
    """(shape dict, geometry block, data block) for each shape, placed in the file's space."""
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
        out.append(({
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
        }, b, dd))

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


def shapes(d):
    """The shapes in a NIF file's bytes: dicts of flat vertex lists, texture and material values."""
    return [sh for sh, _, _ in _shapes(_parse(d))]


# --- Actors ------------------------------------------------------------------------------
# Affine transforms are (3x3 row-major with the scale in it, translation).

def _aff_mul(A, B):
    return _mm(A[0], B[0]), tuple(a + b for a, b in zip(_mv(A[0], B[1]), A[1]))


def _aff_apply(A, flat, normals=False):
    M, t = A
    return _xform(flat, M) if normals else _xform(flat, M, 1.0, t)


def skeleton(d):
    """{bone name (lower case): affine in the skeleton's space} of a skeleton NIF, e.g. base_anim.nif."""
    blocks = _parse(d) if isinstance(d, (bytes, bytearray, memoryview)) else d
    out = {}

    def walk(i, A):
        b = blocks.get(i)
        if b is None or 'children' not in b:
            return
        A2 = _aff_mul(A, (tuple(m * b['s'] for m in b['R']), b['t']))
        out.setdefault(b['name'].decode('latin1').lower(), A2)
        for c in b['children']:
            if c >= 0:
                walk(c, A2)

    root = blocks.get(0, {})
    keep = root.get('name', b'').lower() == b'bip01'
    A = (tuple(m * root['s'] for m in root['R']), root['t']) if keep else (I3, (0.0, 0.0, 0.0))
    if keep:
        out['bip01'] = A
    for c in root.get('children', []):
        if c >= 0:
            walk(c, A)
    return out


def _matches(name, filt):
    n = name.decode('latin1').lower()
    return n.startswith(filt) or (n.startswith('tri ') and n[4:].startswith(filt))


def part_shapes(d, bones, bone, filt):
    """A body part's shapes in the skeleton's space, attached as OpenMW does (components/sceneutil/attach.cpp):
    a skinned file gives its skinned shapes named like the filter, bound to the skeleton's bones; any other
    hangs on the bone (mirrored on a "Left" bone). d: the file's bytes or its parsed blocks."""
    blocks = _parse(d) if isinstance(d, (bytes, bytearray, memoryview)) else d
    found = _shapes(blocks)
    filt = filt.lower()
    out = []
    if any(b.get('skin', -1) >= 0 for _, b, _ in found):
        for sh, b, dd in found:
            inst = blocks.get(b.get('skin', -1))
            data = inst and blocks.get(inst.get('skin_data', -1))
            if not data or 'bone_info' not in data or not _matches(b['name'], filt):
                continue
            nv = len(dd['verts']) // 3
            acc = [[0.0] * 9 + [0.0] * 3 for _ in range(nv)]     # summed weighted 3x3 and translation per vertex
            hit = [False] * nv
            for ref, (inv_bind, weights) in zip(inst['bones'], data['bone_info']):
                A = bones.get(blocks.get(ref, {}).get('name', b'').decode('latin1').lower())
                if A is None:
                    continue
                M, t = _aff_mul(A, inv_bind)
                for k in range(0, len(weights), 2):
                    v, w = weights[k], weights[k + 1]
                    if v < nv:
                        a = acc[v]
                        for j in range(9):
                            a[j] += M[j] * w
                        for j in range(3):
                            a[9 + j] += t[j] * w
                        hit[v] = True
            pos, nor = [], [] if dd['normals'] is not None else None
            for v in range(nv):
                x, y, z = dd['verts'][3 * v:3 * v + 3]
                if not hit[v]:
                    pos += (x, y, z)
                    if nor is not None:
                        nor += dd['normals'][3 * v:3 * v + 3]
                    continue
                a = acc[v]
                pos += (a[0] * x + a[1] * y + a[2] * z + a[9], a[3] * x + a[4] * y + a[5] * z + a[10],
                        a[6] * x + a[7] * y + a[8] * z + a[11])
                if nor is not None:
                    p, q, r = dd['normals'][3 * v:3 * v + 3]
                    nor += (a[0] * p + a[1] * q + a[2] * r, a[3] * p + a[4] * q + a[5] * r,
                            a[6] * p + a[7] * q + a[8] * r)
            out.append(dict(sh, pos=pos, normal=nor))
        return out
    A = bones.get(bone.lower())
    if A is None:
        return out
    offset = next((b['t'] for b in blocks.values() if b.get('name', b'').lower() == b'boneoffset'), None)
    mirror = 'left' in bone.lower()
    local = (((-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0) if mirror else I3), offset or (0.0, 0.0, 0.0))
    A = _aff_mul(A, local)
    for sh, _, _ in found:
        idx = sh['index']
        if mirror:                                   # the mirror turns triangles inside out: wind them back
            idx = [idx[k + j] for k in range(0, len(idx), 3) for j in (0, 2, 1)]
        out.append(dict(sh, pos=_aff_apply(A, sh['pos']), index=idx,
                        normal=None if sh['normal'] is None else _aff_apply(A, sh['normal'], True)))
    return out
