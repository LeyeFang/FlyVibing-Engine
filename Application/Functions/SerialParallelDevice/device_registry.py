"""DeviceRegistry — 逻辑设备名 → 物理端点 的**机器侧**台账（本扩展自持实现）。

归属（2026-11-14 完成迁移）
--------------------------
台账原先住在 `Application.Core.DeviceRegistry`（核心为一个扩展写的 183 行实现）。
按"引擎不依赖扩展"的规则，实现现在**只在这里**：

* 核心只保留**能力凭据** `Application.Core.DeviceAliases`（注册/查询，缺席安全降级）；
* 本模块在导入时自注册（`DeviceAliases.register("device", ...)`），于是
  节点编辑器的端口下拉、离线校验器、`SerialSend` 求值器看到的都是同一份状态；
* 产物里没有本扩展 → 没人注册 → 核心返回空清单，编辑器只显示物理端口（正确形态）。

语义与存储**保持不变**（用户机器上已有绑定数据）:
  - 路径: `AppIdentity.data_dir("devices.json")`（`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 可覆盖）
  - 格式: `{"version": 1, "devices": {name: entry}}`
  - `@name` 引用；未绑定 → `DeviceUnresolved`（**绝不静默回退默认端口**）
  - 条目字段全部可选，由各 transport 约定:
    `{"transport": "serial", "port": "COM5", "baud": 115200,
      "hint": {"usb_serial": "AB12CD", "vid_pid": "1A86:7523"}, "updated": "..."}`

协议: `engine-editor-cli doc show dev/device_io_protocol#10`（设备别名与跨机器迁移）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

from Application.Core import AppIdentity

try:  # 核心能力凭据（2026-11-14+）。旧引擎没有它 → 跳过自注册，台账本身照常工作。
    from Application.Core import DeviceAliases as _Aliases
    _ALIAS_CAPABILITY = "Application.Core.DeviceAliases"
except Exception:  # noqa: BLE001 — 跨版本兼容: 旧引擎（api_version 1 早期）无能力层
    _Aliases = None
    _ALIAS_CAPABILITY = ""

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")

_data: dict = {}          # name → entry dict
_loaded: bool = False
_lock = threading.Lock()


class DeviceUnresolved(RuntimeError):
    """逻辑设备名在本机未绑定（或缺少必需端点字段）。"""


# ── 路径 / 读写 ──────────────────────────────────────────────

def path() -> str:
    """台账文件路径（env `*_DEVICES_FILE` 覆盖 — 测试沙箱/便携部署）。"""
    env = AppIdentity.env_get("DEVICES_FILE")
    if env:
        return env
    return AppIdentity.data_dir("devices.json")


def load(force: bool = False) -> dict:
    """载入台账（缺文件/损坏 → 空表 + 告警；永不抛错）。"""
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
        except Exception as e:  # noqa: BLE001 — 坏台账不致命
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
        os.replace(tmp, p)                  # 原子替换（避免半截文件）
    except Exception as e:  # noqa: BLE001
        print(f"[DeviceRegistry] save failed ({p}): {e!r}")


# ── 引用语法 (`@name`) ─────────────────────────────────────────

def is_ref(text) -> bool:
    """`"@mibox"` → True；物理地址（`COM5`）→ False。"""
    return isinstance(text, str) and text.startswith("@")


def parse_ref(text: str) -> str:
    """去掉 `@`（不做合法性校验）。"""
    value = str(text or "")
    return value[1:] if value.startswith("@") else value


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


def names() -> list:
    """已绑定的逻辑名（不含 `@`），已排序。"""
    return sorted(all().keys())


def resolve(text: str) -> dict:
    """解析 `@name` → 端点 entry；未绑定 → `DeviceUnresolved`（含可操作提示）。"""
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
        hints = dict(entry.get("hint") or {})
        hints.update({k: v for k, v in hint.items() if v})
        entry["hint"] = hints
        _data[clean] = entry
    _save()
    return dict(entry)


def _reset_for_tests() -> None:
    """清空内存态（不动文件）—— 测试隔离用。"""
    global _loaded
    with _lock:
        _data.clear()
        _loaded = False


def backend() -> str:
    """实现来源（诊断用）。迁移完成后永远是 `"extension"`。"""
    return "extension"


def capability() -> str:
    """核心能力凭据模块的限定名；旧引擎无该模块时返回 `""`（诊断用）。"""
    return _ALIAS_CAPABILITY


def capability_status() -> dict:
    """核心能力凭据的视角（`available / provider / aliases`）—— 诊断用。

    面板/op 只调这个函数，**不直接 import `Application.Core`**（层级边界；
    也让旧引擎（无能力层）能安全降级为 `available=False`）。
    """
    if _Aliases is None:
        return {"available": False, "provider": "", "aliases": [], "capability": ""}
    try:
        snap = dict(_Aliases.status())
    except Exception as e:  # noqa: BLE001 — 诊断接口不把头错误传染给面板
        return {"available": False, "provider": "", "aliases": [],
                "capability": _ALIAS_CAPABILITY,
                "error": f"{type(e).__name__}: {e}"}
    snap.setdefault("capability", _ALIAS_CAPABILITY)
    return snap


# ── 自注册为核心的别名能力提供者 ─────────────────────────────
# 导入即注册：求值器 / 编辑器 / 离线校验器都不需要"启用扩展"就能看到同一份台账。
# 旧引擎没有 `Application.Core.DeviceAliases` → 上面已降级为 None，此处跳过。
if _Aliases is not None:
    _Aliases.register("device", sys.modules[__name__])
