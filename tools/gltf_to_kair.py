"""Convert a rigged, animated .glb (Blender / Mixamo export) to ZeusLab KAIR.

    python3 tools/gltf_to_kair.py zeus.glb out/Zeus [--height 1.0]
        [--rename "Armature|mixamo.com|Layer0=Idle"] [--clips Idle,Run,...]

Writes into the output folder:
    model.bin.gz     KAIR model the lab loads (ImportedModels/<Folder>/)
    <material>.png   one texture per glTF material with a base color texture
    materials.txt    mesh-name=texture.png map read by RealModelLab

Conventions handled here so they never have to be fixed in-game:
  * glTF right-handed -> Unity left-handed (mirror X, flip winding)
  * glTF UV top-left origin -> Unity bottom-left (v = 1 - v)
  * armature/parent node transforms (e.g. Mixamo's 0.01 scale or Blender's
    -90deg X) are folded into the root bone so the rig stands upright
  * clips resampled to the lab's fixed 30 FPS, quaternions kept continuous
  * weights normalised to 4 influences
  * optional uniform rescale so the character stands --height units tall
  * KAIR meshes are named after their material so materials.txt lines up
"""

import argparse
import io
import json
import math
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kair  # noqa: E402

COMP = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
NORM_DIV = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}

MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])


class Gltf:
    def __init__(self, path):
        raw = open(path, "rb").read()
        if raw[:4] == b"glTF":
            off = 12
            self.json, self.bin = None, b""
            while off < len(raw):
                ln, kind = struct.unpack_from("<I4s", raw, off)
                chunk = raw[off + 8:off + 8 + ln]
                if kind == b"JSON":
                    self.json = json.loads(chunk)
                elif kind == b"BIN\0":
                    self.bin = chunk
                off += 8 + ln
            self.base = os.path.dirname(path)
        else:
            self.json = json.loads(raw)
            self.bin = None
            self.base = os.path.dirname(path)
        self._buffers = {}

    def buffer(self, i):
        if i not in self._buffers:
            b = self.json["buffers"][i]
            if "uri" not in b:
                self._buffers[i] = self.bin
            elif b["uri"].startswith("data:"):
                import base64
                self._buffers[i] = base64.b64decode(b["uri"].split(",", 1)[1])
            else:
                self._buffers[i] = open(os.path.join(self.base, b["uri"]), "rb").read()
        return self._buffers[i]

    def view_bytes(self, vi):
        v = self.json["bufferViews"][vi]
        buf = self.buffer(v["buffer"])
        o = v.get("byteOffset", 0)
        return buf[o:o + v["byteLength"]], v.get("byteStride")

    def accessor(self, ai):
        a = self.json["accessors"][ai]
        n, nc = a["count"], NCOMP[a["type"]]
        dt = np.dtype(COMP[a["componentType"]])
        if "bufferView" in a:
            data, stride = self.view_bytes(a["bufferView"])
            o = a.get("byteOffset", 0)
            item = dt.itemsize * nc
            if stride and stride != item:
                rows = [np.frombuffer(data, dt, nc, o + i * stride) for i in range(n)]
                arr = np.array(rows)
            else:
                arr = np.frombuffer(data, dt, n * nc, o).reshape(n, nc)
        else:
            arr = np.zeros((n, nc), dt)
        if "sparse" in a:
            sp = a["sparse"]
            idt = np.dtype(COMP[sp["indices"]["componentType"]])
            ib, _ = self.view_bytes(sp["indices"]["bufferView"])
            idx = np.frombuffer(ib, idt, sp["count"], sp["indices"].get("byteOffset", 0))
            vb, _ = self.view_bytes(sp["values"]["bufferView"])
            val = np.frombuffer(vb, dt, sp["count"] * nc, sp["values"].get("byteOffset", 0))
            arr = arr.copy()
            arr[idx] = val.reshape(-1, nc)
        if a.get("normalized") and a["componentType"] in NORM_DIV:
            arr = arr.astype(np.float64) / NORM_DIV[a["componentType"]]
        return arr


# ------------------------------------------------------------------ helpers


def node_local(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    return kair.pose_to_mat4(tuple(t) + tuple(r) + tuple(s))


def to_unity(m):
    return MIRROR @ m @ MIRROR


def continuous(qs):
    """Flip quaternion signs so consecutive frames stay in one hemisphere."""
    qs = qs.copy()
    for i in range(1, len(qs)):
        if np.dot(qs[i], qs[i - 1]) < 0:
            qs[i] = -qs[i]
    return qs


def sample(times, values, t, interp, is_rot):
    if len(times) == 1 or t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    i = int(np.searchsorted(times, t, side="right") - 1)
    t0, t1 = times[i], times[i + 1]
    a, b = values[i], values[i + 1]
    if interp == "STEP":
        return a
    u = (t - t0) / max(t1 - t0, 1e-9)
    if not is_rot:
        return a + (b - a) * u
    if np.dot(a, b) < 0:
        b = -b
    d = min(1.0, float(np.dot(a, b)))
    if d > 0.9995:
        q = a + (b - a) * u
    else:
        th = math.acos(d)
        q = (math.sin((1 - u) * th) * a + math.sin(u * th) * b) / math.sin(th)
    return q / np.linalg.norm(q)


# ------------------------------------------------------------------ convert


def convert(src, out_dir, height=None, renames=None, keep_clips=None, quiet=False):
    g = Gltf(src)
    J = g.json
    nodes = J.get("nodes", [])
    log = (lambda *a: None) if quiet else print

    parent = [-1] * len(nodes)
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i

    local = [node_local(n) for n in nodes]
    world = [None] * len(nodes)

    def wm(i):
        if world[i] is None:
            world[i] = local[i] if parent[i] < 0 else wm(parent[i]) @ local[i]
        return world[i]

    for i in range(len(nodes)):
        wm(i)

    skins = J.get("skins", [])
    if len(skins) > 1:
        log("WARN: %d skins found, using the union of all joints" % len(skins))

    joint_nodes = []
    for s in skins:
        for j in s["joints"]:
            if j not in joint_nodes:
                joint_nodes.append(j)

    # Unskinned meshes parented under a joint (props) are bound rigidly to it.
    mesh_nodes = [i for i, n in enumerate(nodes) if "mesh" in n]
    if not joint_nodes:
        log("No skin found: creating a single Root bone.")
    joint_set = set(joint_nodes)

    # ---- bones
    bones = []
    bone_of_node = {}
    synthetic_root = not joint_nodes
    if synthetic_root:
        bones.append(kair.Bone("Root", -1, np.eye(4), kair.IDENTITY_POSE))

    def joint_parent(n):
        p = parent[n]
        while p >= 0 and p not in joint_set:
            p = parent[p]
        return p

    # Pre-transform of non-joint ancestors for each root joint
    root_pre = {}
    for k, n in enumerate(joint_nodes):
        bone_of_node[n] = k
    for n in joint_nodes:
        jp = joint_parent(n)
        if jp < 0:
            root_pre[n] = wm(parent[n]) if parent[n] >= 0 else np.eye(4)
        else:
            # Non-joint nodes between two joints are folded in as well.
            pre, p = np.eye(4), parent[n]
            while p != jp:
                pre = local[p] @ pre
                p = parent[p]
            root_pre[n] = pre if not np.allclose(pre, np.eye(4)) else None

    # Inverse bind matrices from the skins (fallback: inverse rest world).
    ibm = {}
    for s in skins:
        if "inverseBindMatrices" in s:
            mats = g.accessor(s["inverseBindMatrices"]).astype(np.float64)
            for j, m in zip(s["joints"], mats):
                ibm.setdefault(j, m.reshape(4, 4).T)
    for n in joint_nodes:
        ibm.setdefault(n, np.linalg.inv(wm(n)))

    def joint_local_matrix(n, lm):
        pre = root_pre.get(n)
        return lm if pre is None else pre @ lm

    for n in joint_nodes:
        jp = joint_parent(n)
        name = nodes[n].get("name", "joint%d" % n)
        rest = kair.mat4_to_pose(to_unity(joint_local_matrix(n, local[n])))
        bones.append(kair.Bone(name, bone_of_node[jp] if jp >= 0 else -1,
                               to_unity(ibm[n]), rest))

    # ---- meshes
    images = {}
    meshes_out = []
    materials = J.get("materials", [])
    name_count = {}

    def mesh_name(prim, node, mesh):
        if "material" in prim:
            base = materials[prim["material"]].get("name") or "Material%d" % prim["material"]
        else:
            base = mesh.get("name") or node.get("name") or "Mesh"
        base = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in base)
        k = name_count.get(base, 0)
        name_count[base] = k + 1
        return base if k == 0 else "%s_%d" % (base, k)

    for ni in mesh_nodes:
        node = nodes[ni]
        mesh = J["meshes"][node["mesh"]]
        skinned = "skin" in node
        if skinned:
            sk_joints = skins[node["skin"]]["joints"]
            remap = np.array([bone_of_node[j] for j in sk_joints], dtype=np.int32)
            xf = np.eye(4)  # glTF: skinned mesh node transform is ignored
        else:
            # rigid attach to nearest joint ancestor (or synthetic root)
            p = ni
            while p >= 0 and p not in joint_set:
                p = parent[p]
            rigid_bone = bone_of_node[p] if p >= 0 else 0
            # vertices go to rest-pose model space; the joint's bindpose
            # then carries them into bone space exactly like skinned verts
            xf = wm(ni)
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                log("skip non-triangle primitive in %s" % mesh.get("name"))
                continue
            at = prim["attributes"]
            pos = g.accessor(at["POSITION"]).astype(np.float64)
            nv = len(pos)
            nrm = g.accessor(at["NORMAL"]).astype(np.float64) if "NORMAL" in at else None
            uv = g.accessor(at["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in at else np.zeros((nv, 2))
            if skinned and "JOINTS_0" in at:
                jt = remap[g.accessor(at["JOINTS_0"]).astype(np.int64)]
                wt = g.accessor(at["WEIGHTS_0"]).astype(np.float64)
                if "JOINTS_1" in at:
                    # keep the 4 strongest of 8 influences
                    jt2 = remap[g.accessor(at["JOINTS_1"]).astype(np.int64)]
                    wt2 = g.accessor(at["WEIGHTS_1"]).astype(np.float64)
                    jall = np.concatenate([jt, jt2], 1)
                    wall = np.concatenate([wt, wt2], 1)
                    order = np.argsort(-wall, axis=1)[:, :4]
                    jt = np.take_along_axis(jall, order, 1)
                    wt = np.take_along_axis(wall, order, 1)
            else:
                jt = np.zeros((nv, 4), np.int64)
                jt[:, 0] = 0 if skinned else rigid_bone
                wt = np.zeros((nv, 4))
                wt[:, 0] = 1.0

            # transform rigid props into rest-pose world space
            if not skinned:
                pos = (xf[:3, :3] @ pos.T).T + xf[:3, 3]
                if nrm is not None:
                    nrm = (np.linalg.inv(xf[:3, :3]).T @ nrm.T).T

            if "indices" in prim:
                idx = g.accessor(prim["indices"]).reshape(-1).astype(np.int64)
            else:
                idx = np.arange(nv)
            idx = idx.reshape(-1, 3)

            if nrm is None:
                fn = np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]])
                nrm = np.zeros_like(pos)
                for k in range(3):
                    np.add.at(nrm, idx[:, k], fn)

            # mirror X and reverse winding
            pos = pos * [-1, 1, 1]
            nrm = nrm * [-1, 1, 1]
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
            uv = np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1)
            idx = idx[:, [0, 2, 1]].reshape(-1)

            ws = wt.sum(1, keepdims=True)
            wt = np.where(ws > 0, wt / np.maximum(ws, 1e-9), [[1, 0, 0, 0]])
            jt = np.where(wt > 0, jt, 0)

            name = mesh_name(prim, node, mesh)
            meshes_out.append(kair.Mesh(name, pos[idx], nrm[idx], uv[idx], jt[idx], wt[idx]))

            if "material" in prim:
                mat = materials[prim["material"]]
                tex = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
                if tex is not None:
                    images[name] = J["textures"][tex["index"]]["source"]
                else:
                    f = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.8, 0.8, 0.8, 1])
                    images[name] = ("color", tuple(f))

    # ---- animations
    clips = {}
    renames = renames or {}
    for ai, anim in enumerate(J.get("animations", [])):
        raw_name = anim.get("name") or "Clip%d" % ai
        name = renames.get(raw_name, raw_name.split("|")[-1] if "|" in raw_name and raw_name not in renames else raw_name)
        if keep_clips and name not in keep_clips:
            continue
        chans = {}
        dur = 0.0
        for ch in anim["channels"]:
            tgt = ch["target"]
            if tgt.get("node") not in joint_set:
                continue
            smp = anim["samplers"][ch["sampler"]]
            t = g.accessor(smp["input"]).reshape(-1).astype(np.float64)
            v = g.accessor(smp["output"]).astype(np.float64)
            interp = smp.get("interpolation", "LINEAR")
            if interp == "CUBICSPLINE":
                v = v.reshape(len(t), 3, -1)[:, 1]
                interp = "LINEAR"
            chans[(tgt["node"], tgt["path"])] = (t, v, interp)
            dur = max(dur, float(t[-1]))
        t0 = min((c[0][0] for c in chans.values()), default=0.0)
        dur -= t0
        nf = max(1, int(round(dur * kair.FPS)) + 1)
        frames = np.empty((nf, len(bones), 10), np.float32)
        for bi, b in enumerate(bones):
            frames[:, bi] = b.rest
        for bi, n in enumerate(joint_nodes):
            bi += 1 if synthetic_root else 0
            nd = nodes[n]
            base_t = nd.get("translation", [0, 0, 0])
            base_r = nd.get("rotation", [0, 0, 0, 1])
            base_s = nd.get("scale", [1, 1, 1])
            if "matrix" in nd:
                p = kair.mat4_to_pose(local[n])
                base_t, base_r, base_s = p[0:3], p[3:7], p[7:10]
            has = any((n, k) in chans for k in ("translation", "rotation", "scale"))
            if not has:
                continue
            qs = []
            for f in range(nf):
                tt = t0 + f / kair.FPS
                tr = sample(*chans[(n, "translation")][:2], tt, chans[(n, "translation")][2], False) if (n, "translation") in chans else np.array(base_t)
                rr = sample(*chans[(n, "rotation")][:2], tt, chans[(n, "rotation")][2], True) if (n, "rotation") in chans else np.array(base_r)
                ss = sample(*chans[(n, "scale")][:2], tt, chans[(n, "scale")][2], False) if (n, "scale") in chans else np.array(base_s)
                lm = kair.pose_to_mat4(tuple(tr) + tuple(rr) + tuple(ss))
                p = kair.mat4_to_pose(to_unity(joint_local_matrix(n, lm)))
                frames[f, bi] = p
                qs.append(p[3:7])
            frames[:, bi, 3:7] = continuous(np.array(qs))
        clips[name] = frames
        log("clip %-20s -> %-10s frames=%d" % (raw_name, name, nf))

    model = kair.Model(bones, clips, meshes_out)

    # ---- optional rescale to a target height (rest pose)
    if height:
        sk = kair.skin(model, kair.rest_poses(model))
        ys = np.concatenate([p[:, 1] for _, p, _ in sk]) if sk else np.array([0, 1])
        h = float(ys.max() - ys.min())
        if h > 1e-6:
            s = height / h
            log("rescale x%.4f (rest height %.3f -> %.3f)" % (s, h, height))
            for b in model.bones:
                r = list(b.rest)
                r[0:3] = [x * s for x in r[0:3]]
                b.rest = tuple(r)
                b.bindpose[:3, 3] *= s
            for fr in model.clips.values():
                fr[..., 0:3] *= s
            for m in model.meshes:
                m.positions *= s

    # ---- write
    os.makedirs(out_dir, exist_ok=True)
    kair.save(model, os.path.join(out_dir, "model.bin.gz"))
    lines = []
    written = {}
    from PIL import Image
    for mesh_nm, src_img in images.items():
        if isinstance(src_img, tuple):
            col = tuple(int(round(max(0, min(1, c)) * 255)) for c in src_img[1])
            key = ("color", col)
            if key not in written:
                fn = "color_%02x%02x%02x.png" % col[:3]
                Image.new("RGBA", (4, 4), col).save(os.path.join(out_dir, fn))
                written[key] = fn
        else:
            key = src_img
            if key not in written:
                img = J["images"][src_img]
                if "bufferView" in img:
                    data, _ = g.view_bytes(img["bufferView"])
                elif img.get("uri", "").startswith("data:"):
                    import base64
                    data = base64.b64decode(img["uri"].split(",", 1)[1])
                else:
                    data = open(os.path.join(g.base, img["uri"]), "rb").read()
                fn = "".join(ch if ch.isalnum() or ch in "_-" else "_"
                             for ch in (img.get("name") or "tex%d" % src_img)) + ".png"
                Image.open(io.BytesIO(data)).convert("RGBA").save(os.path.join(out_dir, fn))
                written[key] = fn
        lines.append("%s=%s" % (mesh_nm, written[key]))
    with open(os.path.join(out_dir, "materials.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    errors, warnings = kair.validate(model)
    log(kair.summary(model))
    for w in warnings:
        log("  WARN ", w)
    for e in errors:
        log("  ERROR", e)
    return model, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--height", type=float, default=None,
                    help="rescale so rest pose is this tall (Janna/lab scale is ~1.0)")
    ap.add_argument("--rename", action="append", default=[],
                    help="SOURCE=TARGET clip rename, repeatable")
    ap.add_argument("--clips", default=None, help="comma list of clip names to keep")
    a = ap.parse_args()
    renames = dict(r.split("=", 1) for r in a.rename)
    keep = set(a.clips.split(",")) if a.clips else None
    _, errors = convert(a.src, a.out_dir, a.height, renames, keep)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
