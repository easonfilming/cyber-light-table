"""胶卷暗盒的绘制。被 strip.py 调用，画在生成图的左上角。

按真 135 暗盒来画：
  · 黑色塑料筒身 —— 横向渐变做出圆柱光影
  · 顶上的卷轴头 —— 从筒身顶面露出一截小圆柱
  · 整圈包住的标签 —— 上下是直边，不是贴上去的小方块
  · 出片口 —— 侧面凸出的小舌，中间一道黑缝
  · 片头 —— 从缝里拉出来，照片就从这儿开始
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

import theme

# 预设暗盒：name 下拉框里显示的名字 / body 塑料壳色（都是深色）/ band 标签色 / ink 标签上的字
CANISTERS = {
    "kodak": {
        "name": "柯达黄 KODAK 400",
        "label": "KODAK 400", "sub": "135 · 36 EXP",
        "body": (40, 37, 34),
        "band": (240, 196, 32), "ink": (26, 22, 18),
    },
    "fuji": {
        "name": "富士绿 FUJI 400",
        "label": "FUJI 400", "sub": "135 · 36 EXP",
        "body": (34, 39, 37),
        "band": (24, 122, 74), "ink": (246, 246, 241),
    },
    "ilford": {
        "name": "伊尔福黑白 ILFORD HP5",
        "label": "ILFORD HP5", "sub": "135 · 36 EXP",
        "body": (30, 30, 30),
        "band": (238, 238, 232), "ink": (22, 22, 22),
    },
}

DEFAULT = "kodak"
NAMES = ["kodak", "fuji", "ilford"]

# 新建暗盒时的初始值（设计器用）
NEW_TEMPLATE = {"name": "我的暗盒", "label": "MY FILM 400", "sub": "135 · 36 EXP",
                "band": "#2a5fa8", "body": "#282523", "ink": ""}

PREVIEW_BG = (238, 235, 229)   # 设计器预览的底（浅色，深色暗盒才看得清）
REF_W, REF_H, REF_LEADER = 230, 330, 118   # 预览按真暗盒尺寸等比缩放

CAP_RATIO = 0.20      # 上下椭圆的高度 ÷ 宽度
HIGHLIGHT = 0.34      # 高光位置（0=最左，1=最右）
NUB_H = 0.16          # 顶上卷轴头的高度 ÷ 暗盒总高
NUB_W = 0.40          # 卷轴头的宽度 ÷ 暗盒总宽
LIP_OUT = 0.075       # 出片口小舌探出柱身多少 ÷ 总宽


def _contrast(c) -> tuple[int, int, int]:
    """在给定底色上取一个能看清的文字色。"""
    lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    return (250, 246, 238) if lum < 140 else (26, 22, 18)


def from_dict(d: dict) -> dict:
    """把存起来的暗盒（颜色是 "#rrggbb"）转成绘制参数。

    也用来兼容老项目里的 canister_custom —— 那会儿 body 存的就是颜色，形状一样。
    """
    d = d or {}
    band = theme.hex_to_rgb(d.get("band") or d.get("body") or "#2a5fa8")
    body_hex = d.get("body") if d.get("band") else None
    body = theme.hex_to_rgb(body_hex) if body_hex else (36, 35, 33)
    ink_raw = str(d.get("ink") or "").strip()
    return {
        "label": str(d.get("label") or "MY FILM 400")[:26],
        "sub": str(d.get("sub") or "135 · 36 EXP")[:26],
        "body": body,
        "band": band,
        "ink": theme.hex_to_rgb(ink_raw) if ink_raw else _contrast(band),
    }


def resolve(name: str, custom: dict | None = None, library: dict | None = None) -> dict:
    """把暗盒 id 解析成一份完整的绘制参数。

    name 可以是：
      内置   "kodak" / "fuji" / "ilford"
      库里的 "u:xxxxxxxx"  → 从 library 取
      老项目的 "custom" + custom（内联的颜色）→ 兼容旧数据
    认不出的一律回退到默认内置 —— 暗盒被删掉后项目还得能打开、能渲染。
    """
    name = str(name or "")
    if name in CANISTERS:
        return dict(CANISTERS[name])
    if name == "custom":
        return from_dict(custom or {})
    entry = (library or {}).get(name)
    if entry:
        return from_dict(entry)
    return dict(CANISTERS[DEFAULT])


def choices(library: dict | None = None) -> list[tuple[str, str]]:
    """下拉框用的 (显示名, id)：内置三个 + 库里保存的。"""
    out = [(s["name"], k) for k, s in CANISTERS.items()]
    for cid, c in (library or {}).items():
        out.append((str(c.get("name") or "未命名暗盒"), cid))
    return out


def name_of(cid: str, library: dict | None = None) -> str:
    """某个 id 对应的显示名。找不到就返回默认内置的名字。"""
    if cid in CANISTERS:
        return CANISTERS[cid]["name"]
    entry = (library or {}).get(cid)
    if entry:
        return str(entry.get("name") or "未命名暗盒")
    return CANISTERS[DEFAULT]["name"]


def render_preview(spec: dict, size=(640, 620)) -> Image.Image:
    """设计器用的大预览：一只暗盒 + 一小截片头，画在浅色底上。"""
    W, H = size
    img = Image.new("RGB", (W, H), PREVIEW_BG)
    scale = (H * 0.80) / REF_H
    cw, ch = int(REF_W * scale), int(REF_H * scale)
    cx = int(W * 0.06)
    cy = int((H - ch) / 2)

    exit_x, exit_y = draw_canister(img, cx, cy, cw, ch, spec)
    length = max(24, W - exit_x - int(W * 0.06))
    draw_leader(ImageDraw.Draw(img), exit_x, exit_y, length,
                int(REF_LEADER * scale), (28, 24, 21), (9, 8, 7))
    return img


def _cyl_gradient(w: int, h: int, color, highlight: float = HIGHLIGHT,
                  span: int | None = None, offset: int = 0) -> Image.Image:
    """横向渐变，模拟圆柱侧面：左暗 → 偏左一道高光 → 右暗。

    span / offset 让贴在柱面上的标签跟筒身**共用同一套光影**，
    否则各算各的高光位置，看着就像贴了块会发光的板子。
    """
    total = max(2, span if span else w)
    line = Image.new("RGB", (max(1, w), 1))
    px = line.load()
    for i in range(w):
        t = (offset + i) / (total - 1)
        k = (t / highlight) if t < highlight else ((1.0 - t) / (1.0 - highlight))
        f = 0.40 + 0.82 * math.sin(math.pi * 0.5 * max(0.0, min(1.0, k)))
        px[i, 0] = theme.shade(color, f)
    return line.resize((max(1, w), max(1, h)), Image.Resampling.NEAREST)


def _ellipse_mask(w: int, h: int) -> Image.Image:
    m = Image.new("L", (max(1, w), max(1, h)), 0)
    ImageDraw.Draw(m).ellipse([0, 0, w - 1, h - 1], fill=255)
    return m


def _cyl_mask(w: int, h: int, cap: int) -> Image.Image:
    """圆柱的轮廓遮罩：中间一个矩形 + 上下各一个椭圆。"""
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rectangle([0, cap // 2, w - 1, h - 1 - cap // 2], fill=255)
    d.ellipse([0, 0, w - 1, cap - 1], fill=255)
    d.ellipse([0, h - cap, w - 1, h - 1], fill=255)
    return m


def draw_canister(canvas: Image.Image, x: int, y: int, w: int, h: int, spec) -> tuple[float, float]:
    """画一只立起来的 135 暗盒。返回出片缝的位置（片头从这里往外画）。"""
    body = spec["body"]
    nub_h = max(10, int(h * NUB_H))
    nub_w = max(14, int(w * NUB_W))
    lip_out = max(9, int(w * LIP_OUT))
    bw = w - lip_out                          # 柱身宽度
    cap = max(6, int(bw * CAP_RATIO))
    rim = theme.shade(body, 2.1)
    dark = theme.shade(body, 0.55)
    by = y + nub_h                            # 柱身顶部
    bh = h - nub_h                            # 柱身高度
    lip_y0, lip_y1 = by + int(cap * 1.05), y + h - int(cap * 1.05)

    # ---------- 顶上的卷轴头（先画，等下被柱身顶面盖住底边）----------
    nx = int(x + (w - nub_w) / 2)
    ncap = max(4, int(nub_w * CAP_RATIO))
    canvas.paste(_cyl_gradient(nub_w, nub_h + ncap, theme.shade(body, 0.92)),
                 (nx, y), _cyl_mask(nub_w, nub_h + ncap, ncap))
    canvas.paste(_cyl_gradient(nub_w, ncap, theme.shade(body, 1.55)),
                 (nx, y), _ellipse_mask(nub_w, ncap))
    nd = ImageDraw.Draw(canvas)
    nd.ellipse([nx, y, nx + nub_w - 1, y + ncap - 1], outline=rim, width=2)

    # ---------- 柱身轮廓：柱身 + 出片口小舌，一体成型 ----------
    # 掩码跟渐变一样宽（w），柱身只占左边 bw
    mask = Image.new("L", (w, bh), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([0, cap // 2, bw - 1, bh - 1 - cap // 2], fill=255)
    md.ellipse([0, 0, bw - 1, cap - 1], fill=255)
    md.ellipse([0, bh - cap, bw - 1, bh - 1], fill=255)
    md.rounded_rectangle([bw - lip_out, lip_y0 - by, w - 1, lip_y1 - by],
                         radius=lip_out // 2, fill=255)
    canvas.paste(_cyl_gradient(w, bh, body), (x, by), mask)

    d = ImageDraw.Draw(canvas)

    # 顶面（黑的，微微受光）
    canvas.paste(_cyl_gradient(bw, cap, theme.shade(body, 1.32)), (x, by),
                 _ellipse_mask(bw, cap))
    d.ellipse([x, by, x + bw - 1, by + cap - 1], outline=rim, width=2)

    # ---------- 整圈包住的标签 ----------
    # 上下是直边（贴纸才不会看着像贴上去的小方块），光影跟筒身一致
    ly0, ly1 = by + int(cap * 1.45), y + h - int(cap * 1.45)
    lw = int(bw * 0.88)
    canvas.paste(_cyl_gradient(lw, ly1 - ly0, spec["band"], span=bw, offset=0),
                 (x, ly0))

    # 标签右边留一条窄带（真胶卷上印厂名/型号的地方），颜色跟标签反着来才看得见
    band_lum = 0.299 * spec["band"][0] + 0.587 * spec["band"][1] + 0.114 * spec["band"][2]
    side_rgb = (222, 218, 210) if band_lum < 150 else (128, 124, 118)
    side_x = x + lw
    side_w = max(6, int(bw * 0.07))
    canvas.paste(_cyl_gradient(side_w, ly1 - ly0, side_rgb, span=bw, offset=lw),
                 (side_x, ly0))

    lh = ly1 - ly0
    d.text((x + lw / 2, ly0 + lh * 0.34), spec["label"],
           font=theme.pil_font(max(12, int(lh * 0.19)), "mono"),
           fill=spec["ink"], anchor="mm")
    d.text((x + lw / 2, ly0 + lh * 0.72), spec["sub"],
           font=theme.pil_font(max(9, int(lh * 0.115)), "mono"),
           fill=theme.shade(spec["ink"], 0.78), anchor="mm")

    # 窄带上的竖排小字
    for i, ch in enumerate("135"):
        d.text((side_x + side_w / 2, ly0 + lh * (0.28 + i * 0.16)), ch,
               font=theme.pil_font(max(8, int(lh * 0.10)), "mono"),
               fill=_contrast(side_rgb), anchor="mm")

    # ---------- 底部椭圆边（做出厚度和落地感）----------
    d.arc([x, y + h - cap, x + bw - 1, y + h - 1], 0, 180, fill=dark, width=3)

    # ---------- 小舌只描右半边轮廓（左半边跟柱身连着的）----------
    ex = x + w - 1
    d.line([ex, lip_y0 + lip_out // 2, ex, lip_y1 - lip_out // 2], fill=rim, width=2)
    d.arc([ex - lip_out, lip_y0, ex, lip_y0 + lip_out], 270, 360, fill=rim, width=2)
    d.arc([ex - lip_out, lip_y1 - lip_out, ex, lip_y1], 0, 90, fill=rim, width=2)

    # 出片缝
    slot_x = x + w - lip_out * 0.85
    d.rectangle([slot_x, lip_y0 + 8, slot_x + 6, lip_y1 - 8], fill=(12, 11, 10))

    # 片头就从出片缝里出来
    return slot_x + 6, (lip_y0 + lip_y1) / 2


def draw_leader(draw, x, y, length, height, base, perf, drop: float = 0.0):
    """从暗盒出片缝往外伸的片头。(x, y) 是左端中点。

    drop > 0 时右端向下斜 drop 像素 —— 胶片摊在桌上自然往下走，
    视觉上把暗盒和下面那一叠胶片连起来。
    """
    h2 = height / 2
    x2, y2 = x + length, y + drop
    draw.polygon([(x, y - h2), (x2, y2 - h2), (x2, y2 + h2), (x, y + h2)],
                 fill=base, outline=(52, 46, 40))

    # 上下两排圆角矩形齿孔，尺寸按片头宽度等比算
    hole_w = height * 0.26
    hole_h = height * 0.20
    step = height * 0.46
    edge = height * 0.09
    pad = step * 0.7
    n = max(1, int((length - pad * 2) // step))
    for i in range(n):
        t = (i + 0.5) / n
        px = x + pad + t * (length - pad * 2)
        py = y + t * drop
        for dy in (-h2 + edge, h2 - edge - hole_h):
            draw.rounded_rectangle([px, py + dy, px + hole_w, py + dy + hole_h],
                                   radius=hole_h * 0.34, fill=perf)
