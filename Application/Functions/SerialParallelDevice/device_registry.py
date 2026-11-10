"""DeviceRegistry — 逻辑设备名 → 物理端点 的**机器侧**台账（扩展自持实现）。

迁移背景（2026-11-10 主线耦合审计 §4.1 / §8.1-2，方案 3.1a）:
  台账此前住在 `Application.Core.DeviceRegistry`（核心为串并口扩展而写）。
  按"引擎不依赖扩展"的依赖倒置原则，本模块是扩展侧的**正式实现**：
    - 过渡期（核心模块仍存在）: 公开函数**整体委托**给核心实现，
      编辑器通用端口下拉 / 离线校验器仍读核心模块 → 两边看到同一份状态；
    - 核心模块被主线删除后: 本模块自动接管，无需再改扩展代码。

语义与存储**保持不变**（用户机器上已有绑定数据）:
  - 路径: `AppIdentity.data_dir("devices.json")`（`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 可覆盖）
  - 格式: `{"version": 1, "devices": {name: entry}}`
  - `@name` 引用；未绑定 → `DeviceUnresolved`（**绝不静默回退**）
  - 条目字段全部可选，由各 transport 约定:
    `{"transport": "serial", "port": "COM5", "baud": 115200,
      "hint": {"usb_serial": "AB12CD", "vid_pid": "1A86:7523"}, "updated": "..."}`

协议: `engine-editor-cli doc show dev/device_io_protocol#10`（设备别名与跨机器迁移）。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from Application.Core import AppIdentity

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")

try:
    # 过渡期复用核心异常类型：调用方（含既有测试）按类名捕获仍然成立。
    from Application.Core.DeviceRegistry import DeviceUnresolved as DeviceUnresolved
except Exception:  # noqa: BLE001 — 核心模块已移除时启用自持异常
    class DeviceUnresolved(RuntimeError):
        """逻辑设备名在本机未绑定（或缺少必需端点字段）。"""


# ── 过渡期后端探测 ───────────────────────────────────────────

_legacy = None
_legacy_probed = False
_MISSING = object()

_local_data: dict = {}          # name → entry dict
_local_loaded: bool = False
_local_lock = threading.Lock()


def _legacy_module():
    """核心台账模块（存在则委托；不存在/不可用 → None）。"""
    global _legacy, _legacy_probed
    if not _legacy_probed:
        _legacy_probed = True
        try:
            from Application.Core import DeviceRegistry as mod
        except Exception:  # noqa: BLE001 — 已移出核心或依赖不可用
            mod = None
        _legacy = mod
    return _legacy


def backend() -> str:
    """当前生效实现: `"core"`（过渡委托）/ `"extension"`（自持）。

    供 `ext.device.status` 与迁移回执取证使用；不参与业务逻辑。
    """
    mod = _legacy_module()
    return "core" if mod is not None and callable(getattr(mod, "resolve", None)) else "extension"


def _delegate(name: str, *args, **kwargs):
    mod = _legacy_module()
    fn = getattr(mod, name, None) if mod is not None else None
    if not callable(fn):
        return _MISSING
    return fn(*args, **kwargs)


# ── 路径 / 读写 ──────────────────────────────────────────────

def path() -> str:
    """注册表文件路径（env `*_DEVICES_FILE` 覆盖 — 测试沙箱/便携部署）。"""
    result = _delegate("path")
    if result is not _MISSING:
        return result
    env = AppIdentity.env_get("DEVICES_FILE")
    if env:
        return env
    return AppIdentity.data_dir("devices.json")


def load(force: bool = False) -> dict:
    """载入台账（缺文件/损坏 → 空表 + 告警；永不抛错）。"""
    result = _delegate("load", force)
    if result is not _MISSING:
        return result
    global _local_loaded
    with _local_lock:
        if _local_loaded and not force:
            return dict(_local_data)
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
        _local_data.clear()
        _local_data.update(data)
        _local_loaded = True
        return dict(_local_data)


def _local_save() -> None:
    p = path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        payload = {"version": 1, "devices": dict(sorted(_local_data.items()))}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)                  # 原子替换（避免半截文件）
    except Exception as e:  # noqa: BLE001
        print(f"[DeviceRegistry] save failed ({p}): {e!r}")


# ── 引用语法 (`@name`) ─────────────────────────────────────────

def is_ref(text: str) -> bool:
    """`"@mibox"` → True；物理地址（`COM5`）→ False。"""
    result = _delegate("is_ref", text)
    if result is not _MISSING:
        return bool(result)
    return isinstance(text, str) and text.startswith("@")


def parse_ref(text: str) -> str:
    """去掉 `@` 得到逻辑名（不做合法性校验）。"""
    result = _delegate("parse_ref", text)
    if result is not _MISSING:
        return str(result)
    return text[1:] if _is_ref_local(text) else text


def _is_ref_local(text: str) -> bool:
    """自持实现的引用判定（避免过渡期 parse_ref 递归委托）。"""
    return isinstance(text, str) and text.startswith("@")


def valid_name(name: str) -> bool:
    result = _delegate("valid_name", name)
    if result is not _MISSING:
        return bool(result)
    return bool(_NAME_RE.match(name or ""))


# ── 查询 ──────────────────────────────────────────────────────

def get(name: str) -> dict | None:
    result = _delegate("get", name)
    if result is not _MISSING:
        return result
    load()
    with _local_lock:
        entry = _local_data.get(_local_parse(name))
        return dict(entry) if entry else None


def all() -> dict:
    """全部绑定（name → entry 副本）。"""
    result = _delegate("all")
    if result is not _MISSING:
        return result
    load()
    with _local_lock:
        return {k: dict(v) for k, v in _local_data.items()}


def resolve(text: str) -> dict:
    """解析 `@name` → 端点 entry；未绑定 → `DeviceUnresolved`（含可操作提示）。"""
    result = _delegate("resolve", text)
    if result is not _MISSING:
        return result
    name = _local_parse(text)
    entry = get(name)
    if entry is None:
        raise DeviceUnresolved(
            f"device '@{name}' is not bound on this machine — bind it in the "
            f"Serial/Parallel panel (or via ext.device.bind_alias name={name} port=COMx) "
            f"[registry: {path()}]")
    return entry


def describe(name: str) -> str:
    """人类可读状态（面板/日志用）: `@mibox -> COM5 @115200` / `@mibox -> (unbound)`。"""
    result = _delegate("describe", name)
    if result is not _MISSING:
        return result
    entry = get(name)
    if entry is None:
        return f"@{_local_parse(name)} -> (unbound)"
    endpoint = entry.get("port") or entry.get("address") or entry.get("serial") or "?"
    baud = entry.get("baud")
    return f"@{_local_parse(name)} -> {endpoint}" + (f" @{baud}" if baud else "")


# ── 写入 ──────────────────────────────────────────────────────

def bind(name: str, **fields) -> dict:
    """绑定/更新逻辑名（合并字段）。name 非法 → ValueError。"""
    result = _delegate("bind", name, **fields)
    if result is not _MISSING:
        return result
    clean = _local_parse(str(name or "").strip())
    if not valid_name(clean):
        raise ValueError(f"invalid device name '@{clean}' (要求 ^[A-Za-z][A-Za-z0-9_.-]{{0,31}}$)")
    load()
    with _local_lock:
        entry = dict(_local_data.get(clean) or {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _local_data[clean] = entry
    _local_save()
    return dict(entry)


def unbind(name: str) -> bool:
    """解绑（返回是否确实存在）。"""
    result = _delegate("unbind", name)
    if result is not _MISSING:
        return bool(result)
    clean = _local_parse(str(name or "").strip())
    load()
    with _local_lock:
        existed = _local_data.pop(clean, None) is not None
    if existed:
        _local_save()
    return existed


def set_hint(name: str, **hint) -> dict:
    """更新自动重绑线索（usb_serial / vid_pid …）。"""
    result = _delegate("set_hint", name, **hint)
    if result is not _MISSING:
        return result
    load()
    with _local_lock:
        clean = _local_parse(name)
        entry = dict(_local_data.get(clean) or {})
        hints = dict(entry.get("hint") or {})
        hints.update({k: v for k, v in hint.items() if v})
        entry["hint"] = hints
        _local_data[clean] = entry
    _local_save()
    return dict(entry)


def _reset_for_tests() -> None:
    """清空内存态（不动文件）—— 测试隔离用。"""
    result = _delegate("_reset_for_tests")
    if result is not _MISSING:
        return result
    global _local_loaded
    with _local_lock:
        _local_data.clear()
        _local_loaded = False


def _local_parse(text: str) -> str:
    """自持实现的 `@` 解析（不经过委托）。"""
    return text[1:] if _is_ref_local(text) else text
