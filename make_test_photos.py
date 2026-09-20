"""生成测试照片，用来验证分卷逻辑和渲染效果。

用法：
    python make_test_photos.py [数量] [输出目录]

默认生成 100 张到 ~/Pictures/test_photos（应分成 40 / 40 / 20 三卷）。
其中每 7 张是竖构图，另外夹两张带 EXIF 旋转标记的，用来验证方向处理。
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 800


def _font(size):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_one(index: int, total: int) -> tuple[Image.Image, int | None]:
    """返回 (图片, 要写入的 EXIF orientation 或 None)。"""
    hue = (index - 1) / max(1, total)
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.78)
    bg = (int(r * 255), int(g * 255), int(b * 255))
    dark = tuple(int(c * 0.42) for c in bg)

    portrait = (index % 7 == 0)
    size = (H, W) if portrait else (W, H)

    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    w, h = size

    # 斜条纹背景，方便看出有没有被拉伸
    for i in range(-h, w, 90):
        d.polygon([(i, h), (i + 45, h), (i + 45 + h, 0), (i + h, 0)], fill=dark)

    # 大号编号
    d.text((w / 2, h / 2 - 40), f"{index:03d}", font=_font(int(h * 0.30)),
           fill=(255, 255, 255), anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0))

    # 构图提示 + 方向标记
    label = "竖构图 PORTRAIT" if portrait else "横构图 LANDSCAPE"
    d.text((w / 2, h / 2 + int(h * 0.16)), label, font=_font(int(h * 0.055)),
           fill=(255, 255, 255), anchor="mm")
    d.text((30, 30), "TOP-LEFT", font=_font(30), fill=(255, 255, 255))
    d.text((w - 30, h - 30), "BOTTOM-RIGHT", font=_font(30),
           fill=(255, 255, 255), anchor="rd")

    # 第 5、19 张写成"横放存储 + EXIF 旋转标记"，用来验证 exif_transpose
    orientation = None
    if index in (5, 19):
        img = img.rotate(-90, expand=True)   # 存成横放
        orientation = 6                      # 显示时应转回竖构图
    return img, orientation


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "Pictures" / "test_photos"
    out.mkdir(parents=True, exist_ok=True)

    for i in range(1, n + 1):
        img, orientation = make_one(i, n)
        path = out / f"IMG_{i:04d}.jpg"
        if orientation is None:
            img.save(path, "JPEG", quality=90)
        else:
            exif = Image.Exif()
            exif[274] = orientation          # Orientation
            img.save(path, "JPEG", quality=90, exif=exif)
        if i % 20 == 0 or i == n:
            print(f"  {i}/{n}")

    print(f"完成：{n} 张测试照片已生成到 {out}")


if __name__ == "__main__":
    main()
