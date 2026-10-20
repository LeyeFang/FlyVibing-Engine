"""DeviceRegistry — 逻辑设备名 → 物理端点 的**机器侧**注册表（跨机器迁移的核心）。

问题（2026-10-12 立项）: 场景/节点里存的是**物理地址**（`COM3` / `LPT1` / 品牌序列号），
换一台电脑插同一个设备 → 口号变了 → 实验悄悄发错端口或打不开；而面板里的端口又是另一份
真相。解法 = 两级身份:

  - **逻辑设备名**（`@mibox`）进场景（节点 props）—— 实验设计不依赖机器;
  - **物理端点**留在本机（本文件）—— `@mibox → COM5 @115200`，换机器重绑一次即可;
  - 未绑定 → **显式报错**（`DeviceUnresolved`），绝不静默回退默认端口。

存储: `%APPDATA%/MyGameEngine/devices.json`（env `MGE_DEVICES_FILE` 覆盖 — 测试沙箱）。
条目字段（全部可选, 由各 transport 约定）:
    {"transport": "serial", "port": "COM5", "baud": 115200,
     "hint": {"usb_serial": "AB12CD", "vid_pid": "1a86:7523"},   # 自动重绑线索
     "updated": "2026-10-12T18:00:00"}

协议: `Doc/Dev/device_io_protocol.md` §10（设备别名与跨机器迁移）。
"""

from __future__ import annotations

from Application.Core import AppIdentity

import json
import os
import re
import threading
import time

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")


class DeviceUnresolved(RuntimeError):
    """逻辑设备名在本机未绑定（或缺少必需端点字段）。"""


_data: dict = {}          # name → entry dict
_loaded: bool = False
_lock = threading.Lock()


# ── 路径 / 读写 ────────────────────────────────────────────────

def path() -> str:
    """注册表文件路径（env `MGE_DEVICES_FILE` 覆盖 — 测试沙箱/便携部署）。"""
    env = AppIdentity.env_get("DEVICES_FILE")
    if env:
        return env
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return AppIdentity.data_dir("devices.json")


def load(force: bool = False) -> dict:
    """载入注册表（缺文件/损坏 → 空表 + 告警; 永不抛错）。"""
    global _loaded
    with _lock:
        if _loaded and not force:
            return dict(_data)
        data: dict = {}
        try:
            with open(path(), encoding="utf-8-sig") as fh:
                raw = json.load(fh)
            entries = raw.get("devices") if isinstance(raw, dict) else None
            if isinstance(entries, dict):
                data = {str(k): dict(v) for k, v in entries.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001 — 坏注册表不致命
            print(f"[DeviceRegistry] load failed ({path()}): {e!r}")
        _data.clear()
        _data.update(data)
        _loaded = True
        return dict(_data)


def _save() -> None:
    p = path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        payload = {"version": 1, "devices": dict(sorted(_data.items()))}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)                      # 原子替换（避免半截文件）
    except Exception as e:  # noqa: BLE001
        print(f"[DeviceRegistry] save failed ({p}): {e!r}")


# ── 引用语法 (`@name`) ─────────────────────────────────────────

def is_ref(text: str) -> bool:
    """`"@mibox"` → True; 物理地址（`COM5`）→ False。"""
    return isinstance(text, str) and text.startswith("@")


def parse_ref(text: str) -> str:
    """去掉 `@` 得到逻辑名（不做合法性校验）。"""
    return text[1:] if is_ref(text) else text


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


# ── 查询 ──────────────────────────────────────────────────────

def get(name: str) -> dict | None:
    load()
    with _lock:
        entry = _data.get(parse_ref(name))
        return dict(entry) if entry else None


def all() -> dict:
    """全部绑定（name → entry 副本）。"""
    load()
    with _lock:
        return {k: dict(v) for k, v in _data.items()}


def resolve(text: str) -> dict:
    """解析 `@name` → 端点 entry; 未绑定 → `DeviceUnresolved`（含可操作提示）。"""
    name = parse_ref(text)
    entry = get(name)
    if entry is None:
        raise DeviceUnresolved(
            f"device '@{name}' is not bound on this machine — bind it in the "
            f"Serial/Parallel panel (or via ext.device.bind_alias name={name} port=COMx) "
            f"[registry: {path()}]")
    return entry


def describe(name: str) -> str:
    """人类可读状态（面板/日志用）: `@mibox -> COM5 @115200` / `@mibox -> (unbound)`。"""
    entry = get(name)
    if entry is None:
        return f"@{parse_ref(name)} -> (unbound)"
    endpoint = entry.get("port") or entry.get("address") or entry.get("serial") or "?"
    baud = entry.get("baud")
    return f"@{parse_ref(name)} -> {endpoint}" + (f" @{baud}" if baud else "")


# ── 写入 ──────────────────────────────────────────────────────

def bind(name: str, **fields) -> dict:
    """绑定/更新逻辑名（合并字段）。name 非法 → ValueError。"""
    clean = parse_ref(str(name or "").strip())
    if not valid_name(clean):
        raise ValueError(f"invalid device name '@{clean}' (要求 ^[A-Za-z][A-Za-z0-9_.-]{{0,31}}$)")
    load()
    with _lock:
        entry = dict(_data.get(clean) or {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _data[clean] = entry
    _save()
    return dict(entry)


def unbind(name: str) -> bool:
    """解绑（返回是否确实存在）。"""
    clean = parse_ref(str(name or "").strip())
    load()
    with _lock:
        existed = _data.pop(clean, None) is not None
    if existed:
        _save()
    return existed


def set_hint(name: str, **hint) -> dict:
    """更新自动重绑线索（usb_serial / vid_pid …）。"""
    load()
    with _lock:
        clean = parse_ref(name)
        entry = dict(_data.get(clean) or {})
        h = dict(entry.get("hint") or {})
        h.update({k: v for k, v in hint.items() if v})
        entry["hint"] = h
        _data[clean] = entry
    _save()
    return dict(entry)


def _reset_for_tests() -> None:
    """清空内存态（不动文件）—— 测试隔离用。"""
    global _loaded
    with _lock:
        _data.clear()
        _loaded = False
