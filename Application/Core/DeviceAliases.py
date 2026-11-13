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

## 惰性发现（`ensure()`，2026-11-14）

"provider 在导入时自注册"有一个副作用：**没人导入就没有 provider**。离线校验器
（`flyvibing_node_editor`，不启用扩展）与"用户停用了该扩展"的编辑器都会因此拿不到
别名 —— 而台账本身是**机器侧数据**，与扩展启停无关（旧的 `Core.DeviceRegistry`
正是直接读文件，所以一直能用）。

所以核心按**声明**发现，仍然不认识任何具体扩展名：

```json
"device_aliases": { "module": "device_registry", "dir": "." }
```

首次查询时扫描 `Application/Functions/*/extension.json` 与用户扩展目录，读这个键，
按**包限定名**导入模块（`Application.Functions.<Folder>.<module>`，与扩展自己的
import 路径一致 → 只有一个模块对象、一份缓存），然后校验它确实注册了。没有这个键的
扩展不参与。失败只告警，不影响任何调用方。

产品侧影响：用了 `@alias` 的场景必然含该扩展的节点 → 扩展目录随包分发 → provider
存在；纯核心场景没有别名，`names()` 返回空，编辑器只显示物理端口。两边都正确。
"""

from __future__ import annotations

import importlib
import json
import os
import threading

#: manifest 里声明"本扩展提供设备别名能力"的键
SPEC_KEY = "device_aliases"

#: provider 必须实现的最小面（鸭子类型，无需继承）:
#:   names() -> list[str] | all() -> dict | get(name) -> dict|None
#:   describe(name) -> str | parse_ref(text) -> str | is_ref(text) -> bool
#:   resolve(text) -> dict
_PROVIDERS: dict[str, object] = {}
_lock = threading.Lock()
_discovery_attempted = False


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


def _app_dir() -> str:
    """`<Application>`（本文件在 `Core/`）—— 不依赖 `Application.__file__`（命名空间包下为 None）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _declared_providers() -> list[tuple]:
    """扫描 manifest 声明 → `[("Application.Functions.<Folder>.<module>", abs_dir)]`。

    只读 JSON，**不 import**；解析顺序稳定（排序后遍历），所以多 provider 时行为确定。
    找不到用户的扩展目录时不报错（编辑器之外的场景很常见）。
    """
    roots: list[str] = [os.path.join(_app_dir(), "Functions")]
    try:
        from Application.Core import AppIdentity

        user_root = (AppIdentity.env_get("EXTENSIONS_DIR")
                     or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                                     AppIdentity.APP_NAME, "extensions"))
        roots.append(user_root)
    except Exception:  # noqa: BLE001 — 没有 AppIdentity 就只扫引擎内
        pass

    out: list[tuple] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            folder = os.path.join(root, name)
            manifest = os.path.join(folder, "extension.json")
            if not os.path.isfile(manifest):
                continue
            try:
                data = json.load(open(manifest, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            spec = data.get(SPEC_KEY) if isinstance(data, dict) else None
            if not isinstance(spec, dict):
                continue
            module = str(spec.get("module") or "").strip()
            if not module:
                continue
            rel = str(spec.get("dir") or "").strip()
            directory = os.path.abspath(os.path.join(folder, rel) if rel else folder)
            qualified = f"Application.Functions.{name}.{module}"
            out.append((qualified, directory))
    return out


def _raw_provider():
    """已注册的 provider（**不触发发现** —— 发现过程本身要用它，否则递归）。"""
    with _lock:
        for value in _PROVIDERS.values():
            return value
    return None


def ensure() -> bool:
    """确保 provider 已就绪（惰性发现；幂等，最多尝试一次）。返回是否可用。

    为什么按声明发现而不是按名字 import：核心不能认识任何具体扩展（见 O9）。
    为什么按**包限定名**导入：与扩展自己的 `from Application.Functions.X import Y`
    是同一个模块对象，只有一份内存缓存 —— 否则两个模块对象各缓存一份台账，
    面板写、编辑器读时会出现"刚绑的别名看不到"。
    """
    global _discovery_attempted
    if _raw_provider() is not None:
        return True
    if _discovery_attempted:
        return False
    _discovery_attempted = True
    for qualified, directory in _declared_providers():
        try:
            if not os.path.isdir(directory):
                continue
            import sys

            if directory not in sys.path:
                sys.path.insert(0, directory)
            importlib.import_module(qualified)
        except Exception as exc:  # noqa: BLE001 — 单个坏 provider 不影响他人
            print(f"[DeviceAliases] provider {qualified} unavailable: "
                  f"{type(exc).__name__}: {exc}")
            continue
        if _raw_provider() is not None:
            return True
    return _raw_provider() is not None


def provider():
    """当前 provider（多 provider 时取注册顺序第一个；无 → None）。"""
    raw = _raw_provider()
    if raw is not None:
        return raw
    ensure()
    return _raw_provider()


def provider_id() -> str:
    provider()
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
    "SPEC_KEY", "DeviceAliasUnavailable", "register", "unregister", "ensure",
    "provider", "provider_id", "available", "all", "names", "get", "describe",
    "parse_ref", "is_ref", "resolve", "status",
]
