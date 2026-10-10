@echo off
title ZeusLab - Collect Sixfold essentials (small upload)
echo Collecting Sixfold code/config + game API (skipping the 1 GB of model blobs)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0COLLECT_SIXFOLD_ESSENTIALS.ps1" %*
echo.
if errorlevel 1 (
    echo FAILED - see the message above.
    echo If a folder was not found, run from a command prompt like:
    echo   COLLECT_SIXFOLD_ESSENTIALS.cmd -Sixfold "D:\Steam\steamapps\workshop\content\1278540\3798453402"
) else (
    explorer "%USERPROFILE%\Desktop\ZeusLab_Upload"
)
pause
