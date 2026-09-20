"""把「赛博观片台」打包成单文件 exe。

用法：
    python build_exe.py            正常打包
    python build_exe.py --clean    先清掉上次的中间产物再打
    python build_exe.py --icon     只生成图标（调试用）

产物：
    dist/赛博观片台.exe
    dist/使用说明.txt

打包过程用一个**临时虚拟环境**，不碰你现有的 Python。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).parent
BUILD = ROOT / "_build"                 # 虚拟环境 + 中间产物，可以随时删
DIST = ROOT / "dist"
VENV = BUILD / "venv"
APP_NAME = "赛博观片台"
EXE_BASE = "CyberLightTable"            # PyInstaller 内部用的名字（ASCII，免得踩坑）
VERSION = (1, 0, 0, 0)

# 打包时要一起带上的源文件（程序本身不需要额外数据文件）
SOURCES = ["main.py", "home.py", "designer.py", "gallery.py", "settings_page.py",
           "exporter.py", "photoview.py", "dropfiles.py", "lighttable.py",
           "strip.py", "canister.py", "effects.py", "appconfig.py", "theme.py",
           "project.py"]


# ======================================================================
# 图标
# ======================================================================
def make_icon(path: Path):
    """画一个图标：米色底上一只柯达黄暗盒，片头往右拉出来。"""
    from PIL import Image

    import canister
    import theme

    size = 256
    img = Image.new("RGB", (size, size), theme.hex_to_rgb(theme.BG))

    spec = dict(canister.CANISTERS["kodak"])
    cw, ch = 104, 152
    cx, cy = 46, 52
    exit_x, exit_y = canister.draw_canister(img, cx, cy, cw, ch, spec)

    # 片头拉到右边缘
    from PIL import ImageDraw
    canister.draw_leader(ImageDraw.Draw(img), exit_x, exit_y,
                         size - exit_x - 14, 56, (28, 24, 21), (9, 8, 7))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    return path


# ======================================================================
# 版本信息（让 exe 在「属性」里看着像个正经软件）
# ======================================================================
VERSION_FILE = '''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(v)s, prodvers=%(v)s,
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('FileDescription', '%(name)s'),
        StringStruct('FileVersion', '%(ver)s'),
        StringStruct('InternalName', '%(base)s'),
        StringStruct('OriginalFilename', '%(name)s.exe'),
        StringStruct('ProductName', '%(name)s'),
        StringStruct('ProductVersion', '%(ver)s'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
'''


def write_version_file(path: Path) -> Path:
    ver = ".".join(str(x) for x in VERSION)
    path.write_text(VERSION_FILE % {"v": VERSION, "ver": ver,
                                    "name": APP_NAME, "base": EXE_BASE},
                    encoding="utf-8")
    return path


# ======================================================================
# 打包
# ======================================================================
def venv_python() -> Path:
    return VENV / "Scripts" / "python.exe"


def ensure_venv(quiet=False):
    py = venv_python()
    if not py.exists():
        print("· 建临时虚拟环境（不碰你现有的 Python）…")
        venv.create(VENV, with_pip=True)
    else:
        print("· 复用上次的虚拟环境")
    return py


def pip_install(py: Path):
    print("· 装 PyInstaller（需要联网，第一次会慢一点）…")
    for args in (["install", "-q", "--upgrade", "pip"],
                 ["install", "-q", "pyinstaller", "pillow"]):
        subprocess.run([str(py), "-m", "pip", *args], check=True)


def check_sources():
    missing = [s for s in SOURCES if not (ROOT / s).is_file()]
    if missing:
        raise SystemExit(f"缺文件：{missing}")


def build(py: Path, icon: Path, vfile: Path):
    print("· 开始打包（要一两分钟）…")
    DIST.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(py), "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",                     # 单文件
        "--windowed",                    # 不弹黑框
        f"--name={EXE_BASE}",
        f"--icon={icon}",
        f"--version-file={vfile}",
        "--hidden-import=PIL._tkinter_finder",   # ImageTk 有时候 PyInstaller 抓不到
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        str(ROOT / "main.py"),
    ]
    subprocess.run(cmd, check=True)

    produced = DIST / f"{EXE_BASE}.exe"
    target = DIST / f"{APP_NAME}.exe"
    if produced != target:
        if target.exists():
            target.unlink()
        produced.rename(target)
    return target


def copy_readme():
    src = ROOT / "使用说明.txt"
    if src.is_file():
        shutil.copy(src, DIST / src.name)
        return DIST / src.name
    return None


def main():
    if "--icon" in sys.argv:
        p = make_icon(ROOT / "app.ico")
        print("图标已生成：", p)
        return

    if "--clean" in sys.argv and BUILD.exists():
        print("· 清掉上次的中间产物")
        shutil.rmtree(BUILD, ignore_errors=True)

    check_sources()
    py = ensure_venv()
    pip_install(py)

    icon = make_icon(BUILD / "app.ico")
    vfile = write_version_file(BUILD / "version.txt")
    exe = build(py, icon, vfile)
    readme = copy_readme()

    size_mb = exe.stat().st_size / 1024 / 1024
    print()
    print("打包完成：")
    print(f"  {exe}   （{size_mb:.1f} MB）")
    if readme:
        print(f"  {readme}")
    print()
    print("整个 dist 文件夹可以拷给别人用 —— 对方不需要装 Python。")


if __name__ == "__main__":
    main()
