"""批量导出胶卷图：一次导出当前项目的所有卷，或者全部项目的所有卷。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image

import theme
from project import Project, list_projects, strip_files_for

FORMATS = {"JPG": ".jpg", "PNG": ".png"}


def project_jobs(project: Project, subfolder: bool = True,
                 strips_root: str = "") -> list[tuple[str, Path]]:
    """当前项目的所有卷：[(相对路径（不带扩展名）, 源文件)]。"""
    files = strip_files_for(project, strips_root)
    prefix = f"{project.name}/" if subfolder else ""
    return [(f"{prefix}{project.name}_第{i:02d}卷", f) for i, f in enumerate(files, 1)]


def all_jobs(base_dir, subfolder: bool = True,
             strips_root: str = "") -> list[tuple[str, Path]]:
    """所有项目的所有卷。"""
    out: list[tuple[str, Path]] = []
    for root in list_projects(base_dir):
        try:
            p = Project.load(root)
        except Exception:
            continue
        out.extend(project_jobs(p, subfolder, strips_root))
    return out


def write_jobs(jobs, out_dir, ext: str, progress=None) -> int:
    """把 jobs 写进 out_dir。返回写出的文件数。

    单独抽出来是为了能脱开界面直接测。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (rel, src) in enumerate(jobs, 1):
        if progress:
            progress(f"正在导出 {i}/{len(jobs)}…")
        dest = out_dir / (rel + ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            if ext == ".png":
                im.save(dest, "PNG")
            else:
                im.save(dest, "JPEG", quality=95, subsampling=0)
    return len(jobs)


class ExportDialog(tk.Toplevel):
    """批量导出的设置对话框。构造完调 show() 拿结果，取消返回 None。"""

    def __init__(self, parent, build_jobs, title: str, allow_subfolder: bool = True,
                 initial_dir=None):
        super().__init__(parent)
        self.build_jobs = build_jobs
        self.allow_subfolder = allow_subfolder
        self.result: dict | None = None

        self.title(title)
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(padx=24, pady=20)

        tk.Label(body, text="目标文件夹", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 3))
        self.var_dir = tk.StringVar(value=str(initial_dir or Path.home()))
        tk.Entry(body, textvariable=self.var_dir, bg=theme.FIELD, fg=theme.TEXT,
                 relief="flat", font=theme.FONT_UI, width=42, highlightthickness=1,
                 highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT).grid(
            row=1, column=0, columnspan=2, sticky="we", ipady=5)
        theme.button(body, "浏览…", self._browse, kind="ghost", size="sm").grid(
            row=1, column=2, padx=(8, 0))

        tk.Label(body, text="格式", bg=theme.BG, fg=theme.DIM, font=theme.FONT_SM,
                 anchor="w").grid(row=2, column=0, sticky="w", pady=(16, 3))
        self.var_fmt = tk.StringVar(value="JPG")
        fmt_row = tk.Frame(body, bg=theme.BG)
        fmt_row.grid(row=3, column=0, columnspan=3, sticky="w")
        for name in FORMATS:
            tk.Radiobutton(fmt_row, text=name, variable=self.var_fmt, value=name,
                           bg=theme.BG, fg=theme.TEXT, selectcolor=theme.FIELD,
                           activebackground=theme.BG, activeforeground=theme.TEXT,
                           font=theme.FONT_UI, highlightthickness=0).pack(
                side="left", padx=(0, 18))

        self.var_sub = tk.BooleanVar(value=allow_subfolder)
        if allow_subfolder:
            tk.Checkbutton(body, text="按项目名分文件夹", variable=self.var_sub,
                           bg=theme.BG, fg=theme.TEXT, selectcolor=theme.FIELD,
                           activebackground=theme.BG, activeforeground=theme.TEXT,
                           font=theme.FONT_UI, highlightthickness=0).grid(
                row=4, column=0, columnspan=3, sticky="w", pady=(14, 0))

        self.lbl_hint = tk.Label(body, text="", bg=theme.BG, fg=theme.ACCENT,
                                 font=theme.FONT_UI, anchor="w")
        self.lbl_hint.grid(row=5, column=0, columnspan=3, sticky="w", pady=(16, 0))

        foot = tk.Frame(self, bg=theme.BG)
        foot.pack(fill="x", padx=24, pady=(0, 20))
        theme.button(foot, "导出", self._ok, kind="accent").pack(side="right")
        theme.button(foot, "取消", self.destroy, kind="ghost").pack(side="right",
                                                                   padx=(0, 8))
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

        self.var_sub.trace_add("write", self._refresh_hint)
        self.var_dir.trace_add("write", self._refresh_hint)
        self._refresh_hint()

        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 140}+{parent.winfo_rooty() + 120}")

    def sub_on(self) -> bool:
        return self.allow_subfolder and bool(self.var_sub.get())

    def jobs(self):
        return self.build_jobs(self.sub_on())

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.var_dir.get() or str(Path.home()),
                                    parent=self, mustexist=False)
        if d:
            self.var_dir.set(d)

    def _refresh_hint(self, *_a):
        n = len(self.jobs())
        folder = Path(self.var_dir.get().strip() or ".").name or "."
        self.lbl_hint.configure(text=f"会导出 {n} 个文件到「{folder}」")

    def _ok(self):
        d = self.var_dir.get().strip()
        if not d:
            messagebox.showwarning("还差一步", "先选个目标文件夹。", parent=self)
            return
        jobs = self.jobs()
        if not jobs:
            messagebox.showinfo("没有可导出的", "还没有生成过胶卷图。", parent=self)
            return
        self.result = {"jobs": jobs, "dir": Path(d), "ext": FORMATS[self.var_fmt.get()]}
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


def batch_export(parent, app, build_jobs, title: str, allow_subfolder: bool = True):
    """弹对话框选文件夹和格式，然后后台写盘。

    build_jobs(subfolder: bool) -> [(相对路径, 源文件)]
    目标文件夹默认用设置里的「导出路径」，用户改了就记住。
    """
    if not build_jobs(allow_subfolder):
        messagebox.showinfo("没有可导出的", "还没有生成过胶卷图。", parent=parent)
        return

    cfg = getattr(app, "config_data", None)
    initial = cfg.export_path() if cfg is not None else Path.home()
    res = ExportDialog(parent, build_jobs, title, allow_subfolder, initial).show()
    if not res:
        return
    out_dir, ext, jobs = res["dir"], res["ext"], res["jobs"]

    if cfg is not None:                     # 记住这次选的，下次直接填上
        cfg.export_dir = str(out_dir)
        cfg.save()

    def work(progress):
        return write_jobs(jobs, out_dir, ext, progress), out_dir

    def done(result):
        n, d = result
        app.set_status(f"导出完成：{n} 个文件 → {d}")

    app.run_bg(work, done, busy_text="准备导出…")
