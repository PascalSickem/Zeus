using GameMain;
using GameMain.UnitSystem;
using Mod;
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.Rendering;

namespace ZeusLab;

internal sealed class MyModScript : ModScrptBase
{
    public override void OnModInit()
    {
        Debug.Log("[ZeusLab] STEP 7 LOADED - CLEAN MODEL PASS");
    }

    public override void OnGameEntered(Game game)
    {
        Debug.Log("[ZeusLab] STEP 7 Game entered.");
        CustomRosterProbe.LogCandidates(game);
        SixfoldRuntimeProbe.LogStatus();
        CustomOnlyRosterBridge.TryApply(game);
        RealModelLab.Ensure();
    }
}

internal static class CustomRosterProbe
{
    public static void LogCandidates(Game game)
    {
        try
        {
            if (game == null || game.C_Rules == null)
            {
                Debug.LogWarning("[ZeusLab][RosterProbe] game.C_Rules unavailable.");
                return;
            }

            object rules = game.C_Rules;
            Type t = rules.GetType();

            Debug.Log("[ZeusLab][RosterProbe] Rules type: " + t.FullName);

            BindingFlags flags =
                BindingFlags.Instance |
                BindingFlags.Public |
                BindingFlags.NonPublic;

            foreach (FieldInfo f in t.GetFields(flags))
            {
                if (!LooksHeroRelated(f.Name, f.FieldType))
                    continue;

                LogMember("FIELD", f.Name, f.FieldType, SafeGet(() => f.GetValue(rules)));
            }

            foreach (PropertyInfo p in t.GetProperties(flags))
            {
                if (!p.CanRead || p.GetIndexParameters().Length != 0)
                    continue;

                if (!LooksHeroRelated(p.Name, p.PropertyType))
                    continue;

                object value = null;
                try { value = p.GetValue(rules, null); } catch { }
                LogMember("PROP", p.Name, p.PropertyType, value);
            }

            LogHeroRosterInventory(rules, t, flags);

            Debug.Log(
                "[ZeusLab][RosterProbe] Probe complete. " +
                "No roster was modified in Step 4.1."
            );
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[ZeusLab][RosterProbe] Probe failed: " + ex);
        }
    }

    private static void LogHeroRosterInventory(
        object rules,
        Type rulesType,
        BindingFlags flags)
    {
        try
        {
            PropertyInfo p =
                rulesType.GetProperty("HeroChangeWeight", flags);

            object value =
                p != null ? p.GetValue(rules, null) : null;

            IDictionary dict = value as IDictionary;

            if (dict == null)
            {
                FieldInfo f =
                    rulesType.GetField(
                        "<HeroChangeWeight>k__BackingField",
                        flags
                    );

                value =
                    f != null ? f.GetValue(rules) : null;

                dict = value as IDictionary;
            }

            if (dict == null)
            {
                Debug.LogWarning(
                    "[ZeusLab][RosterProbe] Could not enumerate HeroChangeWeight."
                );
                return;
            }

            int index = 0;

            foreach (DictionaryEntry entry in dict)
            {
                UnitSetting hero = entry.Key as UnitSetting;

                if (hero == null)
                    continue;

                Debug.Log(
                    "[ZeusLab][RosterProbe][Hero] #" + index +
                    " | Key=" + hero.Key +
                    " | Name=" + hero.Name +
                    " | Id=" + hero.Id +
                    " | IsHero=" + hero.IsHero +
                    " | Weight=" + entry.Value
                );

                index++;
            }

            Debug.Log(
                "[ZeusLab][RosterProbe] Enumerated live HeroChangeWeight heroes=" +
                index
            );
        }
        catch (Exception ex)
        {
            Debug.LogWarning(
                "[ZeusLab][RosterProbe] Hero inventory failed: " + ex
            );
        }
    }


    private static bool LooksHeroRelated(string name, Type type)
    {
        string n = (name ?? string.Empty).ToLowerInvariant();
        string tn = type == null ? string.Empty : type.ToString().ToLowerInvariant();

        return
            n.Contains("hero") ||
            n.Contains("unit") ||
            tn.Contains("hero") ||
            tn.Contains("unitsetting");
    }

    private static object SafeGet(Func<object> getter)
    {
        try { return getter(); }
        catch { return null; }
    }

    private static void LogMember(string kind, string name, Type declaredType, object value)
    {
        string countText = string.Empty;

        ICollection collection = value as ICollection;
        if (collection != null)
            countText = " | Count=" + collection.Count;

        Debug.Log(
            "[ZeusLab][RosterProbe] " + kind +
            " " + name +
            " | Type=" + declaredType +
            countText
        );
    }
}



internal static class SixfoldRuntimeProbe
{
    public static void LogStatus()
    {
        try
        {
            string[] expected =
            {
                "Janna",
                "Kaisa",
                "TacticalArmory",
                "FrostArmory.QiyanaAssets"
            };

            HashSet<string> loaded =
                new HashSet<string>(
                    AppDomain.CurrentDomain
                        .GetAssemblies()
                        .Select(a => a.GetName().Name ?? ""),
                    StringComparer.OrdinalIgnoreCase
                );

            int hits = 0;

            for (int i = 0; i < expected.Length; i++)
            {
                bool present = loaded.Contains(expected[i]);
                if (present)
                    hits++;

                Debug.Log(
                    "[ZeusLab][SixfoldRuntime] " +
                    expected[i] + "=" + (present ? "LOADED" : "NOT_LOADED")
                );
            }

            Debug.Log(
                "[ZeusLab][SixfoldRuntime] Summary=" +
                hits + "/" + expected.Length +
                (hits >= 2
                    ? " | Sixfold runtime assemblies appear ACTIVE."
                    : " | Sixfold runtime does NOT appear active in this session.")
            );
        }
        catch (Exception ex)
        {
            Debug.LogWarning(
                "[ZeusLab][SixfoldRuntime] Probe failed: " + ex.Message
            );
        }
    }
}

internal static class CustomOnlyRosterBridge
{
    private const int MinimumCustomHeroes = 5;

    public static void TryApply(Game game)
    {
        try
        {
            if (game == null || game.C_Rules == null)
            {
                Debug.LogWarning("[ZeusLab][CustomOnly] Rules unavailable.");
                return;
            }

            var weights = game.C_Rules.HeroChangeWeight;
            var abilities = game.C_Rules.HeroAbilitySettings;
            var cards = game.C_Rules.HeroCardTupleSettings;

            if (weights == null || abilities == null || cards == null)
            {
                Debug.LogWarning(
                    "[ZeusLab][CustomOnly] Hero dictionaries unavailable. No changes made."
                );
                return;
            }

            List<UnitSetting> customHeroes =
                weights.Keys
                    .Where(IsCustomHeroKey)
                    .Where(h => abilities.ContainsKey(h) && cards.ContainsKey(h))
                    .ToList();

            Debug.Log(
                "[ZeusLab][CustomOnly] Detected custom playable heroes=" +
                customHeroes.Count +
                " | TotalBefore=" + weights.Count
            );

            foreach (UnitSetting hero in customHeroes)
            {
                Debug.Log(
                    "[ZeusLab][CustomOnly][KEEP] Key=" + hero.Key +
                    " | Name=" + hero.Name +
                    " | Id=" + hero.Id
                );
            }

            // Safety gate: ZeusLab alone currently has no registered custom
            // UnitSettings. Sixfold/Hero Battleground should add many textual
            // hero keys. Never clear the vanilla pool unless a real custom pool
            // is visibly present.
            if (customHeroes.Count < MinimumCustomHeroes)
            {
                Debug.LogWarning(
                    "[ZeusLab][CustomOnly] SAFE NO-OP: fewer than " +
                    MinimumCustomHeroes +
                    " custom playable heroes were detected. " +
                    "Enable Sixfold/Hero Battleground together with ZeusLab " +
                    "for the bridge test. Vanilla roster was NOT changed."
                );
                return;
            }

            var keepWeights =
                customHeroes.ToDictionary(h => h, h => weights[h]);

            var keepAbilities =
                customHeroes.ToDictionary(h => h, h => abilities[h]);

            var keepCards =
                customHeroes.ToDictionary(h => h, h => cards[h]);

            weights.Clear();
            abilities.Clear();
            cards.Clear();

            foreach (UnitSetting hero in customHeroes)
            {
                weights.Add(hero, keepWeights[hero]);
                abilities.Add(hero, keepAbilities[hero]);
                cards.Add(hero, keepCards[hero]);
            }

            // These indexes were zero at our current OnGameEntered seam, but
            // filter them too if another mod/version populates them earlier.
            FilterOptionalIndex(game.C_Rules.HeroAbilityIndex, customHeroes);
            FilterOptionalIndex(game.C_Rules.HeroCardTupleIndex, customHeroes);

            Debug.Log(
                "[ZeusLab][CustomOnly] ACTIVE: vanilla heroes removed from LIVE " +
                "rule dictionaries only. FinalCount=" + weights.Count +
                " | AbilityCount=" + abilities.Count +
                " | CardTupleCount=" + cards.Count
            );
        }
        catch (Exception ex)
        {
            Debug.LogError(
                "[ZeusLab][CustomOnly] FAILED SAFELY. " +
                "No file assets were modified. " + ex
            );
        }
    }

    private static bool IsCustomHeroKey(UnitSetting hero)
    {
        if (hero == null)
            return false;

        string key = hero.Key == null ? "" : hero.Key.ToString().Trim();

        if (string.IsNullOrEmpty(key))
            return false;

        int numeric;
        if (int.TryParse(key, out numeric))
            return false;

        // Sixfold/Hero Battleground catalog uses textual keys such as:
        // AHRI_HERO, FA_JANNA_HERO, FA_KAISA_HERO, etc.
        return true;
    }

    private static void FilterOptionalIndex<TValue>(
        Dictionary<UnitSetting, TValue> index,
        List<UnitSetting> keep)
    {
        if (index == null || index.Count == 0)
            return;

        HashSet<UnitSetting> keepSet = new HashSet<UnitSetting>(keep);

        List<UnitSetting> remove =
            index.Keys.Where(k => !keepSet.Contains(k)).ToList();

        for (int i = 0; i < remove.Count; i++)
            index.Remove(remove[i]);
    }
}

internal sealed class RealModelLab : MonoBehaviour
{
    private static RealModelLab _instance;

    private readonly List<ModelSpec> _specs = new List<ModelSpec>();
    private readonly List<UnityEngine.Object> _ownedObjects = new List<UnityEngine.Object>();

    private RenderTexture _rt;
    private Camera _camera;
    private GameObject _modelRoot;
    private Transform[] _bones;
    private KairModel _model;
    private KairClip _clip;
    private string _clipName = "";
    private float _clipStart;
    private int _lastFrame = -1;

    private readonly List<SkinnedMeshRenderer> _renderers =
        new List<SkinnedMeshRenderer>();

    private readonly Dictionary<string, SkinnedMeshRenderer> _rendererByMesh =
        new Dictionary<string, SkinnedMeshRenderer>(
            StringComparer.OrdinalIgnoreCase
        );

    private KairPose[] _blendFromPose;
    private float _blendStartedAt;
    private const float ClipBlendSeconds = 0.18f;
    private float _nextCameraFitAt;
    private ModelSpec _currentSpec;

    private string _assemblyDir;
    private string _importDir;
    private int _selectedModel = -1;
    private string _status = "Waiting...";
    private bool _flipped = false;


    public static void Ensure()
    {
        if (_instance != null)
            return;

        GameObject host = new GameObject("ZeusLab_RealModelLab");
        UnityEngine.Object.DontDestroyOnLoad(host);
        _instance = host.AddComponent<RealModelLab>();
    }

    private void Start()
    {
        _assemblyDir =
            Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
            ?? string.Empty;

        _importDir = Path.Combine(_assemblyDir, "ImportedModels");

        BuildSpecs();
        BuildCamera();

        int firstAvailable = FindFirstAvailableSpec();
        if (firstAvailable >= 0)
            LoadModel(firstAvailable);
        else
            _status = "No imported models found. Run INSTALL_STEP4_REAL_MODEL_LAB.cmd.";
    }

    private void BuildSpecs()
    {
        _specs.Clear();

        _specs.Add(new ModelSpec("Zeus Prototype", "Zeus", "model.bin.gz"));
        _specs.Add(new ModelSpec("Janna", "Janna", "model.bin.gz"));
        _specs.Add(new ModelSpec("Kai'Sa", "Kaisa", "model.bin.gz"));
        _specs.Add(new ModelSpec("Qiyana", "Qiyana", "model.bin.gz"));
        _specs.Add(new ModelSpec("Evelynn", "Evelynn", "model.bin.gz"));
        _specs.Add(new ModelSpec("Zed", "Zed", "model.bin.gz"));
    }

    private int FindFirstAvailableSpec()
    {
        for (int i = 0; i < _specs.Count; i++)
        {
            if (File.Exists(ModelPath(_specs[i])))
                return i;
        }
        return -1;
    }

    private string ModelPath(ModelSpec spec)
    {
        return Path.Combine(_importDir, spec.Folder, spec.ModelFile);
    }

    private void BuildCamera()
    {
        _rt = new RenderTexture(640, 760, 24, RenderTextureFormat.ARGB32);
        _rt.name = "ZeusLab_RealModelRT";
        _rt.Create();

        GameObject go = new GameObject("ZeusLab_RealModelCamera");
        UnityEngine.Object.DontDestroyOnLoad(go);

        _camera = go.AddComponent<Camera>();
        _camera.targetTexture = _rt;
        _camera.clearFlags = CameraClearFlags.SolidColor;
        _camera.backgroundColor = new Color(0.018f, 0.024f, 0.055f, 1f);
        _camera.cullingMask = 1 << 30;
        _camera.orthographic = true;
        _camera.nearClipPlane = 0.01f;
        _camera.farClipPlane = 100f;
    }

    private void LoadModel(int index)
    {
        if (index < 0 || index >= _specs.Count)
            return;

        ModelSpec spec = _specs[index];
        string path = ModelPath(spec);

        if (!File.Exists(path))
        {
            _status = spec.DisplayName + " model missing.";
            return;
        }

        try
        {
            DestroyCurrentModel();

            _status = "Loading " + spec.DisplayName + "...";
            _selectedModel = index;
            _currentSpec = spec;

            _model = KairReader.Load(path);

            BuildSkeleton(_model);
            BuildMeshes(_model, spec);
            FitCamera(_model.Bounds);

            string initial =
                _model.Clips.ContainsKey("Idle")
                    ? "Idle"
                    : FirstClipName();

            SelectClip(initial);

            _status =
                spec.DisplayName +
                " | CLEAN PREVIEW" +
                " | Bones=" + _model.Bones.Length +
                " | Meshes=" + _model.Meshes.Length +
                " | Clips=" + _model.Clips.Count;

            Debug.Log(
                "[ZeusLab][RealModel] LOADED " + spec.DisplayName +
                " | Bones=" + _model.Bones.Length +
                " | Meshes=" + _model.Meshes.Length +
                " | Clips=" + _model.Clips.Count +
                " | Bounds=" + _model.Bounds
            );
        }
        catch (Exception ex)
        {
            _status = spec.DisplayName + " FAILED - see Player.log";
            Debug.LogError(
                "[ZeusLab][RealModel] FAILED " + spec.DisplayName + ":\n" + ex
            );
        }
    }

    private void DestroyCurrentModel()
    {
        if (_modelRoot != null)
            UnityEngine.Object.Destroy(_modelRoot);

        for (int i = 0; i < _ownedObjects.Count; i++)
        {
            if (_ownedObjects[i] != null)
                UnityEngine.Object.Destroy(_ownedObjects[i]);
        }

        _ownedObjects.Clear();
        _renderers.Clear();
        _rendererByMesh.Clear();
        _modelRoot = null;
        _bones = null;
        _model = null;
        _clip = null;
        _clipName = "";
        _lastFrame = -1;
        _blendFromPose = null;
        _currentSpec = null;
    }

    private void BuildSkeleton(KairModel model)
    {
        _modelRoot = new GameObject("ZeusLab_ModelRoot");
        _modelRoot.layer = 30;
        UnityEngine.Object.DontDestroyOnLoad(_modelRoot);

        _bones = new Transform[model.Bones.Length];

        for (int i = 0; i < model.Bones.Length; i++)
        {
            GameObject boneGo = new GameObject("B_" + model.Bones[i].Name);
            boneGo.layer = 30;
            _bones[i] = boneGo.transform;
        }

        for (int i = 0; i < model.Bones.Length; i++)
        {
            KairBone b = model.Bones[i];

            Transform parent =
                b.ParentIndex >= 0 && b.ParentIndex < _bones.Length
                    ? _bones[b.ParentIndex]
                    : _modelRoot.transform;

            _bones[i].SetParent(parent, false);
            ApplyPose(_bones[i], b.RestPose);
        }

        ApplyFlip();
    }

    private void BuildMeshes(KairModel model, ModelSpec spec)
    {
        Shader texShader =
            Shader.Find("Unlit/Texture") ??
            Shader.Find("Sprites/Default");

        Shader colorShader =
            Shader.Find("Unlit/Color") ??
            Shader.Find("Standard");

        if (texShader == null && colorShader == null)
            throw new InvalidOperationException("No usable shader found.");

        for (int m = 0; m < model.Meshes.Length; m++)
        {
            KairMesh src = model.Meshes[m];

            Mesh mesh = new Mesh();
            mesh.name = spec.DisplayName + "_" + src.Name;

            if (src.Positions.Length > 65535)
                mesh.indexFormat = IndexFormat.UInt32;

            mesh.vertices = src.Positions;
            mesh.normals = src.Normals;
            mesh.uv = src.Uvs;
            mesh.boneWeights = src.Weights;
            mesh.bindposes = model.BindPoses;

            int[] triangles = new int[src.Positions.Length];
            for (int i = 0; i < triangles.Length; i++)
                triangles[i] = i;

            mesh.triangles = triangles;
            mesh.RecalculateBounds();

            _ownedObjects.Add(mesh);

            GameObject part = new GameObject("M_" + src.Name);
            part.layer = 30;
            part.transform.SetParent(_modelRoot.transform, false);

            SkinnedMeshRenderer smr =
                part.AddComponent<SkinnedMeshRenderer>();

            smr.sharedMesh = mesh;
            smr.bones = _bones;
            smr.rootBone = FindRootBone();
            smr.updateWhenOffscreen = true;
            smr.localBounds = mesh.bounds;

            Texture2D texture =
                TryLoadTexture(spec, src.Name);

            Material material;

            if (texture != null && texShader != null)
            {
                material = new Material(texShader);
                material.mainTexture = texture;
            }
            else
            {
                material = new Material(colorShader ?? texShader);
                material.color = FallbackColor(src.Name, m);
            }

            material.name =
                "ZeusLab_" + spec.DisplayName + "_" + src.Name;

            _ownedObjects.Add(material);
            smr.sharedMaterial = material;

            _renderers.Add(smr);
            _rendererByMesh[src.Name] = smr;
        }

        ApplyMeshVisibilityProfile();
    }

    private void ApplyMeshVisibilityProfile()
    {
        if (_currentSpec == null)
            return;

        foreach (KeyValuePair<string, SkinnedMeshRenderer> pair in _rendererByMesh)
        {
            pair.Value.enabled =
                ShouldMeshBeVisible(
                    _currentSpec.Folder,
                    pair.Key,
                    _clipName
                );
        }
    }

    private static bool ShouldMeshBeVisible(
        string modelFolder,
        string meshName,
        string clipName)
    {
        string folder = (modelFolder ?? "").ToLowerInvariant();
        string mesh = (meshName ?? "").ToLowerInvariant();
        string clip = (clipName ?? "").ToLowerInvariant();

        // Kai'Sa's asset contains alternate transformation meshes.
        // Showing both the base and Form 3 geometry at the same time is one
        // source of the obvious clipping in the raw viewer.
        if (folder == "kaisa")
        {
            if (mesh == "form3_changes" || mesh == "pistols_form3")
                return false;

            return true;
        }

        // Qiyana packages all elemental weapon variants plus a recall rope in
        // one file. For the normal presentation only the base body + default
        // weapon should be visible.
        if (folder == "qiyana")
        {
            if (mesh == "recall_rope")
                return false;

            if (mesh.StartsWith("weapon_"))
                return mesh == "weapon_default";

            return true;
        }

        // Evelynn packages normal and shade versions together. Rendering both
        // simultaneously produces the doubled/intersecting silhouette seen in
        // the Step 6 recording.
        if (folder == "evelynn")
        {
            bool shade = clip == "shadeidle";
            bool shadowMesh = mesh.Contains("shadow");

            return shade ? shadowMesh : !shadowMesh;
        }

        return true;
    }

    private Transform FindRootBone()
    {
        if (_model == null || _bones == null)
            return null;

        for (int i = 0; i < _model.Bones.Length; i++)
        {
            if (_model.Bones[i].ParentIndex < 0)
                return _bones[i];
        }

        return _bones.Length > 0 ? _bones[0] : null;
    }

    private Texture2D TryLoadTexture(ModelSpec spec, string meshName)
    {
        string folder =
            Path.Combine(_importDir, spec.Folder);

        string file = ResolveMaterialFile(folder, spec.Folder, meshName);

        if (string.IsNullOrEmpty(file))
            return null;

        string full = Path.Combine(folder, file);

        if (!File.Exists(full))
            return null;

        try
        {
            byte[] bytes = File.ReadAllBytes(full);
            Texture2D tex =
                new Texture2D(2, 2, TextureFormat.RGBA32, false);

            if (!ImageConversion.LoadImage(tex, bytes, false))
            {
                UnityEngine.Object.Destroy(tex);
                return null;
            }

            tex.name = spec.DisplayName + "_" + meshName + "_Texture";
            _ownedObjects.Add(tex);
            return tex;
        }
        catch
        {
            return null;
        }
    }

    private static string ResolveMaterialFile(
        string folder,
        string modelFolder,
        string meshName)
    {
        string mapPath = Path.Combine(folder, "materials.txt");

        if (File.Exists(mapPath))
        {
            string[] lines = File.ReadAllLines(mapPath);

            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i];
                int eq = line.IndexOf('=');

                if (eq <= 0)
                    continue;

                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1).Trim();

                if (string.Equals(
                        key,
                        meshName,
                        StringComparison.OrdinalIgnoreCase))
                {
                    return value;
                }
            }
        }

        if (string.Equals(modelFolder, "Qiyana", StringComparison.OrdinalIgnoreCase))
        {
            string n = (meshName ?? string.Empty).ToLowerInvariant();
            return
                n.Contains("weapon") ||
                n.Contains("ring") ||
                n.Contains("blade")
                    ? "weapon.png"
                    : "body.png";
        }

        string defaultPng = Path.Combine(folder, "default.png");
        if (File.Exists(defaultPng))
            return "default.png";

        return null;
    }

    private static Color FallbackColor(string meshName, int index)
    {
        string n = (meshName ?? string.Empty).ToLowerInvariant();

        if (n.Contains("hair"))
            return new Color(0.86f, 0.88f, 0.95f, 1f);

        if (n.Contains("metal") || n.Contains("weapon"))
            return new Color(0.75f, 0.58f, 0.23f, 1f);

        float t = (index % 7) / 6f;
        return Color.HSVToRGB(0.52f + t * 0.18f, 0.55f, 0.88f);
    }

    private void FitCamera(Bounds b)
    {
        Vector3 center = b.center;
        Vector3 size = b.size;

        float aspect =
            (float)_rt.width / (float)_rt.height;

        float halfHeight = Mathf.Max(0.5f, size.y * 0.58f);
        float halfWidthNeed =
            Mathf.Max(0.5f, size.x * 0.58f / aspect);

        _camera.orthographicSize =
            Mathf.Max(halfHeight, halfWidthNeed);

        float distance =
            Mathf.Max(4f, Mathf.Max(size.x, Mathf.Max(size.y, size.z)) * 3f);

        _camera.transform.position =
            new Vector3(center.x, center.y, center.z + distance);

        _camera.transform.LookAt(center);
    }

    private void ApplyFlip()
    {
        if (_modelRoot != null)
        {
            _modelRoot.transform.rotation =
                Quaternion.Euler(0f, _flipped ? 180f : 0f, 0f);
        }
    }

    private string FirstClipName()
    {
        if (_model == null)
            return null;

        foreach (string key in _model.Clips.Keys)
            return key;

        return null;
    }

    private void SelectClip(string clipName)
    {
        if (_model == null || string.IsNullOrEmpty(clipName))
            return;

        KairClip c;

        if (!_model.Clips.TryGetValue(clipName, out c))
            return;

        _blendFromPose = CaptureCurrentPose();
        _blendStartedAt = Time.unscaledTime;

        _clip = c;
        _clipName = clipName;
        _clipStart = Time.unscaledTime;
        _lastFrame = -1;

        ApplyMeshVisibilityProfile();

        Debug.Log(
            "[ZeusLab][RealModel] Animation -> " +
            _clipName +
            " | Frames=" + _clip.Frames.Length +
            " | SmoothInterpolation=ON | CrossFade=" +
            ClipBlendSeconds.ToString("0.00") + "s"
        );
    }

    private KairPose[] CaptureCurrentPose()
    {
        if (_bones == null)
            return null;

        KairPose[] pose = new KairPose[_bones.Length];

        for (int i = 0; i < _bones.Length; i++)
        {
            Transform t = _bones[i];

            pose[i] = new KairPose
            {
                Position = t.localPosition,
                Rotation = t.localRotation,
                Scale = t.localScale
            };
        }

        return pose;
    }

    private void Update()
    {
        if (_clip == null ||
            _bones == null ||
            _clip.Frames == null ||
            _clip.Frames.Length == 0)
        {
            return;
        }

        float frameFloat =
            (Time.unscaledTime - _clipStart) * 30f;

        int frame0 =
            Mathf.FloorToInt(frameFloat) %
            _clip.Frames.Length;

        if (frame0 < 0)
            frame0 += _clip.Frames.Length;

        int frame1 =
            (frame0 + 1) %
            _clip.Frames.Length;

        float frameT =
            frameFloat - Mathf.Floor(frameFloat);

        ApplyInterpolatedFrame(
            _clip.Frames[frame0],
            _clip.Frames[frame1],
            frameT
        );

        if (Time.unscaledTime >= _nextCameraFitAt)
        {
            _nextCameraFitAt = Time.unscaledTime + 0.08f;
            UpdateDynamicCameraFit();
        }
    }

    private void ApplyInterpolatedFrame(
        KairPose[] a,
        KairPose[] b,
        float t)
    {
        int count =
            Mathf.Min(
                _bones.Length,
                Mathf.Min(a.Length, b.Length)
            );

        float blendT =
            Mathf.Clamp01(
                (Time.unscaledTime - _blendStartedAt) /
                ClipBlendSeconds
            );

        for (int i = 0; i < count; i++)
        {
            KairPose desired =
                InterpolatePose(a[i], b[i], t);

            // Root motion is intentionally disabled in the character viewer.
            // EGF should control a hero's world movement; animation should not
            // drag the whole character through the preview/fight scene.
            if (_model.Bones[i].ParentIndex < 0)
                desired.Position = _model.Bones[i].RestPose.Position;

            if (_blendFromPose != null &&
                i < _blendFromPose.Length &&
                blendT < 1f)
            {
                desired =
                    InterpolatePose(
                        _blendFromPose[i],
                        desired,
                        SmoothStep01(blendT)
                    );
            }

            ApplyPose(_bones[i], desired);
        }

        if (blendT >= 1f)
            _blendFromPose = null;
    }

    private static KairPose InterpolatePose(
        KairPose a,
        KairPose b,
        float t)
    {
        return new KairPose
        {
            Position = Vector3.Lerp(a.Position, b.Position, t),
            Rotation = Quaternion.Slerp(a.Rotation, b.Rotation, t),
            Scale = Vector3.Lerp(a.Scale, b.Scale, t)
        };
    }

    private static float SmoothStep01(float t)
    {
        t = Mathf.Clamp01(t);
        return t * t * (3f - 2f * t);
    }

    private void UpdateDynamicCameraFit()
    {
        if (_camera == null || _rt == null || _renderers.Count == 0)
            return;

        bool found = false;
        Bounds bounds = new Bounds();

        for (int i = 0; i < _renderers.Count; i++)
        {
            SkinnedMeshRenderer r = _renderers[i];

            if (r == null || !r.enabled || !r.gameObject.activeInHierarchy)
                continue;

            if (!found)
            {
                bounds = r.bounds;
                found = true;
            }
            else
            {
                bounds.Encapsulate(r.bounds);
            }
        }

        if (!found)
            return;

        float aspect =
            (float)_rt.width /
            Mathf.Max(1f, (float)_rt.height);

        float margin = 1.18f;

        float targetSize =
            Mathf.Max(
                0.5f,
                Mathf.Max(
                    bounds.extents.y,
                    bounds.extents.x / Mathf.Max(0.1f, aspect)
                ) * margin
            );

        _camera.orthographicSize =
            Mathf.Lerp(
                _camera.orthographicSize,
                targetSize,
                0.22f
            );

        Vector3 targetPosition =
            new Vector3(
                bounds.center.x,
                bounds.center.y,
                bounds.center.z +
                    Mathf.Max(
                        4f,
                        bounds.extents.magnitude * 4f
                    )
            );

        _camera.transform.position =
            Vector3.Lerp(
                _camera.transform.position,
                targetPosition,
                0.22f
            );

        _camera.transform.LookAt(bounds.center);
    }

    private static void ApplyPose(Transform t, KairPose p)
    {
        t.localPosition = p.Position;
        t.localRotation = p.Rotation;
        t.localScale = p.Scale;
    }

    private void OnGUI()
    {
        float w = 560f;
        float h = 760f;
        float x = Screen.width - w - 18f;
        float y = 18f;

        GUI.Box(
            new Rect(x, y, w, h),
            "ZEUS LAB — CLEAN CHARACTER LAB"
        );

        GUI.DrawTexture(
            new Rect(x + 12f, y + 28f, w - 24f, 545f),
            _rt,
            ScaleMode.ScaleToFit,
            false
        );

        GUI.Label(
            new Rect(x + 16f, y + 578f, w - 32f, 42f),
            _status
        );

        float bx = x + 14f;
        float by = y + 620f;
        float bw = 82f;
        float bh = 26f;
        float gap = 6f;

        for (int i = 0; i < _specs.Count; i++)
        {
            ModelSpec spec = _specs[i];

            bool exists = File.Exists(ModelPath(spec));
            GUI.enabled = exists;

            if (GUI.Button(
                    new Rect(
                        bx + (i % 6) * (bw + gap),
                        by,
                        bw,
                        bh
                    ),
                    spec.DisplayName))
            {
                LoadModel(i);
            }
        }

        GUI.enabled = true;

        if (GUI.Button(
                new Rect(x + 14f, y + 652f, 92f, 25f),
                "Flip 180"))
        {
            _flipped = !_flipped;
            ApplyFlip();
        }

        if (_model != null)
        {
            int clipIndex = 0;

            foreach (KeyValuePair<string, KairClip> pair in _model.Clips)
            {
                int col = clipIndex % 6;
                int row = clipIndex / 6;

                if (row >= 2)
                    break;

                if (GUI.Button(
                        new Rect(
                            x + 112f + col * 72f,
                            y + 652f + row * 30f,
                            66f,
                            25f
                        ),
                        pair.Key))
                {
                    SelectClip(pair.Key);
                }

                clipIndex++;
            }
        }

        GUI.Label(
            new Rect(x + 14f, y + 714f, w - 28f, 35f),
            "Current clip: " +
            (string.IsNullOrEmpty(_clipName) ? "<none>" : _clipName) +
            " | CLEAN MODE: mesh states + interpolation + crossfade + root lock."
        );
    }

    private void OnDestroy()
    {
        DestroyCurrentModel();

        if (_rt != null)
        {
            _rt.Release();
            UnityEngine.Object.Destroy(_rt);
        }
    }

    private sealed class ModelSpec
    {
        public readonly string DisplayName;
        public readonly string Folder;
        public readonly string ModelFile;

        public ModelSpec(string displayName, string folder, string modelFile)
        {
            DisplayName = displayName;
            Folder = folder;
            ModelFile = modelFile;
        }
    }
}

internal static class KairReader
{
    public static KairModel Load(string gzipPath)
    {
        byte[] raw;

        using (FileStream fs = File.OpenRead(gzipPath))
        using (GZipStream gz = new GZipStream(fs, CompressionMode.Decompress))
        using (MemoryStream ms = new MemoryStream())
        {
            gz.CopyTo(ms);
            raw = ms.ToArray();
        }

        using (MemoryStream ms = new MemoryStream(raw, false))
        using (BinaryReader br = new BinaryReader(ms, Encoding.UTF8))
        {
            string magic =
                Encoding.ASCII.GetString(br.ReadBytes(4));

            bool supportedMagic =
                magic == "KAIR" ||
                magic == "QIYR" ||
                magic == "EVLR" ||
                magic == "ZEDR";

            if (!supportedMagic)
                throw new InvalidDataException(
                    "Unsupported rigged model format. Magic=" + magic
                );

            Debug.Log("[ZeusLab][ModelFormat] Accepted magic=" + magic);

            int version = br.ReadInt32();
            int boneCount = br.ReadInt32();
            int clipCount = br.ReadInt32();
            int meshCount = br.ReadInt32();

            if (version != 1)
                throw new InvalidDataException(
                    "Unsupported KAIR version " + version
                );

            if (boneCount <= 0 || boneCount > 4096)
                throw new InvalidDataException(
                    "Invalid bone count " + boneCount
                );

            KairBone[] bones =
                new KairBone[boneCount];

            Matrix4x4[] bindPoses =
                new Matrix4x4[boneCount];

            for (int i = 0; i < boneCount; i++)
            {
                string name = ReadText(br);
                int parent = br.ReadInt32();

                bindPoses[i] = ReadMatrix(br);

                bones[i] = new KairBone
                {
                    Name = name,
                    ParentIndex = parent,
                    RestPose = ReadPose(br)
                };
            }

            Dictionary<string, KairClip> clips =
                new Dictionary<string, KairClip>(
                    StringComparer.OrdinalIgnoreCase
                );

            for (int c = 0; c < clipCount; c++)
            {
                string clipName = ReadText(br);
                int frameCount = br.ReadInt32();

                if (frameCount < 0 || frameCount > 10000)
                    throw new InvalidDataException(
                        "Invalid frame count " + frameCount +
                        " for " + clipName
                    );

                KairPose[][] frames =
                    new KairPose[frameCount][];

                for (int f = 0; f < frameCount; f++)
                {
                    br.ReadSingle();

                    KairPose[] frame =
                        new KairPose[boneCount];

                    for (int b = 0; b < boneCount; b++)
                        frame[b] = ReadPose(br);

                    frames[f] = frame;
                }

                clips[clipName] = new KairClip
                {
                    Name = clipName,
                    Frames = frames
                };
            }

            KairMesh[] meshes =
                new KairMesh[meshCount];

            bool boundsInit = false;
            Bounds combined = new Bounds();

            for (int m = 0; m < meshCount; m++)
            {
                string meshName = ReadText(br);
                int vertexCount = br.ReadInt32();

                if (vertexCount < 0 || vertexCount > 2000000)
                    throw new InvalidDataException(
                        "Invalid vertex count " +
                        vertexCount +
                        " for " + meshName
                    );

                Vector3[] positions =
                    new Vector3[vertexCount];

                Vector3[] normals =
                    new Vector3[vertexCount];

                Vector2[] uvs =
                    new Vector2[vertexCount];

                BoneWeight[] weights =
                    new BoneWeight[vertexCount];

                for (int v = 0; v < vertexCount; v++)
                {
                    Vector3 p = new Vector3(
                        br.ReadSingle(),
                        br.ReadSingle(),
                        br.ReadSingle()
                    );

                    positions[v] = p;

                    normals[v] = new Vector3(
                        br.ReadSingle(),
                        br.ReadSingle(),
                        br.ReadSingle()
                    );

                    uvs[v] = new Vector2(
                        br.ReadSingle(),
                        br.ReadSingle()
                    );

                    int i0 = br.ReadInt32();
                    int i1 = br.ReadInt32();
                    int i2 = br.ReadInt32();
                    int i3 = br.ReadInt32();

                    float w0 = br.ReadSingle();
                    float w1 = br.ReadSingle();
                    float w2 = br.ReadSingle();
                    float w3 = br.ReadSingle();

                    weights[v] = new BoneWeight
                    {
                        boneIndex0 = i0,
                        boneIndex1 = i1,
                        boneIndex2 = i2,
                        boneIndex3 = i3,
                        weight0 = w0,
                        weight1 = w1,
                        weight2 = w2,
                        weight3 = w3
                    };

                    if (!boundsInit)
                    {
                        combined = new Bounds(p, Vector3.zero);
                        boundsInit = true;
                    }
                    else
                    {
                        combined.Encapsulate(p);
                    }
                }

                meshes[m] = new KairMesh
                {
                    Name = meshName,
                    Positions = positions,
                    Normals = normals,
                    Uvs = uvs,
                    Weights = weights
                };
            }

            if (br.BaseStream.Position != br.BaseStream.Length)
            {
                Debug.LogWarning(
                    "[ZeusLab][KAIR] trailing bytes=" +
                    (br.BaseStream.Length - br.BaseStream.Position)
                );
            }

            return new KairModel
            {
                Bones = bones,
                BindPoses = bindPoses,
                Clips = clips,
                Meshes = meshes,
                Bounds = combined
            };
        }
    }

    private static string ReadText(BinaryReader br)
    {
        int length = br.ReadInt32();

        if (length < 0 || length > 1024 * 1024)
            throw new InvalidDataException(
                "Invalid KAIR string length " + length
            );

        byte[] bytes = br.ReadBytes(length);

        if (bytes.Length != length)
            throw new EndOfStreamException();

        return Encoding.UTF8.GetString(bytes);
    }

    private static Matrix4x4 ReadMatrix(BinaryReader br)
    {
        Matrix4x4 m = new Matrix4x4();

        m.m00 = br.ReadSingle();
        m.m01 = br.ReadSingle();
        m.m02 = br.ReadSingle();
        m.m03 = br.ReadSingle();

        m.m10 = br.ReadSingle();
        m.m11 = br.ReadSingle();
        m.m12 = br.ReadSingle();
        m.m13 = br.ReadSingle();

        m.m20 = br.ReadSingle();
        m.m21 = br.ReadSingle();
        m.m22 = br.ReadSingle();
        m.m23 = br.ReadSingle();

        m.m30 = br.ReadSingle();
        m.m31 = br.ReadSingle();
        m.m32 = br.ReadSingle();
        m.m33 = br.ReadSingle();

        return m;
    }

    private static KairPose ReadPose(BinaryReader br)
    {
        return new KairPose
        {
            Position = new Vector3(
                br.ReadSingle(),
                br.ReadSingle(),
                br.ReadSingle()
            ),

            Rotation = new Quaternion(
                br.ReadSingle(),
                br.ReadSingle(),
                br.ReadSingle(),
                br.ReadSingle()
            ),

            Scale = new Vector3(
                br.ReadSingle(),
                br.ReadSingle(),
                br.ReadSingle()
            )
        };
    }
}

internal sealed class KairModel
{
    public KairBone[] Bones;
    public Matrix4x4[] BindPoses;
    public Dictionary<string, KairClip> Clips;
    public KairMesh[] Meshes;
    public Bounds Bounds;
}

internal sealed class KairBone
{
    public string Name;
    public int ParentIndex;
    public KairPose RestPose;
}

internal struct KairPose
{
    public Vector3 Position;
    public Quaternion Rotation;
    public Vector3 Scale;
}

internal sealed class KairClip
{
    public string Name;
    public KairPose[][] Frames;
}

internal sealed class KairMesh
{
    public string Name;
    public Vector3[] Positions;
    public Vector3[] Normals;
    public Vector2[] Uvs;
    public BoneWeight[] Weights;
}
