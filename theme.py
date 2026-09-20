"""米色主题：全程序统一的配色、字体和控件外观。

界面控件用 tkinter 的 "#rrggbb" 字符串，
图片合成（观片台、暗盒）用 (r, g, b) 元组。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import ImageFont

# ================= 界面配色（tkinter 用） =================
BG        = "#f4eee3"   # 页面底：暖米
PANEL     = "#eae2d3"   # 面板
FIELD     = "#fbf8f1"   # 输入框 / 卡片底
BORDER    = "#d8ccb6"   # 描边
SHADOW    = "#ddd3c0"   # 卡片投影

TEXT      = "#3b332a"   # 主文字（深褐）
DIM       = "#8b8072"   # 次要文字
FAINT     = "#a89d8c"   # 更淡的提示文字

ACCENT    = "#b07d3a"   # 强调色（黄铜）
ACCENT_DK = "#8c6229"
ACCENT_FG = "#fdf9f0"   # 强调色上的文字
SEL       = "#e6d9c0"   # 选中底

DANGER    = "#a8503c"   # 删除等危险操作

# ================= 观片台（PIL 用，RGB 元组） =================
TABLE_OFF      = (20, 18, 15)      # 关灯时的灯箱
TABLE_OFF_EDGE = (11, 10, 8)       # 关灯渐晕
TABLE_ON       = (255, 255, 255)   # 开灯：纯白匀光板
TABLE_ON_EDGE  = (233, 233, 231)   # 开灯渐晕（很淡，别抢胶片）
SILHOUETTE     = 0.08              # 关灯时胶卷图的亮度（只留剪影）
LOUPE_DIM      = 0.10              # 观片器外往黑里混多少 —— 白底上太深会显得发脏

# ================= 观片器镜圈 =================
RIM_OUT = (104, 80, 42)            # 镜圈外沿
RIM_MID = (168, 132, 74)           # 镜圈中间
RIM_IN  = (222, 186, 118)          # 镜圈内沿（黄铜亮边）

# ================= 字体 =================
FONT_UI    = ("Microsoft YaHei UI", 10)
FONT_SM    = ("Microsoft YaHei UI", 8)
FONT_MONO  = ("Consolas", 9)
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")
FONT_H1    = ("Microsoft YaHei UI", 20, "bold")

_FONT_DIRS = [Path(r"C:\Windows\Fonts"),
              Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
              Path("/usr/share/fonts"),
              Path("/System/Library/Fonts")]
_PIL_FONTS: dict = {}


def pil_font(size: int, kind: str = "ui"):
    """给 PIL 用的字体，带多级回退（要能显示中文）。"""
    key = (size, kind)
    if key in _PIL_FONTS:
        return _PIL_FONTS[key]
    names = {
        "ui":   ["msyh.ttc", "simhei.ttf", "simsun.ttc", "arial.ttf", "DejaVuSans.ttf"],
        "bold": ["msyhbd.ttc", "simhei.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
        "mono": ["consola.ttf", "cour.ttf", "lucon.ttf", "DejaVuSansMono.ttf"],
    }[kind]
    font = None
    for d in _FONT_DIRS:
        if not d.is_dir():
            continue
        for n in names:
            p = d / n
            if p.is_file():
                try:
                    font = ImageFont.truetype(str(p), size)
                    break
                except Exception:
                    continue
        if font is not None:
            break
    if font is None:
        try:
            font = ImageFont.load_default(size)      # Pillow >= 10.1
        except Exception:
            font = ImageFont.load_default()
    _PIL_FONTS[key] = font
    return font


def hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = str(s).lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))   # type: ignore[return-value]
    except Exception:
        return (128, 128, 128)


def rgb_to_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def shade(c, factor: float):
    """把颜色调亮(factor>1)或调暗(factor<1)，自动夹到 0~255。"""
    return tuple(max(0, min(255, int(v * factor))) for v in c[:3])


# ================= 控件外观 =================
def button(parent, text, command, kind: str = "normal", size: str = "md", **kw):
    """统一样式的扁平按钮。kind: normal / accent / ghost / danger"""
    pad_x, pad_y = (14, 6) if size == "md" else (9, 3)
    font = FONT_UI if size == "md" else FONT_SM
    styles = {
        "normal": dict(bg=FIELD,     fg=TEXT,      activebackground=SEL,        activeforeground=TEXT),
        "accent": dict(bg=ACCENT,    fg=ACCENT_FG, activebackground=ACCENT_DK,  activeforeground=ACCENT_FG),
        "ghost":  dict(bg=PANEL,     fg=TEXT,      activebackground=SEL,        activeforeground=TEXT),
        "danger": dict(bg=FIELD,     fg=DANGER,    activebackground="#f0dcd6",  activeforeground=DANGER),
    }[kind]
    b = tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                  padx=pad_x, pady=pad_y, cursor="hand2", font=font,
                  disabledforeground=FAINT, highlightthickness=0, **styles, **kw)
    return b


def option_menu(parent, var, values, command, width: int = 10):
    """统一样式的下拉框。"""
    om = tk.OptionMenu(parent, var, *values, command=command)
    om.configure(bg=FIELD, fg=TEXT, bd=0, relief="flat", highlightthickness=0,
                 activebackground=SEL, activeforeground=TEXT,
                 font=FONT_SM, width=width, anchor="w")
    om["menu"].configure(bg=FIELD, fg=TEXT, font=FONT_SM,
                         activebackground=ACCENT, activeforeground=ACCENT_FG,
                         bd=0, relief="flat")
    return om


def label(parent, text, fg=None, font=None, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or BG, fg=fg or TEXT,
                    font=font or FONT_UI, **kw)


def rule(parent, color=None, thickness: int = 1):
    """一条细分割线。"""
    f = tk.Frame(parent, bg=color or BORDER, height=thickness)
    return f
