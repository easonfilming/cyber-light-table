"""暗盒设计器：自己设计暗盒并保存，之后在项目里直接选用。

改动**自动保存**（防抖 400ms），不用点保存按钮 —— 免得改了半天忘了存。
内置的三个是只读的，可以「复制」一份出来改。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, messagebox

from PIL import ImageTk

import canister as canister_mod
import theme

LIST_W = 220


class CanisterDesigner(tk.Frame):
    def __init__(self, master, config, on_change=None):
        super().__init__(master, bg=theme.BG)
        self.config = config
        self.on_change = on_change          # 库变了通知外面（工作区下拉框要刷新）

        self.entries: list[tuple[str, str, str]] = []   # (显示名, kind, key)
        self.sel: tuple[str, str] | None = None         # ("builtin"|"user", key)
        self.form = dict(canister_mod.NEW_TEMPLATE)
        self._photo = None
        self._render_job = None
        self._save_job = None
        self._loading = False

        self._build()
        self.reload()

    # ================= 界面 =================
    def _build(self):
        head = tk.Frame(self, bg=theme.BG)
        head.pack(side="top", fill="x", padx=28, pady=(24, 0))
        tk.Label(head, text="暗盒设计器", bg=theme.BG, fg=theme.TEXT,
                 font=theme.FONT_H1).pack(side="left")
        self.lbl_hint = tk.Label(head, text="改动自动保存", bg=theme.BG, fg=theme.DIM,
                                 font=theme.FONT_SM)
        self.lbl_hint.pack(side="left", padx=14)

        self.btn_delete = theme.button(head, "删除", self.delete, kind="danger")
        self.btn_delete.pack(side="right")
        theme.button(head, "复制一份", self.duplicate).pack(side="right", padx=(0, 8))
        theme.button(head, "新建", self.new_one, kind="accent").pack(side="right", padx=(0, 8))

        theme.rule(self, theme.BORDER).pack(side="top", fill="x", padx=28, pady=(14, 0))

        body = tk.Frame(self, bg=theme.BG)
        body.pack(side="top", fill="both", expand=True, padx=28, pady=20)

        # --- 左：暗盒列表 ---
        left = tk.Frame(body, bg=theme.PANEL, width=LIST_W)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="暗盒", bg=theme.PANEL, fg=theme.DIM, font=theme.FONT_UI,
                 anchor="w").pack(fill="x", padx=12, pady=(12, 6))
        self.listbox = tk.Listbox(left, bg=theme.FIELD, fg=theme.TEXT, bd=0,
                                  highlightthickness=0, activestyle="none",
                                  selectbackground=theme.ACCENT,
                                  selectforeground=theme.ACCENT_FG,
                                  font=theme.FONT_UI, exportselection=False)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)

        # --- 右：预览 + 编辑 ---
        right = tk.Frame(body, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(20, 0))

        self.canvas = tk.Canvas(right, bg=theme.rgb_to_hex(canister_mod.PREVIEW_BG),
                                highlightthickness=1,
                                highlightbackground=theme.BORDER)
        self.canvas.pack(side="top", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.schedule_render())

        self._build_form(right)

    def _build_form(self, parent):
        box = tk.Frame(parent, bg=theme.BG)
        box.pack(side="bottom", fill="x", pady=(16, 0))
        self.form_box = box

        def row(r, label):
            tk.Label(box, text=label, bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                     anchor="w", width=8).grid(row=r, column=0, sticky="w", pady=4)

        self.var_name = tk.StringVar()
        self.var_label = tk.StringVar()
        self.var_sub = tk.StringVar()
        for r, (lab, var) in enumerate((("名称", self.var_name),
                                        ("标签文字", self.var_label),
                                        ("副标题", self.var_sub))):
            row(r, lab)
            e = tk.Entry(box, textvariable=var, bg=theme.FIELD, fg=theme.TEXT,
                         relief="flat", insertbackground=theme.TEXT,
                         font=theme.FONT_UI, width=26, highlightthickness=1,
                         highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
            e.grid(row=r, column=1, sticky="we", ipady=4, padx=(0, 18))
            var.trace_add("write", self._on_field)

        # 颜色行
        row(3, "标签颜色")
        self.sw_band = self._swatch(box, 3, 1, "band")
        row(4, "筒身颜色")
        self.sw_body = self._swatch(box, 4, 1, "body")

        row(5, "文字颜色")
        cf = tk.Frame(box, bg=theme.BG)
        cf.grid(row=5, column=1, sticky="w")
        self.sw_ink = tk.Frame(cf, width=46, height=26, bg=theme.FIELD,
                               highlightthickness=1, highlightbackground=theme.BORDER)
        self.sw_ink.pack(side="left")
        self.sw_ink.pack_propagate(False)
        theme.button(cf, "自动", lambda: self.set_ink(""), size="sm").pack(
            side="left", padx=(8, 4))
        theme.button(cf, "选颜色", lambda: self.pick_color("ink"), size="sm").pack(side="left")

        box.columnconfigure(1, weight=1)

    def _swatch(self, parent, r, c, which):
        f = tk.Frame(parent, bg=theme.BG)
        f.grid(row=r, column=c, sticky="w")
        sw = tk.Frame(f, width=46, height=26, bg=theme.FIELD,
                      highlightthickness=1, highlightbackground=theme.BORDER)
        sw.pack(side="left")
        sw.pack_propagate(False)
        theme.button(f, "选颜色", lambda w=which: self.pick_color(w), size="sm").pack(
            side="left", padx=(8, 0))
        return sw

    # ================= 列表 =================
    def reload(self, keep: tuple[str, str] | None = None):
        want = keep or self.sel
        self.entries = [(s["name"], "builtin", k) for k, s in canister_mod.CANISTERS.items()]
        self.entries += [(str(c.get("name") or "未命名暗盒"), "user", c["id"])
                         for c in self.config.canisters]

        self.listbox.delete(0, "end")
        for i, (name, kind, _key) in enumerate(self.entries):
            self.listbox.insert("end", ("　" if kind == "builtin" else "★ ") + name)
        if self.entries:
            idx = 0
            if want in [(k, key) for _n, k, key in self.entries]:
                idx = [(k, key) for _n, k, key in self.entries].index(want)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self._select(*[(k, key) for _n, k, key in self.entries][idx])

    def _on_pick(self, _e=None):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.entries):
            return
        _name, kind, key = self.entries[sel[0]]
        self._select(kind, key)

    def _select(self, kind: str, key: str):
        self.sel = (kind, key)
        self._loading = True
        try:
            if kind == "builtin":
                spec = canister_mod.CANISTERS[key]
                self.form = {"name": spec["name"], "label": spec["label"],
                             "sub": spec["sub"],
                             "band": theme.rgb_to_hex(spec["band"]),
                             "body": theme.rgb_to_hex(spec["body"]),
                             "ink": theme.rgb_to_hex(spec["ink"])}
            else:
                c = self.config.find_canister(key) or {}
                self.form = {"name": c.get("name", ""), "label": c.get("label", ""),
                             "sub": c.get("sub", ""), "band": c.get("band", "#2a5fa8"),
                             "body": c.get("body", "#282523"), "ink": c.get("ink", "")}
            self.var_name.set(self.form["name"])
            self.var_label.set(self.form["label"])
            self.var_sub.set(self.form["sub"])
            self._sync_swatches()
        finally:
            self._loading = False

        editable = (kind == "user")
        self._set_editable(editable)
        self.lbl_hint.configure(
            text="改动自动保存" if editable else "内置暗盒不能改，可以「复制一份」出来改")
        self.schedule_render()

    def _set_editable(self, on: bool):
        """只作用于表单区，顶部的新建/复制/删除不受影响。"""
        state = "normal" if on else "disabled"

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, (tk.Entry, tk.Button)):
                    try:
                        c.configure(state=state)
                    except Exception:
                        pass
                walk(c)
        walk(self.form_box)
        self.btn_delete.configure(state=state)

    def _sync_swatches(self):
        for sw, key in ((self.sw_band, "band"), (self.sw_body, "body"), (self.sw_ink, "ink")):
            c = self.form.get(key) or ""
            if key == "ink" and not c:
                c = theme.rgb_to_hex(canister_mod.from_dict(self.form)["ink"])
            try:
                sw.configure(bg=c)
            except Exception:
                sw.configure(bg=theme.FIELD)

    # ================= 编辑 =================
    def _on_field(self, *_a):
        if self._loading or self.sel is None or self.sel[0] != "user":
            return
        self.form["name"] = self.var_name.get().strip() or "未命名暗盒"
        self.form["label"] = self.var_label.get()
        self.form["sub"] = self.var_sub.get()
        self.schedule_render()
        self.schedule_save()

    def pick_color(self, which: str):
        if self.sel is None or self.sel[0] != "user":
            return
        cur = self.form.get(which) or "#888888"
        _rgb, hexv = colorchooser.askcolor(color=cur, parent=self, title="选颜色")
        if not hexv:
            return
        self.form[which] = hexv
        self._sync_swatches()
        self.schedule_render()
        self.schedule_save()

    def set_ink(self, value: str):
        if self.sel is None or self.sel[0] != "user":
            return
        self.form["ink"] = value
        self._sync_swatches()
        self.schedule_render()
        self.schedule_save()

    def schedule_render(self):
        if self._render_job:
            self.after_cancel(self._render_job)
        self._render_job = self.after(60, self.render)

    def schedule_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.save_now)

    def save_now(self):
        self._save_job = None
        if self.sel is None or self.sel[0] != "user":
            return
        cid = self.sel[1]
        self.config.update_canister(cid, self.form)
        # 名字可能改了，列表那一行要跟着更新
        idx = self.listbox.curselection()
        if idx:
            self.listbox.delete(idx[0])
            self.listbox.insert(idx[0], "★ " + self.form["name"])
            self.listbox.selection_set(idx[0])
        if self.on_change:
            self.on_change()
        self.lbl_hint.configure(text="已保存")

    # ================= 增删 =================
    def new_one(self):
        data = dict(canister_mod.NEW_TEMPLATE)
        data["name"] = "我的暗盒"
        item = self.config.add_canister(data)
        self.reload(keep=("user", item["id"]))
        if self.on_change:
            self.on_change()

    def duplicate(self):
        if self.sel is None:
            return
        src = canister_mod.from_dict(self.form)
        item = self.config.add_canister({
            "name": (self.form.get("name") or "暗盒") + " 副本",
            "label": self.form.get("label", ""), "sub": self.form.get("sub", ""),
            "band": theme.rgb_to_hex(src["band"]), "body": theme.rgb_to_hex(src["body"]),
            "ink": theme.rgb_to_hex(src["ink"]) if self.form.get("ink") else "",
        })
        self.reload(keep=("user", item["id"]))
        if self.on_change:
            self.on_change()

    def delete(self):
        if self.sel is None or self.sel[0] != "user":
            return
        cid = self.sel[1]
        name = self.form.get("name") or "这只暗盒"
        if not messagebox.askyesno(
                "删除暗盒",
                f"删掉「{name}」？\n\n"
                f"已经用它的项目不会坏 —— 会退回用默认的柯达黄，"
                f"但重新生成胶卷图才会变。", parent=self):
            return
        self.config.remove_canister(cid)
        self.sel = None
        self.reload(keep=None)
        if self.on_change:
            self.on_change()

    # ================= 预览 =================
    def render(self):
        self._render_job = None
        cw = max(self.canvas.winfo_width(), 120)
        ch = max(self.canvas.winfo_height(), 120)
        spec = canister_mod.from_dict(self.form)
        try:
            img = canister_mod.render_preview(spec, (cw, ch))
        except Exception:
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
