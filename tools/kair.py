"""KAIR rigged-model format: reader, writer, validator.

Mirrors KairReader in lab/step7/MyModScript.cs exactly:

    gzip(
      magic[4]  "KAIR" (also accepted: QIYR, EVLR, ZEDR)
      int32 version (=1), boneCount, clipCount, meshCount
      bones[boneCount]:
        text name, int32 parent, float32[16] bindpose (row-major m00..m33),
        pose rest
      clips[clipCount]:
        text name, int32 frameCount,
        frames[frameCount]: float32 time (ignored), pose[boneCount]
      meshes[meshCount]:
        text name, int32 vertexCount (non-indexed triangle list),
        vertices[vertexCount]:
          float32[3] position, float32[3] normal, float32[2] uv,
          int32[4] bone indices, float32[4] weights
    )
    text = int32 byteLength + UTF-8 bytes
    pose = float32[3] position, float32[4] rotation (x,y,z,w), float32[3] scale

All coordinates are Unity space (left-handed, +Y up). The lab samples clips
at a fixed 30 FPS and locks the root bone's position.

Usage:  python3 tools/kair.py inspect model.bin.gz
"""

import gzip
import math
import struct
import sys

import numpy as np

FPS = 30
MAGICS = ("KAIR", "QIYR", "EVLR", "ZEDR")

# pose = (px,py,pz, qx,qy,qz,qw, sx,sy,sz)
IDENTITY_POSE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)


class Bone:
    def __init__(self, name, parent, bindpose, rest):
        self.name = name
        self.parent = parent
        self.bindpose = np.asarray(bindpose, dtype=np.float64).reshape(4, 4)
        self.rest = tuple(float(x) for x in rest)


class Mesh:
    def __init__(self, name, positions, normals, uvs, joints, weights):
        self.name = name
        self.positions = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        self.normals = np.asarray(normals, dtype=np.float32).reshape(-1, 3)
        self.uvs = np.asarray(uvs, dtype=np.float32).reshape(-1, 2)
        self.joints = np.asarray(joints, dtype=np.int32).reshape(-1, 4)
        self.weights = np.asarray(weights, dtype=np.float32).reshape(-1, 4)


class Model:
    def __init__(self, bones=None, clips=None, meshes=None, magic="KAIR"):
        self.magic = magic
        self.bones = bones or []
        # name -> float32 array [frames, bones, 10]
        self.clips = clips or {}
        self.meshes = meshes or []


# ---------------------------------------------------------------- reading


def load(path):
    data = gzip.open(path).read()
    off = 0

    def rd(fmt):
        nonlocal off
        v = struct.unpack_from("<" + fmt, data, off)
        off += struct.calcsize("<" + fmt)
        return v

    def text():
        nonlocal off
        (n,) = rd("i")
        if n < 0 or n > 1024 * 1024:
            raise ValueError("bad string length %d at %d" % (n, off))
        s = data[off:off + n].decode("utf-8")
        off += n
        return s

    magic = data[:4].decode("ascii", "replace")
    if magic not in MAGICS:
        raise ValueError("unsupported magic %r" % magic)
    off = 4
    version, nb, nc, nm = rd("4i")
    if version != 1:
        raise ValueError("unsupported version %d" % version)

    bones = []
    for _ in range(nb):
        name = text()
        (parent,) = rd("i")
        bind = rd("16f")
        rest = rd("10f")
        bones.append(Bone(name, parent, bind, rest))

    clips = {}
    for _ in range(nc):
        name = text()
        (nf,) = rd("i")
        arr = np.empty((nf, nb, 10), dtype=np.float32)
        for f in range(nf):
            rd("f")
            arr[f] = np.frombuffer(data, "<f4", nb * 10, off).reshape(nb, 10)
            off += nb * 40
        clips[name] = arr

    vdt = np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("uv", "<f4", 2),
                    ("j", "<i4", 4), ("w", "<f4", 4)])
    meshes = []
    for _ in range(nm):
        name = text()
        (nv,) = rd("i")
        v = np.frombuffer(data, vdt, nv, off)
        off += nv * vdt.itemsize
        meshes.append(Mesh(name, v["p"], v["n"], v["uv"], v["j"], v["w"]))

    m = Model(bones, clips, meshes, magic)
    m.trailing = len(data) - off
    m.raw_size = len(data)
    return m


# ---------------------------------------------------------------- writing


def save(model, path):
    out = bytearray()

    def text(s):
        b = s.encode("utf-8")
        out.extend(struct.pack("<i", len(b)))
        out.extend(b)

    nb = len(model.bones)
    out.extend(model.magic.encode("ascii"))
    out.extend(struct.pack("<4i", 1, nb, len(model.clips), len(model.meshes)))

    for b in model.bones:
        text(b.name)
        out.extend(struct.pack("<i", b.parent))
        out.extend(struct.pack("<16f", *b.bindpose.reshape(16)))
        out.extend(struct.pack("<10f", *b.rest))

    for name, frames in model.clips.items():
        frames = np.asarray(frames, dtype="<f4")
        assert frames.shape[1:] == (nb, 10), (name, frames.shape)
        text(name)
        out.extend(struct.pack("<i", frames.shape[0]))
        for f in range(frames.shape[0]):
            out.extend(struct.pack("<f", f / FPS))
            out.extend(frames[f].tobytes())

    vdt = np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("uv", "<f4", 2),
                    ("j", "<i4", 4), ("w", "<f4", 4)])
    for m in model.meshes:
        text(m.name)
        nv = len(m.positions)
        out.extend(struct.pack("<i", nv))
        v = np.empty(nv, vdt)
        v["p"], v["n"], v["uv"], v["j"], v["w"] = (
            m.positions, m.normals, m.uvs, m.joints, m.weights)
        out.extend(v.tobytes())

    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(bytes(out))


# ---------------------------------------------------------------- math


def quat_to_mat3(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def mat3_to_quat(m):
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s,
             (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s,
             (m[2, 1] - m[1, 2]) / s)
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s,
             (m[0, 2] - m[2, 0]) / s)
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s,
             (m[1, 0] - m[0, 1]) / s)
    return q


def pose_to_mat4(p):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat3(p[3:7]) * np.asarray(p[7:10])
    m[:3, 3] = p[0:3]
    return m


def mat4_to_pose(m):
    sx = np.linalg.norm(m[:3, 0])
    sy = np.linalg.norm(m[:3, 1])
    sz = np.linalg.norm(m[:3, 2])
    if np.linalg.det(m[:3, :3]) < 0:
        sx = -sx
    r = m[:3, :3] / np.array([sx, sy, sz])
    q = mat3_to_quat(r)
    return (m[0, 3], m[1, 3], m[2, 3], q[0], q[1], q[2], q[3], sx, sy, sz)


def world_matrices(model, poses):
    """poses: [bones,10] local poses -> list of 4x4 world matrices."""
    nb = len(model.bones)
    world = [None] * nb
    local = [pose_to_mat4(poses[i]) for i in range(nb)]

    def get(i):
        if world[i] is None:
            p = model.bones[i].parent
            world[i] = local[i] if p < 0 else get(p) @ local[i]
        return world[i]

    for i in range(nb):
        get(i)
    return world


def skin(model, poses, lock_root=True):
    """Return list of (mesh, skinned positions, skinned normals)."""
    poses = np.array(poses, dtype=np.float64)
    if lock_root:
        for i, b in enumerate(model.bones):
            if b.parent < 0:
                poses[i, 0:3] = b.rest[0:3]
    world = world_matrices(model, poses)
    skm = np.stack([world[i] @ b.bindpose for i, b in enumerate(model.bones)])
    out = []
    for m in model.meshes:
        j = np.clip(m.joints, 0, len(model.bones) - 1)
        w = m.weights.astype(np.float64)
        mats = (skm[j] * w[..., None, None]).sum(axis=1)  # [v,4,4]
        p = np.einsum("vij,vj->vi", mats[:, :3, :3], m.positions) + mats[:, :3, 3]
        n = np.einsum("vij,vj->vi", mats[:, :3, :3], m.normals)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        out.append((m, p, n))
    return out


def rest_poses(model):
    return np.array([b.rest for b in model.bones], dtype=np.float64)


# ---------------------------------------------------------------- validation


def validate(model):
    """Return (errors, warnings) lists of strings."""
    errors, warnings = [], []
    nb = len(model.bones)
    names = [b.name for b in model.bones]

    if len(set(names)) != nb:
        errors.append("duplicate bone names")
    roots = [b.name for b in model.bones if b.parent < 0]
    if not roots:
        errors.append("no root bone")
    if len(roots) > 1:
        warnings.append("multiple root bones: %s" % roots)
    for i, b in enumerate(model.bones):
        if b.parent >= nb:
            errors.append("bone %s parent out of range" % b.name)
    # cycles
    for i in range(nb):
        seen, p = set(), i
        while p >= 0:
            if p in seen:
                errors.append("bone hierarchy cycle at %s" % names[i])
                break
            seen.add(p)
            p = model.bones[p].parent if p < nb else -1

    for b in model.bones:
        if not np.all(np.isfinite(b.bindpose)):
            errors.append("non-finite bindpose on %s" % b.name)

    used = np.zeros(nb, bool)
    total_tris = 0
    for m in model.meshes:
        nv = len(m.positions)
        if nv % 3:
            errors.append("mesh %s vertex count %d not a multiple of 3" % (m.name, nv))
        total_tris += nv // 3
        if nv <= 3:
            warnings.append("mesh %s is an empty placeholder (%d verts)" % (m.name, nv))
            continue
        if not np.all(np.isfinite(m.positions)):
            errors.append("mesh %s has non-finite positions" % m.name)
        bad = (m.joints < 0) | (m.joints >= nb)
        if np.any(bad & (m.weights > 0)):
            errors.append("mesh %s references bones out of range" % m.name)
        ws = m.weights.sum(axis=1)
        if np.any(np.abs(ws - 1) > 0.01):
            warnings.append("mesh %s: %d verts with weights not summing to 1"
                            % (m.name, int(np.sum(np.abs(ws - 1) > 0.01))))
        if np.any((m.uvs < -0.01) | (m.uvs > 1.01)):
            warnings.append("mesh %s has UVs outside 0..1 (texture will tile)" % m.name)
        jj = np.clip(m.joints, 0, nb - 1)
        used[jj[m.weights > 0]] = True

    if total_tris < 500:
        warnings.append("only %d triangles total: blockout-level detail" % total_tris)

    for name, fr in model.clips.items():
        if fr.shape[0] == 0:
            errors.append("clip %s has no frames" % name)
            continue
        if not np.all(np.isfinite(fr)):
            errors.append("clip %s has non-finite values" % name)
        q = fr[..., 3:7]
        qn = np.linalg.norm(q, axis=-1)
        if np.any(np.abs(qn - 1) > 0.02):
            warnings.append("clip %s has unnormalized rotations" % name)

    unused = nb - int(used.sum())
    if model.meshes and unused > max(8, nb // 2):
        warnings.append("%d of %d bones influence no vertices (rig heavier than mesh)"
                        % (unused, nb))
    return errors, warnings


def summary(model):
    lines = []
    lines.append("magic=%s bones=%d clips=%d meshes=%d"
                 % (model.magic, len(model.bones), len(model.clips), len(model.meshes)))
    for name, fr in model.clips.items():
        lines.append("  clip %-12s frames=%4d  (%.2fs @30fps)" % (name, fr.shape[0], fr.shape[0] / FPS))
    tris = 0
    for m in model.meshes:
        tris += len(m.positions) // 3
        if len(m.positions) > 3:
            p = m.positions
            lines.append("  mesh %-14s tris=%6d  y=[%.2f..%.2f]"
                         % (m.name, len(p) // 3, p[:, 1].min(), p[:, 1].max()))
        else:
            lines.append("  mesh %-14s (empty placeholder)" % m.name)
    lines.append("  total triangles=%d" % tris)
    return "\n".join(lines)


def main(argv):
    if len(argv) < 3 or argv[1] != "inspect":
        print(__doc__)
        return 2
    rc = 0
    for path in argv[2:]:
        m = load(path)
        print("==", path)
        print(summary(m))
        errors, warnings = validate(m)
        for w in warnings:
            print("  WARN ", w)
        for e in errors:
            print("  ERROR", e)
        print("  RESULT:", "FAIL" if errors else "OK")
        rc |= bool(errors)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
