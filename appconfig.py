"""赛博观片台 —— 应用级配置 + 暗盒库。

存在 `%APPDATA%\\CyberLightTable\\config.json` —— 放在这儿而不是项目目录里，
这样用户改项目目录时暗盒库不会跟着丢。

配置读不到或者写坏了，一律回退到默认值，**绝不能因此打不开程序**。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from project import DEFAULT_BASE_DIR

_APPDATA = Path(os.environ.get("APPDATA") or Path.home())
CONFIG_DIR = _APPDATA / "CyberLightTable"
CONFIG_FILE = CONFIG_DIR / "config.json"
# 改名前（叫「胶片总览图工具」时）的位置，第一次运行会自动搬过来
LEGACY_CONFIG_FILE = _APPDATA / "FilmStrip" / "config.json"

# 新建项目时用的默认值
DEFAULT_DEFAULTS = {
    "photos_per_strip": 40,
    "photos_per_row": 8,
    "fit_mode": "rotate",
    "canister": "kodak",
}

# 用户保存的暗盒长这样（颜色都是 "#rrggbb"，ink 空串表示自动配对比色）
CANISTER_FIELDS = ("id", "name", "label", "sub", "band", "body", "ink")

# 观片器镜外压暗多少（往黑里混的比例）
DEFAULT_LOUPE_DIM = 0.10
LOUPE_DIM_MIN, LOUPE_DIM_MAX = 0.0, 0.35

# 批量导出的默认目标文件夹（空 = 用户主目录）
DEFAULT_EXPORT_DIR = ""
# 生成的胶卷图存哪儿（空 = 存在项目文件夹里的 strips/，项目自包含）
DEFAULT_STRIPS_ROOT = ""


def new_id() -> str:
    return "u:" + uuid.uuid4().hex[:8]


class AppConfig:
    def __init__(self, path=None):
        # path 不写死成默认值，这样测试里可以改 appconfig.CONFIG_FILE
        self.path = Path(path) if path else Path(CONFIG_FILE)
        self.base_dir: Path = DEFAULT_BASE_DIR
        self.defaults: dict = dict(DEFAULT_DEFAULTS)
        self.canisters: list[dict] = []
        self.loupe_dim: float = DEFAULT_LOUPE_DIM
        self.export_dir: str = DEFAULT_EXPORT_DIR      # 导出目标文件夹，空=主目录
        self.strips_root: str = DEFAULT_STRIPS_ROOT    # 胶卷图存放根目录，空=项目里
        self.load()

    # ---------------- 读写 ----------------
    def load(self):
        """读配置。文件不在 / 读不动 / 内容坏了，都退回默认值。

        新位置没有、但旧位置（改名前叫 FilmStrip）有时，从旧位置读并搬过来 ——
        免得改个程序名就把用户之前存的暗盒和设置全弄丢。
        """
        self.base_dir = DEFAULT_BASE_DIR
        self.defaults = dict(DEFAULT_DEFAULTS)
        self.canisters = []
        self.loupe_dim = DEFAULT_LOUPE_DIM
        self.export_dir = DEFAULT_EXPORT_DIR
        self.strips_root = DEFAULT_STRIPS_ROOT

        src = self.path
        if not src.is_file() and LEGACY_CONFIG_FILE.is_file():
            src = LEGACY_CONFIG_FILE
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
        except Exception:
            return

        bd = raw.get("base_dir")
        if isinstance(bd, str) and bd.strip():
            self.base_dir = Path(bd)

        d = raw.get("defaults")
        if isinstance(d, dict):
            for k, v in DEFAULT_DEFAULTS.items():
                got = d.get(k)
                if isinstance(v, int) and isinstance(got, int) and not isinstance(got, bool):
                    self.defaults[k] = got
                elif isinstance(v, str) and isinstance(got, str) and got:
                    self.defaults[k] = got
        # 数字要合理，免得填个 0 或负数把分卷搞崩
        self.defaults["photos_per_strip"] = max(1, self.defaults["photos_per_strip"])
        self.defaults["photos_per_row"] = max(1, self.defaults["photos_per_row"])

        cs = raw.get("canisters")
        if isinstance(cs, list):
            seen = set()
            for c in cs:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if not isinstance(cid, str) or not cid or cid in seen:
                    continue
                seen.add(cid)
                self.canisters.append({k: c.get(k, "") for k in CANISTER_FIELDS})

        ld = raw.get("loupe_dim")
        if isinstance(ld, (int, float)) and not isinstance(ld, bool):
            self.loupe_dim = max(LOUPE_DIM_MIN, min(LOUPE_DIM_MAX, float(ld)))

        ed = raw.get("export_dir")
        if isinstance(ed, str):
            self.export_dir = ed.strip()
        sr = raw.get("strips_root")
        if isinstance(sr, str):
            self.strips_root = sr.strip()

        if src != self.path:
            self.save()          # 从旧位置读的，搬到新位置存一份

    def export_path(self) -> Path:
        """导出目标文件夹。没设就用用户主目录。"""
        return Path(self.export_dir) if self.export_dir else Path.home()

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "base_dir": str(self.base_dir),
                "defaults": dict(self.defaults),
                "canisters": [dict(c) for c in self.canisters],
                "loupe_dim": round(float(self.loupe_dim), 4),
                "export_dir": self.export_dir,
                "strips_root": self.strips_root,
            }
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception:
            return False

    # ---------------- 暗盒库 ----------------
    def find_canister(self, cid: str) -> dict | None:
        return next((c for c in self.canisters if c.get("id") == cid), None)

    def add_canister(self, data: dict) -> dict:
        """加一只暗盒，自动分配 id。"""
        item = {k: str(data.get(k, "")) for k in CANISTER_FIELDS}
        item["id"] = new_id()
        item["name"] = item["name"] or "未命名暗盒"
        self.canisters.append(item)
        self.save()
        return item

    def update_canister(self, cid: str, data: dict) -> bool:
        cur = self.find_canister(cid)
        if cur is None:
            return False
        for k in CANISTER_FIELDS:
            if k != "id" and k in data:
                cur[k] = str(data[k])
        self.save()
        return True

    def remove_canister(self, cid: str) -> bool:
        n = len(self.canisters)
        self.canisters = [c for c in self.canisters if c.get("id") != cid]
        if len(self.canisters) == n:
            return False
        self.save()
        return True

    def library(self) -> dict[str, dict]:
        """{id: 暗盒} —— 喂给 canister.resolve() 用。"""
        return {c["id"]: c for c in self.canisters if c.get("id")}
