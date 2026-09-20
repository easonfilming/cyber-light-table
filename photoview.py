"""看单张照片原图的弹窗。

工作区双击缩略图、灯箱里点某一格，都走这里。
"""
from __future__ import annotations

import os
import tkinter as tk

from PIL import Image, ImageOps, ImageTk

import theme


def show_photo_window(parent, photo, project):
    """弹出 photo 的原图。photo 是 project.Photo，project 是它所属的 Project。"""
    path = photo.path(project.root)

    top = tk.Toplevel(parent)
    top.title(photo.display_name)
    top.configure(bg=theme.rgb_to_hex((17, 17, 17)))
    try:
        im = Image.open(path)
        im.load()
        im = (ImageOps.exif_transpose(im) or im).convert("RGB")
    except Exception as exc:
        tk.Label(top, text=f"打不开：{exc}", bg="#111111", fg="#e6e2dc",
                 font=theme.FONT_UI).pack(padx=30, pady=30)
        return

    im.thumbnail((int(top.winfo_screenwidth() * 0.8),
                  int(top.winfo_screenheight() * 0.78)), Image.Resampling.LANCZOS)
    ph = ImageTk.PhotoImage(im)
    lbl = tk.Label(top, image=ph, bg="#111111")
    lbl.image = ph                      # 保持引用
    lbl.pack(padx=10, pady=10)

    foot = tk.Frame(top, bg="#111111")
    foot.pack(fill="x", pady=(0, 10))
    tk.Label(foot, text=f"{photo.display_name}　·　{im.size[0]}×{im.size[1]}"
                        + (f"　·　拍摄于 {photo.taken}" if photo.taken else ""),
             bg="#111111", fg="#9a948c", font=theme.FONT_SM).pack(side="left", padx=14)
    theme.button(foot, "用系统查看器打开", lambda: os.startfile(str(path)),
                 kind="ghost", size="sm").pack(side="right", padx=14)
    top.bind("<Escape>", lambda e: top.destroy())
