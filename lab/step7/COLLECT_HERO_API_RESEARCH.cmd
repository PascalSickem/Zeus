@echo off
setlocal EnableExtensions
title ZeusLab - Collect Custom Hero API Research

set "GAME=C:\SteamLibrary\steamapps\common\Esports Godfather\Esport Godfather_Data\Managed"
set "SIX=C:\SteamLibrary\steamapps\workshop\content\1278540\3798453402"
set "ROOT=%USERPROFILE%\AppData\LocalLow\Asteroid Studio\Esport Godfather"
set "OUT=%USERPROFILE%\Desktop\ZeusLab_HeroAPI_Research"

if exist "%OUT%" rmdir /S /Q "%OUT%"
mkdir "%OUT%"

echo Copying Esports Godfather managed API assemblies...
for %%F in (
  "Assembly-CSharp.dll"
  "Utility.GameSystem.dll"
  "Utility.dll"
) do (
  if exist "%GAME%\%%~F" copy /Y "%GAME%\%%~F" "%OUT%\" >nul
)

echo Copying mod metadata...
if exist "%SIX%\mod.json" copy /Y "%SIX%\mod.json" "%OUT%\Sixfold.mod.json" >nul
if exist "%ROOT%\ModWorkspaces\ZeusLab\mod.json" copy /Y "%ROOT%\ModWorkspaces\ZeusLab\mod.json" "%OUT%\ZeusLab.mod.json" >nul

echo Recording Sixfold DLL inventory...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem '%SIX%\Dll' -File -Filter *.dll | Sort-Object Name | Select-Object Name,Length | Format-Table -AutoSize | Out-String -Width 240 | Set-Content '%OUT%\Sixfold_Dll_List.txt'"

echo Copying a few hero-registration reference DLLs...
for %%F in (
  "Janna.dll"
  "Kaisa.dll"
  "TacticalArmory.dll"
  "FrostArmory.QiyanaAssets.dll"
  "FrostArmory.PedestalPresentation.dll"
) do (
  if exist "%SIX%\Dll\%%~F" copy /Y "%SIX%\Dll\%%~F" "%OUT%\" >nul
)

echo Creating ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%OUT%\*' -DestinationPath '%USERPROFILE%\Desktop\ZeusLab_HeroAPI_Research.zip' -Force"

echo.
echo DONE.
echo Upload this file to ChatGPT:
echo %USERPROFILE%\Desktop\ZeusLab_HeroAPI_Research.zip
echo.
pause
