"""Generate an ORIGINAL Zeus blockout as a rigged, animated .glb.

    python3 tools/make_zeus_blockout.py out/zeus_blockout.glb

Everything here is authored from scratch (geometry, 30-bone rig, clips), so
it carries no third-party IP and can be shipped. It is a *blockout*: the
goal is a correct, clean-animating stand-in that proves the whole pipeline
(glb -> gltf_to_kair -> KAIR -> RealModelLab) and gives the final artist a
rig, proportions and clip timings to match. Open the .glb in Blender to
refine or replace the mesh while keeping the skeleton and clip names.

glTF space: +Y up, character faces +Z, character's RIGHT side is -X.

Shading: the lab renders with Unlit/Texture, so each material is a small
toon "matcap" texture and UVs are derived from bind-pose normals. That gives
lit-looking forms under an unlit shader.
"""

import io
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FPS = 30

# --------------------------------------------------------------- skeleton
# name, parent, world rest position (glTF space). Rest rotations are identity.
SKELETON = [
    ("Root", None, (0.0, 0.0, 0.0)),
    ("Pelvis", "Root", (0.0, 0.47, 0.0)),
    ("Spine1", "Pelvis", (0.0, 0.55, 0.0)),
    ("Spine2", "Spine1", (0.0, 0.65, 0.0)),
    ("Neck", "Spine2", (0.0, 0.76, 0.0)),
    ("Head", "Neck", (0.0, 0.81, 0.0)),
    ("Jaw", "Head", (0.0, 0.83, 0.06)),
    ("R_Shoulder", "Spine2", (-0.165, 0.735, 0.0)),
    ("R_Elbow", "R_Shoulder", (-0.205, 0.565, 0.0)),
    ("R_Hand", "R_Elbow", (-0.225, 0.405, 0.02)),
    ("R_Weapon", "R_Hand", (-0.225, 0.375, 0.05)),
    ("L_Shoulder", "Spine2", (0.165, 0.735, 0.0)),
    ("L_Elbow", "L_Shoulder", (0.205, 0.565, 0.0)),
    ("L_Hand", "L_Elbow", (0.225, 0.405, 0.02)),
    ("R_Hip", "Pelvis", (-0.07, 0.45, 0.0)),
    ("R_Knee", "R_Hip", (-0.078, 0.255, 0.012)),
    ("R_Foot", "R_Knee", (-0.08, 0.06, 0.0)),
    ("L_Hip", "Pelvis", (0.07, 0.45, 0.0)),
    ("L_Knee", "L_Hip", (0.078, 0.255, 0.012)),
    ("L_Foot", "L_Knee", (0.08, 0.06, 0.0)),
    ("Skirt_F", "Pelvis", (0.0, 0.47, 0.07)),
    ("Skirt_B", "Pelvis", (0.0, 0.47, -0.07)),
    ("Cape1", "Spine2", (0.0, 0.73, -0.095)),
    ("Cape2", "Cape1", (0.0, 0.52, -0.12)),
    ("Cape3", "Cape2", (0.0, 0.30, -0.14)),
    ("HairBack", "Head", (0.0, 0.86, -0.07)),
    # Attachment points for VFX (no geometry) -- the game/lab can look these up.
    ("FX_BoltTip", "R_Weapon", (-0.225, 0.68, 0.05)),
    ("FX_Chest", "Spine2", (0.0, 0.66, 0.1)),
    ("FX_Overhead", "Root", (0.0, 1.12, 0.0)),
    ("FX_Ground", "Root", (0.0, 0.0, 0.0)),
]
BONE = {n: i for i, (n, _, _) in enumerate(SKELETON)}
WPOS = {n: np.array(p, float) for n, _, p in SKELETON}


# --------------------------------------------------------------- geometry


class Builder:
    def __init__(self):
        self.parts = {}  # material -> lists

    def add(self, mat, pos, nrm, idx, joints, weights):
        p = self.parts.setdefault(mat, dict(pos=[], nrm=[], idx=[], j=[], w=[], n=0))
        p["pos"].append(np.asarray(pos, float))
        p["nrm"].append(np.asarray(nrm, float))
        p["idx"].append(np.asarray(idx, np.int64) + p["n"])
        p["j"].append(np.asarray(joints, np.int64))
        p["w"].append(np.asarray(weights, float))
        p["n"] += len(pos)


def _rigid(n, bone):
    j = np.zeros((n, 4), np.int64)
    j[:, 0] = BONE[bone]
    w = np.zeros((n, 4))
    w[:, 0] = 1
    return j, w


def rot_matrix(rx=0, ry=0, rz=0):
    rx, ry, rz = map(math.radians, (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Z @ Y @ X


def ellipsoid(b, mat, bone, c, r, rot=(0, 0, 0), seg=(14, 10), weights=None, squash=None):
    nu, nv = seg
    R = rot_matrix(*rot)
    pos, nrm = [], []
    for i in range(nv + 1):
        th = math.pi * i / nv
        for k in range(nu + 1):
            ph = 2 * math.pi * k / nu
            d = np.array([math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)])
            if squash:
                d = squash(d)
            p = d * r
            n = d / np.maximum(np.array(r, float), 1e-6)
            pos.append(R @ p + c)
            nrm.append(R @ (n / np.linalg.norm(n)))
    idx = []
    for i in range(nv):
        for k in range(nu):
            a = i * (nu + 1) + k
            bb = a + nu + 1
            idx += [a, a + 1, bb, a + 1, bb + 1, bb]
    pos = np.array(pos)
    j, w = weights(pos) if weights else _rigid(len(pos), bone)
    b.add(mat, pos, nrm, idx, j, w)


def tube(b, mat, pts, radii, bones_w, seg=12, cap=True, wobble=None):
    """Lofted tube through points with per-ring radius (scalar or (rx,rz))."""
    pts = [np.asarray(p, float) for p in pts]
    pos, nrm, idx = [], [], []
    rings = len(pts)
    for i in range(rings):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == rings - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        t /= np.linalg.norm(t)
        ref = np.array([0, 0, 1.0]) if abs(t[2]) < 0.9 else np.array([1.0, 0, 0])
        u = np.cross(t, ref)
        u /= np.linalg.norm(u)
        v = np.cross(u, t)
        rr = radii[i]
        rx, rz = (rr, rr) if np.isscalar(rr) else rr
        for k in range(seg + 1):
            a = 2 * math.pi * k / seg
            f = 1.0 + (wobble(a, i / (rings - 1)) if wobble else 0.0)
            d = u * math.cos(a) * rx * f + v * math.sin(a) * rz * f
            pos.append(pts[i] + d)
            n = u * math.cos(a) / max(rx, 1e-6) + v * math.sin(a) / max(rz, 1e-6)
            nrm.append(n / np.linalg.norm(n))
    for i in range(rings - 1):
        for k in range(seg):
            a = i * (seg + 1) + k
            c = a + seg + 1
            idx += [a, c, a + 1, a + 1, c, c + 1]
    pos = np.array(pos)
    j, w = bones_w(pos)
    b.add(mat, pos, nrm, idx, j, w)


def box(b, mat, bone, c, size, rot=(0, 0, 0)):
    R = rot_matrix(*rot)
    hx, hy, hz = np.array(size) / 2
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
             ((0, 1, 0), (0, 0, 1), (1, 0, 0)), ((0, -1, 0), (0, 0, -1), (1, 0, 0)),
             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (-1, 0, 0), (0, 1, 0))]
    pos, nrm, idx = [], [], []
    for n, u, v in faces:
        n, u, v = map(np.array, (n, u, v))
        base = len(pos)
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p = n * np.array([hx, hy, hz]) + u * su * np.array([hx, hy, hz]) + v * sv * np.array([hx, hy, hz])
            pos.append(R @ p + c)
            nrm.append(R @ n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    pos = np.array(pos)
    j, w = _rigid(len(pos), bone)
    b.add(mat, pos, nrm, idx, j, w)


def extrude(b, mat, bone, outline, depth, origin, rot=(0, 0, 0)):
    """Extrude a 2D polygon (x,y) along z. Fan-triangulated: keep convex-ish."""
    R = rot_matrix(*rot)
    o = np.asarray(origin, float)
    pts = np.array(outline, float)
    n = len(pts)
    pos, nrm, idx = [], [], []
    for side, z in ((1, depth / 2), (-1, -depth / 2)):
        base = len(pos)
        cen = pts.mean(0)
        pos.append(R @ np.array([cen[0], cen[1], z]) + o)
        nrm.append(R @ np.array([0, 0, side]))
        for p in pts:
            pos.append(R @ np.array([p[0], p[1], z]) + o)
            nrm.append(R @ np.array([0, 0, side]))
        for k in range(n):
            a, c = base + 1 + k, base + 1 + (k + 1) % n
            idx += [base, a, c] if side > 0 else [base, c, a]
    for k in range(n):
        p0, p1 = pts[k], pts[(k + 1) % n]
        e = p1 - p0
        nn = np.array([e[1], -e[0], 0.0])
        nn /= max(np.linalg.norm(nn), 1e-9)
        base = len(pos)
        for p, z in ((p0, depth / 2), (p1, depth / 2), (p1, -depth / 2), (p0, -depth / 2)):
            pos.append(R @ np.array([p[0], p[1], z]) + o)
            nrm.append(R @ nn)
        idx += [base, base + 2, base + 1, base, base + 3, base + 2]
    pos = np.array(pos)
    j, w = _rigid(len(pos), bone)
    b.add(mat, pos, nrm, idx, j, w)


def blend_y(pairs):
    """weights by height: pairs = [(y, bone), ...] high to low, linear blend."""
    ys = [p[0] for p in pairs]
    bs = [BONE[p[1]] for p in pairs]

    def f(pos):
        j = np.zeros((len(pos), 4), np.int64)
        w = np.zeros((len(pos), 4))
        for i, p in enumerate(pos):
            y = p[1]
            if y >= ys[0]:
                j[i, 0], w[i, 0] = bs[0], 1
                continue
            if y <= ys[-1]:
                j[i, 0], w[i, 0] = bs[-1], 1
                continue
            for k in range(len(ys) - 1):
                if ys[k] >= y >= ys[k + 1]:
                    t = (ys[k] - y) / (ys[k] - ys[k + 1])
                    t = t * t * (3 - 2 * t)
                    j[i, 0], w[i, 0] = bs[k], 1 - t
                    j[i, 1], w[i, 1] = bs[k + 1], t
                    break
        return j, w
    return f


def rigid(bone):
    return lambda pos: _rigid(len(pos), bone)


def build_mesh():
    b = Builder()
    P = WPOS

    # ---- head & face (Skin)
    ellipsoid(b, "Skin", "Head", P["Head"] + [0, 0.065, 0.005], (0.075, 0.085, 0.078))
    ellipsoid(b, "Skin", "Head", P["Head"] + [0, 0.06, 0.075], (0.014, 0.022, 0.016), seg=(8, 6))  # nose
    for s in (-1, 1):
        ellipsoid(b, "Skin", "Head", P["Head"] + [s * 0.074, 0.065, 0.0], (0.012, 0.022, 0.014), seg=(8, 6))  # ears
    # neck (thick)
    tube(b, "Skin", [P["Spine2"] + [0, 0.07, 0], P["Head"] + [0, 0.04, 0]], [0.05, 0.045], blend_y([(0.80, "Head"), (0.74, "Neck")]))

    # eyes: glowing storm-blue
    for s in (-1, 1):
        ellipsoid(b, "Eyes", "Head", P["Head"] + [s * 0.03, 0.08, 0.068], (0.016, 0.009, 0.008), seg=(8, 6))
    # brows (Hair)
    for s in (-1, 1):
        ellipsoid(b, "Hair", "Head", P["Head"] + [s * 0.032, 0.097, 0.068], (0.026, 0.008, 0.01), rot=(0, 0, s * -12), seg=(8, 5))

    # ---- hair & beard (Hair): big, flowing, white-silver
    ellipsoid(b, "Hair", "Head", P["Head"] + [0, 0.1, -0.012], (0.085, 0.06, 0.085))  # top
    ellipsoid(b, "Hair", "HairBack", P["HairBack"] + [0, -0.03, -0.02], (0.08, 0.1, 0.05))  # back mane
    ellipsoid(b, "Hair", "HairBack", P["HairBack"] + [0, -0.11, -0.03], (0.07, 0.07, 0.04))
    for s in (-1, 1):
        ellipsoid(b, "Hair", "Head", P["Head"] + [s * 0.07, 0.04, -0.01], (0.025, 0.06, 0.05), seg=(10, 8))  # sideburns
    # beard: layered teardrops from the jaw
    ellipsoid(b, "Hair", "Jaw", P["Jaw"] + [0, -0.03, 0.01], (0.07, 0.055, 0.04))
    ellipsoid(b, "Hair", "Jaw", P["Jaw"] + [0, -0.085, 0.015], (0.055, 0.06, 0.035))
    ellipsoid(b, "Hair", "Jaw", P["Jaw"] + [0, -0.135, 0.01], (0.035, 0.045, 0.028))
    ellipsoid(b, "Hair", "Head", P["Head"] + [0, 0.035, 0.072], (0.04, 0.012, 0.012), seg=(8, 5))  # moustache

    # ---- laurel crown (Gold)
    for k in range(13):
        a = math.radians(-150 + k * 25)
        c = P["Head"] + [math.sin(a) * 0.082, 0.118 + 0.01 * math.cos(a), math.cos(a) * 0.082]
        ellipsoid(b, "Gold", "Head", c, (0.012, 0.022, 0.006), rot=(0, math.degrees(a), 25 * (1 if math.sin(a) > 0 else -1)), seg=(6, 5))
    ellipsoid(b, "Gold", "Head", P["Head"] + [0, 0.12, 0.084], (0.014, 0.014, 0.008), seg=(8, 6))  # center gem setting

    # ---- torso (Skin): heroic V shape
    tube(b, "Skin", [P["Pelvis"] + [0, 0.04, 0], P["Spine1"] + [0, 0.02, 0], P["Spine2"] + [0, 0.02, 0], P["Spine2"] + [0, 0.085, 0]],
         [(0.10, 0.07), (0.115, 0.08), (0.15, 0.09), (0.13, 0.07)],
         blend_y([(0.68, "Spine2"), (0.58, "Spine1"), (0.5, "Pelvis")]), seg=16)
    for s in (-1, 1):  # pecs
        ellipsoid(b, "Skin", "Spine2", P["Spine2"] + [s * 0.06, 0.035, 0.07], (0.06, 0.045, 0.03))
    for s in (-1, 1):  # trapezius / deltoids
        ellipsoid(b, "Skin", "Spine2", P["Spine2"] + [s * 0.09, 0.075, -0.005], (0.07, 0.03, 0.05))

    # ---- chiton drape over LEFT shoulder (Cloth) + sash
    tube(b, "Cloth", [P["Pelvis"] + [0, 0.02, 0], P["Spine1"], P["Spine2"] + [0, -0.03, 0]],
         [(0.112, 0.082), (0.125, 0.09), (0.152, 0.096)],
         blend_y([(0.65, "Spine2"), (0.56, "Spine1"), (0.48, "Pelvis")]), seg=16,
         wobble=lambda a, t: 0.03 * math.sin(a * 7))
    ellipsoid(b, "Cloth", "Spine2", P["Spine2"] + [0.07, 0.05, 0.0], (0.07, 0.06, 0.1), rot=(0, 0, -35))  # over L shoulder
    tube(b, "Gold", [P["L_Shoulder"] + [-0.04, 0.02, 0.09], P["Spine2"] + [0, -0.02, 0.1], P["Pelvis"] + [-0.09, 0.06, 0.08]],
         [0.012, 0.012, 0.012], rigid("Spine2"), seg=6)  # sash strap

    # pauldron (Gold) on left shoulder
    ellipsoid(b, "Gold", "L_Shoulder", P["L_Shoulder"] + [0.02, 0.01, 0], (0.06, 0.035, 0.065), rot=(0, 0, -25))
    ellipsoid(b, "Eyes", "L_Shoulder", P["L_Shoulder"] + [0.045, 0.02, 0.0], (0.012, 0.012, 0.012), seg=(8, 6))  # storm gem

    # belt (Gold)
    tube(b, "Gold", [P["Pelvis"] + [0, 0.035, 0], P["Pelvis"] + [0, 0.065, 0]], [(0.118, 0.088), (0.118, 0.088)], rigid("Pelvis"), seg=16)
    ellipsoid(b, "Eyes", "Pelvis", P["Pelvis"] + [0, 0.05, 0.09], (0.02, 0.02, 0.01), seg=(8, 6))  # buckle gem

    # skirt (Cloth): pleated, front/back flaps follow legs
    def skirt_w(pos):
        j = np.zeros((len(pos), 4), np.int64)
        w = np.zeros((len(pos), 4))
        for i, p in enumerate(pos):
            t = np.clip((0.47 - p[1]) / 0.22, 0, 1)
            side = BONE["Skirt_F"] if p[2] >= 0 else BONE["Skirt_B"]
            j[i, 0], w[i, 0] = BONE["Pelvis"], 1 - t
            j[i, 1], w[i, 1] = side, t
        return j, w
    tube(b, "Cloth", [P["Pelvis"] + [0, 0.04, 0], P["Pelvis"] + [0, -0.06, 0], P["Pelvis"] + [0, -0.2, 0.0]],
         [(0.115, 0.085), (0.135, 0.105), (0.15, 0.12)], skirt_w, seg=24,
         wobble=lambda a, t: 0.06 * t * math.sin(a * 10))

    # ---- arms (Skin) with gold bracers
    for s, side in ((-1, "R"), (1, "L")):
        sh, el, ha = P[side + "_Shoulder"], P[side + "_Elbow"], P[side + "_Hand"]
        ellipsoid(b, "Skin", side + "_Shoulder", sh + [s * 0.01, 0, 0], (0.052, 0.05, 0.05))
        tube(b, "Skin", [sh, (sh + el) / 2, el], [0.045, 0.043, 0.034], rigid(side + "_Shoulder"))
        ellipsoid(b, "Skin", side + "_Elbow", el, (0.034, 0.034, 0.034), seg=(10, 8))
        tube(b, "Skin", [el, (el + ha) / 2, ha], [0.034, 0.033, 0.026], rigid(side + "_Elbow"))
        tube(b, "Gold", [el + (ha - el) * 0.3, ha + (el - ha) * 0.12], [0.037, 0.031], rigid(side + "_Elbow"))
        ellipsoid(b, "Skin", side + "_Hand", ha + [0, -0.03, 0.005], (0.03, 0.038, 0.026), seg=(10, 8))  # fist

    # ---- legs
    for s, side in ((-1, "R"), (1, "L")):
        hp, kn, ft = P[side + "_Hip"], P[side + "_Knee"], P[side + "_Foot"]
        tube(b, "Skin", [hp, (hp + kn) / 2, kn], [0.058, 0.052, 0.038], rigid(side + "_Hip"))
        ellipsoid(b, "Skin", side + "_Knee", kn, (0.038, 0.038, 0.038), seg=(10, 8))
        tube(b, "Skin", [kn, (kn + ft) / 2 + [0, 0, -0.008], ft], [0.037, 0.035, 0.026], rigid(side + "_Knee"))
        # sandals: gold greave + sole + straps
        tube(b, "Gold", [kn + (ft - kn) * 0.35, ft + [0, 0.015, 0]], [0.04, 0.03], rigid(side + "_Knee"))
        box(b, "Leather", side + "_Foot", ft + [0, -0.045, 0.035], (0.06, 0.02, 0.13))
        ellipsoid(b, "Skin", side + "_Foot", ft + [0, -0.03, 0.04], (0.03, 0.022, 0.06), seg=(10, 6))

    # ---- cape (Cape): storm-blue, double-sided curved sheet on 3 bones
    cols, rows = 9, 10
    pos, nrm, idx = [], [], []
    top, bot = 0.74, 0.14
    for r in range(rows + 1):
        v = r / rows
        y = top + (bot - top) * v
        half = 0.14 + 0.08 * v
        for c in range(cols + 1):
            u = c / cols * 2 - 1
            x = u * half
            z = -0.10 - 0.05 * v - 0.035 * (1 - u * u) + 0.012 * math.sin(u * 9 + v * 2) * v
            pos.append([x, y, z])
    pos = np.array(pos)
    grid = lambda r, c: r * (cols + 1) + c
    tris = []
    for r in range(rows):
        for c in range(cols):
            a, b2, c2, d = grid(r, c), grid(r, c + 1), grid(r + 1, c), grid(r + 1, c + 1)
            tris += [(a, c2, b2), (b2, c2, d)]
    # normals: outward = -Z (back) for one side, flipped copy for inside
    nr = np.zeros_like(pos)
    for a, c2, b2 in tris:
        fn = np.cross(pos[c2] - pos[a], pos[b2] - pos[a])
        nr[[a, c2, b2]] += fn
    nr /= np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-9)
    if nr[:, 2].mean() > 0:
        nr = -nr
        tris = [(a, b2, c2) for a, c2, b2 in tris]
    cw = blend_y([(0.72, "Cape1"), (0.5, "Cape2"), (0.28, "Cape3")])
    j, w = cw(pos)
    b.add("Cape", pos, nr, np.array(tris).reshape(-1), j, w)
    inner = [(a, c2, b2) for a, b2, c2 in tris]
    b.add("CapeInner", pos + nr * -0.004, -nr, np.array(inner).reshape(-1), j, w)
    # cape clasps
    for s in (-1, 1):
        ellipsoid(b, "Gold", "Spine2", P["Spine2"] + [s * 0.12, 0.085, 0.02], (0.022, 0.022, 0.012), seg=(10, 8))

    # ---- lightning bolt (Bolt) held in right fist, pointing up
    bolt = [(-0.012, -0.10), (0.026, 0.0), (0.006, 0.0), (0.03, 0.09), (0.012, 0.19),
            (-0.014, 0.075), (0.004, 0.075), (-0.02, -0.02), (-0.004, -0.02)]
    bolt = [(x * 1.7, y * 1.7 - 0.03) for x, y in bolt]
    extrude(b, "Bolt", "R_Weapon", bolt, 0.022, P["R_Weapon"] + [0, 0.02, 0])
    extrude(b, "BoltCore", "R_Weapon", [(x * 0.55, y * 0.92 + 0.004) for x, y in bolt], 0.03, P["R_Weapon"] + [0, 0.02, 0])
    return b


# --------------------------------------------------------------- textures

MATERIALS = {
    # name: (base, shadow, highlight, rim)
    "Skin": ((222, 170, 128), (150, 96, 70), (255, 222, 190), (255, 236, 205)),
    "Hair": ((226, 230, 240), (150, 158, 184), (255, 255, 255), (190, 225, 255)),
    "Cloth": ((238, 236, 228), (160, 168, 190), (255, 255, 255), (200, 225, 255)),
    "Gold": ((232, 178, 60), (130, 78, 24), (255, 246, 190), (255, 230, 140)),
    "Leather": ((120, 74, 44), (60, 34, 22), (178, 124, 80), (190, 150, 110)),
    "Cape": ((38, 72, 160), (14, 22, 70), (110, 160, 240), (130, 210, 255)),
    "CapeInner": ((20, 34, 92), (8, 12, 40), (60, 90, 170), (90, 150, 230)),
    "Eyes": ((120, 220, 255), (60, 170, 255), (235, 252, 255), (255, 255, 255)),
    "Bolt": ((255, 226, 90), (255, 170, 40), (255, 255, 220), (255, 255, 255)),
    "BoltCore": ((255, 255, 236), (255, 240, 170), (255, 255, 255), (255, 255, 255)),
}
EMISSIVE = {"Eyes", "Bolt", "BoltCore"}


def matcap(name, size=128):
    base, shadow, hi, rim = (np.array(c, float) for c in MATERIALS[name])
    ys, xs = np.mgrid[0:size, 0:size]
    nx = (xs + 0.5) / size * 2 - 1
    ny = 1 - (ys + 0.5) / size * 2
    r2 = nx * nx + ny * ny
    nz = np.sqrt(np.clip(1 - r2, 0, 1))
    if name in EMISSIVE:
        k = np.clip(0.75 + 0.25 * nz, 0, 1)[..., None]
        col = base * (1 - k) + hi * k
    else:
        L = np.array([-0.45, 0.6, 0.66])
        L /= np.linalg.norm(L)
        d = nx * L[0] + ny * L[1] + nz * L[2]
        # toon bands with soft edges
        s1 = np.clip((d - 0.05) / 0.08, 0, 1)
        s2 = np.clip((d - 0.82) / 0.06, 0, 1)
        col = shadow[None, None] * (1 - s1[..., None]) + base[None, None] * s1[..., None]
        spec = 0.55 if name in ("Gold", "Eyes") else 0.25
        col = col * (1 - spec * s2[..., None]) + hi[None, None] * spec * s2[..., None]
        rimk = np.clip((1 - nz - 0.6) / 0.25, 0, 1) * np.clip(ny * 0.5 + 0.6, 0, 1)
        col = col * (1 - 0.45 * rimk[..., None]) + rim[None, None] * 0.45 * rimk[..., None]
    img = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), "RGB")
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------- animation


def q_euler(x=0.0, y=0.0, z=0.0):
    """Degrees, applied X then Y then Z (q = qz*qy*qx)."""
    def axis(ax, deg):
        h = math.radians(deg) / 2
        v = [0.0, 0.0, 0.0]
        v[ax] = math.sin(h)
        return np.array(v + [math.cos(h)])

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return np.array([aw * bx + ax * bw + ay * bz - az * by,
                         aw * by - ax * bz + ay * bw + az * bx,
                         aw * bz + ax * by - ay * bx + az * bw,
                         aw * bw - ax * bx - ay * by - az * bz])
    return mul(mul(axis(2, z), axis(1, y)), axis(0, x))


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def track(t, keys):
    """keys: [(time, value)], smooth-eased; value scalar or tuple."""
    if t <= keys[0][0]:
        return np.asarray(keys[0][1], float)
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = ease((t - t0) / max(t1 - t0, 1e-9))
            return np.asarray(v0, float) * (1 - u) + np.asarray(v1, float) * u
    return np.asarray(keys[-1][1], float)


S = math.sin
TAU = 2 * math.pi


def base_pose(t, breathe=1.0):
    """Shared upright stance: elbows bent, bolt hand at shoulder height."""
    b = breathe * S(TAU * t / 2.4)
    return {
        "Spine1": (1.5 * b, 0, 0),
        "Spine2": (-1.5 * b, 0, 0),
        "Neck": (0, 0, 0),
        "Head": (2 + b, 0, 0),
        "R_Shoulder": (-12, 0, -16),
        "R_Elbow": (-75, -10, 0),
        "R_Hand": (0, 0, 8),
        "L_Shoulder": (2, 0, 10),
        "L_Elbow": (-14, 0, 0),
        "R_Hip": (0, 0, -3), "L_Hip": (0, 0, 3),
        "Cape1": (6 + 2 * b, 0, 0), "Cape2": (2, 0, 0), "Cape3": (2, 0, 0),
        "HairBack": (3 * b, 0, 0),
    }


def clip_idle(t):
    p = base_pose(t)
    p["Cape2"] = (3 + 3 * S(TAU * t / 2.4 + 1), 0, 2 * S(TAU * t / 2.4))
    p["Cape3"] = (4 + 4 * S(TAU * t / 2.4 + 2), 0, 3 * S(TAU * t / 2.4 + 1))
    p["R_Weapon"] = (0, 18 * S(TAU * t / 2.4), 0)
    p["__pelvis_y"] = 0.004 * S(TAU * t / 2.4 * 2)
    return p


def clip_run(t, T=0.6):
    ph = TAU * t / T
    p = base_pose(t, 0.3)
    p["Spine1"] = (10, 6 * S(ph), 0)
    p["Spine2"] = (4, 6 * S(ph), 0)
    p["Head"] = (-8, -6 * S(ph), 0)
    p["R_Hip"] = (-38 * S(ph), 0, -3)
    p["L_Hip"] = (38 * S(ph), 0, 3)
    p["R_Knee"] = (45 + 40 * S(ph + 1.6), 0, 0)
    p["L_Knee"] = (45 + 40 * S(ph + 1.6 + math.pi), 0, 0)
    p["R_Foot"] = (-10 * S(ph + 1.6), 0, 0)
    p["L_Foot"] = (-10 * S(ph + 1.6 + math.pi), 0, 0)
    p["R_Shoulder"] = (-20 - 18 * S(ph + math.pi), 0, -18)
    p["R_Elbow"] = (-80, -10, 0)
    p["L_Shoulder"] = (35 * S(ph + math.pi), 0, 12)
    p["L_Elbow"] = (-50, 0, 0)
    p["Skirt_F"] = (-12 * abs(S(ph)) - 6, 0, 0)
    p["Skirt_B"] = (10 * abs(S(ph)) + 6, 0, 0)
    p["Cape1"] = (35 + 6 * S(2 * ph), 0, 0)
    p["Cape2"] = (18 + 10 * S(2 * ph + 1), 0, 0)
    p["Cape3"] = (14 + 12 * S(2 * ph + 2), 0, 0)
    p["HairBack"] = (12, 0, 0)
    p["__pelvis_y"] = -0.012 + 0.018 * abs(S(ph))
    return p


def clip_attack(t):
    """Hurl the bolt: windup 0-0.35, release 0.45, recover to 1.0."""
    p = base_pose(t)
    k = [(0.0, 0), (0.35, 1), (0.48, 2), (0.65, 2), (1.0, 3)]

    def at(keys):
        return tuple(track(t, keys))
    p["R_Shoulder"] = at([(0, (-12, 0, -16)), (0.35, (-160, 20, -30)), (0.48, (-70, -10, -10)), (0.65, (-60, -10, -10)), (1.0, (-12, 0, -16))])
    p["R_Elbow"] = at([(0, (-75, -10, 0)), (0.35, (-95, 0, 0)), (0.48, (-5, 0, 0)), (0.65, (-10, 0, 0)), (1.0, (-75, -10, 0))])
    p["Spine1"] = at([(0, (0, 0, 0)), (0.35, (-8, -25, 0)), (0.48, (12, 20, 0)), (1.0, (0, 0, 0))])
    p["Spine2"] = at([(0, (0, 0, 0)), (0.35, (-6, -15, 0)), (0.48, (8, 15, 0)), (1.0, (0, 0, 0))])
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.35, (-60, 0, 30)), (0.48, (20, 0, 20)), (1.0, (2, 0, 10))])
    p["L_Elbow"] = at([(0, (-14, 0, 0)), (0.35, (-30, 0, 0)), (1.0, (-14, 0, 0))])
    p["R_Hip"] = at([(0, (0, 0, -3)), (0.35, (12, 0, -6)), (0.48, (-18, 0, -6)), (1.0, (0, 0, -3))])
    p["L_Hip"] = at([(0, (0, 0, 3)), (0.35, (-18, 0, 6)), (0.48, (14, 0, 6)), (1.0, (0, 0, 3))])
    p["R_Knee"] = at([(0, (0, 0, 0)), (0.35, (8, 0, 0)), (0.48, (25, 0, 0)), (1.0, (0, 0, 0))])
    p["L_Knee"] = at([(0, (0, 0, 0)), (0.35, (22, 0, 0)), (0.48, (6, 0, 0)), (1.0, (0, 0, 0))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.48, (28, 0, 0)), (1.0, (6, 0, 0))])
    p["__pelvis_y"] = float(track(t, [(0, 0), (0.35, -0.01), (0.48, -0.02), (1.0, 0)]))
    p["__bolt_scale"] = float(track(t, [(0, 1), (0.44, 1.15), (0.5, 0.0), (0.8, 0.0), (1.0, 1)]))
    return p


def clip_q(t):
    """Chain Lightning: left hand points, sparks from fingertips."""
    p = base_pose(t)

    def at(keys):
        return tuple(track(t, keys))
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.25, (-95, -10, 0)), (0.7, (-90, -10, 0)), (1.0, (2, 0, 10))])
    p["L_Elbow"] = at([(0, (-14, 0, 0)), (0.25, (-4, 0, 0)), (1.0, (-14, 0, 0))])
    p["L_Hand"] = at([(0, (0, 0, 0)), (0.3, (0, 0, -10)), (0.36, (0, 0, 15)), (0.42, (0, 0, -10)), (0.5, (0, 0, 0))])
    p["Spine1"] = at([(0, (0, 0, 0)), (0.25, (0, -18, 0)), (0.7, (0, -18, 0)), (1.0, (0, 0, 0))])
    p["Spine2"] = at([(0, (0, 0, 0)), (0.25, (-4, -12, 0)), (0.3, (6, -12, 0)), (0.7, (0, -12, 0)), (1.0, (0, 0, 0))])
    p["Head"] = at([(0, (2, 0, 0)), (0.25, (0, 18, 0)), (0.7, (0, 18, 0)), (1.0, (2, 0, 0))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.3, (18, 0, 6)), (1.0, (6, 0, 0))])
    return p


def clip_w(t):
    """Aegis of Storms: both arms rise to the sky, energy gathers."""
    p = base_pose(t)

    def at(keys):
        return tuple(track(t, keys))
    p["R_Shoulder"] = at([(0, (-12, 0, -16)), (0.35, (-170, 0, -25)), (0.75, (-170, 0, -25)), (1.0, (-12, 0, -16))])
    p["R_Elbow"] = at([(0, (-75, -10, 0)), (0.35, (-10, 0, 0)), (1.0, (-75, -10, 0))])
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.35, (-170, 0, 25)), (0.75, (-170, 0, 25)), (1.0, (2, 0, 10))])
    p["L_Elbow"] = at([(0, (-14, 0, 0)), (0.35, (-10, 0, 0)), (1.0, (-14, 0, 0))])
    p["Spine2"] = at([(0, (0, 0, 0)), (0.35, (-10, 0, 0)), (0.75, (-10, 0, 0)), (1.0, (0, 0, 0))])
    p["Head"] = at([(0, (2, 0, 0)), (0.35, (-25, 0, 0)), (0.75, (-25, 0, 0)), (1.0, (2, 0, 0))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.4, (40, 0, 0)), (0.8, (30, 0, 0)), (1.0, (6, 0, 0))])
    p["Cape2"] = at([(0, (2, 0, 0)), (0.4, (20, 0, 0)), (1.0, (2, 0, 0))])
    p["HairBack"] = at([(0, (0, 0, 0)), (0.4, (20, 0, 0)), (1.0, (0, 0, 0))])
    p["__pelvis_y"] = float(track(t, [(0, 0), (0.35, 0.02), (0.75, 0.02), (1.0, 0)]))
    return p


def clip_e(t):
    """Thunder Step: crouch, spring, land."""
    p = base_pose(t)

    def at(keys):
        return tuple(track(t, keys))
    p["__pelvis_y"] = float(track(t, [(0, 0), (0.2, -0.08), (0.45, 0.12), (0.7, -0.06), (1.0, 0)]))
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = at([(0, (0, 0, s * 3)), (0.2, (-55, 0, s * 8)), (0.45, (-35, 0, s * 8)), (0.7, (-50, 0, s * 8)), (1.0, (0, 0, s * 3))])
        p[side + "_Knee"] = at([(0, (0, 0, 0)), (0.2, (95, 0, 0)), (0.45, (70, 0, 0)), (0.7, (90, 0, 0)), (1.0, (0, 0, 0))])
        p[side + "_Foot"] = at([(0, (0, 0, 0)), (0.2, (-35, 0, 0)), (0.45, (20, 0, 0)), (0.7, (-35, 0, 0)), (1.0, (0, 0, 0))])
    p["Spine1"] = at([(0, (0, 0, 0)), (0.2, (25, 0, 0)), (0.45, (5, 0, 0)), (0.7, (22, 0, 0)), (1.0, (0, 0, 0))])
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.2, (30, 0, 25)), (0.45, (-40, 0, 50)), (0.7, (20, 0, 30)), (1.0, (2, 0, 10))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.2, (10, 0, 0)), (0.45, (-5, 0, 0)), (0.6, (60, 0, 0)), (1.0, (6, 0, 0))])
    p["Cape2"] = at([(0, (2, 0, 0)), (0.5, (-10, 0, 0)), (0.7, (25, 0, 0)), (1.0, (2, 0, 0))])
    return p


def clip_r(t):
    """Wrath of Olympus: rise, gather, two-handed bolt slam."""
    p = base_pose(t)
    T = 1.6

    def at(keys):
        return tuple(track(t, [(a * T, v) for a, v in keys]))
    p["__pelvis_y"] = float(track(t, [(0, 0), (0.45 * T, 0.16), (0.6 * T, 0.18), (0.72 * T, -0.07), (0.85 * T, -0.07), (T, 0)]))
    p["R_Shoulder"] = at([(0, (-12, 0, -16)), (0.45, (-90, 0, -80)), (0.6, (-175, 0, -10)), (0.72, (-40, 0, -5)), (0.85, (-40, 0, -5)), (1, (-12, 0, -16))])
    p["R_Elbow"] = at([(0, (-75, -10, 0)), (0.45, (-10, 0, 0)), (0.6, (-20, 0, 0)), (0.72, (-5, 0, 0)), (1, (-75, -10, 0))])
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.45, (-90, 0, 80)), (0.6, (-175, 0, 10)), (0.72, (-40, 0, 5)), (0.85, (-40, 0, 5)), (1, (2, 0, 10))])
    p["L_Elbow"] = at([(0, (-14, 0, 0)), (0.45, (-10, 0, 0)), (0.6, (-20, 0, 0)), (0.72, (-5, 0, 0)), (1, (-14, 0, 0))])
    p["Spine1"] = at([(0, (0, 0, 0)), (0.45, (-8, 0, 0)), (0.6, (-12, 0, 0)), (0.72, (28, 0, 0)), (0.85, (24, 0, 0)), (1, (0, 0, 0))])
    p["Head"] = at([(0, (2, 0, 0)), (0.45, (-20, 0, 0)), (0.6, (-25, 0, 0)), (0.72, (15, 0, 0)), (1, (2, 0, 0))])
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = at([(0, (0, 0, s * 3)), (0.45, (-15, 0, s * 12)), (0.6, (-20, 0, s * 14)), (0.72, (-60, 0, s * 18)), (0.85, (-60, 0, s * 18)), (1, (0, 0, s * 3))])
        p[side + "_Knee"] = at([(0, (0, 0, 0)), (0.45, (35, 0, 0)), (0.6, (40, 0, 0)), (0.72, (100, 0, 0)), (0.85, (100, 0, 0)), (1, (0, 0, 0))])
        p[side + "_Foot"] = at([(0, (0, 0, 0)), (0.45, (25, 0, 0)), (0.72, (-35, 0, 0)), (0.85, (-35, 0, 0)), (1, (0, 0, 0))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.45, (-10, 0, 0)), (0.6, (-15, 0, 0)), (0.72, (70, 0, 0)), (1, (6, 0, 0))])
    p["Cape2"] = at([(0, (2, 0, 0)), (0.6, (-15, 0, 0)), (0.8, (30, 0, 0)), (1, (2, 0, 0))])
    p["Cape3"] = at([(0, (2, 0, 0)), (0.6, (-10, 0, 0)), (0.85, (35, 0, 0)), (1, (2, 0, 0))])
    p["HairBack"] = at([(0, (0, 0, 0)), (0.6, (-15, 0, 0)), (0.75, (25, 0, 0)), (1, (0, 0, 0))])
    p["__bolt_scale"] = float(track(t, [(0, 1), (0.6 * T, 1.6), (0.72 * T, 1.9), (0.85 * T, 1.0), (T, 1)]))
    return p


def clip_taunt(t):
    """Booming laugh: hands on hips, head thrown back."""
    p = base_pose(t, 0.5)
    T = 2.0

    def at(keys):
        return tuple(track(t, [(a * T, v) for a, v in keys]))
    laugh = 4 * S(TAU * t * 5) * (1 if 0.3 * T < t < 0.8 * T else 0)
    p["L_Shoulder"] = at([(0, (2, 0, 10)), (0.2, (15, 0, 45)), (0.85, (15, 0, 45)), (1, (2, 0, 10))])
    p["L_Elbow"] = at([(0, (-14, 0, 0)), (0.2, (-95, 40, 0)), (0.85, (-95, 40, 0)), (1, (-14, 0, 0))])
    p["Spine2"] = (float(track(t, [(0, 0), (0.3 * T, -12), (0.8 * T, -12), (T, 0)])) + laugh, 0, 0)
    p["Head"] = (float(track(t, [(0, 2), (0.3 * T, -28), (0.8 * T, -28), (T, 2)])) + laugh, 0, 0)
    p["Jaw"] = (float(track(t, [(0, 0), (0.3 * T, 14), (0.8 * T, 14), (T, 0)])) + abs(laugh) * 2, 0, 0)
    p["R_Weapon"] = (0, float(track(t, [(0, 0), (T, 360)])), 0)
    return p


def clip_death(t):
    p = base_pose(t, 0)
    T = 1.6

    def at(keys):
        return tuple(track(t, [(a * T, v) for a, v in keys]))
    p["__pelvis_y"] = float(track(t, [(0, 0), (0.3 * T, -0.06), (0.55 * T, -0.2), (0.8 * T, -0.38), (T, -0.38)]))
    p["__pelvis_rot"] = at([(0, (0, 0, 0)), (0.3, (8, 0, 0)), (0.55, (20, 0, 0)), (0.8, (-75, 0, 8)), (1, (-82, 0, 8))])
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = at([(0, (0, 0, s * 3)), (0.3, (-30, 0, s * 6)), (0.55, (-85, 0, s * 10)), (0.8, (-20, 0, s * 16)), (1, (-10, 0, s * 18))])
        p[side + "_Knee"] = at([(0, (0, 0, 0)), (0.3, (40, 0, 0)), (0.55, (120, 0, 0)), (0.8, (30, 0, 0)), (1, (20, 0, 0))])
        p[side + "_Shoulder"] = at([(0, (-12, 0, s * 16)), (0.3, (-40, 0, s * 25)), (0.55, (-20, 0, s * 20)), (0.8, (-150, 0, s * 70)), (1, (-160, 0, s * 80))])
        p[side + "_Elbow"] = at([(0, (-60, 0, 0)), (0.55, (-40, 0, 0)), (1, (-10, 0, 0))])
    p["Head"] = at([(0, (2, 0, 0)), (0.3, (25, 0, 0)), (0.55, (30, 0, 0)), (0.8, (-15, 25, 0)), (1, (-10, 35, 0))])
    p["Cape1"] = at([(0, (6, 0, 0)), (0.55, (20, 0, 0)), (0.8, (-50, 0, 0)), (1, (-60, 0, 0))])
    p["__bolt_scale"] = float(track(t, [(0, 1), (0.5 * T, 1), (0.7 * T, 0), (T, 0)]))
    return p


CLIPS = [
    # name, duration, fn, loop
    ("Idle", 2.4, clip_idle, True),
    ("Run", 0.6, clip_run, True),
    ("Attack", 1.0, clip_attack, False),
    ("Q", 1.0, clip_q, False),
    ("W", 1.0, clip_w, False),
    ("E", 1.0, clip_e, False),
    ("R", 1.6, clip_r, False),
    ("Taunt", 2.0, clip_taunt, False),
    ("Death", 1.6, clip_death, False),
]


# --------------------------------------------------------------- glb writer


class GlbWriter:
    def __init__(self):
        self.bin = bytearray()
        self.j = {"asset": {"version": "2.0", "generator": "ZeusLab make_zeus_blockout"},
                  "buffers": [], "bufferViews": [], "accessors": []}

    def view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin += b"\0"
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.j["bufferViews"].append(v)
        return len(self.j["bufferViews"]) - 1

    def acc(self, arr, ctype, typ, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        vi = self.view(arr.tobytes(), target)
        a = {"bufferView": vi, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"] = np.asarray(arr.reshape(len(arr), -1).min(0), float).tolist()
            a["max"] = np.asarray(arr.reshape(len(arr), -1).max(0), float).tolist()
        self.j["accessors"].append(a)
        return len(self.j["accessors"]) - 1

    def write(self, path):
        while len(self.bin) % 4:
            self.bin += b"\0"
        self.j["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<4sII", b"glTF", 2, total))
            f.write(struct.pack("<I4s", len(js), b"JSON") + js)
            f.write(struct.pack("<I4s", len(self.bin), b"BIN\0") + bytes(self.bin))


def build_glb(path):
    w = GlbWriter()
    J = w.j

    # nodes: joints first (indices == BONE), then mesh node, then armature
    nodes = []
    children = {i: [] for i in range(len(SKELETON))}
    for i, (name, parent, pos) in enumerate(SKELETON):
        ppos = WPOS[parent] if parent else np.zeros(3)
        nodes.append({"name": name, "translation": (WPOS[name] - ppos).tolist()})
        if parent:
            children[BONE[parent]].append(i)
    for i, ch in children.items():
        if ch:
            nodes[i]["children"] = ch

    # materials/textures
    builder = build_mesh()
    J["images"], J["textures"], J["materials"], J["samplers"] = [], [], [], [{"magFilter": 9729, "minFilter": 9729}]
    prims = []
    for mi, (mat, part) in enumerate(builder.parts.items()):
        png = matcap(mat)
        J["images"].append({"name": "Zeus_" + mat, "mimeType": "image/png", "bufferView": w.view(png)})
        J["textures"].append({"source": mi, "sampler": 0})
        J["materials"].append({"name": mat, "pbrMetallicRoughness": {
            "baseColorTexture": {"index": mi}, "metallicFactor": 0.0, "roughnessFactor": 1.0},
            "doubleSided": mat.startswith("Cape")})
        pos = np.concatenate(part["pos"]).astype("<f4")
        nrm = np.concatenate(part["nrm"])
        nrm = (nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)).astype("<f4")
        # matcap UVs from bind normals (screen-facing view from +Z)
        uv = np.stack([nrm[:, 0] * 0.49 + 0.5, 0.5 - nrm[:, 1] * 0.49], 1).astype("<f4")
        idx = np.concatenate(part["idx"]).astype("<u4")
        jt = np.concatenate(part["j"]).astype("<u2")
        wt = np.concatenate(part["w"]).astype("<f4")
        prims.append({"attributes": {
            "POSITION": w.acc(pos, 5126, "VEC3", 34962, True),
            "NORMAL": w.acc(nrm, 5126, "VEC3", 34962),
            "TEXCOORD_0": w.acc(uv, 5126, "VEC2", 34962),
            "JOINTS_0": w.acc(jt, 5123, "VEC4", 34962),
            "WEIGHTS_0": w.acc(wt, 5126, "VEC4", 34962)},
            "indices": w.acc(idx, 5125, "SCALAR", 34963), "material": mi})
    J["meshes"] = [{"name": "Zeus", "primitives": prims}]

    ibm = np.stack([np.linalg.inv(np.array([[1, 0, 0, p[0]], [0, 1, 0, p[1]], [0, 0, 1, p[2]], [0, 0, 0, 1]])).T.reshape(16)
                    for _, _, p in SKELETON]).astype("<f4")
    J["skins"] = [{"name": "ZeusRig", "joints": list(range(len(SKELETON))),
                   "inverseBindMatrices": w.acc(ibm, 5126, "MAT4"), "skeleton": 0}]
    mesh_node = len(nodes)
    nodes.append({"name": "ZeusMesh", "mesh": 0, "skin": 0})
    arm = len(nodes)
    nodes.append({"name": "Armature", "children": [0, mesh_node]})
    J["nodes"] = nodes
    J["scenes"] = [{"nodes": [arm]}]
    J["scene"] = 0

    # animations
    anims = []
    animated = [n for n, _, _ in SKELETON if not n.startswith("FX_") and n != "Root"]
    for name, dur, fn, loop in CLIPS:
        nf = int(round(dur * FPS)) + (0 if loop else 1)
        times = (np.arange(nf) / FPS).astype("<f4")
        tacc = w.acc(times, 5126, "SCALAR", minmax=True)
        rot = {b: np.zeros((nf, 4)) for b in animated}
        pel_t = np.zeros((nf, 3))
        bolt_s = np.ones((nf, 3))
        for f in range(nf):
            p = fn(f / FPS)
            for b in animated:
                e = p.get(b, (0, 0, 0))
                if b == "Pelvis":
                    e = p.get("__pelvis_rot", (0, 0, 0))
                q = q_euler(*e)
                if f and np.dot(q, rot[b][f - 1]) < 0:
                    q = -q
                rot[b][f] = q
            pel_t[f] = WPOS["Pelvis"] - WPOS["Root"] + [0, p.get("__pelvis_y", 0.0), 0]
            bolt_s[f] = max(1e-3, p.get("__bolt_scale", 1.0))
        samplers, channels = [], []

        def chan(node, path_, arr, typ):
            samplers.append({"input": tacc, "output": w.acc(arr.astype("<f4"), 5126, typ), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path_}})
        for b in animated:
            if np.allclose(rot[b], [0, 0, 0, 1]):
                continue
            chan(BONE[b], "rotation", rot[b], "VEC4")
        chan(BONE["Pelvis"], "translation", pel_t, "VEC3")
        if not np.allclose(bolt_s, 1):
            chan(BONE["R_Weapon"], "scale", bolt_s, "VEC3")
        anims.append({"name": name, "samplers": samplers, "channels": channels})
    J["animations"] = anims
    w.write(path)
    tri = sum(len(np.concatenate(p["idx"])) // 3 for p in builder.parts.values())
    return {"bones": len(SKELETON), "materials": len(builder.parts), "triangles": tri, "clips": [c[0] for c in CLIPS]}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "build/zeus_blockout.glb"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    print(build_glb(out))
    print("wrote", out)
