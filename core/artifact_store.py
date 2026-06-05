# -*- coding: utf-8 -*-
"""
core/artifact_store.py — 运行产物归档工具
"""

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import json
import re


def to_jsonable(value):
    """将 dataclass / Enum / 容器递归转换为 JSON 可写结构。"""
    if is_dataclass(value):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


def slugify(text: str, fallback: str = "analysis") -> str:
    """生成适合目录名的产品标识，保留中英文、数字、下划线和短横线。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (text or "").strip())
    slug = slug.strip("_-")
    return (slug or fallback)[:60]


class ArtifactStore:
    """每次分析运行的文件归档目录。"""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._saved_files: list[str] = []

    @classmethod
    def create_for_product(cls, output_root: str | Path, product_name: str) -> "ArtifactStore":
        runs_dir = Path(output_root) / "runs"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{timestamp}_{slugify(product_name)}"
        run_dir = runs_dir / base_name

        suffix = 2
        while run_dir.exists():
            run_dir = runs_dir / f"{base_name}_{suffix}"
            suffix += 1

        return cls(run_dir)

    def path(self, name: str) -> Path:
        return self.run_dir / name

    def save_json(self, name: str, data) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(to_jsonable(data), f, ensure_ascii=False, indent=2)
        self._record(name)
        return path

    def save_text(self, name: str, text: str) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._record(name)
        return path

    def saved_files(self) -> list[str]:
        return list(self._saved_files)

    def _record(self, name: str):
        if name not in self._saved_files:
            self._saved_files.append(name)
