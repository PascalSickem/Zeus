@echo off
setlocal EnableExtensions
title ZeusLab STEP 7 - REAL CUSTOM MODEL LAB

set "ROOT=%USERPROFILE%\AppData\LocalLow\Asteroid Studio\Esport Godfather"
set "WORK=%ROOT%\ModWorkspaces\ZeusLab\Src"
set "LIVE=%ROOT%\Mods\Content\Dll\Src"

echo ============================================
echo ZEUS LAB STEP 7 - REAL CUSTOM MODEL LAB
echo ============================================
echo.

if not exist "%~dp0Src.csproj" (
    echo ERROR: Extract the entire ZIP before running this installer.
    pause
    exit /b 1
)

if not exist "%WORK%" mkdir "%WORK%"
if not exist "%LIVE%" mkdir "%LIVE%"

echo [1/5] Installing Step 7 source...
copy /Y "%~dp0Src.csproj" "%WORK%\Src.csproj" >nul
copy /Y "%~dp0MyModScript.cs" "%WORK%\MyModScript.cs" >nul
copy /Y "%~dp0IMPORT_REAL_MODELS.ps1" "%WORK%\IMPORT_REAL_MODELS.ps1" >nul

echo.
echo [2/5] Importing LOCAL copies of real Sixfold models/textures...
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORK%\IMPORT_REAL_MODELS.ps1"
if errorlevel 1 (
    echo.
    echo MODEL IMPORT FAILED.
    pause
    exit /b 1
)

if exist "%~dp0ZeusPrototype.model-rigged.bin.gz" (
    if not exist "%WORK%\ImportedModels\Zeus" mkdir "%WORK%\ImportedModels\Zeus"
    copy /Y "%~dp0ZeusPrototype.model-rigged.bin.gz" "%WORK%\ImportedModels\Zeus\model.bin.gz" >nul
)

echo.
echo [3/5] Building ZeusLab...
pushd "%WORK%"
dotnet build "%WORK%\Src.csproj" -c Debug
if errorlevel 1 (
    popd
    echo.
    echo BUILD FAILED. Do not launch the game.
    pause
    exit /b 1
)
popd

set "DLL=%WORK%\bin\Debug\netstandard2.1\Src.dll"

if not exist "%DLL%" (
    echo ERROR: Built DLL not found:
    echo %DLL%
    pause
    exit /b 1
)

echo.
echo [4/5] Deploying DLL...
copy /Y "%DLL%" "%LIVE%\Src.dll" >nul
if errorlevel 1 (
    echo COPY FAILED. Close Esports Godfather and retry.
    pause
    exit /b 1
)

echo.
echo [5/5] Deploying ImportedModels...
if exist "%LIVE%\ImportedModels" rmdir /S /Q "%LIVE%\ImportedModels"
xcopy "%WORK%\ImportedModels" "%LIVE%\ImportedModels\" /E /I /Y >nul
if errorlevel 1 (
    echo MODEL DEPLOY FAILED.
    pause
    exit /b 1
)

echo.
echo ============================================
echo STEP 7 INSTALLED SUCCESSFULLY
echo ============================================
echo.
echo Launch Esports Godfather and enter your save.
echo Look at the TOP-RIGHT for:
echo   ZEUS LAB - REAL CUSTOM CHARACTER LAB
echo.
echo Buttons:
echo   Zeus Prototype / Janna / Kai'Sa / Qiyana / Evelynn / Zed
echo.
echo Step 7 also performs a SAFE read-only roster probe.
echo Send Player.log after testing so Step 7 can filter the
echo live draft pool to CUSTOM CHARACTERS ONLY.
echo.
pause
