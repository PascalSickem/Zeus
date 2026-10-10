"""Seed the voxel Zeus: writes zeus/parts/*.vox and zeus/rig.json.

    python3 tools/seed_zeus_voxels.py [--force]

Run ONCE. After that the .vox files are the source of truth: open them in
MagicaVoxel (free), edit, save, and rebuild with tools/voxel_build.py.
--force overwrites existing parts (your MagicaVoxel edits would be lost).

Style target: Esports Godfather's native heroes -- chunky voxels, chibi
proportions (head ~1/3 of height), strong silhouette, saturated palette.
Character voxel space: +Y up, faces +Z, character's RIGHT is -X.
One part per bone (rigid voxel segments, like the game's own heroes).
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voxel  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zeus")

# ------------------------------------------------------------------ palette
PAL = {
    1: ("Skin", (236, 178, 128)), 2: ("SkinShade", (204, 140, 100)), 3: ("SkinLight", (250, 204, 160)),
    4: ("Hair", (238, 240, 250)), 5: ("HairShade", (190, 198, 222)),
    6: ("Cloth", (246, 244, 236)), 7: ("ClothShade", (204, 208, 224)),
    8: ("Gold", (246, 190, 60)), 9: ("GoldDark", (186, 120, 36)), 10: ("GoldLight", (255, 232, 140)),
    11: ("Cape", (48, 84, 196)), 12: ("CapeDark", (32, 54, 140)), 13: ("CapeInner", (34, 26, 92)),
    14: ("Leather", (128, 80, 46)),
    15: ("Eye", (120, 230, 255)), 16: ("EyeCore", (255, 255, 255)),
    17: ("Bolt", (255, 214, 64)), 18: ("BoltCore", (255, 252, 214)),
    19: ("Electric", (84, 170, 255)), 20: ("ElectricCore", (214, 246, 255)),
    21: ("Mouth", (110, 52, 44)), 22: ("Gem", (64, 150, 255)), 23: ("Storm", (156, 110, 255)),
}
EMISSIVE = [15, 16, 17, 18, 19, 20, 22, 23]
C = {name: i for i, (name, _) in PAL.items()}

VOXEL_SCALE = 1.0 / 46.0   # ~46 voxels tall -> 1.0 unit, same as the lab's other models

# ------------------------------------------------------------------ skeleton
# name, parent, bind pivot (voxel space). FX bones also get a rest pivot
# inside the body and a near-zero rest scale so they are hidden (and do not
# inflate the lab's camera framing) until a clip shows them.
BODY_CENTER = (0, 24, 0)
SKELETON = [
    ("Root", None, (0, 0, 0)),
    ("Pelvis", "Root", (0, 13, 0)),
    ("Spine1", "Pelvis", (0, 16, 0)),
    ("Spine2", "Spine1", (0, 20, 0)),
    ("Neck", "Spine2", (0, 27, 0)),
    ("Head", "Neck", (0, 28, 0)),
    ("Jaw", "Head", (0, 30, 5)),
    ("HairBack", "Head", (0, 38, -7)),
    ("R_Shoulder", "Spine2", (-9.5, 25, 0)),
    ("R_Elbow", "R_Shoulder", (-9.5, 20, 0)),
    ("R_Hand", "R_Elbow", (-9.5, 15, 0)),
    ("R_Weapon", "R_Hand", (-9.5, 13, 0.5)),
    ("L_Shoulder", "Spine2", (9.5, 25, 0)),
    ("L_Elbow", "L_Shoulder", (9.5, 20, 0)),
    ("L_Hand", "L_Elbow", (9.5, 15, 0)),
    ("R_Hip", "Pelvis", (-3.5, 12, 0)),
    ("R_Knee", "R_Hip", (-3.5, 7.5, 0)),
    ("R_Foot", "R_Knee", (-3.5, 3, 0)),
    ("L_Hip", "Pelvis", (3.5, 12, 0)),
    ("L_Knee", "L_Hip", (3.5, 7.5, 0)),
    ("L_Foot", "L_Knee", (3.5, 3, 0)),
    ("Skirt_F", "Pelvis", (0, 12, 2)),
    ("Skirt_B", "Pelvis", (0, 12, -2)),
    ("Cape1", "Spine2", (0, 27, -5)),
    ("Cape2", "Cape1", (0, 18, -5.5)),
    ("Cape3", "Cape2", (0, 11, -6)),
    # --- FX (emissive geometry, hidden at rest)
    ("R_Spark", "R_Weapon", (-9.5, 13, 8)),
    ("L_Spark", "L_Hand", (9.5, 12.5, 0.5)),
    ("FX_Chain1", "L_Hand", (9.5, 11, 0.5)),
    ("FX_Chain2", "FX_Chain1", (9.5, -4, 0.5)),
    ("FX_Chain3", "FX_Chain2", (9.5, -19, 0.5)),
    ("FX_Proj", "Root", (0, 24, 0)),
    ("FX_Ring", "Root", (0, 14, 0)),
    ("FX_Ring2", "Root", (0, 30, 0)),
    ("FX_Strike", "Root", (0, 64, 0)),
    ("FX_SkyBolt", "Root", (0, 70, 18)),
    ("FX_Impact", "Root", (0, 0, 18)),
    # --- attach points (no geometry) for in-game VFX hookup
    ("FX_BoltTip", "R_Weapon", (-9.5, 13, 16)),
    ("FX_Chest", "Spine2", (0, 23, 5)),
    ("FX_Overhead", "Root", (0, 50, 0)),
    ("FX_Ground", "Root", (0, 0, 0)),
]
HIDDEN_FX = {"R_Spark", "L_Spark", "FX_Chain1", "FX_Chain2", "FX_Chain3", "FX_Proj",
             "FX_Ring", "FX_Ring2", "FX_Strike", "FX_SkyBolt", "FX_Impact"}
FX_REST = {"FX_Proj": BODY_CENTER, "FX_Ring": BODY_CENTER, "FX_Ring2": BODY_CENTER,
           "FX_Strike": BODY_CENTER, "FX_SkyBolt": BODY_CENTER, "FX_Impact": BODY_CENTER}


# ------------------------------------------------------------------ sculpt kit


class Part(dict):
    """{(x,y,z): palette index} in character voxel space."""

    def box(self, x0, x1, y0, y1, z0, z1, c):
        for x in range(x0, x1):
            for y in range(y0, y1):
                for z in range(z0, z1):
                    self[(x, y, z)] = c
        return self

    def blob(self, cx, cy, cz, hx, hy, hz, c, power=4.0):
        """Rounded box / superellipsoid centred at (cx,cy,cz), half sizes h."""
        for x in range(int(math.floor(cx - hx)), int(math.ceil(cx + hx))):
            for y in range(int(math.floor(cy - hy)), int(math.ceil(cy + hy))):
                for z in range(int(math.floor(cz - hz)), int(math.ceil(cz + hz))):
                    d = (abs(x + 0.5 - cx) / hx) ** power + (abs(y + 0.5 - cy) / hy) ** power + \
                        (abs(z + 0.5 - cz) / hz) ** power
                    if d <= 1.0:
                        self[(x, y, z)] = c
        return self

    def paint(self, cond, c):
        for p in list(self):
            if cond(*p):
                self[p] = c
        return self

    def carve(self, cond):
        for p in list(self):
            if cond(*p):
                del self[p]
        return self

    def front(self, x, y):
        zs = [p[2] for p in self if p[0] == x and p[1] == y]
        return max(zs) if zs else None

    def paint_front(self, x, y, c, depth=1):
        z = self.front(x, y)
        if z is not None:
            for d in range(depth):
                if (x, y, z - d) in self:
                    self[(x, y, z - d)] = c

    def line(self, pts, core, glow=None, r_core=0.5, r_glow=1.3):
        """Thick 3D polyline: core voxels + glow shell (only into empty space)."""
        samples = []
        for a, b in zip(pts, pts[1:]):
            n = max(2, int(math.dist(a, b) * 4))
            for i in range(n + 1):
                t = i / n
                samples.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
        core_set, glow_set = set(), set()
        for s in samples:
            rr = int(math.ceil(r_glow)) + 1
            for x in range(int(s[0]) - rr, int(s[0]) + rr + 1):
                for y in range(int(s[1]) - rr, int(s[1]) + rr + 1):
                    for z in range(int(s[2]) - rr, int(s[2]) + rr + 1):
                        d = math.dist((x + 0.5, y + 0.5, z + 0.5), s)
                        if d <= r_core + 0.35:
                            core_set.add((x, y, z))
                        elif glow and d <= r_glow + 0.35:
                            glow_set.add((x, y, z))
        for p in glow_set - core_set:
            self.setdefault(p, glow)
        for p in core_set:
            self[p] = core
        return self


def rng(seed):
    s = [seed]

    def r():
        s[0] = (s[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return s[0] / 0x7FFFFFFF
    return r


def zigzag(start, direction, length, step, jitter, seed, side_axes=(0, 2)):
    r = rng(seed)
    pts = [tuple(start)]
    n = max(1, int(length / step))
    for i in range(1, n + 1):
        p = [start[k] + direction[k] * step * i for k in range(3)]
        if i < n:
            for ax in side_axes:
                p[ax] += (r() * 2 - 1) * jitter
        pts.append(tuple(p))
    return pts


# ------------------------------------------------------------------ the sculpt


def sculpt():
    P = {}

    # ---- HEAD: chunky rounded block, glowing eyes, stern brows
    h = Part()
    h.blob(0, 34.5, 0, 8, 6.6, 7, C["Skin"], power=5)
    for x in range(-8, 8):
        h.paint_front(x, 29, C["SkinShade"])          # jaw shadow
    for x in list(range(-6, -2)) + list(range(2, 6)):
        for y in (33, 34):
            h.paint_front(x, y, C["Eye"])
    for x in (-4, 3):
        h.paint_front(x, 34, C["EyeCore"])            # catch-lights
    # brows: one voxel proud, angled down toward the nose (stern)
    for (x0, x1, s) in ((-7, -2, -1), (2, 7, 1)):
        for x in range(x0, x1):
            inner = abs(x + 0.5) < 3.5
            y = 35 if inner else 36
            z = h.front(x, y)
            if z is not None:
                for yy in (y, y + 1):
                    h[(x, yy, z + 1)] = C["Hair"]
    # nose
    h.box(-1, 1, 31, 33, 7, 8, C["Skin"])
    h[(-1, 31, 7)] = C["SkinShade"]
    h[(0, 31, 7)] = C["SkinShade"]
    # ears
    for x in (-9, 8):
        h.box(x, x + 1, 32, 35, -1, 2, C["Skin"])
        h[(x, 33, 0)] = C["SkinShade"]
    # hair cap: shell over the top/back, white with shade strands
    hair = Part().blob(0, 35.5, -0.5, 9, 7.6, 8, C["Hair"], power=5)
    for p, c in hair.items():
        x, y, z = p
        top = y >= 39
        back = z <= -4 and y >= 29
        side = abs(x + 0.5) >= 7.5 and y >= 35 and z <= 3
        if (top or back or side) and p not in h:
            h[p] = C["HairShade"] if (x * 3 + z) % 5 == 0 else C["Hair"]
    # storm-swept tufts on top, flaring back
    for i, (x, z, hgt, lean) in enumerate([(-6, 2, 3, -1), (-3, 4, 4, -2), (0, 3, 5, -2), (3, 4, 4, -2),
                                           (6, 2, 3, -1), (-4, -2, 4, -2), (2, -2, 4, -2), (0, -5, 3, -2)]):
        top = max(p[1] for p in h if p[0] == x and p[2] == z) if any(p[0] == x and p[2] == z for p in h) else 41
        for k in range(hgt):
            zz = z + int(round(lean * k / max(1, hgt - 1)))
            for dx in (0, 1):
                h[(x + dx, top + 1 + k, zz)] = C["Hair"] if k < hgt - 1 else C["HairShade"]
    # laurel crown: gold band with leaves, sapphire at the front
    ring = Part().blob(0, 39.5, 0, 9.2, 1.0, 8.2, C["Gold"], power=2)
    inner = Part().blob(0, 39.5, 0, 7.6, 2.0, 6.6, C["Gold"], power=2)
    for p in ring:
        if p not in inner:
            h[p] = C["GoldDark"] if p[1] == 39 else C["Gold"]
    for k in range(16):
        a = 2 * math.pi * k / 16
        x = int(round(math.sin(a) * 9.4 - 0.5))
        z = int(round(math.cos(a) * 8.4 - 0.5))
        if z < -6:
            continue
        h[(x, 41, z)] = C["GoldLight"] if k % 2 == 0 else C["Gold"]
    zf = max(p[2] for p in h if p[1] == 40 and abs(p[0] + 0.5) < 1)
    h.box(-1, 1, 40, 42, zf, zf + 1, C["Gem"])
    h.box(-2, 2, 39, 40, zf, zf + 1, C["Gold"])
    P["Head"] = h

    # ---- JAW: mighty beard in front of the face and chest, moustache
    j = Part()
    for y in range(23, 31):
        t = (30 - y) / 7.0                        # 0 at the mouth .. 1 at the tip
        half = 5.5 - 4.0 * t ** 1.1 if y < 28 else 7.0
        if y >= 28:
            z0, z1 = 7, 9                         # on the face, in front of it
        else:
            z0, z1 = 4, 8                         # hangs over the chest
        for x in range(-8, 8):
            if abs(x + 0.5) <= half:
                for z in range(z0, z1):
                    strand = (x + (y // 2)) % 3 == 0
                    j[(x, y, z)] = C["HairShade"] if strand or z == z0 else C["Hair"]
    for y in range(28, 34):                       # sideburns joining the hair
        for x in (-9, 8):
            for z in range(1, 6):
                j[(x, y, z)] = C["Hair"]
    j.carve(lambda x, y, z: y >= 29 and abs(x + 0.5) < 2.5 and z == 8)
    j.box(-2, 2, 29, 30, 7, 8, C["Mouth"])        # mouth under the moustache
    j.box(-5, 5, 30, 31, 8, 9, C["Hair"])         # moustache (below the nose)
    for x in (-6, 5):
        j.box(x, x + 1, 28, 30, 8, 9, C["Hair"])
    P["Jaw"] = j

    # ---- HAIR BACK: long flowing mane behind the head
    hb = Part()
    for y in range(24, 40):
        t = (39 - y) / 15.0
        half = 7 - 2.5 * t
        for x in range(-8, 8):
            if abs(x + 0.5) <= half:
                for z in (-9, -8):
                    jag = (x * 7 + 3) % 4
                    if y < 26 and jag > 1:
                        continue
                    hb[(x, y, z)] = C["HairShade"] if (x + y) % 4 == 0 else C["Hair"]
    P["HairBack"] = hb

    # ---- NECK
    P["Neck"] = Part().box(-3, 3, 26, 28, -2, 2, C["Skin"])

    # ---- CHEST: broad, muscular, chiton draped from left shoulder
    ch = Part().blob(0, 23.5, 0, 7.4, 3.6, 4.2, C["Skin"], power=6)
    ch.blob(-3.2, 23.5, 3.2, 3.2, 2.2, 1.2, C["Skin"], power=3)   # pecs
    ch.blob(3.2, 23.5, 3.2, 3.2, 2.2, 1.2, C["Skin"], power=3)
    for x in range(-6, 6):
        ch.paint_front(x, 21, C["SkinShade"])
    for y in range(22, 26):
        ch.paint_front(-1, y, C["SkinShade"])
        ch.paint_front(0, y, C["SkinShade"])
    ch.paint(lambda x, y, z: y == 26 and abs(x + 0.5) < 6 and z >= 2, C["SkinLight"])

    def toga(x, y, z):
        return x + 0.5 >= -3.0 + (y - 19.5) * 1.5

    ch.paint(lambda x, y, z: toga(x, y, z), C["Cloth"])
    ch.paint(lambda x, y, z: toga(x, y, z) and (x - y) % 5 == 0, C["ClothShade"])
    # gold strap painted along the drape edge
    ch.paint(lambda x, y, z: x == int(math.floor(-3.0 + (y - 19.5) * 1.5)), C["Gold"])
    for x in (-6, 5):                              # cape clasps with gems
        ch.box(x, x + 1, 25, 27, 3, 5, C["Gold"])
        ch[(x, 26, 5)] = C["Gem"]
    P["Spine2"] = ch

    # ---- ABDOMEN (Spine1): cloth with folds
    ab = Part().blob(0, 18, 0, 6.6, 2.2, 3.8, C["Cloth"], power=6)
    ab.paint(lambda x, y, z: (x - y) % 5 == 0, C["ClothShade"])
    P["Spine1"] = ab

    # ---- PELVIS: hips + gold belt with storm-gem buckle
    pv = Part().blob(0, 14, 0, 7.2, 2.2, 4.4, C["Cloth"], power=6)
    pv.paint(lambda x, y, z: y == 15, C["Gold"])
    pv.paint(lambda x, y, z: y == 15 and (x + z) % 3 == 0, C["GoldDark"])
    zf = max(p[2] for p in pv if p[1] == 15 and abs(p[0] + 0.5) < 1)
    pv.box(-2, 2, 14, 17, zf + 1, zf + 2, C["Gold"])
    pv.box(-1, 1, 15, 16, zf + 2, zf + 3, C["Gem"])
    P["Pelvis"] = pv

    # ---- SKIRT: pleated, flared, gold hem; front/back halves swing with legs
    sf, sb = Part(), Part()
    for y in range(5, 13):
        t = (12 - y) / 7.0
        ax, az = 7.2 + 1.6 * t, 4.4 + 1.4 * t
        for x in range(-10, 10):
            for z in range(-7, 7):
                d = ((x + 0.5) / ax) ** 2 + ((z + 0.5) / az) ** 2
                if (1 - 2.2 / min(ax, az)) ** 2 <= d <= 1.0:
                    ang = math.atan2(z + 0.5, x + 0.5)
                    pleat = int((ang + math.pi) / (2 * math.pi) * 14) % 2
                    c = C["Gold"] if y == 5 else (C["GoldDark"] if y == 6 and pleat else
                                                  (C["ClothShade"] if pleat else C["Cloth"]))
                    (sf if z >= 0 else sb)[(x, y, z)] = c
    P["Skirt_F"], P["Skirt_B"] = sf, sb

    # ---- ARMS: chunky, muscular, gold bracers; left pauldron
    for side, s in (("R", -1), ("L", 1)):
        cx = 9.5 * s
        ua = Part().blob(cx, 22.8, 0, 2.6, 3.4, 2.3, C["Skin"], power=4)
        ua.blob(cx + 0.4 * s, 24.5, 0, 2.8, 1.8, 2.5, C["Skin"], power=3)   # deltoid
        ua.paint(lambda x, y, z: y == 20, C["SkinShade"])
        if side == "L":
            ua.blob(cx + 0.5, 26.0, 0, 3.6, 1.6, 3.2, C["Gold"], power=3)
            ua.paint(lambda x, y, z: y == 25 and (x + z) % 2 == 0 and (x, y, z) in ua and ua[(x, y, z)] == C["Gold"], C["GoldDark"])
            ua[(int(cx + 3.3), 26, 0)] = C["Gem"]
            ua[(int(cx + 3.3), 26, -1)] = C["Gem"]
        P[side + "_Shoulder"] = ua
        fa = Part().blob(cx, 17.5, 0, 2.4, 2.6, 2.2, C["Skin"], power=4)
        fa.paint(lambda x, y, z: y <= 17, C["Gold"])
        fa.paint(lambda x, y, z: y == 17, C["GoldLight"])
        fa.paint(lambda x, y, z: y == 15, C["GoldDark"])
        P[side + "_Elbow"] = fa
        hd = Part().blob(cx, 13, 0.5, 2.6, 2.1, 2.6, C["Skin"], power=4)
        for x in range(int(cx - 2), int(cx + 2)):
            hd.paint_front(x, 13, C["SkinShade"])  # knuckle line
        P[side + "_Hand"] = hd

    # ---- LEGS: thigh (mostly under skirt), shin with gold greave, sandal
    for side, s in (("R", -1), ("L", 1)):
        cx = 3.5 * s
        P[side + "_Hip"] = Part().blob(cx, 9.8, 0, 2.6, 2.6, 2.4, C["Skin"], power=4)
        sh = Part().blob(cx, 5.2, 0, 2.3, 2.4, 2.2, C["Skin"], power=4)
        sh.paint(lambda x, y, z: z >= 1 and y >= 4, C["Gold"])
        sh.paint(lambda x, y, z: y == 4, C["GoldDark"])
        sh.paint(lambda x, y, z: y == 7 and z >= 1, C["GoldLight"])
        P[side + "_Knee"] = sh
        ft = Part().box(int(cx - 2.5), int(cx + 2.5), 0, 1, -2, 5, C["Leather"])
        ft.blob(cx, 2.0, 1.3, 2.2, 1.2, 3.4, C["Skin"], power=4)
        ft.paint(lambda x, y, z: y >= 1 and (z == 2 or y == 2 and z < 0), C["Gold"])
        P[side + "_Foot"] = ft

    # ---- CAPE: storm-blue, lightning-cut hem, high collar
    capes = {"Cape1": Part(), "Cape2": Part(), "Cape3": Part()}
    for y in range(3, 30):
        t = (27 - y) / 24.0
        half = 8 + 2.2 * max(0, t)
        bone = "Cape1" if y >= 18 else ("Cape2" if y >= 11 else "Cape3")
        for x in range(-11, 11):
            if abs(x + 0.5) > half:
                continue
            if y >= 27 and abs(x + 0.5) > 6:      # collar narrower
                continue
            hem = 3 + int(abs(((x + 0.5) * 0.9) % 4 - 2) * 1.5)   # zig-zag hem
            if y < hem:
                continue
            curve = -6 - int(round(1.2 * (1 - ((x + 0.5) / half) ** 2)))
            if y >= 27:
                curve = -6
            capes[bone][(x, y, curve)] = C["CapeDark"] if x % 4 == 0 else C["Cape"]
            capes[bone][(x, y, curve + 1)] = C["CapeInner"]
    for x in range(-6, 6):                         # gold trim at the collar
        capes["Cape1"][(x, 29, -6)] = C["Gold"]
    for p in list(capes["Cape3"]):
        x, y, z = p
        below = (x, y - 1, z)
        if below not in capes["Cape3"] and capes["Cape3"][p] != C["CapeInner"]:
            capes["Cape3"][p] = C["Storm"]                 # glowing storm hem
    P.update(capes)

    # ---- LIGHTNING BOLT weapon (R_Weapon): points +Z out of the fist
    bw = Part()
    pts = [(-9.5, 13.5, -4), (-7.5, 13.5, 2), (-11, 13.5, 4), (-7, 13.5, 10), (-10.5, 13.5, 11),
           (-8.5, 13.5, 17)]
    bw.line(pts, C["BoltCore"], C["Bolt"], r_core=0.6, r_glow=1.6)
    fist = P["R_Hand"]
    bw.carve(lambda x, y, z: (x, y, z) in fist)
    P["R_Weapon"] = bw

    # ---- FX geometry ---------------------------------------------------
    sp = Part()                                     # sparks crackling round the bolt
    for k in range(6):
        a = 2 * math.pi * k / 6
        c = (-9.5 + math.cos(a) * 4, 13.5 + math.sin(a) * 4, 8 + (k % 3 - 1) * 3)
        sp.line(zigzag(c, (math.sin(a), -math.cos(a), 0), 3, 1, 0.8, k + 7), C["ElectricCore"], C["Electric"], 0.3, 0.9)
    P["R_Spark"] = sp
    lp = Part()                                     # crackle in the open left hand
    for k in range(5):
        a = 2 * math.pi * k / 5
        c = (9.5 + math.cos(a) * 3.2, 12.5 + math.sin(a) * 2.4, 0.5 + math.sin(a * 2) * 2)
        lp.line(zigzag(c, (math.cos(a + 1.2), math.sin(a + 1.2), 0.3), 3.5, 1, 0.9, k + 21), C["ElectricCore"], C["Electric"], 0.3, 0.9)
    P["L_Spark"] = lp
    for i, (name, y0) in enumerate((("FX_Chain1", 11), ("FX_Chain2", -4), ("FX_Chain3", -19))):
        ck = Part()
        pts = zigzag((9.5, y0, 0.5), (0, -1, 0), 15, 2.5, 2.2, 40 + i)
        ck.line(pts, C["ElectricCore"], C["Electric"], 0.5, 1.4)
        fork = zigzag(pts[2], (0.6, -0.8, 0.2), 6, 2, 1.2, 50 + i)
        ck.line(fork, C["ElectricCore"], C["Electric"], 0.3, 1.0)
        if i == 2:                                  # impact burst at the last target
            for k in range(8):
                a = 2 * math.pi * k / 8
                ck.line([(9.5, -34, 0.5), (9.5 + math.cos(a) * 5, -34 + math.sin(a) * 5, 0.5 + math.sin(a * 3) * 2)],
                        C["ElectricCore"], C["Storm"], 0.4, 1.1)
        P[name] = ck
    pj = Part()                                     # thrown bolt projectile (+Z)
    pts = [(0, 24, -8), (3, 24, -1), (-2, 24, 1), (3, 24, 8), (-2, 24, 10), (1, 24, 18)]
    pj.line(pts, C["BoltCore"], C["Bolt"], 0.8, 1.8)
    for k, a in enumerate((0.0, 2.1, 4.2)):         # crackling arcs riding the bolt
        c = (math.cos(a) * 2.5, 24 + math.sin(a) * 2.5, -4 + 7 * k)
        pj.line(zigzag(c, (0, 0, 1), 6, 1.5, 1.5, 100 + k), C["ElectricCore"], C["Electric"], 0.3, 0.9)
    P["FX_Proj"] = pj
    for name, y, r, seed in (("FX_Ring", 14, 13.5, 60), ("FX_Ring2", 30, 11, 70)):
        rg = Part()
        rr = rng(seed)
        pts = []
        for k in range(41):
            a = 2 * math.pi * k / 40
            rad = r + (rr() * 2 - 1) * 1.2
            pts.append((math.cos(a) * rad, y + (rr() * 2 - 1) * 1.5, math.sin(a) * rad))
        rg.line(pts, C["ElectricCore"], C["Electric"], 0.45, 1.3)
        P[name] = rg
    for name, top, z, w, seed in (("FX_Strike", 64, 0, 1.0, 80), ("FX_SkyBolt", 70, 18, 1.6, 90)):
        st = Part()
        pts = zigzag((0, top, z), (0, -1, 0), top, 4, 3.5 * w, seed)
        st.line(pts, C["ElectricCore"], C["Electric"] if w < 1.2 else C["Bolt"], 0.6 * w, 1.6 * w)
        for k in (3, 7, 11):
            if k < len(pts):
                st.line(zigzag(pts[k], ((-1) ** k * 0.7, -0.7, 0), 9 * w, 2.5, 1.5, seed + k),
                        C["ElectricCore"], C["Storm"], 0.35 * w, 1.0 * w)
        P[name] = st
    im = Part()                                     # ground impact starburst
    for k in range(12):
        a = 2 * math.pi * k / 12
        L = 9 + (k % 3) * 3
        im.line([(0, 0.5, 18), (math.cos(a) * L, 0.5 + (k % 2) * 4, 18 + math.sin(a) * L)],
                C["ElectricCore"], C["Bolt"] if k % 2 else C["Electric"], 0.5, 1.3)
    P["FX_Impact"] = im
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=ROOT)
    a = ap.parse_args()
    parts_dir = os.path.join(a.out, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    palette = {i: rgb for i, (_, rgb) in PAL.items()}
    P = sculpt()
    rig_parts = []
    old_anchor = {}
    rig_path = os.path.join(a.out, "rig.json")
    if os.path.exists(rig_path):
        old_anchor = {p["bone"]: p.get("anchor") for p in json.load(open(rig_path)).get("parts", [])}
    for bone, vox in P.items():
        if not vox:
            continue
        fn = "%s.vox" % bone
        path = os.path.join(parts_dir, fn)
        if os.path.exists(path) and not a.force:
            print("keep (exists)", fn)
            anchor = old_anchor.get(bone)
            if anchor is None:
                raise SystemExit("%s exists but rig.json has no anchor for it; use --force" % fn)
        else:
            anchor = voxel.write_vox(path, vox, palette)
            print("wrote", fn, len(vox), "voxels")
        rig_parts.append({"bone": bone, "file": "parts/" + fn, "anchor": anchor})
    bones = []
    for name, parent, pivot in SKELETON:
        b = {"name": name, "parent": parent, "pivot": list(pivot)}
        if name in HIDDEN_FX:
            b["rest_scale"] = 0.0001
        if name in FX_REST:
            b["rest_pivot"] = list(FX_REST[name])
        bones.append(b)
    rig = {
        "name": "Zeus",
        "voxel_scale": VOXEL_SCALE,
        "palette_names": {str(i): n for i, (n, _) in PAL.items()},
        "emissive_indices": EMISSIVE,
        "bones": bones,
        "parts": rig_parts,
        "animations": "anims.py",
    }
    with open(rig_path, "w") as f:
        json.dump(rig, f, indent=1)
    print("wrote", rig_path)


if __name__ == "__main__":
    main()
