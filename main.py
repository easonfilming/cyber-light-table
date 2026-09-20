"""赛博观片台 —— 主程序。

运行：  python main.py

左边是常驻侧边栏（项目 / 暗盒 / 图库 / 设置），右边是当前页面。
进项目后左边挑照片，右边是观片台 —— 开灯才看得见照片，还能拿观片器凑近看细节。
"""
from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageOps, ImageTk

import canister as canister_mod
import effects as effects_mod
import strip as strip_mod
import theme
from appconfig import AppConfig
from designer import CanisterDesigner
from exporter import batch_export, project_jobs
from gallery import GalleryPage
from home import HomePage
from lighttable import LightTablePanel
from photoview import show_photo_window
from project import (SUPPORTED_EXTS, Project, rename_project, strip_files_for,
                     strips_write_dir)
from settings_page import SettingsPage

# 显示方式：界面文字 → strip.make_thumb 的模式名
FIT_LABELS = {"rotate": "竖图转90°", "contain": "完整显示", "cover": "填满画幅"}
FIT_MODES = {v: k for k, v in FIT_LABELS.items()}

SORT_LABELS = {"added": "导入顺序", "filename": "文件名", "taken": "拍摄时间"}
SORT_KEYS = {v: k for k, v in SORT_LABELS.items()}

# 侧边栏：(页面 key, 显示名)
PAGES = [("projects", "项目"), ("canister", "暗盒"),
         ("gallery", "图库"), ("settings", "设置")]


# ======================================================================
# 左侧常驻导航栏
# ======================================================================
class NavRail(tk.Frame):
    """左边那一条。选中项有强调色左边条 + 高亮底色。"""

    def __init__(self, master, on_pick, **kw):
        super().__init__(master, bg=theme.PANEL, width=96, **kw)
        self.pack_propagate(False)
        self.on_pick = on_pick
        self._items: dict[str, dict] = {}

        tk.Label(self, text="赛博", bg=theme.PANEL, fg=theme.ACCENT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(22, 2))
        tk.Label(self, text="观片台", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.FONT_SM).pack(pady=(0, 20))

        for key, label in PAGES:
            self._items[key] = self._make_item(key, label)

    def _make_item(self, key: str, label: str) -> dict:
        row = tk.Frame(self, bg=theme.PANEL, height=48)
        row.pack(fill="x")
        row.pack_propagate(False)
        bar = tk.Frame(row, bg=theme.PANEL, width=3)
        bar.pack(side="left", fill="y")
        txt = tk.Label(row, text=label, bg=theme.PANEL, fg=theme.TEXT,
                       font=theme.FONT_UI)
        txt.pack(side="left", padx=(15, 0))
        for w in (row, txt, bar):
            w.bind("<Button-1>", lambda e, k=key: self.on_pick(k))
            w.configure(cursor="hand2")
        return {"row": row, "bar": bar, "txt": txt}

    def select(self, key: str):
        for k, it in self._items.items():
            on = (k == key)
            bg = theme.SEL if on else theme.PANEL
            it["row"].configure(bg=bg)
            it["txt"].configure(bg=bg, fg=theme.ACCENT if on else theme.TEXT)
            it["bar"].configure(bg=theme.ACCENT if on else theme.PANEL)


# ======================================================================
# 照片网格
# ======================================================================
class PhotoGrid(tk.Canvas):
    """照片网格：缩略图 + 序号，支持多选、双击看大图、拖动排序。"""

    CELL_W, CELL_H = 106, 96
    THUMB_W, THUMB_H = 106, 71
    GAP = 8
    BATCH = 16          # 每批载入多少张缩略图，避免卡界面

    def __init__(self, master, on_select=None, on_open=None, on_reorder=None,
                 on_move=None, on_delete=None, **kw):
        super().__init__(master, bg=theme.PANEL, highlightthickness=0,
                         yscrollincrement=24, **kw)
        self.on_select = on_select
        self.on_open = on_open
        self.on_reorder = on_reorder
        self.on_move = on_move            # 移到最前(-1) / 移到最后(1)
        self.on_delete = on_delete

        self.photos: list = []
        self.thumbs: dict = {}
        self.selected: set[str] = set()
        self.anchor: str | None = None    # 上次点的那张，Shift 连选要用
        self.fit_mode = "rotate"
        self._layout: list[tuple[str, int, int, int]] = []
        self._pending: list = []
        self._press = None

        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<Button-3>", self._on_right)
        self.bind("<MouseWheel>", lambda e: self.yview_scroll(int(-e.delta / 120), "units"))

    # ---------- 数据 ----------
    def set_photos(self, photos, root: Path, cache_dir: Path):
        self.photos = list(photos)
        self.thumbs = {}
        self.selected &= {p.id for p in self.photos}
        self._pending = [(p, p.path(root), cache_dir) for p in self.photos]
        self.redraw()
        self._load_batch()

    def _load_batch(self):
        for _ in range(self.BATCH):
            if not self._pending:
                return
            p, path, cache = self._pending.pop(0)
            try:
                im = strip_mod.make_thumb(path, cache, (self.THUMB_W, self.THUMB_H),
                                          self.fit_mode)
                self.thumbs[p.id] = ImageTk.PhotoImage(im)
            except Exception:
                self.thumbs[p.id] = None
        self.redraw()
        if self._pending:
            self.after(1, self._load_batch)

    def _columns(self) -> int:
        w = max(self.winfo_width(), 240)
        return max(1, (w - self.GAP) // (self.CELL_W + self.GAP))

    def redraw(self):
        self.delete("all")
        self._layout = []
        cols = self._columns()

        for i, p in enumerate(self.photos):
            r, c = divmod(i, cols)
            x = self.GAP + c * (self.CELL_W + self.GAP)
            y = self.GAP + r * (self.CELL_H + self.GAP)
            self._layout.append((p.id, x, y, i))

            sel = p.id in self.selected
            self.create_rectangle(x - 3, y - 3, x + self.CELL_W + 3, y + self.CELL_H + 3,
                                  fill=theme.SEL if sel else theme.FIELD,
                                  outline=theme.ACCENT if sel else theme.BORDER, width=2)

            img = self.thumbs.get(p.id)
            if img is not None:
                self.create_image(x + self.CELL_W // 2, y + self.THUMB_H // 2,
                                  image=img, anchor="center")
            else:
                self.create_rectangle(x, y, x + self.CELL_W, y + self.THUMB_H,
                                      fill=theme.PANEL, outline="")
                self.create_text(x + self.CELL_W // 2, y + self.THUMB_H // 2,
                                 text="载入中…", fill=theme.FAINT, font=theme.FONT_SM)

            self.create_text(x + 4, y + self.THUMB_H + 13, text=f"{i + 1:03d}",
                             fill=theme.ACCENT if sel else theme.DIM,
                             anchor="w", font=theme.FONT_MONO)
            # 格子窄，只显示不带扩展名的文件名，够认就行
            self.create_text(x + self.CELL_W - 4, y + self.THUMB_H + 13,
                             text=Path(p.display_name).stem[:12], fill=theme.DIM,
                             anchor="e", font=theme.FONT_SM)

        rows = (len(self.photos) + cols - 1) // cols if self.photos else 0
        self.configure(scrollregion=(0, 0, self.winfo_width(),
                                     self.GAP + rows * (self.CELL_H + self.GAP) + self.GAP))

    # ---------- 交互 ----------
    def _hit(self, x, y):
        for pid, cx, cy, i in self._layout:
            if cx <= x <= cx + self.CELL_W and cy <= y <= cy + self.CELL_H:
                return pid, i
        return None, None

    def _on_press(self, e):
        pid, i = self._hit(self.canvasx(e.x), self.canvasy(e.y))
        self._press = (pid, i, e.x, e.y)
        if pid is None:
            if not (e.state & 0x0004):
                self.selected.clear()
                self.redraw()
                if self.on_select:
                    self.on_select([])
            return

        # Shift 连选：从上次点的那张到这张，整段选中
        if (e.state & 0x0001) and self.anchor is not None:
            ai = next((k for _pid, _x, _y, k in self._layout if _pid == self.anchor), None)
            if ai is not None:
                lo, hi = min(ai, i), max(ai, i)
                self.selected = {p.id for p in self.photos[lo:hi + 1]}
                self.redraw()
                if self.on_select:
                    self.on_select(sorted(self.selected))
                return

        self.anchor = pid
        if e.state & 0x0004:                       # Ctrl 加选
            self.selected.symmetric_difference_update({pid})
        elif pid not in self.selected:
            self.selected = {pid}
        self.redraw()
        if self.on_select:
            self.on_select(sorted(self.selected))

    # ---------- 多选 ----------
    def select_all(self):
        self.selected = {p.id for p in self.photos}
        self.redraw()
        if self.on_select:
            self.on_select(sorted(self.selected))

    def invert_selection(self):
        self.selected = {p.id for p in self.photos if p.id not in self.selected}
        self.redraw()
        if self.on_select:
            self.on_select(sorted(self.selected))

    def _on_right(self, e):
        pid, _i = self._hit(self.canvasx(e.x), self.canvasy(e.y))
        if pid and pid not in self.selected:
            self.selected = {pid}
            self.anchor = pid
            self.redraw()
            if self.on_select:
                self.on_select(sorted(self.selected))

        has = bool(self.selected)
        m = tk.Menu(self, tearoff=0, bg=theme.FIELD, fg=theme.TEXT,
                    activebackground=theme.ACCENT, activeforeground=theme.ACCENT_FG,
                    bd=0, font=theme.FONT_UI)
        m.add_command(label="全选", command=self.select_all)
        m.add_command(label="反选", command=self.invert_selection)
        m.add_separator()
        m.add_command(label="移到最前", state="normal" if has else "disabled",
                      command=lambda: self.on_move and self.on_move(-1))
        m.add_command(label="移到最后", state="normal" if has else "disabled",
                      command=lambda: self.on_move and self.on_move(1))
        m.add_separator()
        m.add_command(label="删除选中", state="normal" if has else "disabled",
                      command=lambda: self.on_delete and self.on_delete())
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _on_motion(self, e):
        if self._press and self._press[0]:
            self.yview_scroll(int((e.y - self._press[3]) / 12), "units")

    def _on_release(self, e):
        if self._press is None:
            return
        pid, i, px, py = self._press
        self._press = None
        if pid is None or (abs(e.x - px) < 10 and abs(e.y - py) < 10):
            return
        tid, ti = self._hit(self.canvasx(e.x), self.canvasy(e.y))
        if ti is not None and ti != i and self.on_reorder:
            self.on_reorder(pid, ti)

    def _on_double(self, e):
        pid, _ = self._hit(self.canvasx(e.x), self.canvasy(e.y))
        if pid and self.on_open:
            self.on_open(pid)


# ======================================================================
# 项目设置对话框
# ======================================================================
class ProjectSettingsDialog(tk.Toplevel):
    """改当前项目的每卷张数 / 每行张数 / 显示方式 / 暗盒。

    改数字时实时算出"会分成几卷、每卷几列几行"。
    """

    def __init__(self, parent, project: Project, config):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.result: dict | None = None

        self.title("项目设置")
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(padx=26, pady=20)

        tk.Label(body, text=f"项目设置 · {project.name}", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_TITLE).grid(row=0, column=0, columnspan=4, sticky="w")
        theme.rule(body, theme.BORDER).grid(row=1, column=0, columnspan=4,
                                            sticky="we", pady=(10, 16))

        self.var_per = tk.StringVar(value=str(project.photos_per_strip))
        self.var_row = tk.StringVar(value=str(project.photos_per_row))
        self._num_field(body, 2, 0, "每卷张数", self.var_per)
        self._num_field(body, 2, 2, "每行张数", self.var_row)

        self.lbl_hint = tk.Label(body, text="", bg=theme.BG, fg=theme.ACCENT,
                                 font=theme.FONT_UI, anchor="w")
        self.lbl_hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(14, 18))

        self.var_fit = tk.StringVar(
            value=FIT_LABELS.get(project.fit_mode, FIT_LABELS["rotate"]))
        tk.Label(body, text="显示方式", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=4, column=0, sticky="w", pady=4)
        theme.option_menu(body, self.var_fit, list(FIT_LABELS.values()),
                          None, width=11).grid(row=4, column=1, columnspan=3, sticky="w")

        self._choices = canister_mod.choices(config.library())
        self.var_can = tk.StringVar(
            value=canister_mod.name_of(project.canister, config.library()))
        tk.Label(body, text="暗盒", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=5, column=0, sticky="w", pady=(8, 4))
        theme.option_menu(body, self.var_can, [n for n, _c in self._choices],
                          None, width=22).grid(row=5, column=1, columnspan=3,
                                               sticky="w", pady=(8, 4))

        foot = tk.Frame(self, bg=theme.BG)
        foot.pack(fill="x", padx=26, pady=(0, 20))
        theme.button(foot, "确定", self._ok, kind="accent").pack(side="right")
        theme.button(foot, "取消", self.destroy, kind="ghost").pack(side="right", padx=(0, 8))

        for v in (self.var_per, self.var_row):
            v.trace_add("write", self._refresh_hint)
        self._refresh_hint()

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 160}+{parent.winfo_rooty() + 130}")

    def show(self):
        """弹出来等用户关掉，返回结果（取消返回 None）。"""
        self.wait_window(self)
        return self.result

    def _num_field(self, parent, r, c, label, var):
        tk.Label(parent, text=label, bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=r, column=c, sticky="w",
                                  padx=(0 if c == 0 else 26, 6))
        tk.Entry(parent, textvariable=var, bg=theme.FIELD, fg=theme.TEXT, relief="flat",
                 font=theme.FONT_UI, width=7, insertbackground=theme.TEXT,
                 highlightthickness=1, highlightbackground=theme.BORDER,
                 highlightcolor=theme.ACCENT).grid(row=r, column=c + 1, sticky="w", ipady=4)

    def _read_numbers(self):
        """读两个数字，非法返回 None。"""
        try:
            per = int(self.var_per.get())
            cols = int(self.var_row.get())
        except (TypeError, ValueError):
            return None
        return (per, cols) if per >= 1 and cols >= 1 else None

    def _refresh_hint(self, *_a):
        nums = self._read_numbers()
        if nums is None:
            self.lbl_hint.configure(text="每卷张数和每行张数都要是大于 0 的整数")
            return
        per, cols = nums
        n = len(self.project.photos)
        strips = -(-n // per) if n else 0
        rows = -(-per // cols)
        self.lbl_hint.configure(
            text=f"{n} 张会分成 {strips} 卷，每卷 {cols} 列 × {rows} 行")

    def _ok(self):
        nums = self._read_numbers()
        if nums is None:
            messagebox.showwarning("数字不对", "每卷张数和每行张数都要是大于 0 的整数。",
                                   parent=self)
            return
        per, cols = nums
        label = self.var_can.get()
        cid = next((c for n, c in self._choices if n == label), self.project.canister)
        self.result = {
            "photos_per_strip": per,
            "photos_per_row": cols,
            "fit_mode": FIT_MODES.get(self.var_fit.get(), "rotate"),
            "canister": cid,
        }
        self.destroy()


# ======================================================================
# 胶片特效对话框
# ======================================================================
FX_PREVIEW_W, FX_PREVIEW_H = 640, 210


class EffectsDialog(tk.Toplevel):
    """挑胶片特效、拖滑块调强度，上面有实时预览。强度 0 就是关掉。"""

    def __init__(self, parent, project: Project, config):
        super().__init__(parent)
        self.project = project
        self.config = config
        self.result: dict | None = None
        self.vars: dict[str, tk.IntVar] = {}
        self.labels: dict[str, tk.Label] = {}
        self._photo = None
        self._job = None
        self._busy = False

        self.title("胶片特效")
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(padx=24, pady=20)

        tk.Label(body, text=f"胶片特效 · {project.name}", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_TITLE).pack(anchor="w")
        theme.rule(body, theme.BORDER).pack(fill="x", pady=(10, 14))

        self.canvas = tk.Canvas(body, width=FX_PREVIEW_W, height=FX_PREVIEW_H,
                                bg=theme.rgb_to_hex(strip_mod.BG),
                                highlightthickness=1,
                                highlightbackground=theme.BORDER)
        self.canvas.pack()

        cur = effects_mod.normalize(project.effects)
        for key, name, desc, _default in effects_mod.EFFECTS:
            row = tk.Frame(body, bg=theme.BG)
            row.pack(fill="x", pady=(12, 0))
            # width 按字体平均字符宽算，中文是双宽 —— 3 个汉字要 width>=6 才不被截
            tk.Label(row, text=name, bg=theme.BG, fg=theme.TEXT, font=theme.FONT_UI,
                     width=7, anchor="w").pack(side="left")
            var = tk.IntVar(value=cur[key])
            self.vars[key] = var
            tk.Scale(row, from_=0, to=100, orient="horizontal", variable=var,
                     bg=theme.BG, fg=theme.TEXT, troughcolor=theme.PANEL, bd=0,
                     highlightthickness=0, showvalue=False, length=190,
                     activebackground=theme.ACCENT,
                     command=lambda _v, k=key: self._changed(k)).pack(side="left")
            lbl = tk.Label(row, text="", bg=theme.BG, fg=theme.ACCENT,
                           font=theme.FONT_SM, width=4, anchor="w")
            lbl.pack(side="left", padx=(8, 10))
            self.labels[key] = lbl
            tk.Label(row, text=desc, bg=theme.BG, fg=theme.DIM,
                     font=theme.FONT_SM, anchor="w").pack(side="left")

        tk.Label(body, text="这里只是三格的预览；改完要点「生成胶卷图」才会应用到整卷上。",
                 bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM).pack(anchor="w",
                                                                     pady=(16, 0))

        foot = tk.Frame(self, bg=theme.BG)
        foot.pack(fill="x", padx=24, pady=(0, 20))
        theme.button(foot, "确定", self._ok, kind="accent").pack(side="right")
        theme.button(foot, "取消", self.destroy, kind="ghost").pack(side="right",
                                                                   padx=(0, 8))
        theme.button(foot, "全部关掉", self._clear, kind="ghost").pack(side="left")

        self._sync_labels()
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 140}+{parent.winfo_rooty() + 90}")
        self.after(30, self.render_preview)

    # ---------- 数据 ----------
    def current(self) -> dict:
        return {k: int(v.get()) for k, v in self.vars.items()}

    def _sync_labels(self):
        for k, lbl in self.labels.items():
            v = int(self.vars[k].get())
            lbl.configure(text="关" if v <= 0 else str(v),
                          fg=theme.DIM if v <= 0 else theme.ACCENT)

    def _changed(self, key):
        # 互斥的效果（乐凯红 / 乐凯绿）：开了这个就把那个清零。
        # 改动会再触发一次回调，所以用 _busy 挡一下，别递归。
        if not self._busy:
            self._busy = True
            try:
                for k, v in effects_mod.exclusive_fix(self.current(), key).items():
                    if int(self.vars[k].get()) != v:
                        self.vars[k].set(v)
            finally:
                self._busy = False
        self._sync_labels()
        self._schedule()

    def _clear(self):
        for v in self.vars.values():
            v.set(0)
        self._sync_labels()
        self._schedule()

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(350, self.render_preview)

    # ---------- 预览 ----------
    def render_preview(self):
        self._job = None
        photos = self.project.sorted_photos("added")[:3]
        if not photos:
            self.canvas.delete("all")
            self.canvas.create_text(FX_PREVIEW_W // 2, FX_PREVIEW_H // 2,
                                    text="项目里还没有照片", fill=theme.FAINT,
                                    font=theme.FONT_UI)
            return
        try:
            img = strip_mod.render_strip(
                [p.path(self.project.root) for p in photos],
                cols=3, cache_dir=self.project.thumbs_dir,
                fit_mode=self.project.fit_mode,
                canister=self.project.canister,
                canister_custom=self.project.canister_custom,
                canister_library=self.config.library(),
                effects=self.current())
        except Exception:
            return
        # 只留胶片那一条，把上面的暗盒带裁掉
        top = strip_mod.HEADER_H + strip_mod.MARGIN
        row_h = strip_mod.PERF_H * 2 + strip_mod.FRAME_PAD_V * 2 + strip_mod.DEFAULT_THUMB_H
        img = img.crop((0, max(0, top - 6), img.width, min(img.height, top + row_h + 6)))
        inner = ImageOps.contain(img, (FX_PREVIEW_W, FX_PREVIEW_H),
                                 Image.Resampling.LANCZOS)
        view = Image.new("RGB", (FX_PREVIEW_W, FX_PREVIEW_H), strip_mod.BG)
        view.paste(inner, ((FX_PREVIEW_W - inner.width) // 2,
                           (FX_PREVIEW_H - inner.height) // 2))
        self._photo = ImageTk.PhotoImage(view)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    # ---------- 收尾 ----------
    def _ok(self):
        self.result = self.current()
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


# ======================================================================
# 工作区
# ======================================================================
class Workspace(tk.Frame):
    """单个项目的工作区：左边照片网格，右边观片台 + 观片器。"""

    def __init__(self, master, app, project: Project):
        super().__init__(master, bg=theme.BG)
        self.app = app
        self.project = project
        self.sort_mode = "added"
        self.strip_files: list[Path] = []
        self.preview_index = 0
        self._choices: list[tuple[str, str]] = []

        self._build()
        self.reload_photos()
        self.reload_strips()

    # ---------------- 界面 ----------------
    def _build(self):
        self._build_toolbar()

        panes = tk.PanedWindow(self, orient="horizontal", bg=theme.BORDER,
                               sashwidth=5, bd=0, relief="flat")
        panes.pack(fill="both", expand=True)

        left = tk.Frame(panes, bg=theme.PANEL)
        right = tk.Frame(panes, bg=theme.BG)
        # 左栏窄一点固定住，窗口变大时多出来的空间全给观片台
        panes.add(left, width=360, minsize=300, stretch="never")
        panes.add(right, minsize=640, stretch="always")

        self._build_photos(left)
        self._build_preview(right)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=theme.PANEL, height=54)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        tk.Label(bar, text=self.project.name, bg=theme.PANEL, fg=theme.TEXT,
                 font=theme.FONT_TITLE).pack(side="left", padx=(16, 0))
        tk.Label(bar, text=f"{self.project.photos_per_strip} 张/卷", bg=theme.PANEL,
                 fg=theme.DIM, font=theme.FONT_SM).pack(side="left", padx=10)

        theme.button(bar, "生成胶卷图", self.generate, kind="accent").pack(
            side="left", padx=(20, 6), pady=10)
        self.app.register(theme.button(bar, "添加照片", self.add_photos)).pack(
            side="left", padx=6, pady=10)
        self.app.register(theme.button(bar, "删除选中", self.delete_selected)).pack(
            side="left", padx=6, pady=10)
        theme.button(bar, "项目设置…", self.open_project_settings, kind="ghost").pack(
            side="left", padx=6, pady=10)
        self.btn_fx = theme.button(bar, "胶片特效…", self.open_effects, kind="ghost")
        self.btn_fx.pack(side="left", padx=6, pady=10)
        self._sync_fx_button()

        # 暗盒下拉框：内置 + 保存的 + 去设计
        self.var_canister = tk.StringVar()
        self.om_canister = theme.option_menu(bar, self.var_canister, ["—"],
                                             None, width=20)
        self.om_canister.pack(side="right", padx=(0, 12))
        tk.Label(bar, text="暗盒", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.FONT_SM).pack(side="right", padx=(0, 6))
        self._reload_canister_menu()

    def _build_photos(self, parent):
        bar = tk.Frame(parent, bg=theme.PANEL)
        bar.pack(fill="x", padx=10, pady=(8, 4))
        # 这一栏窄，标签能省就省
        self.lbl_count = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.ACCENT,
                                  font=theme.FONT_SM)
        self.lbl_count.pack(side="left")

        self.var_fit = tk.StringVar(value=FIT_LABELS[self.project.fit_mode])
        theme.option_menu(bar, self.var_fit, list(FIT_LABELS.values()),
                          self._on_fit, width=9).pack(side="right")
        tk.Label(bar, text="显示", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.FONT_SM).pack(side="right", padx=(0, 4))

        self.var_sort = tk.StringVar(value=SORT_LABELS["added"])
        theme.option_menu(bar, self.var_sort, list(SORT_LABELS.values()),
                          self._on_sort, width=8).pack(side="right", padx=(0, 10))
        tk.Label(bar, text="排序", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.FONT_SM).pack(side="right", padx=(0, 4))

        holder = tk.Frame(parent, bg=theme.PANEL)
        holder.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        sb = tk.Scrollbar(holder, orient="vertical", bd=0, relief="flat",
                          bg=theme.FIELD, troughcolor=theme.PANEL, width=12)
        self.grid = PhotoGrid(holder, on_select=self._on_select,
                              on_open=self.show_photo, on_reorder=self._on_reorder,
                              on_move=self._on_move, on_delete=self.delete_selected,
                              yscrollcommand=sb.set)
        sb.configure(command=self.grid.yview)
        sb.pack(side="right", fill="y")
        self.grid.pack(side="left", fill="both", expand=True)
        self.grid.fit_mode = self.project.fit_mode

    def _build_preview(self, parent):
        bar = tk.Frame(parent, bg=theme.BG)
        bar.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(bar, text="观片台", bg=theme.BG, fg=theme.DIM,
                 font=theme.FONT_UI).pack(side="left")
        self.lbl_page = tk.Label(bar, text="", bg=theme.BG, fg=theme.ACCENT,
                                 font=theme.FONT_UI)
        self.lbl_page.pack(side="left", padx=10)

        theme.button(bar, "导出当前卷", self.export_current, size="sm").pack(
            side="right", padx=(6, 0))
        theme.button(bar, "批量导出…", self.export_all, kind="ghost",
                     size="sm").pack(side="right", padx=(0, 6))
        theme.button(bar, "输出文件夹", self.open_output_folder, kind="ghost",
                     size="sm").pack(side="right", padx=(0, 6))
        theme.button(bar, "▶", lambda: self.goto_strip(1), size="sm").pack(
            side="right", padx=(4, 0))
        theme.button(bar, "◀", lambda: self.goto_strip(-1), size="sm").pack(
            side="right", padx=(0, 4))

        self.panel = LightTablePanel(parent, self._get_light, self._set_light,
                                     on_frame_click=self._on_frame_click,
                                     loupe_dim=self.app.config_data.loupe_dim)
        self.panel.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.table = self.panel.table          # 方便直接调

    # ---------------- 开灯状态（存在 App 上，换页面也不熄）----------------
    def _get_light(self) -> bool:
        return self.app.light_on

    def _set_light(self, on: bool):
        self.app.light_on = on

    # ---------------- 照片 ----------------
    def reload_photos(self):
        p = self.project
        photos = p.sorted_photos(self.sort_mode)
        self.grid.set_photos(photos, p.root, p.thumbs_dir)
        n, per = len(photos), max(1, p.photos_per_strip)
        self.lbl_count.configure(
            text=f"{n} 张 · {(n + per - 1) // per} 卷" if n else "还没有照片")

    def _on_sort(self, label):
        self.sort_mode = SORT_KEYS[label]
        self.reload_photos()

    def _on_fit(self, label):
        mode = FIT_MODES[label]
        self.grid.fit_mode = mode
        self.project.fit_mode = mode
        self.project.save()
        self.reload_photos()
        if self.strip_files:
            self.app.set_status("显示方式已改 —— 重新点「生成胶卷图」才会应用到胶卷图上")

    def _on_select(self, ids):
        self.app.set_status(f"已选中 {len(ids)} 张" if ids else "就绪")

    def _on_reorder(self, pid, new_index):
        if self.project.move_photo(pid, new_index):
            self.sort_mode = "added"
            self.var_sort.set(SORT_LABELS["added"])
            self.reload_photos()
            self.app.set_status("顺序已调整")

    def add_photos(self):
        files = filedialog.askopenfilenames(
            title="选择照片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("所有文件", "*.*")])
        if files:
            self.add_photos_from(list(files))

    def add_photos_from(self, files):
        """把一组文件导入当前项目。从资源管理器拖进来的也走这里。"""
        files = [f for f in files if f]
        if not files:
            return
        p = self.project

        def work(progress):
            return p.add_photos(files, progress_cb=progress)

        def done(result):
            added, skipped = result
            self.reload_photos()
            self.app.set_status(f"导入完成：新增 {added} 张，跳过 {skipped} 张")
            if skipped:
                messagebox.showinfo(
                    "导入完成",
                    f"新增 {added} 张，跳过 {skipped} 张。\n\n"
                    f"跳过的是：不支持的文件格式，或者之前已经导入过的同一张照片。")

        self.app.run_bg(work, done, busy_text="正在导入照片…")

    def delete_selected(self):
        ids = sorted(self.grid.selected)
        if not ids:
            return
        if not messagebox.askyesno("确认删除",
                                   f"从项目里删掉这 {len(ids)} 张照片？\n\n"
                                   f"（会同时删掉项目里复制的那份，原始文件不受影响）"):
            return
        n = self.project.remove_photos(ids)
        self.grid.selected.clear()
        self.reload_photos()
        self.app.set_status(f"已删除 {n} 张")

    def show_photo(self, pid):
        photo = next((x for x in self.project.photos if x.id == pid), None)
        if photo is not None:
            show_photo_window(self, photo, self.project)

    # ---------------- 项目设置 / 批量导出 / 移到最前最后 ----------------
    def open_project_settings(self):
        dlg = ProjectSettingsDialog(self, self.project, self.app.config_data)
        result = dlg.show()
        if not result:
            return
        p = self.project
        p.photos_per_strip = result["photos_per_strip"]
        p.photos_per_row = result["photos_per_row"]
        p.fit_mode = result["fit_mode"]
        p.canister = result["canister"]
        p.save()
        self.var_fit.set(FIT_LABELS.get(p.fit_mode, FIT_LABELS["rotate"]))
        self.grid.fit_mode = p.fit_mode
        self._reload_canister_menu()
        self.reload_photos()
        self.app.set_status("项目设置已保存 —— 重新生成胶卷图才会应用到胶卷图上")

    def open_effects(self):
        dlg = EffectsDialog(self, self.project, self.app.config_data)
        result = dlg.show()
        if result is None:
            return
        self.project.effects = result
        self.project.save()
        self._sync_fx_button()
        on = [n for k, n, *_ in effects_mod.EFFECTS if result.get(k, 0) > 0]
        self.app.set_status(
            ("胶片特效已设为：" + "、".join(on) + " —— 重新生成才会应用")
            if on else "胶片特效已全部关掉")

    def _sync_fx_button(self):
        on = [n for k, n, *_ in effects_mod.EFFECTS
              if effects_mod.normalize(self.project.effects).get(k, 0) > 0]
        self.btn_fx.configure(text="胶片特效…" if not on
                              else f"胶片特效：{'、'.join(on)}")

    def export_all(self):
        batch_export(self, self.app,
                     lambda _sub: project_jobs(self.project, False,
                                               self.app.config_data.strips_root),
                     f"批量导出 · {self.project.name}", allow_subfolder=False)

    def _on_move(self, where: int):
        """where: -1 移到最前，1 移到最后。按原来的先后顺序保持相对次序。"""
        ids = [p.id for p in self.project.photos if p.id in self.grid.selected]
        if not ids:
            return
        last = len(self.project.photos) - 1
        # 移到最前要倒着搬，移到最后要正着搬，这样选中这几张的先后顺序不变
        for pid in (list(reversed(ids)) if where < 0 else ids):
            self.project.move_photo(pid, 0 if where < 0 else last, save=False)
        self.project.save()          # 一批搬完统一存一次，别一张一存
        self.sort_mode = "added"
        self.var_sort.set(SORT_LABELS["added"])
        self.reload_photos()
        self.app.set_status(f"已把 {len(ids)} 张移到{'最前' if where < 0 else '最后'}")

    def _on_frame_click(self, idx: int):
        """点了观片台上某一格 → 打开那张照片的原图。"""
        chunks = self.project.strip_chunks(self.project.last_sort_mode or "added")
        if self.preview_index >= len(chunks):
            return
        chunk = chunks[self.preview_index]
        if idx >= len(chunk):
            return
        show_photo_window(self, chunk[idx], self.project)

    # ---------------- 暗盒 ----------------
    def _reload_canister_menu(self):
        lib = self.app.config_data.library()
        self._choices = canister_mod.choices(lib)
        menu = self.om_canister["menu"]
        menu.delete(0, "end")
        for name, cid in self._choices:
            menu.add_command(label=name, command=lambda c=cid: self._on_canister(c))
        menu.add_separator()
        menu.add_command(label="去设计暗盒…", command=self._goto_designer)
        self.var_canister.set(canister_mod.name_of(self.project.canister, lib))

    def _on_canister(self, cid: str):
        self.project.canister = cid
        self.project.save()
        self.var_canister.set(canister_mod.name_of(cid, self.app.config_data.library()))
        self.app.set_status(f"暗盒已设为「{self.var_canister.get()}」"
                            f"—— 重新生成才会应用")

    def _goto_designer(self):
        self.app.show_page("canister")

    # ---------------- 胶卷图 ----------------
    def reload_strips(self):
        self.strip_files = strip_files_for(self.project,
                                           self.app.config_data.strips_root)
        self.preview_index = 0
        self.show_current_strip()

    def show_current_strip(self):
        n = len(self.strip_files)
        if n == 0:
            self.lbl_page.configure(text="")
            self.table.set_image(None)
            return
        self.preview_index = max(0, min(self.preview_index, n - 1))
        self.lbl_page.configure(text=f"第 {self.preview_index + 1} / {n} 卷")
        self.table.set_image(self.strip_files[self.preview_index],
                             cols=self.project.photos_per_row)

    def goto_strip(self, delta):
        if not self.strip_files:
            return
        self.preview_index = (self.preview_index + delta) % len(self.strip_files)
        self.show_current_strip()

    def generate(self):
        p = self.project
        if not p.photos:
            messagebox.showinfo("提示", "先给项目添加照片吧")
            return

        sort_mode = self.sort_mode
        chunks = p.strip_chunks(sort_mode)
        cols = max(1, p.photos_per_row)
        per = max(1, p.photos_per_strip)
        fit = p.fit_mode
        canister = p.canister
        custom = dict(p.canister_custom)
        fx = dict(p.effects)
        library = self.app.config_data.library()
        total = len(chunks)
        root, name = p.root, p.name
        strips_dir = strips_write_dir(p, self.app.config_data.strips_root)
        thumbs_dir = p.thumbs_dir

        def work(progress):
            strips_dir.mkdir(parents=True, exist_ok=True)
            for old in strips_dir.glob("strip_*.jpg"):
                try:
                    old.unlink()
                except Exception:
                    pass

            files = []
            for i, chunk in enumerate(chunks, 1):
                progress(f"正在生成第 {i}/{total} 卷（{len(chunk)} 张）…")

                def cb(done, count, _i=i):
                    if done % 8 == 0 or done == count:
                        progress(f"正在渲染第 {_i}/{total} 卷　·　{done}/{count} 张")

                img = strip_mod.render_strip(
                    [x.path(root) for x in chunk],
                    start_number=(i - 1) * per + 1,
                    cols=cols, project_name=name,
                    strip_index=i, strip_total=total,
                    cache_dir=thumbs_dir, fit_mode=fit,
                    canister=canister, canister_custom=custom,
                    canister_library=library,
                    effects=fx,
                    progress_cb=cb)
                f = strips_dir / f"strip_{i:03d}.jpg"
                img.save(f, "JPEG", quality=92, subsampling=0)
                files.append(f)
            return files

        def done(files):
            p.strips = [f"strips/{f.name}" for f in files]
            p.last_sort_mode = sort_mode     # 记下这次用的排序，点画幅反查照片要用
            p.save()
            self.reload_strips()
            self.app.set_status(f"完成！生成了 {len(files)} 卷，存在 {strips_dir}")

        self.app.run_bg(work, done, busy_text="准备生成胶卷图…")

    def export_current(self):
        if not self.strip_files:
            messagebox.showinfo("提示", "还没有生成胶卷图")
            return
        src = self.strip_files[self.preview_index]
        dest = filedialog.asksaveasfilename(
            title="导出胶卷图", defaultextension=".jpg", initialfile=src.name,
            filetypes=[("JPEG 图片", "*.jpg"), ("PNG 图片", "*.png")])
        if not dest:
            return
        try:
            with Image.open(src) as im:
                if Path(dest).suffix.lower() == ".png":
                    im.save(dest, "PNG")
                else:
                    im.save(dest, "JPEG", quality=95, subsampling=0)
            self.app.set_status(f"已导出到 {dest}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def open_output_folder(self):
        d = strips_write_dir(self.project, self.app.config_data.strips_root)
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))


# ======================================================================
# 主窗口
# ======================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("赛博观片台")
        self.geometry("1640x980")
        self.minsize(1240, 760)
        self.configure(bg=theme.BG)

        self.config_data = AppConfig()
        self.project: Project | None = None
        self.workspace: Workspace | None = None
        self.light_on = False               # 开灯状态常驻，换页面也不熄

        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._buttons: list[tk.Button] = []
        self._pages: dict[str, tk.Frame] = {}

        self.lbl_status = tk.Label(self, text="就绪", bg=theme.PANEL, fg=theme.DIM,
                                   anchor="w", font=theme.FONT_SM, padx=12, pady=5)
        self.lbl_status.pack(side="bottom", fill="x")

        self.rail = NavRail(self, on_pick=self.show_page)
        self.rail.pack(side="left", fill="y")

        self.container = tk.Frame(self, bg=theme.BG)
        self.container.pack(side="left", fill="both", expand=True)

        # 照片多选 / 删除的快捷键（焦点在输入框里时让输入框自己处理）
        for seq in ("<Control-a>", "<Control-A>"):
            self.bind(seq, lambda e: self._ws("select_all"))
        self.bind("<Control-i>", lambda e: self._ws("invert"))
        self.bind("<Delete>", lambda e: self._ws("delete"))

        # 从资源管理器拖照片进来（tkinter 原生不支持，见 dropfiles.py）
        self._drop_ok = False
        try:
            import dropfiles
            self._drop_ok = dropfiles.enable(self, self._on_drop)
        except Exception:
            self._drop_ok = False

        self.after(80, self._pump)
        self.show_page("projects")

    def _ws(self, action: str):
        """把快捷键转给当前工作区。"""
        if isinstance(self.focus_get(), (tk.Entry, tk.Text)):
            return None                      # 输入框里让默认行为生效
        ws = self.workspace
        if ws is None:
            return "break"
        if action == "select_all":
            ws.grid.select_all()
        elif action == "invert":
            ws.grid.invert_selection()
        elif action == "delete":
            ws.delete_selected()
        return "break"

    def _on_drop(self, paths):
        """从资源管理器拖进来的文件。"""
        ws = self.workspace
        if ws is None:
            messagebox.showinfo(
                "先打开一个项目",
                "拖进来的照片要放进某个项目里。\n\n"
                "先在「项目」里点开一个项目，再把照片拖进来。")
            return
        files = [p for p in paths if Path(p).suffix.lower() in SUPPORTED_EXTS]
        if not files:
            messagebox.showinfo("没有能导入的", "拖进来的东西里没有支持的图片格式。")
            return
        ws.add_photos_from(files)

    # ---------------- 页面路由 ----------------
    def _create_page(self, name: str) -> tk.Frame:
        if name == "projects":
            return HomePage(self.container, self.config_data,
                            on_open=self.show_workspace,
                            on_new=self.new_project,
                            on_delete=self.delete_project,
                            on_change_dir=self.change_base_dir,
                            on_rename=self.rename_project_dialog)
        if name == "canister":
            return CanisterDesigner(self.container, self.config_data)
        if name == "gallery":
            return GalleryPage(self.container, self.config_data, self,
                               on_open_project=self.show_workspace)
        if name == "settings":
            return SettingsPage(self.container, self.config_data,
                                on_base_dir_change=self._on_base_dir_change,
                                on_strips_root_change=self._refresh_after_path_change)
        raise ValueError(name)

    def show_page(self, name: str):
        if name not in dict(PAGES):
            return
        self._close_workspace()
        for key, page in self._pages.items():
            if key != name:
                page.pack_forget()

        page = self._pages.get(name)
        if page is None:
            page = self._create_page(name)
            self._pages[name] = page
        if hasattr(page, "refresh") and name in ("projects", "gallery"):
            page.refresh()
        elif hasattr(page, "reload") and name in ("settings", "canister"):
            page.reload()
        page.pack(fill="both", expand=True)
        self.rail.select(name)

    def show_workspace(self, root):
        self._close_workspace()
        for page in self._pages.values():
            page.pack_forget()
        try:
            self.project = Project.load(root)
        except Exception as exc:
            messagebox.showerror("打不开项目", f"{root}\n\n{exc}")
            self.show_page("projects")
            return
        self.workspace = Workspace(self.container, self, self.project)
        self.workspace.pack(fill="both", expand=True)
        self.rail.select("projects")
        self.set_status(f"已打开项目「{self.project.name}」")

    def _close_workspace(self):
        if self.workspace is not None:
            self.workspace.pack_forget()
            self.workspace.destroy()
            self.workspace = None
        self.project = None

    def _get_light(self) -> bool:
        return self.light_on

    def _set_light(self, on: bool):
        self.light_on = on

    # ---------------- 项目 ----------------
    def new_project(self):
        name = simpledialog.askstring("新建项目", "项目名字：", parent=self)
        if not name:
            return
        try:
            p = Project.create(name, self.config_data.base_dir, self.config_data.defaults)
        except Exception as exc:
            messagebox.showerror("建不了项目", str(exc))
            return
        self.show_workspace(p.root)

    def delete_project(self, root: Path, name: str):
        try:
            n = len(Project.load(root).photos)
        except Exception:
            n = 0
        if not messagebox.askyesno(
                "删除项目",
                f"删掉项目「{name}」？\n\n"
                f"会把整个项目文件夹连同里面复制进来的 {n} 张照片一起删掉，"
                f"删了就找不回来了。\n\n（原始照片不受影响）"):
            return
        try:
            shutil.rmtree(root)
        except Exception as exc:
            messagebox.showerror("删不掉", str(exc))
            return
        if "projects" in self._pages:
            self._pages["projects"].refresh()
        self.set_status(f"已删除项目「{name}」")

    def change_base_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.config_data.base_dir),
                                    mustexist=False, parent=self)
        if not d:
            return
        self.config_data.base_dir = Path(d)
        self.config_data.save()
        self._refresh_after_path_change()
        self.set_status(f"项目目录已改为 {d}")

    def rename_project_dialog(self, root: Path, old_name: str):
        """改项目名 —— 文件夹一起改。"""
        new_name = simpledialog.askstring(
            "重命名项目", f"「{old_name}」的新名字：",
            initialvalue=old_name, parent=self)
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if not messagebox.askyesno(
                "确认改名",
                f"「{old_name}」→「{new_name}」\n\n"
                f"项目文件夹会跟着一起改名。\n"
                f"万一文件夹里有文件正被别的程序占着（资源管理器预览、杀软扫描等），"
                f"可能会改失败，那就先关掉那些再试。"):
            return
        try:
            rename_project(root, new_name, self.config_data.strips_root)
        except Exception as exc:
            messagebox.showerror("改不了名", str(exc))
            return
        self._refresh_after_path_change()
        self.set_status(f"已改名为「{new_name}」")

    def _refresh_after_path_change(self):
        for name in ("projects", "gallery"):
            if name in self._pages:
                self._pages[name].refresh()

    def _on_base_dir_change(self):
        self._refresh_after_path_change()

    # ---------------- 状态 / 后台任务 ----------------
    def set_status(self, text):
        self.lbl_status.configure(text=text)

    def register(self, button: tk.Button) -> tk.Button:
        """登记按钮，跑后台任务时统一禁用。"""
        self._buttons.append(button)
        return button

    def _set_enabled(self, on: bool):
        for b in self._buttons:
            try:
                b.configure(state="normal" if on else "disabled")
            except Exception:
                pass

    def run_bg(self, work, on_done, busy_text="处理中…"):
        if self._busy:
            messagebox.showinfo("请稍候", "还有任务没做完，等它跑完再试")
            return
        self._busy = True
        self.set_status(busy_text)
        self._set_enabled(False)

        def runner():
            try:
                self._q.put(("done", on_done, work(lambda m: self._q.put(("progress", m)))))
            except Exception as exc:
                self._q.put(("error", exc))

        threading.Thread(target=runner, daemon=True).start()

    def _pump(self):
        try:
            while True:
                try:
                    msg = self._q.get_nowait()
                except queue.Empty:
                    break
                try:
                    if msg[0] == "progress":
                        self.set_status(msg[1])
                    elif msg[0] == "done":
                        self._busy = False
                        self._set_enabled(True)
                        msg[1](msg[2])          # msg = ("done", 回调, 结果)
                    elif msg[0] == "error":
                        self._busy = False
                        self._set_enabled(True)
                        self.set_status("出错了")
                        messagebox.showerror("出错了", str(msg[1]))
                except Exception as exc:
                    # 单个回调出错不能把整个轮询循环弄死
                    self._busy = False
                    self._set_enabled(True)
                    self.set_status("出错了")
                    messagebox.showerror("出错了", str(exc))
        finally:
            self.after(80, self._pump)


def enable_dpi_awareness():
    """告诉 Windows 我们自己会处理高 DPI，别把窗口模糊放大。

    不做这一步的话，在 125% / 150% 缩放的屏幕上整个界面会被系统拉伸得发虚。
    必须在建窗口之前调用。
    """
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win 8.1+
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # 更老的系统
    except Exception:
        pass


def main():
    enable_dpi_awareness()
    AppConfig().base_dir.mkdir(parents=True, exist_ok=True)
    App().mainloop()


if __name__ == "__main__":
    main()
