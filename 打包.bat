@echo off
rem Build Cyber Light Table into a single-file exe.
rem First run creates a temp virtualenv and downloads PyInstaller, so it is slower.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    set "PY=py"
) else (
    set "PY=python"
)

echo.
echo   Building Cyber Light Table ...
echo.
%PY% build_exe.py %*
echo.
pause
