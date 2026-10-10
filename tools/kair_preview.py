"""Render KAIR models to PNG without the game, using the lab's own skinning.

    python3 tools/kair_preview.py ImportedModels/Zeus sheet.png
        [--clips Idle,Run,Attack] [--frames 6] [--size 220] [--lit]

Draws a contact sheet: one row per clip, evenly spaced frames across it,
front view, root position locked -- the same framing RealModelLab uses.
Textures come from materials.txt / default.png like RealModelLab. Shading is
unlit by default because the lab renders with Unlit/Texture; --lit adds a
simple key light to judge form.
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kair  # noqa: E402


def load_textures(folder, model):
    mapping = {}
    mp = os.path.join(folder, "materials.txt")
    if os.path.exists(mp):
        for line in open(mp, encoding="utf-8-sig"):
            if "=" in line:
                k, v = line.split("=", 1)
                mapping[k.strip().lower()] = v.strip()
    tex = {}
    for m in model.meshes:
        fn = mapping.get(m.name.lower())
        if not fn and os.path.exists(os.path.join(folder, "default.png")):
            fn = "default.png"
        path = os.path.join(folder, fn) if fn else None
        if path and os.path.exists(path):
            tex[m.name] = np.asarray(Image.open(path).convert("RGBA"), np.float32) / 255.0
    return tex


def render(model, poses, textures, size=(300, 360), lit=False, bounds=None, bg=(5, 6, 14)):
    W, H = size
    sk = kair.skin(model, poses)
    if bounds is None:
        allp = np.concatenate([p for m, p, _ in sk if len(p) > 3])
        lo, hi = allp.min(0), allp.max(0)
    else:
        lo, hi = bounds
    center = (lo + hi) / 2
    half = max((hi[1] - lo[1]) / 2, (hi[0] - lo[0]) / 2 * H / W) * 1.18
    scale = H / (2 * half)

    color = np.zeros((H, W, 3), np.float32)
    color[:] = np.array(bg) / 255.0
    depth = np.full((H, W), -np.inf, np.float32)
    light = np.array([-0.4, 0.6, 0.7])
    light /= np.linalg.norm(light)

    for m, p, n in sk:
        if len(p) <= 3:
            continue
        # camera at +Z looking -Z (Unity): screen right = world -X
        sx = (-(p[:, 0] - center[0])) * scale + W / 2
        sy = (-(p[:, 1] - center[1])) * scale + H / 2
        sz = p[:, 2]
        tex = textures.get(m.name)
        tris = len(p) // 3
        for t in range(tris):
            i = 3 * t
            x0, x1, x2 = sx[i:i + 3]
            y0, y1, y2 = sy[i:i + 3]
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            minx, maxx = int(max(0, np.floor(min(x0, x1, x2)))), int(min(W - 1, np.ceil(max(x0, x1, x2))))
            miny, maxy = int(max(0, np.floor(min(y0, y1, y2)))), int(min(H - 1, np.ceil(max(y0, y1, y2))))
            if minx > maxx or miny > maxy:
                continue
            xs, ys = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
            a = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / den
            b = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / den
            c = 1 - a - b
            inside = (a >= 0) & (b >= 0) & (c >= 0)
            if not inside.any():
                continue
            z = a * sz[i] + b * sz[i + 1] + c * sz[i + 2]
            region = depth[miny:maxy + 1, minx:maxx + 1]
            win = inside & (z > region)
            if not win.any():
                continue
            if tex is not None:
                uv = m.uvs[i:i + 3]
                u = a * uv[0, 0] + b * uv[1, 0] + c * uv[2, 0]
                v = a * uv[0, 1] + b * uv[1, 1] + c * uv[2, 1]
                th, tw = tex.shape[:2]
                tx = np.clip((u % 1.0) * tw, 0, tw - 1).astype(int)
                ty = np.clip((1 - (v % 1.0)) * th, 0, th - 1).astype(int)
                rgb = tex[ty, tx, :3]
            else:
                rgb = np.broadcast_to(np.array([0.7, 0.7, 0.75], np.float32), xs.shape + (3,))
            if lit:
                nn = n[i:i + 3].mean(0)
                nn = nn / max(np.linalg.norm(nn), 1e-9)
                k = 0.45 + 0.55 * max(0.0, float(np.dot(nn, light)))
                rgb = rgb * k
            region[win] = z[win]
            color[miny:maxy + 1, minx:maxx + 1][win] = rgb[win]
    return Image.fromarray((np.clip(color, 0, 1) * 255).astype(np.uint8))


def contact_sheet(folder, out, clips=None, frames=6, size=220, lit=False):
    model = kair.load(os.path.join(folder, "model.bin.gz"))
    tex = load_textures(folder, model)
    names = clips or list(model.clips)
    W, H = size, int(size * 1.2)
    label_w = 90
    sheet = Image.new("RGB", (label_w + W * frames, H * (len(names) + 1)), (20, 22, 30))
    d = ImageDraw.Draw(sheet)

    rest = kair.rest_poses(model)
    allp = np.concatenate([p for m, p, _ in kair.skin(model, rest) if len(p) > 3])
    lo, hi = allp.min(0), allp.max(0)
    pad = (hi - lo) * 0.25
    bounds = (lo - pad, hi + pad)

    sheet.paste(render(model, rest, tex, (W, H), lit, bounds), (label_w, 0))
    d.text((6, H // 2), "rest", fill=(230, 230, 230))
    for r, name in enumerate(names):
        fr = model.clips[name]
        d.text((6, H * (r + 1) + H // 2), "%s\n%d f" % (name, len(fr)), fill=(230, 230, 230))
        for c in range(frames):
            fi = int(round(c * (len(fr) - 1) / max(1, frames - 1)))
            img = render(model, fr[fi], tex, (W, H), lit, bounds)
            sheet.paste(img, (label_w + c * W, H * (r + 1)))
    sheet.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="folder containing model.bin.gz (+ textures, materials.txt)")
    ap.add_argument("out")
    ap.add_argument("--clips", default=None)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--size", type=int, default=220)
    ap.add_argument("--lit", action="store_true")
    a = ap.parse_args()
    contact_sheet(a.folder, a.out, a.clips.split(",") if a.clips else None, a.frames, a.size, a.lit)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
