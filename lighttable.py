"""观片台预览 + 观片器。

整个预览区用**一张 PIL 图合成**后显示，比在 Canvas 上摆图元好写得多
（拖动观片器时只要重画这一张）：

    1. 灯箱底     —— 关灯是深色，开灯是暖白匀光板（带分格线和渐晕）
    2. 胶卷图     —— 关灯时只留 8% 亮度的剪影，看得见有胶片但看不清内容
    3. 压暗外圈   —— 放了观片器时，镜外压暗一点，让镜内更突出
    4. 观片器     —— 圆形黄铜镜圈，镜内是按倍率放大的原始像素

观片器的倍率是**相对原始像素**的：4× 就是 1 个图像像素放大成 4 个屏幕像素，
和真的观片器一样，跟当前视图缩放无关。
"""
from __future__ import annotations

import math
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import theme
from strip import DEFAULT_COLS, DEFAULT_THUMB_H, DEFAULT_THUMB_W
from strip import frame_at as strip_frame_at

PAD = 24               # 胶卷图四周留白

# 倍率 → 镜片半径（倍率越高镜片越小，跟真观片器一样）
MAGS = {1: 112, 2: 100, 4: 88, 8: 74}
DEFAULT_MAG = 4

_VIGNETTES: dict = {}


def loupe_source_box(px: float, py: float, r: float, mag: float,
                     iw: int, ih: int) -> tuple[float, float, float, float]:
    """观片器镜片中心落在原图 (px, py) 时，镜内要采样的原图区域。

    区域边长是 2r/mag（倍率越高看得越细），并夹到图像范围内。
    完全落在图像外时返回一个空框（x1<=x0 或 y1<=y0）。
    """
    half = r / mag
    return (max(0.0, px - half), max(0.0, py - half),
            min(float(iw), px + half), min(float(ih), py + half))


def _vignette(size, power: float = 2.2):
    """从中心到边缘由亮到暗的遮罩，用来做灯箱渐晕。结果缓存。"""
    key = (size, power)
    if key in _VIGNETTES:
        return _VIGNETTES[key]
    small = Image.new("L", (32, 32), 0)
    px = small.load()
    for y in range(32):
        for x in range(32):
            dx = abs(x - 15.5) / 15.5
            dy = abs(y - 15.5) / 15.5
            r = min(1.0, math.hypot(dx, dy) / 1.4142)
            px[x, y] = int(255 * (r ** power))
    mask = small.resize(size, Image.Resampling.BICUBIC)
    _VIGNETTES[key] = mask
    return mask


class LightTable(tk.Canvas):
    """观片台。滚轮缩放、空白处拖动平移、观片器上按住拖动移动观片器。"""

    def __init__(self, master, on_light=None, on_frame_click=None, **kw):
        super().__init__(master, bg=theme.rgb_to_hex(theme.TABLE_OFF),
                         highlightthickness=0, **kw)
        self.src: Image.Image | None = None
        self.light_on = False
        self.loupe: dict | None = None      # {"mag": int, "x": int, "y": int, "r": int}
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.loupe_dim = theme.LOUPE_DIM    # 镜外压暗多少（设置页可调）

        # 当前这张胶卷图的排版参数，反查画幅时要用
        self.cols = DEFAULT_COLS
        self.thumb_w = DEFAULT_THUMB_W
        self.thumb_h = DEFAULT_THUMB_H

        self.on_light = on_light            # 开灯状态变化时回调（用来更新按钮文字）
        self.on_frame_click = on_frame_click  # 点了某一格，回调序号（从 0 数）
        self._photo = None                  # 保持引用，否则会被 GC
        self._job = None
        self._drag = None
        self._pan_from = None
        self._place = None                  # 上次贴图的 (sx, sy, scale)
        self._press_pos = None
        self._moved = False
        self._empty_text = "还没有胶卷图\n\n添加照片后点「生成胶卷图」"

        self.bind("<Configure>", lambda e: self.render())
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ================= 对外接口 =================
    def set_image(self, path, *, cols=None, thumb_w=None, thumb_h=None):
        """换一张胶卷图。cols/thumb_* 是这张图的排版参数（反查画幅时要用）。"""
        if cols:
            self.cols = int(cols)
        if thumb_w:
            self.thumb_w = int(thumb_w)
        if thumb_h:
            self.thumb_h = int(thumb_h)
        self.src = None
        if path is not None:
            try:
                im = Image.open(path)
                im.load()
                self.src = im.convert("RGB")
            except Exception:
                self.src = None
        self.zoom, self.pan_x, self.pan_y = 1.0, 0, 0
        self.render()

    def set_light(self, on: bool):
        if self.light_on != bool(on):
            self.light_on = bool(on)
            if self.on_light:
                self.on_light(self.light_on)
            self.render()

    def toggle_light(self):
        self.set_light(not self.light_on)

    def set_loupe(self, mag: int):
        """选中某个倍率：观片器出现在灯箱正中。"""
        mag = int(mag)
        r = MAGS.get(mag, MAGS[DEFAULT_MAG])
        cw, ch = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        self.loupe = {"mag": mag, "x": cw // 2, "y": ch // 2, "r": r}
        self.render()

    def clear_loupe(self):
        self.loupe = None
        self.render()

    @property
    def loupe_mag(self) -> int | None:
        return self.loupe["mag"] if self.loupe else None

    # ================= 渲染 =================
    def _schedule(self):
        if self._job is None:
            self._job = self.after(33, self.render)     # 约 30fps

    def render(self):
        self._job = None
        cw, ch = max(self.winfo_width(), 1), max(self.winfo_height(), 1)

        view = self._table(cw, ch)
        place = self._paste_strip(view, cw, ch)
        self._place = place             # 点画幅时要用它把视图坐标换算回原图坐标

        if self.loupe:
            self._draw_loupe(view, cw, ch, place)

        if self.src is None:
            d = ImageDraw.Draw(view)
            d.multiline_text((cw / 2, ch / 2), self._empty_text,
                             font=theme.pil_font(15, "ui"),
                             fill=(150, 143, 130), anchor="mm",
                             align="center", spacing=10)
        elif not self.light_on:
            d = ImageDraw.Draw(view)
            d.text((cw / 2, ch - 34), "点右边「开灯」看看",
                   font=theme.pil_font(13, "ui"), fill=(120, 113, 100), anchor="mm")

        self._photo = ImageTk.PhotoImage(view)
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")

    def _table(self, cw: int, ch: int) -> Image.Image:
        """灯箱底：关灯深色 / 开灯纯白。"""
        if self.light_on:
            base, edge = theme.TABLE_ON, theme.TABLE_ON_EDGE
        else:
            base, edge = theme.TABLE_OFF, theme.TABLE_OFF_EDGE

        img = Image.new("RGB", (cw, ch), base)

        # 只留很淡的四周渐晕，中间保持纯白，免得抢了胶片
        img = Image.composite(Image.new("RGB", (cw, ch), edge), img,
                              _vignette((cw, ch), 2.6))
        return img

    def _paste_strip(self, view: Image.Image, cw: int, ch: int):
        """把胶卷图贴到灯箱上。返回 (sx, sy, scale)，没有图时返回 None。"""
        if self.src is None:
            return None
        iw, ih = self.src.size
        fit = min((cw - PAD * 2) / iw, (ch - PAD * 2) / ih)
        scale = fit * self.zoom
        w, h = max(1, int(iw * scale)), max(1, int(ih * scale))

        disp = self.src.resize((w, h), Image.Resampling.LANCZOS)
        if not self.light_on:
            # 关灯：只留 8% 亮度，变成一块看不清内容的剪影
            disp = Image.blend(Image.new("RGB", (w, h), (0, 0, 0)),
                               disp, theme.SILHOUETTE)

        if w <= cw - PAD * 2:
            sx = (cw - w) // 2
        else:
            sx = max(cw - w, min(0, (cw - w) // 2 + self.pan_x))
        if h <= ch - PAD * 2:
            sy = (ch - h) // 2
        else:
            sy = max(ch - h, min(0, (ch - h) // 2 + self.pan_y))

        view.paste(disp, (sx, sy))
        return sx, sy, scale

    def _draw_loupe(self, view: Image.Image, cw: int, ch: int, place):
        """观片器：镜外压暗 → 贴镜内放大画面 → 画黄铜镜圈和手柄。"""
        lp = self.loupe
        r, mag = lp["r"], lp["mag"]
        lx = max(r + 8, min(cw - r - 8, lp["x"]))
        ly = max(r + 8, min(ch - r - 8, lp["y"]))
        lp["x"], lp["y"] = lx, ly

        # 镜外压暗，让镜内突出（白底上别压太狠，不然看着发脏）
        dimmed = Image.blend(view, Image.new("RGB", (cw, ch), (0, 0, 0)),
                             self.loupe_dim)
        mask = Image.new("L", (cw, ch), 255)
        ImageDraw.Draw(mask).ellipse([lx - r - 3, ly - r - 3, lx + r + 3, ly + r + 3], fill=0)
        view.paste(dimmed, (0, 0), mask)

        # 镜内画面：按 mag（相对原始像素）取样
        if place is not None and self.src is not None:
            sx, sy, scale = place
            iw, ih = self.src.size
            px = (lx - sx) / scale
            py = (ly - sy) / scale
            half = r / mag

            region = Image.new("RGB", (int(half * 2), int(half * 2)),
                               theme.TABLE_ON if self.light_on else theme.TABLE_OFF)
            x0, y0, x1, y1 = loupe_source_box(px, py, r, mag, iw, ih)
            if x1 > x0 and y1 > y0:
                piece = self.src.crop((int(x0), int(y0), int(x1), int(y1)))
                region.paste(piece, (int(x0 - (px - half)), int(y0 - (py - half))))

            zoomed = region.resize((r * 2, r * 2), Image.Resampling.LANCZOS)
            circle = Image.new("L", (r * 2, r * 2), 0)
            ImageDraw.Draw(circle).ellipse([0, 0, r * 2 - 1, r * 2 - 1], fill=255)
            view.paste(zoomed, (lx - r, ly - r), circle)

        # 黄铜镜圈（三层做出厚度）
        d = ImageDraw.Draw(view)
        d.ellipse([lx - r - 9, ly - r - 9, lx + r + 9, ly + r + 9],
                  outline=theme.RIM_OUT, width=6)
        d.ellipse([lx - r - 4, ly - r - 4, lx + r + 4, ly + r + 4],
                  outline=theme.RIM_MID, width=3)
        d.ellipse([lx - r - 1, ly - r - 1, lx + r + 1, ly + r + 1],
                  outline=theme.RIM_IN, width=2)

        # 手柄（右上 45°）
        ang = -math.pi / 4
        hx0, hy0 = lx + math.cos(ang) * (r + 6), ly + math.sin(ang) * (r + 6)
        hx1, hy1 = lx + math.cos(ang) * (r + 34), ly + math.sin(ang) * (r + 34)
        d.line([hx0, hy0, hx1, hy1], fill=theme.RIM_OUT, width=14)
        d.ellipse([hx1 - 10, hy1 - 10, hx1 + 10, hy1 + 10],
                  fill=theme.RIM_MID, outline=theme.RIM_OUT, width=2)

    # ================= 交互 =================
    def _in_loupe(self, x, y) -> bool:
        if not self.loupe:
            return False
        return math.hypot(x - self.loupe["x"], y - self.loupe["y"]) <= self.loupe["r"] + 12

    def _on_press(self, e):
        self._press_pos = (e.x, e.y)
        self._moved = False
        if self._in_loupe(e.x, e.y):
            self._drag = (e.x - self.loupe["x"], e.y - self.loupe["y"])
            self.configure(cursor="fleur")
        else:
            self._pan_from = (e.x, e.y, self.pan_x, self.pan_y)

    def _on_motion(self, e):
        if self._press_pos is not None:
            px, py = self._press_pos
            if abs(e.x - px) > 6 or abs(e.y - py) > 6:
                self._moved = True
        if self._drag is not None:
            self.loupe["x"] = e.x - self._drag[0]
            self.loupe["y"] = e.y - self._drag[1]
            self._schedule()
        elif self._pan_from is not None:
            px, py, ox, oy = self._pan_from
            self.pan_x, self.pan_y = ox + (e.x - px), oy + (e.y - py)
            self._schedule()

    def _on_release(self, e):
        # 没拖过、也不是在拖观片器 → 当成一次点击
        clicked = (not self._moved) and self._drag is None
        self._drag = None
        self._pan_from = None
        self._press_pos = None
        self.configure(cursor="")
        if clicked:
            self._emit_frame_click(e.x, e.y)

    def _emit_frame_click(self, vx: int, vy: int):
        """把视图坐标换算回胶卷图原始坐标，反查是第几张画幅。"""
        if self.on_frame_click is None or self.src is None or self._place is None:
            return
        if not self.light_on:
            return                  # 关着灯看不见内容，不响应点击
        sx, sy, scale = self._place
        if scale <= 0:
            return
        idx = strip_frame_at((vx - sx) / scale, (vy - sy) / scale,
                             cols=self.cols, thumb_w=self.thumb_w, thumb_h=self.thumb_h)
        if idx is not None:
            self.on_frame_click(idx)

    def _on_wheel(self, e):
        if self.src is None:
            return
        self.zoom = max(1.0, min(10.0, self.zoom * (1.2 if e.delta > 0 else 1 / 1.2)))
        if self.zoom <= 1.001:
            self.pan_x = self.pan_y = 0
        self._schedule()


class LightTablePanel(tk.Frame):
    """观片台 + 右侧观片器栏 + 开灯开关。

    工作区和图库的灯箱窗口共用这一套。
    开灯状态通过 get_light() / set_light() 跟外面同步（外面存着，换页面也不熄）。
    """

    def __init__(self, master, get_light, set_light, on_frame_click=None,
                 loupe_dim=None, **kw):
        super().__init__(master, bg=theme.BG, **kw)
        self.get_light = get_light
        self.put_light = set_light
        self._mag_buttons: dict[int, tk.Button] = {}

        self.table = LightTable(self, on_light=self._on_light,
                                on_frame_click=on_frame_click)
        if loupe_dim is not None:
            self.table.loupe_dim = float(loupe_dim)
        self.table.pack(side="left", fill="both", expand=True)

        side = tk.Frame(self, bg=theme.PANEL, width=126)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)

        tk.Label(side, text="观片器", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.FONT_UI).pack(pady=(14, 8))
        for mag in sorted(MAGS):
            b = theme.button(side, f"{mag}×", lambda m=mag: self.pick_loupe(m), kind="ghost")
            b.pack(fill="x", padx=12, pady=3)
            self._mag_buttons[mag] = b

        theme.rule(side, theme.BORDER).pack(fill="x", padx=12, pady=12)
        theme.button(side, "收起", self.clear_loupe, size="sm").pack(fill="x", padx=12)

        self.btn_light = theme.button(side, "开灯", self.toggle_light, kind="accent")
        self.btn_light.pack(side="bottom", fill="x", padx=12, pady=14)

        self.sync_light()
        self.table.set_light(self.get_light())

    # ---------- 开灯 ----------
    def _on_light(self, on: bool):
        self.put_light(on)
        self.sync_light()

    def sync_light(self):
        on = self.get_light()
        self.btn_light.configure(text="关灯" if on else "开灯",
                                 bg=theme.ACCENT if on else theme.FIELD,
                                 fg=theme.ACCENT_FG if on else theme.TEXT)

    def toggle_light(self):
        self.table.toggle_light()

    # ---------- 观片器 ----------
    def pick_loupe(self, mag: int):
        if self.table.loupe_mag == mag:          # 再点一次同一个 → 收起
            self.table.clear_loupe()
        else:
            self.table.set_loupe(mag)
        self.sync_mags()

    def clear_loupe(self):
        self.table.clear_loupe()
        self.sync_mags()

    def sync_mags(self):
        cur = self.table.loupe_mag
        for mag, b in self._mag_buttons.items():
            on = (mag == cur)
            b.configure(bg=theme.ACCENT if on else theme.PANEL,
                        fg=theme.ACCENT_FG if on else theme.TEXT,
                        activebackground=theme.ACCENT_DK if on else theme.SEL)
