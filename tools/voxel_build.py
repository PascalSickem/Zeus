"""Build a rigged, animated .glb from MagicaVoxel parts + rig.json + anims.py.

    python3 tools/voxel_build.py zeus/rig.json build/zeus_voxel.glb
    python3 tools/gltf_to_kair.py build/zeus_voxel.glb build/ImportedModels/Zeus

Each .vox part is rigidly bound to its bone (how voxel heroes are animated).
Faces are greedy-meshed, shading + ambient occlusion are baked into one
palette texture (the lab renders unlit). Emissive palette indices (glow)
go to a separate "FX"-free look: they keep full brightness.

Meshes: "Body" (everything on non-FX bones) and "FX" (lightning geometry),
both sharing the palette texture, so the game/lab can toggle FX separately.
"""

import importlib.util
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel  # noqa: E402
from make_zeus_blockout import GlbWriter, q_euler  # noqa: E402

FPS = 30


def load_anims(path):
    spec = importlib.util.spec_from_file_location("zeus_anims", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CLIPS


def build(rig_path, out_path, quiet=False):
    base = os.path.dirname(os.path.abspath(rig_path))
    rig = json.load(open(rig_path))
    sc = float(rig["voxel_scale"])
    emissive = set(rig.get("emissive_indices", []))
    bones = rig["bones"]
    names = [b["name"] for b in bones]
    bi = {n: i for i, n in enumerate(names)}
    pivot = {b["name"]: np.array(b["pivot"], float) for b in bones}
    rest_pivot = {b["name"]: np.array(b.get("rest_pivot", b["pivot"]), float) for b in bones}
    rest_scale = {b["name"]: float(b.get("rest_scale", 1.0)) for b in bones}
    parent = {b["name"]: b["parent"] for b in bones}
    fx_bones = {b["name"] for b in bones if "rest_scale" in b}

    def descends_from_fx(n):
        while n:
            if n in fx_bones:
                return True
            n = parent[n]
        return False

    # ---- mesh all parts
    pal = voxel.Palette()
    groups = {"Body": [], "FX": []}
    for part in rig["parts"]:
        vox, colors = voxel.read_vox(os.path.join(base, part["file"]), part["anchor"])
        bone = part["bone"]
        if bone not in bi:
            raise ValueError("part %s targets unknown bone %s" % (part["file"], bone))

        def key_of(c, b, colors=colors):
            return pal.key(colors.get(c, (255, 0, 255)), c in emissive, b)
        m = voxel.mesh_part(vox, np.zeros(3), key_of, sc, bi[bone])
        if m is not None:
            groups["FX" if descends_from_fx(bone) else "Body"].append(m)

    w = GlbWriter()
    J = w.j
    png = pal.image()
    import io
    buf = io.BytesIO()
    png.save(buf, "PNG")
    J["images"] = [{"name": "Zeus_Palette", "mimeType": "image/png", "bufferView": w.view(buf.getvalue())}]
    J["samplers"] = [{"magFilter": 9728, "minFilter": 9728}]
    J["textures"] = [{"source": 0, "sampler": 0}]
    J["materials"] = []
    prims = []
    tri_total = 0
    for gname, ms in groups.items():
        if not ms:
            continue
        J["materials"].append({"name": gname, "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 1.0}})
        pos, nrm, uv, jt, idx = [], [], [], [], []
        n0 = 0
        for m in ms:
            pos.append(m["pos"])
            nrm.append(m["nrm"])
            uv.append(np.array([pal.uv(c) for c in m["cell"]]))
            jt.append(np.full((len(m["pos"]), 4), [m["bone"], 0, 0, 0]))
            idx.append(m["idx"] + n0)
            n0 += len(m["pos"])
        pos = np.concatenate(pos).astype("<f4")
        idx = np.concatenate(idx).astype("<u4")
        tri_total += len(idx) // 3
        wt = np.zeros((len(pos), 4), "<f4")
        wt[:, 0] = 1
        prims.append({"attributes": {
            "POSITION": w.acc(pos, 5126, "VEC3", 34962, True),
            "NORMAL": w.acc(np.concatenate(nrm).astype("<f4"), 5126, "VEC3", 34962),
            "TEXCOORD_0": w.acc(np.concatenate(uv).astype("<f4"), 5126, "VEC2", 34962),
            "JOINTS_0": w.acc(np.concatenate(jt).astype("<u2"), 5123, "VEC4", 34962),
            "WEIGHTS_0": w.acc(wt, 5126, "VEC4", 34962)},
            "indices": w.acc(idx, 5125, "SCALAR", 34963), "material": len(J["materials"]) - 1})
    J["meshes"] = [{"name": rig.get("name", "Voxel"), "primitives": prims}]

    # ---- skeleton nodes
    nodes = []
    for b in bones:
        n = b["name"]
        par = parent[n]
        t = rest_pivot[n] - (rest_pivot[par] if par else 0)
        node = {"name": n, "translation": (t * sc).tolist()}
        if rest_scale[n] != 1.0:
            node["scale"] = [rest_scale[n]] * 3
        nodes.append(node)
    for b in bones:
        if parent[b["name"]]:
            nodes[bi[parent[b["name"]]]].setdefault("children", []).append(bi[b["name"]])
    ibm = []
    for b in bones:
        p = pivot[b["name"]] * sc
        m = np.eye(4)
        m[:3, 3] = -p
        ibm.append(m.T.reshape(16))
    J["skins"] = [{"name": "Rig", "joints": list(range(len(bones))),
                   "inverseBindMatrices": w.acc(np.array(ibm, "<f4"), 5126, "MAT4"), "skeleton": 0}]
    roots = [bi[b["name"]] for b in bones if not parent[b["name"]]]
    mesh_node = len(nodes)
    nodes.append({"name": rig.get("name", "Voxel") + "Mesh", "mesh": 0, "skin": 0})
    J["nodes"] = nodes
    J["scenes"] = [{"nodes": roots + [mesh_node]}]
    J["scene"] = 0

    # ---- animations
    clips = load_anims(os.path.join(base, rig.get("animations", "anims.py")))
    anims = []
    for cname, dur, fn, loop in clips:
        nf = int(round(dur * FPS)) + (0 if loop else 1)
        frames = [fn(f / FPS) for f in range(nf)]
        used = sorted({b for fr in frames for b in fr if b in bi}, key=lambda n: bi[n])
        unknown = {b for fr in frames for b in fr} - set(bi)
        if unknown:
            raise ValueError("clip %s animates unknown bones %s" % (cname, sorted(unknown)))
        times = (np.arange(nf) / FPS).astype("<f4")
        tacc = w.acc(times, 5126, "SCALAR", minmax=True)
        samplers, channels = [], []
        for n in used:
            par = parent[n]
            rest_t = rest_pivot[n] - (rest_pivot[par] if par else 0)
            T, R, Sc = [], [], []
            for fr in frames:
                d = fr.get(n, {})
                if "pos" in d:
                    if par and np.any(rest_pivot[par] != 0):
                        raise ValueError("'pos' only allowed on Root children (%s)" % n)
                    t = np.array(d["pos"], float)
                else:
                    t = rest_t + np.array(d.get("t", (0, 0, 0)), float)
                q = q_euler(*d.get("r", (0, 0, 0)))
                if R and np.dot(q, R[-1]) < 0:
                    q = -q
                s = d.get("s", rest_scale[n])
                s = (s, s, s) if np.isscalar(s) else tuple(s)
                T.append(t * sc)
                R.append(q)
                Sc.append(s)
            for path_, arr, typ in (("translation", T, "VEC3"), ("rotation", R, "VEC4"), ("scale", Sc, "VEC3")):
                arr = np.array(arr, float)
                samplers.append({"input": tacc, "output": w.acc(arr.astype("<f4"), 5126, typ),
                                 "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": bi[n], "path": path_}})
        anims.append({"name": cname, "samplers": samplers, "channels": channels})
    J["animations"] = anims
    w.write(out_path)
    info = {"bones": len(bones), "parts": len(rig["parts"]), "triangles": tri_total,
            "colors": len(pal.cols), "clips": [c[0] for c in clips]}
    if not quiet:
        print(info)
    return info


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    build(sys.argv[1], sys.argv[2])
    print("wrote", sys.argv[2])
