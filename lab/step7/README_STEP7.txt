ZEUSLAB STEP 7 — CLEAN MODEL PASS

WHY THE MODELS LOOKED JANKY
===========================
The Step 6 viewer was deliberately raw. It rendered every mesh in each model
and sampled animation frames directly at 30 FPS.

Several community files contain mutually-exclusive meshes:
- Kai'Sa: base geometry + Form3_Changes + Pistols_Form3
- Qiyana: default/rock/grass/water weapon variants + recall rope
- Evelynn: normal body + shadow/shade body in the same file

Rendering all of those at once creates obvious interpenetration/clipping.

STEP 7 CLEANUP
==============
- Kai'Sa alternate Form 3 meshes hidden in normal presentation.
- Qiyana uses only her default weapon in normal presentation.
- Evelynn normal/shade meshes are mutually exclusive; ShadeIdle selects shade.
- Animation frames are interpolated instead of hard-snapped.
- 0.18 sec smooth crossfade when changing animation clips.
- Root motion is locked in the viewer so attack/run clips cannot drag the
  whole character around.
- Camera reframes against the currently-visible skinned renderers with margin.

This is the beginning of our final animation/presentation layer. Individual
heroes will still receive per-animation cleanup when we make them production
characters.

CUSTOM-ONLY ROSTER
==================
Step 6 Player.log proved the reason the roster stayed vanilla:
  Sixfold runtime assemblies = 0/4 loaded
  custom playable heroes     = 0
  live vanilla heroes        = 65

So ZeusLab correctly refused to clear the roster.

We are stopping the dependency on Sixfold's runtime registration for the
finished project. The goal is for ZeusLab to register ZEUS_HERO and every
future custom hero itself.

HERO API RESEARCH
=================
Run:
  COLLECT_HERO_API_RESEARCH.cmd

It creates:
  Desktop\ZeusLab_HeroAPI_Research.zip

Upload that ZIP. It contains the game API assemblies + both mod.json files +
selected community hero DLLs. That is what is needed to implement a genuine
ZEUS_HERO UnitSetting/ability/card registration instead of another temporary
roster trick.

INSTALL
=======
1. Close Esports Godfather.
2. Extract the whole ZIP.
3. Run INSTALL_STEP7_CLEAN_MODEL_PASS.cmd.
4. Launch and test Janna, Kai'Sa, Qiyana, Evelynn and Zed.
5. Run COLLECT_HERO_API_RESEARCH.cmd and upload the resulting ZIP.
