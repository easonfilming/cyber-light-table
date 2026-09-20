@echo off
rem Launch Cyber Light Table without a console window.
rem Needs Python 3 with tkinter and Pillow (both are in the standard setup).
set "PYW=pythonw"
where pythonw >nul 2>nul
if errorlevel 1 set "PYW=python"
start "" "%PYW%" "%~dp0main.py"
