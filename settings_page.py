"""设置页：项目目录、新建项目默认值、缩略图缓存、配置文件位置，以及关于。

改动**即时生效并存盘**，没有保存按钮。
"""
from __future__ import annotations

import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import canister as canister_mod
import theme
from appconfig import LOUPE_DIM_MAX, LOUPE_DIM_MIN
from project import list_projects

FIT_LABELS = {"rotate": "竖图转90°", "contain": "完整显示", "cover": "填满画幅"}
FIT_KEYS = {v: k for k, v in FIT_LABELS.items()}

ABOUT = (
    "把照片按项目整理，每 40 张（余数另成一卷）合成一张「胶卷展开」风格的总览图。\n"
    "\n"
    "· 项目页：每个项目一张卡片，封面就是生成好的胶卷图\n"
    "· 进项目后左边挑照片，右边是观片台 —— 点「开灯」才看得见照片\n"
    "· 观片器：侧栏挑倍率，按住左键拖动、松开放下，透过镜片看原始像素\n"
    "· 暗盒设计器：自己设计暗盒并保存，项目里直接选用\n"
    "· 胶卷图库：所有项目生成过的胶卷图汇总成一面墙，点开进灯箱看\n"
    "\n"
    "照片会复制进项目文件夹，原图不受影响；整个项目文件夹可以直接备份。"
)


def cache_stats(base_dir) -> tuple[int, int]:
    """所有项目的缩略图缓存：(文件数, 总字节数)。"""
    count = total = 0
    for root in list_projects(base_dir):
        d = root / "photos" / ".thumbs"
        if not d.is_dir():
            continue
        for f in d.glob("*.jpg"):
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                pass
    return count, total


def clear_caches(base_dir) -> int:
    """删掉所有项目的缩略图缓存。下次用到会自动重建。"""
    n = 0
    for root in list_projects(base_dir):
        d = root / "photos" / ".thumbs"
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


class SettingsPage(tk.Frame):
    def __init__(self, master, config, on_base_dir_change=None,
                 on_strips_root_change=None):
        super().__init__(master, bg=theme.BG)
        self.config = config
        self.on_base_dir_change = on_base_dir_change
        self.on_strips_root_change = on_strips_root_change
        self._loading = False

        self._build()
        self.reload()

    # ---------------- 界面 ----------------
    def _build(self):
        head = tk.Frame(self, bg=theme.BG)
        head.pack(side="top", fill="x", padx=28, pady=(24, 0))
        tk.Label(head, text="设置", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_H1).pack(side="left")
        tk.Label(head, text="改动即时生效并保存", bg=theme.BG, fg=theme.DIM,
                 font=theme.FONT_SM).pack(side="left", padx=14)
        theme.rule(self, theme.BORDER).pack(side="top", fill="x", padx=28, pady=(14, 0))

        # 内容可能比较长，做成可滚动的
        holder = tk.Frame(self, bg=theme.BG)
        holder.pack(side="top", fill="both", expand=True, padx=(28, 0), pady=18)
        sb = tk.Scrollbar(holder, orient="vertical", bd=0, relief="flat",
                          bg=theme.PANEL, troughcolor=theme.BG, width=12)
        cv = tk.Canvas(holder, bg=theme.BG, highlightthickness=0,
                       yscrollincrement=28, yscrollcommand=sb.set)
        sb.configure(command=cv.yview)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        box = tk.Frame(cv, bg=theme.BG)
        win = cv.create_window((0, 0), window=box, anchor="nw")
        box.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        self._section(box, "项目目录")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        self.lbl_base = tk.Label(row, text="", bg=theme.BG, fg=theme.TEXT,
                                 font=theme.FONT_UI, anchor="w", justify="left")
        self.lbl_base.pack(side="left")
        theme.button(row, "打开文件夹", self.open_base, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(row, "更改…", self.change_base, size="sm").pack(side="right")

        # 胶卷图存放位置
        self._section(box, "胶卷图存放位置")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        self.lbl_strips = tk.Label(row, text="", bg=theme.BG, fg=theme.TEXT,
                                   font=theme.FONT_UI, anchor="w", justify="left")
        self.lbl_strips.pack(side="left")
        theme.button(row, "打开", self.open_strips_root, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(row, "恢复默认", self.reset_strips_root, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(row, "更改…", self.change_strips_root, size="sm").pack(side="right")

        # 导出路径
        self._section(box, "导出路径")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        self.lbl_export = tk.Label(row, text="", bg=theme.BG, fg=theme.TEXT,
                                   font=theme.FONT_UI, anchor="w", justify="left")
        self.lbl_export.pack(side="left")
        theme.button(row, "打开", self.open_export_dir, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(row, "恢复默认", self.reset_export_dir, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(row, "更改…", self.change_export_dir, size="sm").pack(side="right")

        self._section(box, "新建项目的默认值")
        grid = tk.Frame(box, bg=theme.BG)
        grid.pack(fill="x", pady=(0, 20))
        self.var_per = tk.StringVar()
        self.var_row = tk.StringVar()
        self._field(grid, 0, "每卷张数", self.var_per, 6)
        self._field(grid, 1, "每行张数", self.var_row, 6)
        self.var_fit = tk.StringVar()
        self.var_can = tk.StringVar()
        # 注册 trace，这样不管是点菜单还是代码直接改变量，都会存盘
        self.var_fit.trace_add("write", self._on_defaults)
        tk.Label(grid, text="显示方式", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=0, column=2, sticky="w", padx=(24, 6))
        theme.option_menu(grid, self.var_fit, list(FIT_LABELS.values()),
                          self._on_defaults, width=11).grid(row=0, column=3, sticky="w")
        tk.Label(grid, text="暗盒", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=1, column=2, sticky="w", padx=(24, 6), pady=(8, 0))
        self.om_can = theme.option_menu(grid, self.var_can, ["—"], self._on_defaults,
                                        width=18)
        self.om_can.grid(row=1, column=3, sticky="w", pady=(8, 0))

        self._section(box, "观片器")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        self.var_dim = tk.DoubleVar(value=self.config.loupe_dim * 100)
        tk.Scale(row, from_=0, to=35, orient="horizontal", variable=self.var_dim,
                 bg=theme.BG, fg=theme.TEXT, troughcolor=theme.PANEL, bd=0,
                 highlightthickness=0, showvalue=False, length=220,
                 activebackground=theme.ACCENT, command=self._on_dim).pack(side="left")
        self.lbl_dim = tk.Label(row, text="", bg=theme.BG, fg=theme.ACCENT,
                                font=theme.FONT_UI, width=5, anchor="w")
        self.lbl_dim.pack(side="left", padx=(12, 10))
        tk.Label(row, text="镜外压暗的深浅，拖到 0 就是完全不压暗",
                 bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM).pack(side="left")

        self._section(box, "缩略图缓存")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        self.lbl_cache = tk.Label(row, text="", bg=theme.BG, fg=theme.TEXT,
                                  font=theme.FONT_UI, anchor="w")
        self.lbl_cache.pack(side="left")
        theme.button(row, "清理", self.clear_cache, kind="danger",
                     size="sm").pack(side="right")

        self._section(box, "配置文件")
        row = tk.Frame(box, bg=theme.BG)
        row.pack(fill="x", pady=(0, 20))
        tk.Label(row, text=str(self.config.path), bg=theme.BG, fg=theme.DIM,
                 font=theme.FONT_SM, anchor="w").pack(side="left")
        theme.button(row, "打开文件夹", self.open_config_dir, kind="ghost",
                     size="sm").pack(side="right")

        self._section(box, "关于")
        tk.Label(box, text=ABOUT, bg=theme.BG, fg=theme.DIM, font=theme.FONT_UI,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 28))

    def _section(self, parent, title):
        tk.Label(parent, text=title, bg=theme.BG, fg=theme.ACCENT,
                 font=("Microsoft YaHei UI", 11, "bold"), anchor="w").pack(
            fill="x", pady=(6, 8))

    def _field(self, parent, col, label, var, width):
        tk.Label(parent, text=label, bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=col, column=0, sticky="w", padx=(0, 6))
        e = tk.Entry(parent, textvariable=var, bg=theme.FIELD, fg=theme.TEXT,
                     relief="flat", insertbackground=theme.TEXT, font=theme.FONT_UI,
                     width=width, highlightthickness=1,
                     highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        e.grid(row=col, column=1, sticky="w", ipady=4)
        var.trace_add("write", self._on_defaults)
        return e

    # ---------------- 数据 ----------------
    def reload(self):
        self._loading = True
        try:
            self._refresh_paths()
            d = self.config.defaults
            self.var_per.set(str(d["photos_per_strip"]))
            self.var_row.set(str(d["photos_per_row"]))
            self.var_fit.set(FIT_LABELS.get(d["fit_mode"], FIT_LABELS["rotate"]))
            self._reload_canister_choices()
            self.var_dim.set(self.config.loupe_dim * 100)
            self.lbl_dim.configure(text=f"{self.config.loupe_dim * 100:.0f}%")
            self._refresh_cache()
        finally:
            self._loading = False

    def _reload_canister_choices(self):
        self._choices = canister_mod.choices(self.config.library())
        menu = self.om_can["menu"]
        menu.delete(0, "end")
        for name, cid in self._choices:
            menu.add_command(label=name, command=lambda c=cid: self._pick_canister(c))
        self.var_can.set(canister_mod.name_of(self.config.defaults["canister"],
                                              self.config.library()))

    def _refresh_cache(self):
        count, total = cache_stats(self.config.base_dir)
        self.lbl_cache.configure(
            text=f"占用 {_fmt_size(total)}（{count} 个文件）" if count
            else "暂无缓存")

    # ---------------- 事件 ----------------
    def _on_defaults(self, *_a):
        if self._loading:
            return
        try:
            per = max(1, int(self.var_per.get()))
            row = max(1, int(self.var_row.get()))
        except (TypeError, ValueError):
            return                       # 正在输入中间态，先不管
        self.config.defaults.update({
            "photos_per_strip": per,
            "photos_per_row": row,
            "fit_mode": FIT_KEYS.get(self.var_fit.get(), "rotate"),
            "canister": self.config.defaults["canister"],
        })
        self.config.save()

    def _pick_canister(self, cid: str):
        self.config.defaults["canister"] = cid
        self.config.save()
        self.var_can.set(canister_mod.name_of(cid, self.config.library()))

    def _on_dim(self, _v=None):
        if self._loading:
            return
        val = max(LOUPE_DIM_MIN, min(LOUPE_DIM_MAX, self.var_dim.get() / 100.0))
        self.config.loupe_dim = val
        self.config.save()
        self.lbl_dim.configure(text=f"{val * 100:.0f}%")

    def change_base(self):
        d = filedialog.askdirectory(initialdir=str(self.config.base_dir),
                                    mustexist=False, parent=self)
        if not d:
            return
        self.config.base_dir = Path(d)
        self.config.save()
        self._refresh_paths()
        self._refresh_cache()
        if self.on_base_dir_change:
            self.on_base_dir_change()

    def open_base(self):
        p = Path(self.config.base_dir)
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))

    # ---------------- 胶卷图存放位置 ----------------
    def change_strips_root(self):
        start = self.config.strips_root or str(self.config.base_dir)
        d = filedialog.askdirectory(initialdir=start, mustexist=False, parent=self)
        if not d:
            return
        self.config.strips_root = d
        self.config.save()
        self._refresh_paths()
        if self.on_strips_root_change:
            self.on_strips_root_change()
        messagebox.showinfo(
            "改好了",
            "以后生成的胶卷图会放到这个文件夹下，按项目名分子文件夹。\n\n"
            "之前生成的那些还在原处，两边都会照常显示，不会丢。",
            parent=self)

    def reset_strips_root(self):
        self.config.strips_root = ""
        self.config.save()
        self._refresh_paths()
        if self.on_strips_root_change:
            self.on_strips_root_change()

    def open_strips_root(self):
        d = (Path(self.config.strips_root) if self.config.strips_root
             else Path(self.config.base_dir))
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))
        except Exception as exc:
            messagebox.showerror("打不开", str(exc), parent=self)

    # ---------------- 导出路径 ----------------
    def change_export_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.config.export_path()),
                                    mustexist=False, parent=self)
        if not d:
            return
        self.config.export_dir = d
        self.config.save()
        self._refresh_paths()

    def reset_export_dir(self):
        self.config.export_dir = ""
        self.config.save()
        self._refresh_paths()

    def open_export_dir(self):
        try:
            d = self.config.export_path()
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))
        except Exception as exc:
            messagebox.showerror("打不开", str(exc), parent=self)

    def _refresh_paths(self):
        self.lbl_base.configure(text=str(self.config.base_dir))
        self.lbl_strips.configure(
            text=self.config.strips_root or "跟着项目走（存在项目文件夹里的 strips/）")
        self.lbl_export.configure(text=str(self.config.export_path()))

    def clear_cache(self):
        if not messagebox.askyesno(
                "清理缓存",
                "删掉所有项目的缩略图缓存？\n\n"
                "不影响照片和已经生成的胶卷图，只是下次打开要重新生成一遍缩略图。",
                parent=self):
            return
        n = clear_caches(self.config.base_dir)
        self._refresh_cache()
        messagebox.showinfo("清理完成", f"清掉了 {n} 个项目的缓存。", parent=self)

    def open_config_dir(self):
        d = self.config.path.parent
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))
