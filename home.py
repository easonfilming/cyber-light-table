"""项目卡片墙 —— 程序启动后的第一页。

每个项目一张卡片，封面用生成好的第一张胶卷图（没有就显示占位块）。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import ImageTk

import strip as strip_mod
import theme
from project import Project, list_projects, strip_files_for

CARD_W, CARD_H = 300, 182      # 封面尺寸
GAP = 22                       # 卡片间距
PAD = 28                       # 页面四周留白
STRIP_BG = (20, 20, 20)        # 胶卷图自己的底色，用它做留边就无缝


def project_cover(project: Project, size=(CARD_W, CARD_H), strips_root: str = ""):
    """项目封面 = 第一张胶卷图。还没生成过就返回 None。"""
    files = strip_files_for(project, strips_root)
    if not files:
        return None
    return strip_mod.cover_thumb(files[0], project.thumbs_dir, size, STRIP_BG)


def _bind_recursive(widget, seq, fn):
    widget.bind(seq, fn)
    for child in widget.winfo_children():
        _bind_recursive(child, seq, fn)


class HomePage(tk.Frame):
    """项目卡片墙。"""

    def __init__(self, master, config, on_open, on_new, on_delete, on_change_dir,
                 on_rename=None):
        super().__init__(master, bg=theme.BG)
        self.config = config
        self.on_open = on_open
        self.on_new = on_new
        self.on_delete = on_delete
        self.on_change_dir = on_change_dir
        self.on_rename = on_rename

        self._projects: list[Path] = []
        self._covers: list = []          # 保持 PhotoImage 引用
        self._cards: list[tk.Widget] = []
        self._cols = 0
        self._resize_job = None

        self._build()
        self.refresh()

    # ================= 界面 =================
    def _build(self):
        head = tk.Frame(self, bg=theme.BG)
        head.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))

        tk.Label(head, text="赛博观片台", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_H1).pack(side="left")
        self.lbl_count = tk.Label(head, text="", bg=theme.BG, fg=theme.DIM,
                                  font=theme.FONT_UI)
        self.lbl_count.pack(side="left", padx=14)

        theme.button(head, "更改目录", self.on_change_dir, kind="ghost",
                     size="sm").pack(side="right", padx=(8, 0))
        theme.button(head, "＋ 新建项目", self.on_new, kind="accent").pack(side="right")

        # 搜索框（项目多了好找）
        self.var_search = tk.StringVar()
        tk.Entry(head, textvariable=self.var_search, bg=theme.FIELD, fg=theme.TEXT,
                 relief="flat", font=theme.FONT_UI, width=16,
                 insertbackground=theme.TEXT, highlightthickness=1,
                 highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT).pack(
            side="right", padx=(8, 14), ipady=4)
        tk.Label(head, text="搜索", bg=theme.BG, fg=theme.DIM,
                 font=theme.FONT_SM).pack(side="right")
        self.var_search.trace_add("write", lambda *a: self._layout())

        theme.rule(self, theme.BORDER).pack(side="top", fill="x", padx=PAD, pady=(14, 0))

        # 可滚动的卡片区
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
        self.grid_frame.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        cols = max(1, (e.width - GAP) // (CARD_W + GAP + 6))
        if cols != self._cols:
            self._cols = cols
            if self._resize_job:
                self.after_cancel(self._resize_job)
            self._resize_job = self.after(80, self._layout)

    # ================= 数据 =================
    def refresh(self):
        self._projects = list_projects(self.config.base_dir)
        n = len(self._projects)
        self.lbl_count.configure(
            text=f"{n} 个项目　·　{self.config.base_dir}" if n
            else f"还没有项目　·　{self.config.base_dir}")
        self._layout()

    def _filtered(self):
        """按搜索框过滤项目。返回 (列表, 是不是正在搜索)。"""
        q = self.var_search.get().strip().lower()
        if not q:
            return list(self._projects), False
        return [p for p in self._projects if q in p.name.lower()], True

    def _layout(self):
        self._resize_job = None
        for c in self._cards:
            c.destroy()
        self._cards.clear()
        self._covers.clear()

        projects, searching = self._filtered()
        if searching and not projects:
            hint = tk.Frame(self.grid_frame, bg=theme.BG)
            hint.grid(row=0, column=0, sticky="nw")
            tk.Label(hint, text="没找到匹配的项目", bg=theme.BG, fg=theme.FAINT,
                     font=theme.FONT_UI).pack(pady=40)
            self._cards.append(hint)
            self.update_idletasks()
            self._on_inner_configure()
            return

        cols = max(1, self._cols or 4)
        # 搜索时把「新建项目」卡片收起来，免得占位置
        entries = ([] if searching else [None]) + projects
        for i, root in enumerate(entries):
            r, c = divmod(i, cols)
            card = self._new_card() if root is None else self._project_card(root)
            card.grid(row=r, column=c, padx=(0, GAP), pady=(0, GAP), sticky="nw")
            self._cards.append(card)

        self.update_idletasks()
        self._on_inner_configure()

    def _card_shell(self, parent):
        """带右下投影的卡片外壳，返回可以往里放东西的 Frame。"""
        shadow = tk.Frame(parent, bg=theme.SHADOW)
        inner = tk.Frame(shadow, bg=theme.FIELD,
                         highlightthickness=1, highlightbackground=theme.BORDER)
        inner.pack(padx=(0, 3), pady=(0, 3))
        return shadow, inner

    def _new_card(self):
        shadow, card = self._card_shell(self.grid_frame)
        body = tk.Frame(card, bg=theme.FIELD, width=CARD_W, height=CARD_H + 62)
        body.pack_propagate(False)
        body.pack()

        # ＋ 和文字作为一个整体居中
        inner = tk.Frame(body, bg=theme.FIELD)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(inner, text="＋", bg=theme.FIELD, fg=theme.ACCENT,
                 font=("Microsoft YaHei UI", 40)).pack()
        tk.Label(inner, text="新建项目", bg=theme.FIELD, fg=theme.DIM,
                 font=theme.FONT_UI).pack(pady=(6, 0))

        _bind_recursive(shadow, "<Button-1>", lambda e: self.on_new())
        shadow.configure(cursor="hand2")
        return shadow

    def _project_card(self, root: Path):
        shadow, card = self._card_shell(self.grid_frame)
        project = None
        try:
            project = Project.load(root)
            name = project.name
            meta = f"{len(project.photos)} 张　·　{project.strip_count()} 卷"
        except Exception:
            name, meta = root.name, "打不开项目"

        cover = project_cover(project, strips_root=self.config.strips_root) \
            if project is not None else None

        body = tk.Frame(card, bg=theme.FIELD, width=CARD_W)
        body.pack()

        if cover is not None:
            photo = ImageTk.PhotoImage(cover)
            self._covers.append(photo)
            tk.Label(body, image=photo, bg=theme.FIELD, bd=0).pack()
        else:
            ph = tk.Frame(body, bg=theme.rgb_to_hex(STRIP_BG), width=CARD_W, height=CARD_H)
            ph.pack_propagate(False)
            ph.pack()
            tk.Label(ph, text="还没生成胶卷图", bg=theme.rgb_to_hex(STRIP_BG),
                     fg="#6d675e", font=theme.FONT_UI).pack(expand=True)

        foot = tk.Frame(body, bg=theme.FIELD)
        foot.pack(fill="x", padx=14, pady=11)
        tk.Label(foot, text=name, bg=theme.FIELD, fg=theme.TEXT,
                 font=theme.FONT_TITLE, anchor="w").pack(fill="x")
        tk.Label(foot, text=meta, bg=theme.FIELD, fg=theme.DIM,
                 font=theme.FONT_SM, anchor="w").pack(fill="x", pady=(2, 0))

        _bind_recursive(shadow, "<Button-1>", lambda e, r=root: self.on_open(r))
        _bind_recursive(shadow, "<Button-3>", lambda e, r=root, n=name: self._menu(e, r, n))
        shadow.configure(cursor="hand2")
        return shadow

    def _menu(self, event, root: Path, name: str):
        m = tk.Menu(self, tearoff=0, bg=theme.FIELD, fg=theme.TEXT,
                    activebackground=theme.ACCENT, activeforeground=theme.ACCENT_FG,
                    bd=0, font=theme.FONT_UI)
        m.add_command(label="打开", command=lambda: self.on_open(root))
        m.add_separator()
        if self.on_rename is not None:
            m.add_command(label="重命名…",
                          command=lambda: self.on_rename(root, name))
        m.add_command(label=f"删除项目「{name}」",
                      command=lambda: self.on_delete(root, name))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
