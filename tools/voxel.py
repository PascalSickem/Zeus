"""Voxel helpers: MagicaVoxel .vox I/O, greedy meshing, baked-shade palette.

Character voxel space (what rig.json and the sculpt code use):
    +Y up, character faces +Z, character's RIGHT is -X,
    voxel (x,y,z) occupies [x,x+1) x [y,y+1) x [z,z+1).
MagicaVoxel is Z-up; parts are stored rotated (see write_vox) with an anchor
in rig.json, so a part edited in MagicaVoxel drops straight back in place.

The lab renders with Unlit/Texture, so lighting is baked: every face picks a
palette cell = (color, brightness level). Brightness comes from the face
direction (top bright, bottom dark) and a per-face ambient-occlusion count.
"""

import struct

import numpy as np

# face directions: normal, (u axis, v axis) for quad construction
DIRS = [
    ((1, 0, 0), 0.84), ((-1, 0, 0), 0.84),
    ((0, 1, 0), 1.12), ((0, -1, 0), 0.66),
    ((0, 0, 1), 1.00), ((0, 0, -1), 0.72),
]
LEVELS = 16          # brightness rows in the palette texture
CELL = 4             # pixels per palette cell (sampled at centre: no bleed)
BMIN, BMAX = 0.40, 1.25


def level_of(b):
    return int(round((np.clip(b, BMIN, BMAX) - BMIN) / (BMAX - BMIN) * (LEVELS - 1)))


def brightness_of(level):
    return BMIN + (BMAX - BMIN) * level / (LEVELS - 1)


# ------------------------------------------------------------------ .vox I/O


def write_vox(path, voxels, palette):
    """voxels: {(x,y,z): idx 1..255} in character space. palette: idx -> (r,g,b).
    Returns the anchor [x_min, y_min, z_max] that read_vox needs to put the
    part back in place.

    Mapping is a pure rotation (no mirror), so MagicaVoxel shows the part
    exactly as it looks in game: vox_x = x - x_min, vox_y = z_max - z,
    vox_z = y - y_min. MagicaVoxel keeps voxel coordinates when a model is
    resized, so growing a part never shifts the voxels already there.
    """
    if not voxels:
        raise ValueError("empty part")
    x0 = min(v[0] for v in voxels)
    y0 = min(v[1] for v in voxels)
    z1 = max(v[2] for v in voxels)
    loc = {(x - x0, z1 - z, y - y0): c for (x, y, z), c in voxels.items()}
    sx = max(v[0] for v in loc) + 1
    sy = max(v[1] for v in loc) + 1
    sz = max(v[2] for v in loc) + 1
    if max(sx, sy, sz) > 256:
        raise ValueError("part larger than MagicaVoxel's 256 limit")
    data = bytearray(struct.pack("<i", len(loc)))
    for (vx, vy, vz), c in sorted(loc.items()):
        data += struct.pack("<4B", vx, vy, vz, c)
    rgba = bytearray()
    for i in range(1, 257):
        r, g, b = palette.get(i, (0, 0, 0)) if i < 256 else (0, 0, 0)
        rgba += struct.pack("<4B", r, g, b, 255)

    def chunk(cid, content, children=b""):
        return cid + struct.pack("<2i", len(content), len(children)) + content + children

    body = chunk(b"SIZE", struct.pack("<3i", sx, sy, sz)) + chunk(b"XYZI", bytes(data)) + chunk(b"RGBA", bytes(rgba))
    with open(path, "wb") as f:
        f.write(b"VOX " + struct.pack("<i", 150) + chunk(b"MAIN", b"", body))
    return [x0, y0, z1]


def read_vox(path, anchor=(0, 0, 0)):
    """Return (voxels {(x,y,z): idx} in character space, palette {idx: rgb})."""
    raw = open(path, "rb").read()
    if raw[:4] != b"VOX ":
        raise ValueError("%s is not a .vox file" % path)
    x0, y0, z1 = anchor
    voxels = {}
    palette = None
    models = 0

    def walk(off, end):
        nonlocal palette, models
        while off < end:
            cid = raw[off:off + 4]
            n, m = struct.unpack_from("<2i", raw, off + 4)
            c = off + 12
            if cid == b"MAIN":
                walk(c + n, c + n + m)
            elif cid == b"XYZI":
                models += 1
                if models == 1:
                    (cnt,) = struct.unpack_from("<i", raw, c)
                    for k in range(cnt):
                        vx, vy, vz, ci = struct.unpack_from("<4B", raw, c + 4 + 4 * k)
                        voxels[(x0 + vx, y0 + vz, z1 - vy)] = ci
            elif cid == b"RGBA":
                palette = {}
                for i in range(255):
                    r, g, b, a = struct.unpack_from("<4B", raw, c + 4 * i)
                    palette[i + 1] = (r, g, b)
            off = c + n + m

    walk(8, len(raw))
    if models > 1:
        print("WARN %s: %d models in file, only the first is used" % (path, models))
    if palette is None:
        raise ValueError("%s has no palette (save it from MagicaVoxel)" % path)
    return voxels, palette


# ------------------------------------------------------------------ meshing


def mesh_part(voxels, origin, key_of, scale, bone_index, ao=True):
    """Greedy-mesh one part.

    voxels: {(x,y,z): idx} local coords; origin: part offset in character
    voxel space; key_of(idx, brightness) -> palette cell (col,row) hashable.
    Returns dict of arrays: pos[n,3], nrm[n,3], cell[n] (per vertex), idx[m].
    """
    if not voxels:
        return None
    occ = set(voxels)
    pos, nrm, cells, tri = [], [], [], []
    xs = np.array(list(occ))
    lo = xs.min(0) - 1
    hi = xs.max(0) + 2

    for (n, shade) in DIRS:
        n = np.array(n)
        ax = int(np.nonzero(n)[0][0])
        u_ax, v_ax = [a for a in range(3) if a != ax]
        # build per-slice masks of face keys
        for d in range(lo[ax], hi[ax]):
            mask = {}
            for (p, c) in voxels.items():
                if p[ax] != d:
                    continue
                q = list(p)
                q[ax] += n[ax]
                if tuple(q) in occ:
                    continue
                b = shade
                if ao:
                    # count solid voxels around the air cell in the face plane
                    k = 0
                    for du in (-1, 0, 1):
                        for dv in (-1, 0, 1):
                            if du == 0 and dv == 0:
                                continue
                            r = list(q)
                            r[u_ax] += du
                            r[v_ax] += dv
                            if tuple(r) in occ:
                                k += 1 if (du == 0 or dv == 0) else 0.5
                    b *= 1.0 - 0.055 * min(k, 6)
                mask[(p[u_ax], p[v_ax])] = key_of(c, b)
            # greedy rectangles
            done = set()
            for (u, v) in sorted(mask):
                if (u, v) in done:
                    continue
                key = mask[(u, v)]
                w = 1
                while (u + w, v) in mask and (u + w, v) not in done and mask[(u + w, v)] == key:
                    w += 1
                h = 1
                while all((u + i, v + h) in mask and (u + i, v + h) not in done
                          and mask[(u + i, v + h)] == key for i in range(w)):
                    h += 1
                for i in range(w):
                    for j in range(h):
                        done.add((u + i, v + j))
                # quad corners
                plane = d + (1 if n[ax] > 0 else 0)
                corners = []
                for (cu, cv) in ((u, v), (u + w, v), (u + w, v + h), (u, v + h)):
                    c3 = [0, 0, 0]
                    c3[ax] = plane
                    c3[u_ax] = cu
                    c3[v_ax] = cv
                    corners.append((np.array(c3, float) + origin) * scale)
                base = len(pos)
                pos.extend(corners)
                nrm.extend([n.astype(float)] * 4)
                cells.extend([key] * 4)
                # winding: counter-clockwise seen from outside (glTF)
                e1 = corners[1] - corners[0]
                e2 = corners[2] - corners[0]
                if np.dot(np.cross(e1, e2), n) > 0:
                    tri += [base, base + 1, base + 2, base, base + 2, base + 3]
                else:
                    tri += [base, base + 2, base + 1, base, base + 3, base + 2]
    return dict(pos=np.array(pos), nrm=np.array(nrm), cell=cells, idx=np.array(tri, np.int64),
                bone=bone_index)


class Palette:
    """Collects (rgb, emissive) colors -> columns; rows are brightness levels."""

    def __init__(self):
        self.cols = []
        self.index = {}

    def key(self, rgb, emissive, brightness):
        k = (tuple(rgb), bool(emissive))
        if k not in self.index:
            self.index[k] = len(self.cols)
            self.cols.append(k)
        col = self.index[k]
        if emissive:
            # glow: keep near full brightness, only a hint of form
            brightness = 1.0 + (brightness - 1.0) * 0.25
        return (col, level_of(brightness))

    def uv(self, cell):
        col, row = cell
        w = max(1, len(self.cols)) * CELL
        h = LEVELS * CELL
        # glTF UV: v measured from the top of the image
        return ((col * CELL + CELL / 2) / w, (row * CELL + CELL / 2) / h)

    def image(self):
        from PIL import Image
        w = max(1, len(self.cols)) * CELL
        img = np.zeros((LEVELS * CELL, w, 3), np.uint8)
        for c, (rgb, em) in enumerate(self.cols):
            base = np.array(rgb, float)
            for r in range(LEVELS):
                b = brightness_of(r)
                if b <= 1.0:
                    # shadows shift slightly cool, like the game's ambient
                    col = base * b + np.array([6, 8, 22]) * (1 - b)
                else:
                    col = base + (255 - base) * (b - 1.0) * 1.2
                img[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = np.clip(col, 0, 255)
        return Image.fromarray(img, "RGB")
