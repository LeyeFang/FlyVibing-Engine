"""DeviceAliases — 逻辑设备名（`@name`）能力的**中立凭据层**（核心不实现它）。

背景（2026-11-14，O9 之后的同一类债）
------------------------------------
`Application/Core/DeviceRegistry.py` 是核心为**串并口扩展**写的实现：一个
`@mibox → COM5 @115200` 的机器侧台账。它被三处使用：

| 使用方 | 需要什么 |
|---|---|
| 串并口扩展的求值器 | `resolve()` 拿物理端点 |
| 节点编辑器 `serial_port` 控件 | 别名清单（下拉里出现 `@mibox`） |
| 离线校验器（无编辑器也能跑） | `get()` / `parse_ref()` 检查未绑定引用 |

于是核心被迫持有一个**只服务于一个扩展**的实现，还带着 183 行 IO/持久化代码。
按"引擎不依赖扩展"的规则，这里改成**依赖倒置**：

* 核心只保留**能力凭据**（本文件）：注册/查询一个 provider，缺席时安全降级；
* 实现归扩展（`SerialParallelDevice/device_registry.py`），导入时自注册；
* 编辑器/校验器通过本文件取数据 —— **不存在任何具体扩展的地址**。

缺席语义（与 `OptionalExtensions` 同一条纪律）：

| 情形 | 结果 |
|---|---|
| 没有 provider（该扩展不在本产物里） | `names()` → `[]`，`get()` → `None`；**不抛** |
| 有 provider，查询未绑定名 | 返回 `None`（校验器据此报"未绑定"） |
| 有 provider 且需要强解析（`resolve`） | provider 自己抛（未绑定绝不静默回退默认端口） |

产品侧影响：用了 `@alias` 的场景必然含该扩展的节点 → 扩展目录随包分发 → provider
存在；纯核心场景没有别名，`names()` 返回空，编辑器只显示物理端口。两边都正确。
"""

from __future__ import annotations

import threading

#: provider 必须实现的最小面（鸭子类型，无需继承）:
#:   names() -> list[str] | all() -> dict | get(name) -> dict|None
#:   describe(name) -> str | parse_ref(text) -> str | is_ref(text) -> bool
#:   resolve(text) -> dict
_PROVIDERS: dict[str, object] = {}
_lock = threading.Lock()


class DeviceAliasUnavailable(RuntimeError):
    """当前安装没有提供逻辑设备名能力的扩展。"""


# ── 注册 ──────────────────────────────────────────────────────

def register(provider_id: str, provider: object) -> str:
    """注册一个 provider（扩展在导入期自注册；幂等）。"""
    key = str(provider_id or "").strip() or "anonymous"
    if provider is None:
        raise ValueError("provider must not be None")
    with _lock:
        _PROVIDERS[key] = provider
    return key


def unregister(provider_id: str) -> bool:
    with _lock:
        return _PROVIDERS.pop(str(provider_id or ""), None) is not None


def provider():
    """当前 provider（多 provider 时取注册顺序第一个；无 → None）。"""
    with _lock:
        for value in _PROVIDERS.values():
            return value
    return None


def provider_id() -> str:
    with _lock:
        for key in _PROVIDERS:
            return key
    return ""


def available() -> bool:
    return provider() is not None


# ── 查询（缺席一律安全降级）────────────────────────────────────

def all() -> dict:
    """全部绑定（name → entry 副本）；无 provider → `{}`。"""
    fn = getattr(provider(), "all", None)
    if not callable(fn):
        return {}
    try:
        return dict(fn() or {})
    except Exception as exc:  # noqa: BLE001 — 台账坏了不该拖垮编辑器
        print(f"[DeviceAliases] provider.all() failed: {type(exc).__name__}: {exc}")
        return {}


def names() -> list:
    """已绑定的逻辑名（不含 `@`），已排序；无 provider → `[]`。"""
    fn = getattr(provider(), "names", None)
    if callable(fn):
        try:
            return sorted(str(n) for n in (fn() or ()))
        except Exception:  # noqa: BLE001
            pass
    return sorted(all().keys())


def get(name: str) -> dict | None:
    fn = getattr(provider(), "get", None)
    if not callable(fn):
        return None
    try:
        entry = fn(str(name or ""))
    except Exception:  # noqa: BLE001
        return None
    return dict(entry) if isinstance(entry, dict) else None


def describe(name: str) -> str:
    fn = getattr(provider(), "describe", None)
    if callable(fn):
        try:
            return str(fn(str(name or "")))
        except Exception:  # noqa: BLE001
            pass
    clean = parse_ref(name)
    return f"@{clean} -> (unbound)" if get(clean) is None else f"@{clean}"


def parse_ref(text: str) -> str:
    """`"@mibox"` → `"mibox"`（不做合法性校验；无 provider 也用核心规则）。"""
    fn = getattr(provider(), "parse_ref", None)
    if callable(fn):
        try:
            return str(fn(text))
        except Exception:  # noqa: BLE001
            pass
    value = str(text or "")
    return value[1:] if value.startswith("@") else value


def is_ref(text) -> bool:
    """`"@mibox"` → True；物理地址（`COM5` / `0x3FF8`）→ False。"""
    fn = getattr(provider(), "is_ref", None)
    if callable(fn):
        try:
            return bool(fn(text))
        except Exception:  # noqa: BLE001
            pass
    return isinstance(text, str) and text.startswith("@")


def resolve(text: str) -> dict:
    """强解析 `@name` → 端点 entry。

    provider 自己抛未绑定错误（绝不静默回退默认端口）；没有 provider 时抛
    `DeviceAliasUnavailable` —— 那是"这个产物根本没有该扩展"，调用方应当先查
    `is_ref()` 决定是否走这条路。
    """
    fn = getattr(provider(), "resolve", None)
    if not callable(fn):
        raise DeviceAliasUnavailable(
            f"device alias '@{parse_ref(text)}' cannot be resolved: no extension "
            f"provides device aliases in this installation/build")
    return dict(fn(str(text or "")) or {})


def status() -> dict:
    """诊断快照（`ext.device.status` / agent 排查用）。"""
    return {
        "available": available(),
        "provider": provider_id(),
        "aliases": ["@" + n for n in names()],
    }


__all__ = [
    "DeviceAliasUnavailable", "register", "unregister", "provider", "provider_id",
    "available", "all", "names", "get", "describe", "parse_ref", "is_ref",
    "resolve", "status",
]
