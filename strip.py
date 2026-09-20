"""胶卷总览图渲染引擎。纯 Pillow 实现，不依赖 tkinter。

一张"胶卷展开总览图"左上角是一只立起来的 135 暗盒，片头从出片口拉出来：

     ╭──────╮
    ╱ ◎ ◎ ◎ ╲
   │ KODAK 400│╮━━━━━━━━━━━        ← 暗盒（圆柱）+ 片头
   │135·36EXP │╯
    ╲        ╱        KODAK 400
     ╰──────╯
    ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪   ← 上齿孔，帧号印在齿孔之间
    ┌────┐┌────┐┌────┐┌────┐┌────┐      ← 画幅
    └────┘└────┘└────┘└────┘└────┘
    ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪   ← 下齿孔，同样印帧号

每卷默认 40 张，折成 8 列 × 5 行叠放；最后一行不满时补空画幅，
这样每一卷宽度一致，看起来才像真正的胶卷。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import canister as canister_mod
import effects as effects_module
import theme

# ---------------- 配色 ----------------
BG           = (20, 20, 20)      # 整图背景
FILM         = (28, 24, 21)      # 片基
FILM_EDGE    = (48, 42, 37)      # 片基描边
PERF         = (9, 8, 7)         # 齿孔（透光孔）
EMPTY_FRAME  = (16, 14, 13)      # 未曝光的空画幅
EMPTY_EDGE   = (58, 52, 46)
MATTE        = (13, 12, 11)      # 竖构图照片两侧的留边
FRAME_BORDER = (216, 210, 200)   # 画幅细边框
EDGE_TEXT    = (200, 134, 42)    # 片边印刷（琥珀色）
FRAME_NO     = (188, 180, 168)   # 帧号
TITLE_TEXT   = (232, 228, 220)
ACCENT       = (200, 134, 42)

# ---------------- 几何 ----------------
EDGE_PAD     = 40    # 片边左右留白
FRAME_GAP    = 8     # 画幅之间的间距
PERF_H       = 30    # 齿孔带高度（帧号就印在齿孔之间）
FRAME_PAD_V  = 10    # 画幅与齿孔带之间的间距
ROW_GAP      = 24    # 两条胶片之间的间距
TITLE_H      = 64    # 顶部标题栏高度
MARGIN       = 32    # 整图四周留白

# 左上角暗盒（立起来的 135 暗盒，含顶上露出来的卷轴头）
CANISTER_W   = 230
CANISTER_H   = 330
CANISTER_TOP = TITLE_H + 6
LEADER_LEN   = 1420  # 从暗盒出片口伸出来的片头长度
LEADER_H     = 118   # 片头宽度（按真胶片比例，约是暗盒柱身的一半高）
LEADER_DROP  = 46    # 片头右端往下斜多少（让视觉流向下面的胶片）
HEADER_H     = CANISTER_TOP + CANISTER_H   # 暗盒带底部，胶片从这下面开始

DEFAULT_COLS    = 8
DEFAULT_THUMB_W = 360
DEFAULT_THUMB_H = 240


def make_thumb(src, cache_dir=None,
               size=(DEFAULT_THUMB_W, DEFAULT_THUMB_H), mode: str = "rotate") -> Image.Image:
    """取缩略图：纠正 EXIF 旋转 → 缩放到指定画幅，带磁盘缓存。

    mode="rotate"  —— 竖构图照片先转 90°（照片顶部朝左）再完整放进画幅（默认，
                      既不会丢内容，也几乎不留黑边）
    mode="contain" —— 不旋转，整张照片可见，不满画幅的地方留深色边
    mode="cover"   —— 居中裁剪填满画幅，画幅最统一，但竖构图会被裁掉两侧
    """
    src = Path(src)
    cache_file = None
    if cache_dir:
        try:
            st = src.stat()
            cache_file = (Path(cache_dir) /
                          f"{src.stem}_{st.st_mtime_ns}_{st.st_size}_{size[0]}x{size[1]}_{mode}.jpg")
            if cache_file.is_file():
                with Image.open(cache_file) as im:
                    im.load()
                    return im.convert("RGB")
        except Exception:
            cache_file = None

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im) or im
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        if mode == "cover":
            thumb = ImageOps.fit(im, size, Image.Resampling.LANCZOS,
                                 centering=(0.5, 0.5)).convert("RGB")
        else:
            if mode == "rotate" and im.height > im.width:
                im = im.transpose(Image.Transpose.ROTATE_90)
            inner = ImageOps.contain(im, size, Image.Resampling.LANCZOS).convert("RGB")
            thumb = Image.new("RGB", size, MATTE)
            thumb.paste(inner, ((size[0] - inner.width) // 2,
                                (size[1] - inner.height) // 2))

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            thumb.save(cache_file, "JPEG", quality=92)
        except Exception:
            pass
    return thumb


def frame_at(x: float, y: float, *, cols: int = DEFAULT_COLS,
             thumb_w: int = DEFAULT_THUMB_W,
             thumb_h: int = DEFAULT_THUMB_H) -> int | None:
    """胶卷图上的坐标 (x, y) 落在第几张画幅上？从 0 数，不在画幅上返回 None。

    跟 _draw_film_row() 的排版是一套几何，改那边记得同步改这边。
    落在齿孔带、行间距、画幅之间的缝、或者图外面，都返回 None。
    """
    film_h = PERF_H * 2 + FRAME_PAD_V * 2 + thumb_h
    step = film_h + ROW_GAP
    top = HEADER_H + MARGIN

    if y < top or x < MARGIN + EDGE_PAD:
        return None

    row = int((y - top) // step)
    frames_y = top + row * step + PERF_H + FRAME_PAD_V
    if not (frames_y <= y < frames_y + thumb_h):
        return None                      # 落在齿孔带或行间距上

    col = int((x - MARGIN - EDGE_PAD) // (thumb_w + FRAME_GAP))
    if not (0 <= col < cols):
        return None
    fx = MARGIN + EDGE_PAD + col * (thumb_w + FRAME_GAP)
    if not (fx <= x < fx + thumb_w):
        return None                      # 落在画幅之间的缝里
    return row * cols + col


def split_into_strips(items, per_strip: int = 40) -> list[list]:
    """按每卷张数切分。不满一卷的余数单独成卷。"""
    per = max(1, int(per_strip))
    return [list(items[i:i + per]) for i in range(0, len(items), per)]


def cover_thumb(src, cache_dir, size=(300, 182), bg=BG) -> Image.Image | None:
    """把一张胶卷图缩成卡片封面：整张完整放进 size，四周用底色补边。

    项目卡片墙和胶卷图库共用这个。带磁盘缓存，读不出来返回 None。
    """
    src = Path(src)
    cache = None
    try:
        st = src.stat()
        cache = Path(cache_dir) / f"cover_{src.stem}_{st.st_mtime_ns}_{size[0]}x{size[1]}.jpg"
        if cache.is_file():
            with Image.open(cache) as im:
                im.load()
                return im.convert("RGB")
    except Exception:
        cache = None

    try:
        with Image.open(src) as im:
            inner = ImageOps.contain(im.convert("RGB"), size, Image.Resampling.LANCZOS)
            out = Image.new("RGB", size, bg)
            out.paste(inner, ((size[0] - inner.width) // 2,
                              (size[1] - inner.height) // 2))
    except Exception:
        return None

    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            out.save(cache, "JPEG", quality=88)
        except Exception:
            pass
    return out


def _triangle(draw, cx, cy, size, color, direction=1):
    """画片头/片尾方向标记。direction=1 向右，-1 向左。"""
    h = size / 2
    if direction > 0:
        pts = [(cx - h, cy - h), (cx - h, cy + h), (cx + h, cy)]
    else:
        pts = [(cx + h, cy - h), (cx + h, cy + h), (cx - h, cy)]
    draw.polygon(pts, fill=color)


def _draw_film_row(canvas, draw, paths, *, x0, y0, cols, thumb_w, thumb_h,
                   start_number, film_label, cache_dir, fit_mode,
                   progress_cb, done, total):
    """画一条完整胶片（不足 cols 张时后面补空画幅）。

    帧号印在上下两条齿孔带里、同一画幅两个齿孔中间 —— 就像真胶片的片边码。
    """
    film_w = EDGE_PAD * 2 + cols * thumb_w + (cols - 1) * FRAME_GAP
    film_h = PERF_H * 2 + FRAME_PAD_V * 2 + thumb_h

    # 片基
    draw.rectangle([x0, y0, x0 + film_w - 1, y0 + film_h - 1], fill=FILM)
    draw.rectangle([x0, y0, x0 + film_w - 1, y0 + film_h - 1], outline=FILM_EDGE, width=1)

    hole_w, hole_h, radius = 20, 14, 4
    hole_dy = (PERF_H - hole_h) // 2
    band_top, band_bot = y0, y0 + film_h - PERF_H
    num_font = theme.pil_font(19, "mono")

    for i in range(cols):
        cx = x0 + EDGE_PAD + i * (thumb_w + FRAME_GAP) + thumb_w / 2

        # 每个画幅上下各 2 个齿孔
        for band_y in (band_top, band_bot):
            for dx in (-thumb_w / 4, thumb_w / 4):
                hx = cx + dx - hole_w / 2
                draw.rounded_rectangle([hx, band_y + hole_dy,
                                        hx + hole_w, band_y + hole_dy + hole_h],
                                       radius=radius, fill=PERF)

        # 片边编号：印在两个齿孔中间，上下两条边都印
        if i < len(paths):
            for band_y in (band_top, band_bot):
                draw.text((cx, band_y + PERF_H / 2), f"{start_number + i:02d}",
                          font=num_font, fill=EDGE_TEXT, anchor="mm")

    # 片名印在上边最左，片头/片尾方向标记印在下边
    if film_label:
        draw.text((x0 + 16, band_top + PERF_H / 2), film_label,
                  font=theme.pil_font(15, "mono"), fill=EDGE_TEXT, anchor="lm")
    _triangle(draw, x0 + 18, band_bot + PERF_H / 2, 11, EDGE_TEXT, 1)
    _triangle(draw, x0 + film_w - 18, band_bot + PERF_H / 2, 11, EDGE_TEXT, -1)

    # 画幅区
    frames_y = y0 + PERF_H + FRAME_PAD_V
    boxes = []
    for i in range(cols):
        fx = x0 + EDGE_PAD + i * (thumb_w + FRAME_GAP)
        if i < len(paths):
            thumb = make_thumb(paths[i], cache_dir, (thumb_w, thumb_h), fit_mode)
            canvas.paste(thumb, (fx, frames_y))
            draw.rectangle([fx - 1, frames_y - 1, fx + thumb_w, frames_y + thumb_h],
                           outline=FRAME_BORDER, width=2)
            boxes.append((fx, frames_y, thumb_w, thumb_h))
            if progress_cb:
                progress_cb(done + i + 1, total)
        else:
            draw.rectangle([fx, frames_y, fx + thumb_w - 1, frames_y + thumb_h - 1],
                           fill=EMPTY_FRAME)
            draw.rectangle([fx - 1, frames_y - 1, fx + thumb_w, frames_y + thumb_h],
                           outline=EMPTY_EDGE, width=1)

    return (x0, y0, film_w, film_h), boxes


def render_strip(image_paths, *, start_number: int = 1, cols: int = DEFAULT_COLS,
                 thumb_w: int = DEFAULT_THUMB_W, thumb_h: int = DEFAULT_THUMB_H,
                 project_name: str = "", strip_index: int = 1, strip_total: int = 1,
                 film_label: str = "FILM 400", cache_dir=None, fit_mode: str = "rotate",
                 canister: str = "kodak", canister_custom: dict | None = None,
                 canister_library: dict | None = None,
                 effects: dict | None = None, effects_seed: int | None = None,
                 progress_cb=None) -> Image.Image:
    """渲染一卷胶卷总览图，返回 PIL Image。

    image_paths      : 本卷的照片路径（最多 cols * rows 张）
    start_number     : 本卷第一张的帧号（跨卷连续编号，如第 2 卷从 41 开始）
    fit_mode         : "rotate" 竖图转90°(默认) / "contain" 完整显示 / "cover" 裁剪填满
    canister         : 暗盒 —— 内置名 / 库里保存的 id / 老项目的 "custom"
    canister_custom  : canister="custom" 时的内联颜色（兼容老项目）
    canister_library : 用户保存的暗盒 {id: 暗盒}
    effects          : 胶片特效 {效果名: 0-100}，见 effects.py
    effects_seed     : 特效的随机种子。**不传就每次随机** —— 漏光和划痕每次
                       生成都落在不同地方。传个固定值可以锁住（测试用）
    progress_cb      : 可选回调 (已处理张数, 总张数)
    """
    paths = [Path(p) for p in image_paths]
    n = len(paths)
    if n == 0:
        raise ValueError("没有照片可以渲染")
    cols = max(1, int(cols))
    rows = math.ceil(n / cols)
    spec = canister_mod.resolve(canister, canister_custom, canister_library)

    film_w = EDGE_PAD * 2 + cols * thumb_w + (cols - 1) * FRAME_GAP
    film_h = PERF_H * 2 + FRAME_PAD_V * 2 + thumb_h
    total_w = film_w + MARGIN * 2
    total_h = HEADER_H + MARGIN * 2 + rows * film_h + (rows - 1) * ROW_GAP

    canvas = Image.new("RGB", (total_w, total_h), BG)
    draw = ImageDraw.Draw(canvas)

    # ---- 顶部标题栏 ----
    title_cy = (TITLE_H - 2) // 2
    if project_name:
        draw.text((MARGIN, title_cy), project_name,
                  font=theme.pil_font(30, "bold"), fill=TITLE_TEXT, anchor="lm")
    draw.text((total_w - MARGIN, title_cy), f"{strip_index} / {strip_total}",
              font=theme.pil_font(26, "mono"), fill=ACCENT, anchor="rm")
    draw.rectangle([MARGIN, TITLE_H - 2, total_w - MARGIN, TITLE_H], fill=ACCENT)

    # ---- 暗盒 + 从出片口拉出来的片头 ----
    exit_x, exit_y = canister_mod.draw_canister(
        canvas, MARGIN, CANISTER_TOP, CANISTER_W, CANISTER_H, spec)
    canister_mod.draw_leader(draw, exit_x, exit_y, LEADER_LEN, LEADER_H, FILM, PERF,
                             drop=LEADER_DROP)

    # ---- 暗盒右边的说明文字（放在片头末端之后，免得打架）----
    tx = MARGIN + CANISTER_W + LEADER_LEN + 100
    cy = CANISTER_TOP + CANISTER_H * 0.6      # 对着柱身（不含顶上的卷轴头）
    draw.text((tx, cy - 38), spec["label"],
              font=theme.pil_font(40, "mono"), fill=ACCENT, anchor="lm")
    draw.text((tx, cy + 38), f"第 {strip_index} / {strip_total} 卷　·　{n} 张",
              font=theme.pil_font(22, "ui"), fill=FRAME_NO, anchor="lm")

    # ---- 逐条胶片 ----
    row_boxes: list = []
    frame_boxes: list = []
    for r in range(rows):
        row = paths[r * cols:(r + 1) * cols]
        y0 = HEADER_H + MARGIN + r * (film_h + ROW_GAP)
        rb, fb = _draw_film_row(canvas, draw, row, x0=MARGIN, y0=y0, cols=cols,
                                thumb_w=thumb_w, thumb_h=thumb_h,
                                start_number=start_number + r * cols,
                                film_label=film_label, cache_dir=cache_dir,
                                fit_mode=fit_mode,
                                progress_cb=progress_cb, done=r * cols, total=n)
        row_boxes.append(rb)
        frame_boxes.extend(fb)

    # ---- 胶片特效 ----
    if effects_module.any_on(effects):
        # 种子默认随机 —— 每次生成漏光和划痕都落在不同地方。
        # 传了 effects_seed 就用传进来的（测试里锁结果用）。
        seed = effects_seed if effects_seed is not None else random.randrange(1 << 32)
        canvas = effects_module.apply(canvas, effects, row_boxes, frame_boxes, seed)

    return canvas
