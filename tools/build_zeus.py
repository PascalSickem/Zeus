"""One command: voxel parts -> .glb -> KAIR lab folder -> preview sheets.

    python3 tools/build_zeus.py            # build + previews
    python3 tools/build_zeus.py --no-preview

Outputs:
    build/zeus_voxel.glb               rig + animations (open in Blender if you like)
    build/ImportedModels/Zeus/         model.bin.gz + Zeus_Palette.png + materials.txt
    build/zeus_preview_front.png       every clip, lab camera (front)
    build/zeus_preview_game.png        every clip, game-style camera (from above)
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import gltf_to_kair  # noqa: E402
import kair  # noqa: E402
import voxel_build  # noqa: E402


def preview(folder, out, yaw, pitch, frames=6, size=160):
    import numpy as np
    from PIL import Image, ImageDraw
    import kair_preview as kp
    m = kair.load(os.path.join(folder, "model.bin.gz"))
    tex = kp.load_textures(folder, m)
    W, H = size, int(size * 1.15)
    lo, hi = np.array([-1.0, -0.6, -1.0]), np.array([1.0, 1.5, 1.0])
    sheet = Image.new("RGB", (70 + W * frames, H * len(m.clips)), (20, 22, 30))
    d = ImageDraw.Draw(sheet)
    for r, (name, fr) in enumerate(m.clips.items()):
        d.text((6, r * H + H // 2), "%s\n%d f" % (name, len(fr)), fill=(230, 230, 230))
        for c in range(frames):
            i = int(round(c * (len(fr) - 1) / max(1, frames - 1)))
            img = kp.render(m, fr[i], tex, (W, H), bounds=(lo, hi), bg=(34, 40, 62), yaw=yaw, pitch=pitch)
            sheet.paste(img, (70 + c * W, r * H))
    sheet.save(out)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args()
    build = os.path.join(REPO, "build")
    os.makedirs(build, exist_ok=True)
    glb = os.path.join(build, "zeus_voxel.glb")
    lab = os.path.join(build, "ImportedModels", "Zeus")
    voxel_build.build(os.path.join(REPO, "zeus", "rig.json"), glb)
    for f in os.listdir(lab) if os.path.isdir(lab) else []:
        os.remove(os.path.join(lab, f))       # no stale textures from older builds
    _, errors = gltf_to_kair.convert(glb, lab, quiet=True)
    m = kair.load(os.path.join(lab, "model.bin.gz"))
    print(kair.summary(m))
    errs, warns = kair.validate(m)
    for w in warns:
        print("  WARN ", w)
    for e in errs + errors:
        print("  ERROR", e)
    if errs or errors:
        return 1
    print("lab folder:", lab)
    if not a.no_preview:
        preview(lab, os.path.join(build, "zeus_preview_front.png"), 0, 0)
        preview(lab, os.path.join(build, "zeus_preview_game.png"), -30, 30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
