"""Zeus combat animations (voxel rig in zeus/rig.json).

Each clip is fn(t) -> {bone: {"r": (x,y,z) euler degrees,
                              "t": (x,y,z) voxel offset from the rest pivot,
                              "pos": (x,y,z) absolute voxel pivot (Root children),
                              "s": scale (number or 3-tuple)}}
Bones not returned keep their rest pose -- FX bones stay hidden.

Axis cheatsheet (glTF space, Zeus faces +Z, his right is -X):
  shoulder X < 0 raises an arm forward/up; L arm Z > 0 / R arm Z < 0 lifts sideways
  elbow X < 0 bends the forearm forward; knee X > 0 bends; hip X < 0 swings the leg forward
  Pelvis Y > 0 turns him toward screen-right.

Kit:
  Attack  Lightning Bolt -- hurls the bolt, a new one sparks back into his hand
  Q       Chain Lightning -- left-hand arc that jumps through three targets
  W       Static Aegis    -- twin electric rings spin up around him
  E       Thunder Step    -- struck by lightning, vanishes, re-forms
  R       Wrath of Olympus -- levitates, calls a sky bolt, ground explodes
"""

import math

S = math.sin
TAU = 2 * math.pi


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def track(t, keys):
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = ease((t - t0) / max(t1 - t0, 1e-9))
            if isinstance(v0, (int, float)):
                return v0 + (v1 - v0) * u
            return tuple(a + (b - a) * u for a, b in zip(v0, v1))
    return keys[-1][1]


def flick(t, k, rate=24):
    """Deterministic 0..1 flicker, changes `rate` times per second."""
    n = math.floor(t * rate) + k * 17.0
    x = math.sin(n * 12.9898 + k * 78.233) * 43758.5453
    return x - math.floor(x)


def base(t, breathe=1.0):
    b = breathe * S(TAU * t / 2.4)
    return {
        "Pelvis": {"t": (0, 0.6 * b, 0)},
        "Spine1": {"r": (1.5 * b, 0, 0)},
        "Spine2": {"r": (-2 * b, 0, 0)},
        "Head": {"r": (3 + 2 * b, 0, 0)},
        "R_Shoulder": {"r": (-18, 0, -14)},
        "R_Elbow": {"r": (-92, -8, 0)},
        "L_Shoulder": {"r": (-10, 0, 22)},
        "L_Elbow": {"r": (-38, 0, 0)},
        "L_Hand": {"r": (0, 0, -15)},
        "R_Hip": {"r": (0, 0, -4)}, "L_Hip": {"r": (0, 0, 4)},
        "Cape1": {"r": (8 + 3 * b, 0, 0)},
        "Cape2": {"r": (3 + 3 * S(TAU * t / 2.4 + 1), 0, 2 * S(TAU * t / 2.4))},
        "Cape3": {"r": (4 + 4 * S(TAU * t / 2.4 + 2), 0, 3 * S(TAU * t / 2.4 + 1))},
        "HairBack": {"r": (4 * b, 0, 0)},
    }


def sparks(p, t, which=("R_Spark", "L_Spark"), amount=1.0):
    for k, name in enumerate(which):
        on = flick(t, k + 1) > 0.25
        p[name] = {"s": (0.65 + 0.45 * flick(t, k + 5)) * amount if on else 0.0001,
                   "r": (0, 360 * flick(t, k + 9), 0)}


def chain_jitter(p, t, names=("FX_Chain1", "FX_Chain2", "FX_Chain3"), scale=None):
    for k, name in enumerate(names):
        s = 1.0 if scale is None else scale[k]
        p[name] = {"s": max(0.0001, s), "r": (0, 360 * flick(t, k + 30, 30), 0)}


# ------------------------------------------------------------------ clips


def idle(t):
    p = base(t)
    p["R_Weapon"] = {"r": (0, 0, 10 * S(TAU * t / 2.4))}
    sparks(p, t, amount=0.8)
    return p


def run(t, T=0.6):
    ph = TAU * t / T
    p = base(t, 0.3)
    p["Pelvis"] = {"t": (0, -0.4 + 0.9 * abs(S(ph)), 0), "r": (0, 6 * S(ph), 0)}
    p["Spine1"] = {"r": (12, -6 * S(ph), 0)}
    p["Head"] = {"r": (-8, 6 * S(ph), 0)}
    p["R_Hip"] = {"r": (-40 * S(ph), 0, -4)}
    p["L_Hip"] = {"r": (40 * S(ph), 0, 4)}
    p["R_Knee"] = {"r": (40 + 38 * S(ph + 1.6), 0, 0)}
    p["L_Knee"] = {"r": (40 + 38 * S(ph + 1.6 + math.pi), 0, 0)}
    p["R_Shoulder"] = {"r": (-30 - 15 * S(ph + math.pi), 0, -16)}
    p["L_Shoulder"] = {"r": (40 * S(ph + math.pi), 0, 14)}
    p["L_Elbow"] = {"r": (-55, 0, 0)}
    p["Skirt_F"] = {"r": (-14 * abs(S(ph)) - 6, 0, 0)}
    p["Skirt_B"] = {"r": (12 * abs(S(ph)) + 6, 0, 0)}
    p["Cape1"] = {"r": (40 + 6 * S(2 * ph), 0, 0)}
    p["Cape2"] = {"r": (20 + 10 * S(2 * ph + 1), 0, 0)}
    p["Cape3"] = {"r": (16 + 12 * S(2 * ph + 2), 0, 0)}
    p["HairBack"] = {"r": (18, 0, 0)}
    sparks(p, t, ("R_Spark",), 0.6)
    return p


def attack(t):
    """Lightning Bolt: windup 0-0.35, release 0.42, bolt re-forms 0.7-0.9."""
    p = base(t)
    p["Pelvis"] = {"t": (0, track(t, [(0, 0), (0.35, -0.5), (0.45, -1.2), (1.0, 0)]), 0),
                   "r": (0, track(t, [(0, 0), (0.35, 25), (0.45, -20), (1.0, 0)]), 0)}
    p["R_Shoulder"] = {"r": track(t, [(0, (-18, 0, -14)), (0.35, (-165, 20, -25)), (0.45, (-60, -10, -10)),
                                      (0.6, (-55, -10, -10)), (1.0, (-18, 0, -14))])}
    p["R_Elbow"] = {"r": track(t, [(0, (-92, -8, 0)), (0.35, (-100, 0, 0)), (0.45, (-5, 0, 0)),
                                   (0.6, (-10, 0, 0)), (1.0, (-92, -8, 0))])}
    p["Spine1"] = {"r": track(t, [(0, (0, 0, 0)), (0.35, (-10, 0, 0)), (0.45, (14, 0, 0)), (1.0, (0, 0, 0))])}
    p["L_Shoulder"] = {"r": track(t, [(0, (-10, 0, 22)), (0.35, (-70, 0, 35)), (0.45, (20, 0, 25)), (1.0, (-10, 0, 22))])}
    p["R_Hip"] = {"r": track(t, [(0, (0, 0, -4)), (0.35, (14, 0, -6)), (0.45, (-22, 0, -6)), (1.0, (0, 0, -4))])}
    p["L_Hip"] = {"r": track(t, [(0, (0, 0, 4)), (0.35, (-20, 0, 6)), (0.45, (14, 0, 6)), (1.0, (0, 0, 4))])}
    p["Cape1"] = {"r": track(t, [(0, (8, 0, 0)), (0.45, (35, 0, 0)), (1.0, (8, 0, 0))])}
    p["R_Weapon"] = {"s": track(t, [(0, 1.0), (0.38, 1.25), (0.42, 0.0001), (0.7, 0.0001), (0.85, 1.1), (1.0, 1.0)])}
    if 0.4 <= t <= 0.72:
        u = (t - 0.4) / 0.32
        p["FX_Proj"] = {"pos": (-10 - 22 * u, 34 - 10 * u, 6 + 30 * u), "r": (0, -40, 0),
                        "s": 0.0001 if t > 0.7 else 1.0 + 0.5 * u}
    if 0.68 <= t <= 0.9:
        sparks(p, t, ("R_Spark",), 1.2)
    return p


def skill_q(t):
    """Chain Lightning from the left hand, three jumps, flickering."""
    p = base(t)
    p["Pelvis"] = {"r": (0, track(t, [(0, 0), (0.2, -45), (0.75, -45), (1.0, 0)]), 0)}
    p["L_Shoulder"] = {"r": track(t, [(0, (-10, 0, 22)), (0.2, (-92, -5, 4)), (0.75, (-90, -5, 4)), (1.0, (-10, 0, 22))])}
    p["L_Elbow"] = {"r": track(t, [(0, (-38, 0, 0)), (0.2, (-4, 0, 0)), (1.0, (-38, 0, 0))])}
    p["L_Hand"] = {"r": (0, 0, 8 * S(TAU * t * 9) if 0.25 < t < 0.7 else 0)}
    p["Spine2"] = {"r": track(t, [(0, (0, 0, 0)), (0.22, (-6, 0, 0)), (0.28, (6, 0, 0)), (0.75, (0, 0, 0))])}
    p["Head"] = {"r": (3, track(t, [(0, 0), (0.2, 20), (0.75, 20), (1.0, 0)]), 0)}
    p["Cape1"] = {"r": track(t, [(0, (8, 0, 0)), (0.3, (25, 0, 8)), (1.0, (8, 0, 0))])}
    if 0.2 <= t <= 0.78:
        g = [track(t, [(0.22, 0.0001), (0.3, 1.0)]),
             track(t, [(0.3, 0.0001), (0.38, 1.0)]),
             track(t, [(0.38, 0.0001), (0.46, 1.0)])]
        if t > 0.7:
            g = [0.0001] * 3
        chain_jitter(p, t, scale=g)
        sparks(p, t, ("L_Spark",), 1.3)
    return p


def skill_w(t):
    """Static Aegis: arms to the sky, two electric rings spin up."""
    p = base(t)
    T = 1.2

    def at(k):
        return track(t, [(a * T, v) for a, v in k])
    p["R_Shoulder"] = {"r": at([(0, (-18, 0, -14)), (0.3, (-170, 0, -25)), (0.8, (-170, 0, -25)), (1, (-18, 0, -14))])}
    p["R_Elbow"] = {"r": at([(0, (-92, -8, 0)), (0.3, (-15, 0, 0)), (1, (-92, -8, 0))])}
    p["L_Shoulder"] = {"r": at([(0, (-10, 0, 22)), (0.3, (-170, 0, 25)), (0.8, (-170, 0, 25)), (1, (-10, 0, 22))])}
    p["L_Elbow"] = {"r": at([(0, (-38, 0, 0)), (0.3, (-15, 0, 0)), (1, (-38, 0, 0))])}
    p["Spine2"] = {"r": at([(0, (0, 0, 0)), (0.3, (-10, 0, 0)), (0.8, (-10, 0, 0)), (1, (0, 0, 0))])}
    p["Head"] = {"r": at([(0, (3, 0, 0)), (0.3, (-25, 0, 0)), (0.8, (-25, 0, 0)), (1, (3, 0, 0))])}
    p["Pelvis"] = {"t": (0, at([(0, 0), (0.3, 1.5), (0.8, 1.5), (1, 0)]), 0)}
    p["Cape1"] = {"r": at([(0, (8, 0, 0)), (0.35, (45, 0, 0)), (0.8, (35, 0, 0)), (1, (8, 0, 0))])}
    p["Cape2"] = {"r": at([(0, (3, 0, 0)), (0.35, (20, 0, 0)), (1, (3, 0, 0))])}
    p["HairBack"] = {"r": at([(0, (0, 0, 0)), (0.35, (25, 0, 0)), (1, (0, 0, 0))])}
    if 0.25 * T <= t <= 0.95 * T:
        s1 = at([(0.25, 0.0001), (0.45, 1.15), (0.55, 1.0), (0.85, 1.0), (0.95, 0.0001)])
        s2 = at([(0.32, 0.0001), (0.52, 1.1), (0.62, 1.0), (0.85, 1.0), (0.95, 0.0001)])
        p["FX_Ring"] = {"pos": (0, 14, 0), "s": (s1, 1.0, s1), "r": (0, 540 * t, 0)}
        p["FX_Ring2"] = {"pos": (0, 30, 0), "s": (s2, 1.0, s2), "r": (0, -720 * t, 0)}
        sparks(p, t, amount=1.3)
    return p


def skill_e(t):
    """Thunder Step: crouch, lightning strikes him, gone, re-forms."""
    p = base(t)
    p["Pelvis"] = {"t": (0, track(t, [(0, 0), (0.2, -2.5), (0.3, -1), (0.62, 0), (0.7, -2.5), (1.0, 0)]), 0),
                   "s": track(t, [(0, 1.0), (0.3, 1.0), (0.36, 0.0001), (0.6, 0.0001), (0.67, 1.0)])}
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = {"r": track(t, [(0, (0, 0, s * 4)), (0.2, (-45, 0, s * 8)), (0.3, (-20, 0, s * 6)),
                                           (0.7, (-45, 0, s * 8)), (1.0, (0, 0, s * 4))])}
        p[side + "_Knee"] = {"r": track(t, [(0, (0, 0, 0)), (0.2, (80, 0, 0)), (0.3, (30, 0, 0)),
                                            (0.7, (80, 0, 0)), (1.0, (0, 0, 0))])}
        p[side + "_Foot"] = {"r": track(t, [(0, (0, 0, 0)), (0.2, (-35, 0, 0)), (0.7, (-35, 0, 0)), (1.0, (0, 0, 0))])}
    p["Spine1"] = {"r": track(t, [(0, (0, 0, 0)), (0.2, (22, 0, 0)), (0.3, (0, 0, 0)), (0.7, (20, 0, 0)), (1.0, (0, 0, 0))])}
    p["L_Shoulder"] = {"r": track(t, [(0, (-10, 0, 22)), (0.2, (20, 0, 45)), (0.7, (10, 0, 55)), (1.0, (-10, 0, 22))])}
    for a, b in ((0.22, 0.42), (0.55, 0.76)):
        if a <= t <= b:
            u = (t - a) / (b - a)
            s = 0.0001 if u > 0.85 else track(u, [(0, 0.0001), (0.25, 1.0)])
            p["FX_Strike"] = {"pos": (0, 64, 0), "s": (1.0, s, 1.0), "r": (0, 360 * flick(t, 40, 30), 0)}
    if 0.6 <= t <= 0.85:
        sparks(p, t, amount=1.4)
    return p


def skill_r(t):
    """Wrath of Olympus: rise, gather the storm, slam -- sky bolt + shockwave."""
    p = base(t)
    T = 1.8

    def at(k):
        return track(t, [(a * T, v) for a, v in k])
    p["Pelvis"] = {"t": (0, at([(0, 0), (0.35, 7), (0.6, 8), (0.7, -3), (0.85, -3), (1, 0)]), 0)}
    p["R_Shoulder"] = {"r": at([(0, (-18, 0, -14)), (0.3, (-80, 0, -75)), (0.6, (-175, 0, -10)), (0.7, (-45, 0, -5)),
                                (0.85, (-45, 0, -5)), (1, (-18, 0, -14))])}
    p["R_Elbow"] = {"r": at([(0, (-92, -8, 0)), (0.3, (-10, 0, 0)), (0.6, (-20, 0, 0)), (0.7, (-5, 0, 0)), (1, (-92, -8, 0))])}
    p["L_Shoulder"] = {"r": at([(0, (-10, 0, 22)), (0.3, (-80, 0, 75)), (0.6, (-175, 0, 10)), (0.7, (-45, 0, 5)),
                                (0.85, (-45, 0, 5)), (1, (-10, 0, 22))])}
    p["L_Elbow"] = {"r": at([(0, (-38, 0, 0)), (0.3, (-10, 0, 0)), (0.6, (-20, 0, 0)), (0.7, (-5, 0, 0)), (1, (-38, 0, 0))])}
    p["Spine1"] = {"r": at([(0, (0, 0, 0)), (0.35, (-8, 0, 0)), (0.6, (-12, 0, 0)), (0.7, (25, 0, 0)), (0.85, (22, 0, 0)), (1, (0, 0, 0))])}
    p["Head"] = {"r": at([(0, (3, 0, 0)), (0.35, (-20, 0, 0)), (0.6, (-25, 0, 0)), (0.7, (15, 0, 0)), (1, (3, 0, 0))])}
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = {"r": at([(0, (0, 0, s * 4)), (0.35, (-15, 0, s * 14)), (0.6, (-20, 0, s * 16)),
                                     (0.7, (-55, 0, s * 18)), (0.85, (-55, 0, s * 18)), (1, (0, 0, s * 4))])}
        p[side + "_Knee"] = {"r": at([(0, (0, 0, 0)), (0.35, (35, 0, 0)), (0.6, (45, 0, 0)), (0.7, (90, 0, 0)),
                                      (0.85, (90, 0, 0)), (1, (0, 0, 0))])}
        p[side + "_Foot"] = {"r": at([(0, (0, 0, 0)), (0.35, (30, 0, 0)), (0.7, (-35, 0, 0)), (0.85, (-35, 0, 0)), (1, (0, 0, 0))])}
    p["Cape1"] = {"r": at([(0, (8, 0, 0)), (0.35, (-10, 0, 0)), (0.6, (-15, 0, 0)), (0.7, (70, 0, 0)), (1, (8, 0, 0))])}
    p["Cape2"] = {"r": at([(0, (3, 0, 0)), (0.6, (-15, 0, 0)), (0.8, (30, 0, 0)), (1, (3, 0, 0))])}
    p["Cape3"] = {"r": at([(0, (4, 0, 0)), (0.6, (-10, 0, 0)), (0.85, (35, 0, 0)), (1, (4, 0, 0))])}
    p["HairBack"] = {"r": at([(0, (0, 0, 0)), (0.6, (-15, 0, 0)), (0.75, (25, 0, 0)), (1, (0, 0, 0))])}
    p["R_Weapon"] = {"s": at([(0, 1.0), (0.6, 1.6), (0.68, 1.9), (0.8, 1.0), (1, 1.0)])}
    if 0.25 * T <= t <= 0.68 * T:                       # storm gathers overhead
        s = at([(0.25, 0.0001), (0.45, 0.8), (0.62, 1.0), (0.68, 0.0001)])
        p["FX_Ring2"] = {"pos": (0, 48, 0), "s": (s, 1.0, s), "r": (0, -900 * t, 0)}
        sparks(p, t, amount=1.5)
    if 0.66 * T <= t <= 0.86 * T:                       # the sky bolt
        u = (t - 0.66 * T) / (0.2 * T)
        s = 0.0001 if u > 0.9 else track(u, [(0, 0.0001), (0.2, 1.0)])
        p["FX_SkyBolt"] = {"pos": (0, 70, 18), "s": (1.0, s, 1.0), "r": (0, 30 * flick(t, 60, 30) - 15, 0)}
    if 0.7 * T <= t <= 0.95 * T:                        # ground shockwave
        s = at([(0.7, 0.0001), (0.78, 1.25), (0.88, 1.0), (0.95, 0.0001)])
        p["FX_Impact"] = {"pos": (0, 0, 18), "s": s, "r": (0, 20 * flick(t, 70, 20), 0)}
    return p


def taunt(t):
    """Booming laugh with the bolt raised, lightning dancing on it."""
    p = base(t, 0.5)
    T = 2.0

    def at(k):
        return track(t, [(a * T, v) for a, v in k])
    laugh = 4 * S(TAU * t * 5) if 0.3 * T < t < 0.8 * T else 0
    p["R_Shoulder"] = {"r": at([(0, (-18, 0, -14)), (0.2, (-165, 0, -20)), (0.85, (-165, 0, -20)), (1, (-18, 0, -14))])}
    p["R_Elbow"] = {"r": at([(0, (-92, -8, 0)), (0.2, (-25, 0, 0)), (0.85, (-25, 0, 0)), (1, (-92, -8, 0))])}
    p["L_Shoulder"] = {"r": at([(0, (-10, 0, 22)), (0.2, (15, 0, 45)), (0.85, (15, 0, 45)), (1, (-10, 0, 22))])}
    p["L_Elbow"] = {"r": at([(0, (-38, 0, 0)), (0.2, (-95, 40, 0)), (0.85, (-95, 40, 0)), (1, (-38, 0, 0))])}
    p["Spine2"] = {"r": (at([(0, 0), (0.3, -12), (0.8, -12), (1, 0)]) + laugh, 0, 0)}
    p["Head"] = {"r": (at([(0, 3), (0.3, -25), (0.8, -25), (1, 3)]) + laugh, 0, 0)}
    p["Jaw"] = {"r": (at([(0, 0), (0.3, 12), (0.8, 12), (1, 0)]) + abs(laugh) * 2, 0, 0)}
    if 0.2 * T <= t <= 0.85 * T:
        sparks(p, t, ("R_Spark",), 1.6)
    return p


def death(t):
    p = base(t, 0)
    T = 1.6

    def at(k):
        return track(t, [(a * T, v) for a, v in k])
    p["Pelvis"] = {"t": (0, at([(0, 0), (0.3, -2), (0.55, -6), (0.8, -10), (1, -10)]), 0),
                   "r": at([(0, (0, 0, 0)), (0.3, (8, 0, 0)), (0.55, (20, 0, 0)), (0.8, (-78, 0, 8)), (1, (-84, 0, 8))])}
    for side, s in (("R", -1), ("L", 1)):
        p[side + "_Hip"] = {"r": at([(0, (0, 0, s * 4)), (0.3, (-30, 0, s * 6)), (0.55, (-85, 0, s * 10)),
                                     (0.8, (-20, 0, s * 16)), (1, (-10, 0, s * 18))])}
        p[side + "_Knee"] = {"r": at([(0, (0, 0, 0)), (0.3, (40, 0, 0)), (0.55, (110, 0, 0)), (0.8, (30, 0, 0)), (1, (20, 0, 0))])}
        p[side + "_Shoulder"] = {"r": at([(0, (-15, 0, s * 18)), (0.3, (-40, 0, s * 25)), (0.55, (-20, 0, s * 20)),
                                          (0.8, (-150, 0, s * 70)), (1, (-160, 0, s * 80))])}
        p[side + "_Elbow"] = {"r": at([(0, (-60, 0, 0)), (0.55, (-40, 0, 0)), (1, (-10, 0, 0))])}
    p["Head"] = {"r": at([(0, (3, 0, 0)), (0.3, (25, 0, 0)), (0.55, (30, 0, 0)), (0.8, (-15, 25, 0)), (1, (-10, 35, 0))])}
    p["Cape1"] = {"r": at([(0, (8, 0, 0)), (0.55, (20, 0, 0)), (0.8, (-50, 0, 0)), (1, (-60, 0, 0))])}
    p["R_Weapon"] = {"s": at([(0, 1.0), (0.5, 1.0), (0.7, 0.0001), (1, 0.0001)])}
    if t < 0.5 * T:
        sparks(p, t, amount=at([(0, 1.0), (0.5, 0.2)]))
    return p


# name, seconds, fn, loops
CLIPS = [
    ("Idle", 2.4, idle, True),
    ("Run", 0.6, run, True),
    ("Attack", 1.0, attack, False),
    ("Q", 1.0, skill_q, False),
    ("W", 1.2, skill_w, False),
    ("E", 1.0, skill_e, False),
    ("R", 1.8, skill_r, False),
    ("Taunt", 2.0, taunt, False),
    ("Death", 1.6, death, False),
]
