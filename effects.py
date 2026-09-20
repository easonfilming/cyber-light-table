"""胶片特效：给生成好的胶卷图加漏光、颗粒、划痕这些"胶片味"。

分两种作用范围：
  · 整条胶片上（漏光、颗粒、划痕）—— 这些是片基和乳剂上的东西
  · 每一格画幅上（褪色、暗角）—— 这些是镜头和冲洗带来的

强度都是 0-100，0 就是关掉。
"""
from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# (键, 名字, 说明, 默认强度)
EFFECTS = [
    ("leak",     "漏光", "边缘射进来一道强光，像相机后盖没盖严", 0),
    ("grain",    "颗粒", "胶片的颗粒感，暗部尤其明显", 0),
    ("scratch",  "划痕", "片基上细细的划痕", 0),
    ("faded",    "褪色", "褪色发暖、黑位发灰，像过期胶卷", 0),
    ("vignette", "暗角", "四角压暗，像老镜头的暗角", 0),
    ("lucky_r",  "乐凯红", "整卷底色偏品红，像乐凯彩色负片", 0),
    ("lucky_g",  "乐凯绿", "整卷底色发黄绿", 0),
]
NAMES = [k for k, *_ in EFFECTS]

# 互斥的效果：同一卷不可能既偏品红又偏黄绿
EXCLUSIVE = [("lucky_r", "lucky_g")]

# 漏光的颜色：饱和的红橙，不是白芯子（参考富士 X-Half 那种）
LEAK_COLORS = [(226, 74, 40), (238, 98, 48), (208, 56, 34),
               (244, 122, 62), (218, 86, 44)]

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


def exclusive_fix(spec: dict, changed: str) -> dict:
    """互斥的效果：开了这个，就把跟它互斥的那个清零。

    同一卷不可能既偏品红又偏黄绿，所以乐凯红和乐凯绿只能开一个。
    """
    out = dict(spec)
    for group in EXCLUSIVE:
        if changed in group and out.get(changed, 0) > 0:
            for other in group:
                if other != changed:
                    out[other] = 0
    return out


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


def _blob_mask(size, cx, cy, rx, ry, rng, lumps=3):
    """一团边缘不规则的椭圆遮罩：几个椭圆叠一起再糊一下。

    最后把峰值拉到 255 —— 糊过之后峰值会掉到一半以下，
    直接拿去当透明度用的话颜色只上一半，漏光会淡得看不见。
    """
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for _ in range(max(1, lumps)):
        ox = rng.uniform(-0.35, 0.35) * rx
        oy = rng.uniform(-0.45, 0.45) * ry
        r1 = rx * rng.uniform(0.45, 0.78)
        r2 = ry * rng.uniform(0.45, 0.78)
        d.ellipse([cx + ox - r1, cy + oy - r2, cx + ox + r1, cy + oy + r2], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(3.0, min(rx, ry) * 0.28)))
    peak = m.getextrema()[1]
    if peak > 0:
        m = m.point(lambda v: min(255, int(v * 255 / peak)))
    return m


def _leak_layer(size, amount: int, rng: random.Random, film_box=None) -> Image.Image:
    """漏光层：一片边缘很柔的红橙光雾。

    参考富士 X-Half 的漏光 —— **不是一道细光带，是一大片糊开的红橙色**，
    横向拉长、没有白芯子，而且区域和大小纯随机：
    可以横跨整个画面，也可以只是偏在角落的一小块。

    film_box 是胶片区域的包围盒 —— 位置只在胶片范围内随机，
    否则光团可能落在暗盒带那片空白里，漏了等于没漏。
    """
    w, h = size
    layer = Image.new("RGB", size, (0, 0, 0))
    fx, fy, fw, fh = film_box if film_box else (0, 0, w, h)

    # 主光团：横向拉长，位置和大小都随机
    bw = fw * rng.uniform(0.35, 1.30)         # 宽：从一段到横跨整幅
    bh = fh * rng.uniform(0.15, 0.55)         # 高：从一条到一大片
    cx = fx + fw * rng.uniform(-0.05, 1.05)
    cy = fy + fh * rng.uniform(0.04, 0.96)
    color = rng.choice(LEAK_COLORS)

    mask = _blob_mask(size, cx, cy, bw / 2, bh / 2, rng,
                      lumps=rng.randint(2, 4))
    layer = Image.composite(Image.new("RGB", size, color), layer, mask)

    # 有时候旁边再带一小团，像光从别处也渗进来一点
    if rng.random() < 0.5:
        bw2 = bw * rng.uniform(0.18, 0.45)
        bh2 = bh * rng.uniform(0.25, 0.6)
        cx2 = cx + rng.uniform(-1.1, 1.1) * bw / 2
        cy2 = cy + rng.uniform(-1.2, 1.2) * bh / 2
        m2 = _blob_mask(size, cx2, cy2, bw2 / 2, bh2 / 2, rng, lumps=2)
        layer = ImageChops.screen(
            layer, Image.composite(Image.new("RGB", size, rng.choice(LEAK_COLORS)),
                                   Image.new("RGB", size, (0, 0, 0)), m2))

    # 光是**加上去**的，所以用 screen：暗部会被点亮成红橙，亮部还是亮
    return Image.blend(Image.new("RGB", size, (0, 0, 0)), layer,
                       min(1.0, amount / 100.0 * 1.15))


# 乐凯偏色：通道增益 + 暗部染的色雾（片基本身带色，暗部最明显）
LUCKY = {
    "lucky_r": {"gains": (1.16, 0.88, 1.08), "veil": (200, 130, 178)},
    "lucky_g": {"gains": (0.98, 1.12, 0.82), "veil": (172, 196, 128)},
}


def _lucky(img: Image.Image, amount: int, gains, veil) -> Image.Image:
    """整卷偏色。强度越大偏得越多，暗部还会染上一层片基的色。"""
    if amount <= 0:
        return img
    a = amount / 100.0
    chans = []
    for ch, k in zip(img.split(), gains):
        kk = 1.0 + (k - 1.0) * a
        chans.append(ch.point(lambda v, _k=kk: min(255, int(v * _k))))
    out = Image.merge("RGB", chans)
    # 暗部染色：越暗染得越多
    shadow = ImageChops.invert(out.convert("L")).point(lambda v: int(v * a * 0.5))
    return Image.composite(Image.new("RGB", img.size, veil), out, shadow)


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

    # ---- 整条：偏色、颗粒、划痕 ----
    if any(spec[k] > 0 for k in ("lucky_r", "lucky_g", "grain", "scratch")):
        for box in rows:
            x, y, w, h = box
            if w < 2 or h < 2:
                continue
            piece = canvas.crop((x, y, x + w, y + h))
            for key in ("lucky_r", "lucky_g"):
                piece = _lucky(piece, spec[key], **LUCKY[key])
            piece = _grain(piece, spec["grain"])
            piece = _scratches(piece, spec["scratch"], rng)
            canvas.paste(piece, (x, y))

    # ---- 整条：漏光（放最后，光要压在所有东西上面）----
    if spec["leak"] > 0:
        # 胶片区域的包围盒 —— 光团只在这块里随机，不然可能落在空白处白漏
        film_box = None
        if rows:
            xs = [b[0] for b in rows]
            ys = [b[1] for b in rows]
            film_box = (min(xs), min(ys),
                        max(b[0] + b[2] for b in rows) - min(xs),
                        max(b[1] + b[3] for b in rows) - min(ys))
        layer = _leak_layer(canvas.size, spec["leak"], rng, film_box)
        rows_mask = Image.new("L", canvas.size, 0)
        md = ImageDraw.Draw(rows_mask)
        for x, y, w, h in rows:
            md.rectangle([x, y, x + w - 1, y + h - 1], fill=255)
        lit = ImageChops.screen(canvas, layer)
        canvas = Image.composite(lit, canvas, rows_mask)

    return canvas
