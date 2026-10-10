$ErrorActionPreference = "Stop"

$shared = "C:\SteamLibrary\steamapps\workshop\content\1278540\3798453402\Dll\SharedAssets"
$root   = "$env:USERPROFILE\AppData\LocalLow\Asteroid Studio\Esport Godfather\ModWorkspaces\ZeusLab\Src\ImportedModels"

if (!(Test-Path $shared)) {
    throw "Sixfold/Hero Battleground SharedAssets was not found: $shared"
}

New-Item -ItemType Directory -Force $root | Out-Null

function Copy-HashFile {
    param(
        [string]$Folder,
        [string]$Hash,
        [string]$OutputName
    )

    $src = Join-Path $shared $Hash
    $dstFolder = Join-Path $root $Folder
    $dst = Join-Path $dstFolder $OutputName

    New-Item -ItemType Directory -Force $dstFolder | Out-Null

    if (!(Test-Path $src)) {
        Write-Host "[MISSING] $Folder / $OutputName" -ForegroundColor Yellow
        return $false
    }

    Copy-Item -Force $src $dst
    Write-Host "[OK] $Folder / $OutputName"
    return $true
}

# ----- Janna -----
Copy-HashFile "Janna" "d6bc196ffc6c3f5f47be6dd7e3d3da43119787a49a6d8f35068d30dcee18ab05" "model.bin.gz" | Out-Null
Copy-HashFile "Janna" "4ef687f5adca7c8d5506b5ddca6d033418b14e8d0a2ab7fce848fdca4dce9efd" "atlasA.png" | Out-Null
Copy-HashFile "Janna" "c0c8abd19feecbda5efdb3a23d6fccdef0205ae45f15c699f43737f1ad729b33" "atlasB.png" | Out-Null
Copy-HashFile "Janna" "c61c1a34023e2daa2f3ebe4b82778964b3b0b317f75659bf62d994d3152f0ceb" "atlasC.png" | Out-Null

@"
Wing=atlasB.png
Body=atlasA.png
Cloths=atlasA.png
Hair=atlasA.png
Ear=atlasA.png
Front_Hair=atlasA.png
WingsHair=atlasA.png
Metal=atlasB.png
Cloak01=atlasB.png
Metal02=atlasB.png
Cloak02=atlasB.png
EyeMask=atlasA.png
Eyes=atlasB.png
Gem=atlasA.png
Glass=atlasA.png
Pupil02=atlasB.png
Pupil=atlasB.png
R_Wing=atlasC.png
R_Ear=atlasC.png
R_Eye_Mask=atlasC.png
R_WingsHair=atlasA.png
Skirt=atlasB.png
Metal03=atlasB.png
Weapon=atlasB.png
"@ | Set-Content -Encoding UTF8 (Join-Path $root "Janna\materials.txt")

# ----- Kai'Sa -----
Copy-HashFile "Kaisa" "e93ce22d455163ff9c273548f4897c51c8920c37ff5152b58c91de44f44c6aad" "model.bin.gz" | Out-Null
Copy-HashFile "Kaisa" "ad156e6c59dcbed2c6b2c8b8f5fb24d90dd5da109bde94680ab2201fd73fa2bb" "atlasA.png" | Out-Null
Copy-HashFile "Kaisa" "8f5c75dd97964b58f923c4c5ded8ff65ce5ffe93fb8c71347211f31e1f9af040" "ropes1.png" | Out-Null
Copy-HashFile "Kaisa" "d3835e588ce56bfca99fdfdfd723d2ff64b937bec815daacf32a6b6828dfdaa2" "ropes2.png" | Out-Null

@"
Body=atlasA.png
Crystal=atlasA.png
Dog_Heads=atlasA.png
Form3_Changes=atlasA.png
Left_Cannon=atlasA.png
Pistols_Form3=atlasA.png
Right_Cannon=atlasA.png
Ropes1=ropes1.png
Ropes2=ropes2.png
TeethEyes=atlasA.png
"@ | Set-Content -Encoding UTF8 (Join-Path $root "Kaisa\materials.txt")

# ----- Qiyana -----
Copy-HashFile "Qiyana" "3e95425cc8f97bef78701fe0afa9af157d6d2c307438e565f2219dee34f14e6b" "model.bin.gz" | Out-Null
Copy-HashFile "Qiyana" "67852bb95d7ea5b218f8da7b92156e9384384e47222ee03daeac149365204864" "body.png" | Out-Null
Copy-HashFile "Qiyana" "21a6070084aa1aae02a7018c65432187e3917eb9b78ce78ccc17ef2210ac8055" "weapon.png" | Out-Null

# ----- Evelynn -----
Copy-HashFile "Evelynn" "ae81fd865cc2212bfd1b1f78dffc61485b16be66c6f2fb7fe9306943e382ab99" "model.bin.gz" | Out-Null
Copy-HashFile "Evelynn" "0f1ad752c19734d29b94cc151ca70fa0346121ebd39a4945ea8e5f4e7144a1c8" "default.png" | Out-Null

# ----- Zed -----
Copy-HashFile "Zed" "975625a7a3e0387cbed3a22034dae12cec9534e3cc0b959e74fcbc5f6bc0a7b2" "model.bin.gz" | Out-Null
Copy-HashFile "Zed" "01d9b1d60b5e2a3f642e2d572cacd6a646185bb4ba4b7eb0f492fbbf08850de3" "default.png" | Out-Null

Write-Host ""
Write-Host "Imported real model test assets into:" -ForegroundColor Cyan
Write-Host $root
Write-Host ""
Write-Host "Original Workshop files were NOT modified." -ForegroundColor Green
