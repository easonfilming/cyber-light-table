@echo off
rem 双击这个文件即可启动「赛博观片台」（不弹黑框）
rem 优先用本机已知的 Python 路径，找不到就退回 PATH 里的 pythonw
set "PYW=D:\Python\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0main.py"
