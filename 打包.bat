@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    set "PY=py"
)

echo.
echo   正在打包「赛博观片台」...
echo   （第一次要建虚拟环境、下载 PyInstaller，会慢一点）
echo.

%PY% build_exe.py %*

echo.
pause
