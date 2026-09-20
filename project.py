"""项目数据模型：project.json 的读写、照片导入/删除/排序。

一个项目就是磁盘上的一个文件夹：

    <项目名>/
        project.json    元数据
        photos/         复制进来的原图（+ .thumbs/ 缩略图缓存）
        strips/         生成的胶卷总览图
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
PROJECT_FILE = "project.json"
DEFAULT_BASE_DIR = Path.home() / "Pictures" / "FilmProjects"

# 自定义暗盒的默认值（用户在界面上可以改）
DEFAULT_CUSTOM_CANISTER = {"label": "MY FILM 400", "body": "#7a4a2b", "sub": "135 · 36 EXP"}

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def natural_key(s: str):
    """自然排序键：让 IMG_2 排在 IMG_10 前面。

    返回 (类型标记, 值) 的列表，保证同位置元素类型一致、可以安全比较。
    """
    return [(1, int(p)) if p.isdigit() else (0, p.lower())
            for p in re.split(r"(\d+)", str(s))]


def safe_stem(name: str, maxlen: int = 60) -> str:
    """把文件名主体清理成 Windows 合法字符。"""
    s = _ILLEGAL.sub("_", str(name)).strip(" .")
    return (s or "photo")[:maxlen]


def read_exif_datetime(path: Path) -> str | None:
    """读取 EXIF 拍摄时间，读不到返回 None。"""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            raw = None
            try:
                raw = exif.get_ifd(0x8769).get(36867)   # Exif SubIFD: DateTimeOriginal
            except Exception:
                raw = None
            if not raw:
                raw = exif.get(306)                      # IFD0: DateTime
            if not raw:
                return None
            dt = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
            return dt.isoformat(timespec="seconds")
    except Exception:
        return None


@dataclass
class Photo:
    id: str                      # "0001"，同时是文件名前缀
    filename: str                # 相对项目目录，如 "photos/0001_IMG_1234.jpg"
    original: str = ""           # 原始路径，仅作记录
    added: str = ""              # 导入时间 ISO
    taken: str | None = None     # EXIF 拍摄时间 ISO
    size: int = 0

    def path(self, root: Path) -> Path:
        return Path(root) / self.filename

    @property
    def display_name(self) -> str:
        """去掉 0001_ 前缀后的原始文件名。"""
        base = Path(self.filename).name
        return base.split("_", 1)[1] if "_" in base else base


@dataclass
class Project:
    name: str
    root: Path
    photos_per_strip: int = 40
    photos_per_row: int = 8
    fit_mode: str = "rotate"       # "rotate" 竖图转90° / "contain" 完整显示 / "cover" 裁剪填满
    canister: str = "kodak"        # 左上角暗盒：kodak / fuji / ilford / custom
    canister_custom: dict = field(
        default_factory=lambda: dict(DEFAULT_CUSTOM_CANISTER))
    last_sort_mode: str = "added"  # 上次生成胶卷图用的排序（从画幅反查照片要用）
    effects: dict = field(default_factory=dict)   # 胶片特效 {效果名: 0-100}
    created: str = ""
    photos: list[Photo] = field(default_factory=list)
    strips: list[str] = field(default_factory=list)

    # ---------------- 目录 ----------------
    @property
    def photos_dir(self) -> Path:
        return Path(self.root) / "photos"

    @property
    def strips_dir(self) -> Path:
        return Path(self.root) / "strips"

    @property
    def thumbs_dir(self) -> Path:
        return self.photos_dir / ".thumbs"

    # ---------------- 创建 / 加载 / 保存 ----------------
    @classmethod
    def create(cls, name: str, base_dir: Path, defaults: dict | None = None) -> "Project":
        """新建项目。defaults 是设置页里的"新建项目默认值"。"""
        name = str(name).strip()
        if not name:
            raise ValueError("项目名不能为空")
        if _ILLEGAL.search(name):
            raise ValueError('项目名不能包含 \\ / : * ? " < > | 这些字符')
        root = Path(base_dir) / name
        if (root / PROJECT_FILE).is_file():
            raise ValueError(f"项目「{name}」已经存在了")
        (root / "photos").mkdir(parents=True, exist_ok=True)
        (root / "strips").mkdir(parents=True, exist_ok=True)

        d = defaults or {}
        try:
            per = max(1, int(d.get("photos_per_strip", 40)))
            row = max(1, int(d.get("photos_per_row", 8)))
        except (TypeError, ValueError):
            per, row = 40, 8
        p = cls(
            name=name, root=root,
            photos_per_strip=per,
            photos_per_row=row,
            fit_mode=str(d.get("fit_mode") or "rotate"),
            canister=str(d.get("canister") or "kodak"),
            created=datetime.now().isoformat(timespec="seconds"),
        )
        p.save()
        return p

    @classmethod
    def load(cls, root: Path) -> "Project":
        root = Path(root)
        data = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8"))
        fields = set(Photo.__dataclass_fields__)
        photos = [Photo(**{k: v for k, v in ph.items() if k in fields})
                  for ph in data.get("photos", [])]
        return cls(
            name=data.get("name", root.name),
            root=root,
            photos_per_strip=int(data.get("photos_per_strip", 40)),
            photos_per_row=int(data.get("photos_per_row", 8)),
            fit_mode=data.get("fit_mode", "rotate"),
            canister=data.get("canister", "kodak"),
            canister_custom={**DEFAULT_CUSTOM_CANISTER,
                             **(data.get("canister_custom") or {})},
            last_sort_mode=data.get("last_sort_mode") or "added",
            effects=dict(data.get("effects") or {}),
            created=data.get("created", ""),
            photos=photos,
            strips=list(data.get("strips", [])),
        )

    def save(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / PROJECT_FILE
        data = json.dumps({
            "name": self.name,
            "created": self.created,
            "photos_per_strip": self.photos_per_strip,
            "photos_per_row": self.photos_per_row,
            "fit_mode": self.fit_mode,
            "canister": self.canister,
            "canister_custom": dict(self.canister_custom),
            "last_sort_mode": self.last_sort_mode,
            "effects": dict(self.effects),
            "photos": [vars(ph) for ph in self.photos],
            "strips": list(self.strips),
        }, ensure_ascii=False, indent=2)

        # 先写临时文件再替换，尽量保证不会写坏。但 Windows 上 replace 偶尔会
        # 被杀软 / 索引器占着报 WinError 5，那就退回直接写目标文件。
        tmp = self.root / (PROJECT_FILE + ".tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(target)
            return
        except OSError:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        target.write_text(data, encoding="utf-8")

    # ---------------- 照片增删 ----------------
    def _next_index(self) -> int:
        used = [int(ph.id) for ph in self.photos if str(ph.id).isdigit()]
        return (max(used) + 1) if used else 1

    def add_photos(self, paths, progress_cb=None) -> tuple[int, int]:
        """把照片复制进项目。返回 (新增数, 跳过数)。

        已经导入过的原图（按原始绝对路径判断）会被跳过，不会重复导入。
        """
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        seen = {str(Path(ph.original)).lower() for ph in self.photos if ph.original}
        paths = [Path(p) for p in paths]
        added = skipped = 0
        idx = self._next_index()

        for i, src in enumerate(paths, 1):
            if progress_cb:
                progress_cb(f"正在导入 {i}/{len(paths)}：{src.name}")
            try:
                if not src.is_file() or src.suffix.lower() not in SUPPORTED_EXTS:
                    skipped += 1
                    continue
                key = str(src.resolve()).lower()
                if key in seen:
                    skipped += 1
                    continue

                dest_name = f"{idx:04d}_{safe_stem(src.stem)}{src.suffix.lower()}"
                dest = self.photos_dir / dest_name
                shutil.copy2(src, dest)

                self.photos.append(Photo(
                    id=f"{idx:04d}",
                    filename=f"photos/{dest_name}",
                    original=str(src.resolve()),
                    added=datetime.now().isoformat(timespec="seconds"),
                    taken=read_exif_datetime(dest),
                    size=dest.stat().st_size,
                ))
                seen.add(key)
                idx += 1
                added += 1
            except Exception:
                skipped += 1

        if added:
            self.save()
        return added, skipped

    def remove_photos(self, ids) -> int:
        ids = set(ids)
        keep, removed = [], 0
        for ph in self.photos:
            if ph.id in ids:
                try:
                    ph.path(self.root).unlink(missing_ok=True)
                except Exception:
                    pass
                removed += 1
            else:
                keep.append(ph)
        self.photos = keep
        if removed:
            self.save()
        return removed

    def move_photo(self, pid: str, new_index: int, save: bool = True) -> bool:
        """把某张照片挪到指定位置。批量挪的时候把 save 关掉，最后统一存一次。"""
        idx = next((i for i, ph in enumerate(self.photos) if ph.id == pid), None)
        if idx is None:
            return False
        new_index = max(0, min(int(new_index), len(self.photos) - 1))
        if new_index == idx:
            return False
        ph = self.photos.pop(idx)
        self.photos.insert(new_index, ph)
        if save:
            self.save()
        return True

    # ---------------- 排序 / 分卷 ----------------
    def sorted_photos(self, mode: str = "added") -> list[Photo]:
        if mode == "filename":
            return sorted(self.photos, key=lambda p: natural_key(p.display_name))
        if mode == "taken":
            return sorted(self.photos,
                          key=lambda p: (p.taken is None, p.taken or "",
                                         natural_key(p.display_name)))
        return list(self.photos)      # added：保持导入顺序，用户可拖动调整

    def strip_chunks(self, mode: str = "added") -> list[list[Photo]]:
        per = max(1, int(self.photos_per_strip))
        ph = self.sorted_photos(mode)
        return [ph[i:i + per] for i in range(0, len(ph), per)]

    def strip_count(self, mode: str = "added") -> int:
        return len(self.strip_chunks(mode))


def list_projects(base_dir: Path) -> list[Path]:
    """列出目录下所有有效项目文件夹。"""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    return sorted((d for d in base.iterdir()
                   if d.is_dir() and (d / PROJECT_FILE).is_file()),
                  key=lambda p: natural_key(p.name))


# ---------------- 胶卷图存哪儿 ----------------
def strips_write_dir(project: Project, strips_root: str = "") -> Path:
    """新生成的胶卷图写到哪儿。

    strips_root 为空 → 项目文件夹里的 strips/（默认，项目自包含）
    有值 → <strips_root>/<项目名>/
    """
    return (Path(strips_root) / project.name) if strips_root else project.strips_dir


def strip_files_for(project: Project, strips_root: str = "") -> list[Path]:
    """这个项目的胶卷图文件，按文件名排好。

    配了 strips_root 就优先看那儿；**同时也看项目文件夹里的** ——
    改了设置之后之前生成的那些还在原处，两边都该显示出来。
    同名的以 strips_root 里的为准。
    """
    dirs: list[Path] = []
    if strips_root:
        dirs.append(Path(strips_root) / project.name)
    dirs.append(project.strips_dir)

    seen: dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("strip_*.jpg")):
            seen.setdefault(f.name, f)          # 前面的优先
    return [seen[k] for k in sorted(seen)]


def rename_project(root: Path, new_name: str, strips_root: str = "") -> Path:
    """改项目名，文件夹一起改。成功返回新路径，失败抛异常。

    动手之前先把能检查的都检查了；中途失败会尽量回滚，不留半改状态。
    """
    root = Path(root)
    new_name = str(new_name).strip()
    if not new_name:
        raise ValueError("项目名不能为空")
    if _ILLEGAL.search(new_name):
        raise ValueError('项目名不能包含 \\ / : * ? " < > | 这些字符')
    if new_name == root.name:
        raise ValueError("新名字跟原来一样")

    new_root = root.parent / new_name
    if new_root.exists():
        raise ValueError(f"「{new_name}」这个文件夹已经存在了")

    old_name = Project.load(root).name

    # 先改外面那层胶卷图目录，再改项目文件夹。
    # 万一半路失败，项目文件夹还没动，最坏只是胶卷图那层名字对不上。
    old_strips = (Path(strips_root) / old_name) if strips_root else None
    new_strips = (Path(strips_root) / new_name) if strips_root else None
    moved_strips = False
    if old_strips is not None and old_strips.is_dir() and not new_strips.exists():
        try:
            old_strips.rename(new_strips)
            moved_strips = True
        except OSError:
            moved_strips = False

    try:
        root.rename(new_root)
    except OSError:
        if moved_strips:
            try:
                new_strips.rename(old_strips)       # 回滚
            except OSError:
                pass
        raise

    project = Project.load(new_root)
    project.name = new_name
    project.save()
    return new_root
