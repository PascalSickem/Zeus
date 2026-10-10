# ZeusLab - collect the SMALL, useful parts of Sixfold + the game API for upload.
#
# Sixfold is ~1 GB, almost all of it model/texture blobs in Dll\SharedAssets.
# Those are NOT needed (the KAIR model format is already understood). What is
# needed is the code + config that registers custom heroes, cards and combat
# animations. Output: Desktop\ZeusLab_Upload\ZeusLab_Research_partN.zip,
# every part under the 30 MB upload limit.

param(
    [string]$Sixfold = "",
    [string]$Game = "",
    [int]$PartLimitMB = 28,
    [int]$MaxFileMB = 12
)

$ErrorActionPreference = "Stop"
$SEP = [IO.Path]::DirectorySeparatorChar
function NativePath([string]$p) { return ($p -replace '[\\/]', $SEP) }
function RelOf([string]$full, [string]$base) {
    # relative path with "\" separators, for matching and naming
    return ($full.Substring($base.Length).TrimStart('\', '/') -replace '/', '\')
}

function Find-First([string[]]$candidates) {
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }
    return $null
}

# --- locate Steam libraries (default install + every library in libraryfolders.vdf)
$libs = @("C:\SteamLibrary", "C:\Program Files (x86)\Steam", "D:\SteamLibrary", "E:\SteamLibrary")
$vdf = "C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf"
if (Test-Path $vdf) {
    Select-String -Path $vdf -Pattern '"path"\s+"([^"]+)"' | ForEach-Object {
        $libs += ($_.Matches[0].Groups[1].Value -replace '\\\\', '\')
    }
}
$libs = $libs | Select-Object -Unique

if (-not $Sixfold) {
    $Sixfold = Find-First ($libs | ForEach-Object { Join-Path $_ "steamapps\workshop\content\1278540\3798453402" })
}
if (-not $Game) {
    $Game = Find-First ($libs | ForEach-Object { Join-Path $_ "steamapps\common\Esports Godfather" })
}
if (-not $Sixfold) { throw "Sixfold folder not found. Run again with -Sixfold ""<path to 3798453402>""" }
if (-not $Game)    { throw "Game folder not found. Run again with -Game ""<path to Esports Godfather>""" }
Write-Host "Sixfold: $Sixfold"
Write-Host "Game:    $Game"

$out     = Join-Path $env:USERPROFILE (NativePath "Desktop\ZeusLab_Upload")
$tmp = if ($env:TEMP) { $env:TEMP } else { [IO.Path]::GetTempPath() }
$staging = Join-Path $tmp "ZeusLab_Research_staging"
if (Test-Path $out)     { Remove-Item $out -Recurse -Force }
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force $out, $staging | Out-Null

$picked = New-Object System.Collections.ArrayList   # [dest-relative, source]
function Pick([string]$src, [string]$rel) { [void]$picked.Add(@($rel, $src)) }

# --- 1. Sixfold: code + config, never the SharedAssets blobs
$textExt = @(".dll", ".json", ".txt", ".xml", ".cfg", ".ini", ".md", ".csv", ".yaml", ".yml", ".lua", ".cs", ".pdb", ".i18n", ".mod_info", ".override_info")
$inventory = New-Object System.Collections.ArrayList
Get-ChildItem $Sixfold -Recurse -File | ForEach-Object {
    $rel = RelOf $_.FullName $Sixfold
    [void]$inventory.Add(("{0,12}  {1}" -f $_.Length, $rel))
    $inShared = $rel -like "Dll\SharedAssets\*"
    $small = $_.Length -le ($MaxFileMB * 1MB)
    $ext = $_.Extension.ToLowerInvariant()
    if (-not $inShared -and $small -and ($textExt -contains $ext -or $_.Length -le 256KB)) {
        Pick $_.FullName ("Sixfold\" + $rel)
    }
}
$inventory | Set-Content -Encoding UTF8 (Join-Path $staging "Sixfold_inventory.txt")

# --- 2. Game API assemblies (what mods compile against)
$managed = Join-Path $Game (NativePath "Esport Godfather_Data\Managed")
foreach ($n in @("Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll", "Utility.dll", "Utility.GameSystem.dll")) {
    $p = Join-Path $managed $n
    if (Test-Path $p) { Pick $p ("Game\Managed\" + $n) }
}
Get-ChildItem $managed -File | Sort-Object Name | ForEach-Object { "{0,12}  {1}" -f $_.Length, $_.Name } |
    Set-Content -Encoding UTF8 (Join-Path $staging "Game_Managed_list.txt")
Get-ChildItem $Game -Recurse -File -Include *.json, *.md, *.txt -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -le 2MB -and $_.FullName -notlike "*\Managed\*" } |
    ForEach-Object { Pick $_.FullName ("Game\" + (RelOf $_.FullName $Game)) }

# --- 3. ZeusLab side: mod.json + the latest Player.log
$root = Join-Path $env:USERPROFILE (NativePath "AppData\LocalLow\Asteroid Studio\Esport Godfather")
foreach ($p in @((Join-Path $root (NativePath "ModWorkspaces\ZeusLab\mod.json")), (Join-Path $root "Player.log"), (Join-Path $root "Player-prev.log"))) {
    if (Test-Path $p) { Pick $p ("ZeusLab\" + (Split-Path $p -Leaf)) }
}

# --- copy into staging
foreach ($e in $picked) {
    $dst = Join-Path $staging (NativePath $e[0])
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $e[1] -Destination $dst -Force
}

# --- split into zips that each stay under the limit (files are compressed,
#     so packing by raw size is conservative)
$files = Get-ChildItem $staging -Recurse -File | Sort-Object Length -Descending
$limit = $PartLimitMB * 1MB
$parts = @()
foreach ($f in $files) {
    $placed = $false
    foreach ($p in $parts) {
        if ($p.Size + $f.Length -le $limit) { $p.Files += $f; $p.Size += $f.Length; $placed = $true; break }
    }
    if (-not $placed) { $parts += [pscustomobject]@{ Files = @($f); Size = $f.Length } }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$i = 0
foreach ($p in $parts) {
    $i++
    $zipPath = Join-Path $out ("ZeusLab_Research_part{0}_of_{1}.zip" -f $i, $parts.Count)
    $zip = [System.IO.Compression.ZipFile]::Open($zipPath, "Create")
    try {
        foreach ($f in $p.Files) {
            $entry = (RelOf $f.FullName $staging) -replace '\\', '/'   # zip entries use "/"
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $entry, "Optimal")
        }
    } finally { $zip.Dispose() }
    $mb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host ("[OK] {0}  ({1} MB, {2} files)" -f (Split-Path $zipPath -Leaf), $mb, $p.Files.Count)
    if ($mb -gt 29.5) {
        Write-Host ("  WARNING: over the 30 MB upload limit. Upload the other parts first and tell Claude which file is too big.") -ForegroundColor Yellow
    }
}

Remove-Item $staging -Recurse -Force
Write-Host ""
Write-Host "DONE. Upload every zip in:" -ForegroundColor Green
Write-Host "  $out"
Write-Host "(SharedAssets models/textures were skipped on purpose - only their names and sizes are listed.)"
