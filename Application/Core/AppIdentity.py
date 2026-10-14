"""应用身份与应用数据目录（FlyVibingEngine）。

三件事:
  1. 显示名 `APP_NAME` — 窗口标题 / 横幅 / 描述统一取自这里（或同名常量）。
  2. 数据目录 `%APPDATA%/FlyVibingEngine` — `data_dir()`；首次使用时把旧目录
     `%APPDATA%/MyGameEngine` 复制过来（**不删旧**，只在新目录不存在时迁移）。
  3. 环境变量双读 — `env_get("X")` 先读 `FVE_X`，回退 `MGE_X`（≥1 版本兼容；
     写入侧只写新名）。
"""

from __future__ import annotations

import os
import shutil

APP_NAME = "FlyVibingEngine"
LEGACY_APP_NAME = "MyGameEngine"

_ENV_PREFIXES = ("FVE_", "MGE_")     # 新名优先，旧名回退
_LEGACY_MIGRATED = False


def env_get(name: str, default: str | None = None) -> str | None:
    """读 `FVE_<name>`，回退 `MGE_<name>`（空串视为未设置）。"""
    for prefix in _ENV_PREFIXES:
        value = os.environ.get(prefix + name)
        if value:
            return value
    return default


def appdata_root() -> str:
    return os.environ.get("APPDATA") or os.path.expanduser("~")


def migrate_legacy_data_dir() -> str | None:
    """旧数据目录 → 新目录（复制，不删旧）。返回迁移后的新目录，无迁移则 None。"""
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED:
        return None
    _LEGACY_MIGRATED = True
    old = os.path.join(appdata_root(), LEGACY_APP_NAME)
    new = os.path.join(appdata_root(), APP_NAME)
    if os.path.isdir(old) and not os.path.exists(new):
        try:
            shutil.copytree(old, new)
            print(f"[AppIdentity] migrated data dir: {old} -> {new}")
            return new
        except OSError as e:            # noqa: BLE001 — 迁移失败不致命（旧目录仍在）
            print(f"[AppIdentity] data dir migration failed: {e!r}")
    return None


def data_dir(*parts: str) -> str:
    """应用数据目录（可按需拼子路径）；首次调用会触发旧目录迁移。"""
    base = env_get("DATA_DIR") or os.path.join(appdata_root(), APP_NAME)
    migrate_legacy_data_dir()
    return os.path.join(base, *parts) if parts else base
