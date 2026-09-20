"""胶卷图库：把所有项目生成过的胶卷图汇总成一面墙，点开进全屏灯箱看。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

import strip as strip_mod
import theme
from lighttable import LightTablePanel
from photoview import show_photo_window
from project import Project, list_projects, strip_files_for

CARD_W, CARD_H = 300, 182
GAP = 22
PAD = 28
STRIP_BG = (20, 20, 20)


def scan_strips(base_dir, strips_root: str = "") -> list[dict]:
    """扫出所有项目里生成过的胶卷图。

    返回 [{project, root, thumbs, sort_mode, photos_per_row, index, total, path}, ...]
    —— sort_mode 是生成时用的排序，点画幅反查照片要用。
    """
    out = []
    for root in list_projects(base_dir):
        try:
            p = Project.load(root)
        except Exception:
            continue
        files = strip_files_for(p, strips_root)
        for i, f in enumerate(files, 1):
            out.append({"project": p.name, "root": root, "thumbs": p.thumbs_dir,
                        "sort_mode": p.last_sort_mode,
                        "photos_per_row": p.photos_per_row,
                        "index": i, "total": len(files), "path": f})
    return out


def _bind_recursive(widget, seq, fn):
    # 按钮自己有点击行为，别给它绑卡片那套
    if not isinstance(widget, tk.Button):
        widget.bind(seq, fn)
    for child in widget.winfo_children():
        _bind_recursive(child, seq, fn)


class GalleryPage(tk.Frame):
    """一面胶卷图墙。"""

    def __init__(self, master, config, app, on_open_project=None):
        super().__init__(master, bg=theme.BG)
        self.config = config
        self.app = app
        self.on_open_project = on_open_project

        self.items: list[dict] = []
        self._photos: list = []          # 保持 PhotoImage 引用
        self._cards: list[tk.Widget] = []
        self._cols = 0
        self._job = None

        self._build()
        self.refresh()

    # ---------------- 界面 ----------------
    def _build(self):
        head = tk.Frame(self, bg=theme.BG)
        head.pack(side="top", fill="x", padx=PAD, pady=(24, 0))
        tk.Label(head, text="胶卷图库", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_H1).pack(side="left")
        self.lbl_count = tk.Label(head, text="", bg=theme.BG, fg=theme.DIM,
                                  font=theme.FONT_UI)
        self.lbl_count.pack(side="left", padx=14)
        theme.button(head, "刷新", self.refresh, kind="ghost", size="sm").pack(side="right")
        theme.button(head, "全部导出…", self.export_all, size="sm").pack(
            side="right", padx=(0, 8))

        theme.rule(self, theme.BORDER).pack(side="top", fill="x", padx=PAD, pady=(14, 0))

        holder = tk.Frame(self, bg=theme.BG)
        holder.pack(side="top", fill="both", expand=True, padx=(PAD, 0), pady=(GAP, PAD))
        sb = tk.Scrollbar(holder, orient="vertical", bd=0, relief="flat",
                          bg=theme.PANEL, troughcolor=theme.BG, width=12)
        self.canvas = tk.Canvas(holder, bg=theme.BG, highlightthickness=0,
                                yscrollincrement=28, yscrollcommand=sb.set)
        sb.configure(command=self.canvas.yview)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg=theme.BG)
        self._win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _on_resize(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        cols = max(1, (e.width - GAP) // (CARD_W + GAP + 6))
        if cols != self._cols:
            self._cols = cols
            if self._job:
                self.after_cancel(self._job)
            self._job = self.after(80, self._layout)

    # ---------------- 数据 ----------------
    def refresh(self):
        self.items = scan_strips(self.config.base_dir, self.config.strips_root)
        n_proj = len({it["project"] for it in self.items})
        self.lbl_count.configure(
            text=f"共 {len(self.items)} 卷　·　{n_proj} 个项目" if self.items
            else "还没有生成过胶卷图")
        self._layout()

    def _layout(self):
        self._job = None
        for c in self._cards:
            c.destroy()
        self._cards.clear()
        self._photos.clear()

        if not self.items:
            empty = tk.Frame(self.grid_frame, bg=theme.BG)
            empty.grid(row=0, column=0, sticky="nw")
            tk.Label(empty, text="还没有胶卷图\n\n进项目里点「生成胶卷图」，这里就会汇总出来",
                     bg=theme.BG, fg=theme.FAINT, font=theme.FONT_UI,
                     justify="left").pack(pady=40)
            self._cards.append(empty)
            return

        cols = max(1, self._cols or 4)
        for i, it in enumerate(self.items):
            r, c = divmod(i, cols)
            card = self._card(it)
            card.grid(row=r, column=c, padx=(0, GAP), pady=(0, GAP), sticky="nw")
            self._cards.append(card)

        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _card(self, it: dict):
        shadow = tk.Frame(self.grid_frame, bg=theme.SHADOW)
        inner = tk.Frame(shadow, bg=theme.FIELD, highlightthickness=1,
                         highlightbackground=theme.BORDER)
        inner.pack(padx=(0, 3), pady=(0, 3))

        body = tk.Frame(inner, bg=theme.FIELD, width=CARD_W)
        body.pack()

        cover = strip_mod.cover_thumb(it["path"], it["thumbs"], (CARD_W, CARD_H), STRIP_BG)
        if cover is not None:
            photo = ImageTk.PhotoImage(cover)
            self._photos.append(photo)
            tk.Label(body, image=photo, bg=theme.FIELD, bd=0).pack()
        else:
            ph = tk.Frame(body, bg=theme.rgb_to_hex(STRIP_BG), width=CARD_W, height=CARD_H)
            ph.pack_propagate(False)
            ph.pack()
            tk.Label(ph, text="读不出来", bg=theme.rgb_to_hex(STRIP_BG),
                     fg="#6d675e", font=theme.FONT_UI).pack(expand=True)

        foot = tk.Frame(body, bg=theme.FIELD)
        foot.pack(fill="x", padx=14, pady=11)
        left = tk.Frame(foot, bg=theme.FIELD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=it["project"], bg=theme.FIELD, fg=theme.TEXT,
                 font=theme.FONT_TITLE, anchor="w").pack(fill="x")
        tk.Label(left, text=f"第 {it['index']} / {it['total']} 卷", bg=theme.FIELD,
                 fg=theme.DIM, font=theme.FONT_SM, anchor="w").pack(fill="x", pady=(2, 0))

        if self.on_open_project is not None:
            theme.button(foot, "去项目",
                         lambda r=it["root"]: self.on_open_project(r),
                         kind="ghost", size="sm").pack(side="right")

        _bind_recursive(shadow, "<Button-1>",
                        lambda e, i=self.items.index(it): self.open_box(i))
        shadow.configure(cursor="hand2")
        return shadow

    # ---------------- 打开灯箱 / 导出 ----------------
    def open_box(self, index: int):
        LightBoxWindow(self, self.items, index, self.app,
                       loupe_dim=self.config.loupe_dim)

    def export_all(self):
        from exporter import all_jobs, batch_export
        batch_export(self, self.app,
                     lambda sub: all_jobs(self.config.base_dir, sub,
                                          self.config.strips_root),
                     "批量导出全部胶卷图")


class LightBoxWindow(tk.Toplevel):
    """全屏灯箱：把工作区右边那套观片台搬进独立窗口，方便一张张翻着看。"""

    def __init__(self, master, items: list[dict], index: int, app,
                 loupe_dim=None):
        super().__init__(master)
        self.items = items
        self.index = max(0, min(index, len(items) - 1))
        self.app = app
        self.loupe_dim = loupe_dim

        self.title("灯箱 · 胶卷图库")
        self.configure(bg=theme.BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = int(sw * 0.86), int(sh * 0.88)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(900, 620)

        self._build()
        self.show_current()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Left>", lambda e: self.goto(-1))
        self.bind("<Right>", lambda e: self.goto(1))
        self.bind("<F5>", lambda e: self.panel.toggle_light())
        self.focus_force()

    def _build(self):
        bar = tk.Frame(self, bg=theme.PANEL, height=54)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        self.lbl_title = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.TEXT,
                                  font=theme.FONT_TITLE)
        self.lbl_title.pack(side="left", padx=(16, 12))
        self.lbl_page = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.ACCENT,
                                 font=theme.FONT_UI)
        self.lbl_page.pack(side="left")

        theme.button(bar, "关闭", self.destroy, kind="ghost").pack(
            side="right", padx=(6, 14), pady=10)
        theme.button(bar, "导出这张", self.export, kind="accent").pack(
            side="right", padx=6, pady=10)
        theme.button(bar, "▶", lambda: self.goto(1)).pack(side="right", padx=(4, 0), pady=10)
        theme.button(bar, "◀", lambda: self.goto(-1)).pack(side="right", padx=(0, 4), pady=10)

        self.panel = LightTablePanel(self, self.app._get_light, self.app._set_light,
                                     on_frame_click=self._on_frame_click,
                                     loupe_dim=self.loupe_dim)
        self.panel.pack(side="top", fill="both", expand=True, padx=14, pady=14)

    def _on_frame_click(self, idx: int):
        """点了灯箱上某一格 → 打开那张照片的原图。"""
        it = self.items[self.index]
        try:
            p = Project.load(it["root"])
        except Exception:
            return
        chunks = p.strip_chunks(it.get("sort_mode") or "added")
        if self.index >= len(chunks) or idx >= len(chunks[self.index]):
            return
        show_photo_window(self, chunks[self.index][idx], p)

    def show_current(self):
        it = self.items[self.index]
        self.lbl_title.configure(text=it["project"])
        self.lbl_page.configure(text=f"第 {it['index']} / {it['total']} 卷")
        self.panel.table.set_image(it["path"],
                                   cols=it.get("photos_per_row") or 8)
        self.title(f"灯箱 · {it['project']} 第 {it['index']}/{it['total']} 卷")

    def goto(self, delta: int):
        self.index = (self.index + delta) % len(self.items)
        self.show_current()

    def export(self):
        src = self.items[self.index]["path"]
        dest = filedialog.asksaveasfilename(
            parent=self, title="导出胶卷图", defaultextension=".jpg",
            initialfile=Path(src).name,
            filetypes=[("JPEG 图片", "*.jpg"), ("PNG 图片", "*.png")])
        if not dest:
            return
        try:
            with Image.open(src) as im:
                if Path(dest).suffix.lower() == ".png":
                    im.save(dest, "PNG")
                else:
                    im.save(dest, "JPEG", quality=95, subsampling=0)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
