"""胶片特效：给生成好的胶卷图加漏光、颗粒、划痕这些"胶片味"。

分两种作用范围：
  · 整条胶片上（漏光、颗粒、划痕）—— 这些是片基和乳剂上的东西
  · 每一格画幅上（褪色、暗角）—— 这些是镜头和冲洗带来的

强度都是 0-100，0 就是关掉。
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw

# (键, 名字, 说明, 默认强度)
EFFECTS = [
    ("leak",     "漏光", "边缘漏进一片暖光，像相机后盖没盖严", 0),
    ("grain",    "颗粒", "胶片的颗粒感，暗部尤其明显", 0),
    ("scratch",  "划痕", "片基上细细的划痕", 0),
    ("faded",    "褪色", "褪色发暖、黑位发灰，像过期胶卷", 0),
    ("vignette", "暗角", "四角压暗，像老镜头的暗角", 0),
]
NAMES = [k for k, *_ in EFFECTS]

# 漏光用的暖色（偏橙红，真漏光就这个色）
LEAK_COLORS = [(255, 138, 48), (255, 96, 40), (255, 186, 92), (250, 120, 60)]

_VIGNETTES: dict = {}


def defaults() -> dict:
    return {k: 0 for k in NAMES}


def normalize(spec) -> dict:
    """把存下来的特效设置清理成 {键: 0-100}。认不出的键丢掉，缺的补 0。"""
    out = defaults()
    if not isinstance(spec, dict):
        return out
    for k in NAMES:
        v = spec.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = max(0, min(100, int(v)))
    return out


def any_on(spec) -> bool:
    spec = normalize(spec)
    return any(v > 0 for v in spec.values())


# ======================================================================
# 逐格画幅上的
# ======================================================================
def _faded(img: Image.Image, amount: int) -> Image.Image:
    """褪色：往暖灰里混，黑位提起来，对比降下去。"""
    if amount <= 0:
        return img
    a = amount / 100.0
    out = Image.blend(img, Image.new("RGB", img.size, (216, 198, 170)), a * 0.55)
    return Image.blend(out, Image.new("RGB", img.size, (132, 126, 118)), a * 0.22)


def _vignette_mask(size, amount: int) -> Image.Image:
    """四角压暗的遮罩，缓存起来（每格尺寸一样，不用算 40 遍）。"""
    key = (size, amount)
    if key in _VIGNETTES:
        return _VIGNETTES[key]
    s = amount / 100.0 * 0.85
    # radial_gradient：中心 0、边缘 255
    grad = Image.radial_gradient("L").point(
        lambda v: int(255 * (1.0 - s * (v / 255.0) ** 1.4)))
    mask = grad.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    _VIGNETTES[key] = mask
    return mask


def _apply_frame(img: Image.Image, spec: dict) -> Image.Image:
    img = _faded(img, spec["faded"])
    if spec["vignette"] > 0:
        img = ImageChops.multiply(img, _vignette_mask(img.size, spec["vignette"]))
    return img


# ======================================================================
# 整条胶片上的
# ======================================================================
def _grain(img: Image.Image, amount: int) -> Image.Image:
    """颗粒：叠一层高斯噪声。effect_noise 的均值就是 128，overlay 上去基本不变调。"""
    if amount <= 0:
        return img
    sigma = 6 + amount * 0.42
    noise = Image.effect_noise(img.size, sigma).convert("RGB")
    out = ImageChops.overlay(img, noise)
    return Image.blend(img, out, min(0.85, 0.18 + amount / 120.0))


def _scratches(img: Image.Image, amount: int, rng: random.Random) -> Image.Image:
    """划痕：沿着胶片方向（横向）的细线，有亮有暗。"""
    if amount <= 0:
        return img
    d = ImageDraw.Draw(img, "RGBA")
    n = 1 + int(amount / 11)
    w, h = img.size
    for _ in range(n):
        y = rng.uniform(h * 0.02, h * 0.98)
        th = rng.choice([1, 1, 1, 2])
        alpha = rng.randint(24, 34 + int(amount * 0.7))
        if rng.random() < 0.72:
            col = (255, 248, 232, alpha)          # 亮划痕（乳剂被刮）
        else:
            col = (18, 15, 12, alpha)             # 暗划痕
        # 划痕不是通到底的，随机起止
        x0 = rng.uniform(0, w * 0.35)
        x1 = rng.uniform(w * 0.65, w)
        d.rectangle([x0, y, x1, y + th], fill=col)
    return img


def _leak_layer(size, amount: int, rng: random.Random) -> Image.Image:
    """漏光层：从某一侧边缘漏进来的一片暖光。返回一张和画布同尺寸的 RGB 层。"""
    w, h = size
    layer = Image.new("RGB", size, (0, 0, 0))
    r = int(max(w, h) * rng.uniform(0.55, 0.85))
    grad = ImageChops.invert(Image.radial_gradient("L")).resize(
        (r, r), Image.Resampling.LANCZOS)

    side = rng.choice(["left", "right", "left", "top"])
    if side == "left":
        px, py = int(-r * 0.45), int(rng.uniform(-r * 0.3, h - r * 0.7))
    elif side == "right":
        px, py = int(w - r * 0.55), int(rng.uniform(-r * 0.3, h - r * 0.7))
    else:
        px, py = int(rng.uniform(-r * 0.3, w - r * 0.7)), int(-r * 0.45)

    color = rng.choice(LEAK_COLORS)
    blob = Image.new("RGB", (r, r), color)
    layer.paste(blob, (px, py), grad)

    # 再补一道窄的斜光带，像从缝隙里漏的
    if rng.random() < 0.6:
        band = Image.new("RGB", (w, h), (0, 0, 0))
        bd = ImageDraw.Draw(band, "RGBA")
        bw = int(h * rng.uniform(0.10, 0.22))
        bx = int(w * rng.uniform(0.05, 0.5))
        bd.rectangle([bx, 0, bx + bw, h], fill=color + (rng.randint(30, 70),))
        layer = ImageChops.screen(layer, band)

    return Image.blend(Image.new("RGB", size, (0, 0, 0)), layer,
                       min(1.0, amount / 100.0 * 1.15))


# ======================================================================
# 入口
# ======================================================================
def apply(canvas: Image.Image, spec, rows, frames, seed: int = 0) -> Image.Image:
    """在画好的胶卷图上加特效，返回新图。

    rows   : [(x, y, w, h)] 每条胶片的矩形
    frames : [(x, y, w, h)] 每格画幅的矩形
    seed   : 随机种子 —— 同一个项目同一卷给同一个种子，重新生成结果才稳定
    """
    spec = normalize(spec)
    if not any_on(spec):
        return canvas

    rng = random.Random(seed)
    canvas = canvas.copy()

    # ---- 逐格：褪色、暗角 ----
    if spec["faded"] > 0 or spec["vignette"] > 0:
        for box in frames:
            x, y, w, h = box
            if w < 2 or h < 2:
                continue
            piece = canvas.crop((x, y, x + w, y + h))
            canvas.paste(_apply_frame(piece, spec), (x, y))

    # ---- 整条：颗粒、划痕 ----
    if spec["grain"] > 0 or spec["scratch"] > 0:
        for box in rows:
            x, y, w, h = box
            if w < 2 or h < 2:
                continue
            piece = canvas.crop((x, y, x + w, y + h))
            piece = _grain(piece, spec["grain"])
            piece = _scratches(piece, spec["scratch"], rng)
            canvas.paste(piece, (x, y))

    # ---- 整条：漏光（放最后，光要压在所有东西上面）----
    if spec["leak"] > 0:
        layer = _leak_layer(canvas.size, spec["leak"], rng)
        rows_mask = Image.new("L", canvas.size, 0)
        md = ImageDraw.Draw(rows_mask)
        for x, y, w, h in rows:
            md.rectangle([x, y, x + w - 1, y + h - 1], fill=255)
        lit = ImageChops.screen(canvas, layer)
        canvas = Image.composite(lit, canvas, rows_mask)

    return canvas
