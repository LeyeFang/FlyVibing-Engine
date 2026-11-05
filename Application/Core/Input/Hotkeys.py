"""Hotkey registry — 热键的唯一事实源（Help 面板 / CLI / 真实派发 同源）。

## 为什么存在

热键以前散落在三处，且互不知情：

  - `EditorInputLayer.OnEvent`  —— G / R / S（gizmo 模式）、Space（预览相机），事件式硬编码
  - 节点编辑器 `panel.py`        —— Delete（画布内删除）
  - `glfwWindow` / 运行时       —— Esc（关闭 PIE 窗口）

而主菜单里还挂着一批**没有实现的快捷键标注**（Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Z …）。
结果：人和 agent 都无法回答"现在按什么键会做什么"，也无法判断菜单里那些提示是真是假。

本模块把「键位 + 说明 + 动作」收在一处（**纯数据，不 import imgui** — Core 会进导出成品）：

  - `Help ▸ Hot Keys` 面板读 `all_hotkeys()` —— 纯展示，不可编辑
  - CLI `hotkeys.list` 读 `snapshot()`      —— agent 可发现
  - 真实按键：`Application/Editor/HotkeyDispatch.py` 的 `poll()` / `fired(id)`
    读同一条记录（Core 不依赖 UI 工具包，成品不带 imgui）

任何一处改动都会同时反映到另外两处，不可能漂移。

## 口径

- `kind="key"`   真实键盘绑定；`keys` 必须是可解析的和弦（`"Ctrl+Shift+S"` / `"G"` / `"Esc"`）
- `kind="mouse"` 鼠标操作提示（`"MMB drag"` / `"Wheel"`）—— 仅展示，不参与派发
- `dispatch="global"` → `poll()` 每帧自动派发（`impl` 必填）
- `dispatch="owner"`  → 由拥有者在自己语境里调 `fired(id)`（如节点编辑器焦点内的 Delete）
- `scope` ∈ `SCOPES`（editor / viewport / node_editor / pie）

## 测试

`Test/Application/Core/test_hotkeys.py` 锁定：键位可解析、同 scope 内和弦不重复、
每条都有 en/zh 说明、`global` 必带 `impl`、CLI op 与注册表同源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ── 作用域（面板分组顺序 = 此顺序）──────────────────────────────
SCOPES: dict[str, str] = {
    "editor": "hotkeys.scope.editor",
    "viewport": "hotkeys.scope.viewport",
    "node_editor": "hotkeys.scope.node_editor",
    "pie": "hotkeys.scope.pie",
}
SCOPE_ORDER: tuple[str, ...] = ("editor", "viewport", "node_editor", "pie")

_KINDS = ("key", "mouse")
_DISPATCH = ("global", "owner")

# ── 和弦解析 ────────────────────────────────────────────────────
_MOD_ORDER = ("ctrl", "shift", "alt", "super")
_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt", "option": "alt",
    "super": "super", "cmd": "super", "meta": "super", "win": "super",
}
_KEY_ALIASES = {
    "esc": "escape",
    "del": "delete",
    "return": "enter",
}


@dataclass(frozen=True)
class Hotkey:
    """一条热键记录（不可变 — 注册后不允许改键位）。"""

    id: str
    keys: str                 # 规范化后的键位文本（面板/CLI 直接显示）
    scope: str
    action: str               # 动作标识（稳定、可读；`action` 用于日志与 CLI 匹配）
    description_key: str      # i18n 键（`hotkey.<id>`；由解析器注入文案）
    kind: str = "key"         # key | mouse
    dispatch: str = "owner"   # global | owner
    impl: Callable | None = None


_REGISTRY: dict[str, Hotkey] = {}
_CHORDS: dict[tuple[str, tuple[str, ...]], str] = {}


# ════════════════════════════════════════════════════════════════
# 和弦（keys 文本）
# ════════════════════════════════════════════════════════════════

def parse_chord(text: str) -> tuple[str, tuple[str, ...]]:
    """`"Ctrl+Shift+S"` → `("s", ("ctrl", "shift"))`。非法输入 → ValueError。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty hotkey chord")
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty hotkey chord: {text!r}")
    raw_key = parts[-1].lower()
    key = _KEY_ALIASES.get(raw_key, raw_key)
    mods: list[str] = []
    for part in parts[:-1]:
        mod = _MOD_ALIASES.get(part.lower(), "")
        if not mod:
            raise ValueError(f"unknown modifier {part!r} in {text!r}")
        if mod not in mods:
            mods.append(mod)
    mods.sort(key=_MOD_ORDER.index)
    return key, tuple(mods)


def normalize(text: str) -> str:
    """和弦 → 展示用规范文本（`"ctrl+shift+s"` → `"Ctrl+Shift+S"`）。"""
    key, mods = parse_chord(text)
    return "+".join([m.capitalize() for m in mods] + [_key_label(key)])


def _key_label(key: str) -> str:
    """和弦键名 → 展示文本（单字母大写，其余首字母大写）。"""
    return key.upper() if len(key) == 1 else key.capitalize()


# ════════════════════════════════════════════════════════════════
# 注册
# ════════════════════════════════════════════════════════════════

def register(hotkey: Hotkey) -> Hotkey:
    """登记一条热键。重复 id / 同 scope 同和弦 / 非法字段 → ValueError（启动期即失败）。"""
    if not hotkey.id:
        raise ValueError("hotkey id must not be empty")
    if hotkey.id in _REGISTRY:
        raise ValueError(f"hotkey already registered: {hotkey.id!r}")
    if hotkey.scope not in SCOPES:
        raise ValueError(f"unknown hotkey scope {hotkey.scope!r} (see SCOPES)")
    if hotkey.kind not in _KINDS:
        raise ValueError(f"unknown hotkey kind {hotkey.kind!r}")
    if hotkey.dispatch not in _DISPATCH:
        raise ValueError(f"unknown dispatch {hotkey.dispatch!r}")
    if not hotkey.description_key:
        raise ValueError(f"hotkey {hotkey.id!r} needs a description_key")
    if hotkey.kind == "key":
        if hotkey.dispatch == "global" and hotkey.impl is None:
            raise ValueError(f"global hotkey {hotkey.id!r} needs an impl")
        _key, mods = parse_chord(hotkey.keys)
        chord_key = (hotkey.scope, tuple(sorted(mods)) + (_key,))
        owner = _CHORDS.get(chord_key)
        if owner is not None:
            raise ValueError(
                f"hotkey chord {hotkey.keys!r} already used in scope "
                f"{hotkey.scope!r} by {owner!r}")
        _CHORDS[chord_key] = hotkey.id
        hotkey = Hotkey(
            id=hotkey.id, keys=normalize(hotkey.keys), scope=hotkey.scope,
            action=hotkey.action, description_key=hotkey.description_key,
            kind=hotkey.kind, dispatch=hotkey.dispatch, impl=hotkey.impl,
        )
    _REGISTRY[hotkey.id] = hotkey
    return hotkey


def clear() -> None:
    """清空注册表 — 仅供测试（生产代码不应调用）。"""
    _REGISTRY.clear()
    _CHORDS.clear()


def get(hotkey_id: str) -> Hotkey | None:
    return _REGISTRY.get(str(hotkey_id))


def all_hotkeys(scope: str | None = None) -> list[Hotkey]:
    """全部热键（scope 顺序 → 键盘绑定在前 → 键位 → id）。"""
    rows = [hk for hk in _REGISTRY.values() if scope is None or hk.scope == scope]
    rows.sort(key=lambda hk: (SCOPE_ORDER.index(hk.scope)
                              if hk.scope in SCOPE_ORDER else len(SCOPE_ORDER),
                              hk.kind != "key",
                              hk.keys.lower(), hk.id))
    return rows


def snapshot(resolve: Callable[[str, str], str] | None = None,
             scope: str | None = None) -> list[dict]:
    """给面板 / CLI 用的扁平数据（`resolve(key, fallback)` 注入当前语言文案）。"""
    out: list[dict] = []
    for hk in all_hotkeys(scope):
        desc = resolve(hk.description_key, hk.action) if resolve else hk.action
        out.append({
            "id": hk.id,
            "scope": hk.scope,
            "keys": hk.keys,
            "action": hk.action,
            "description": desc,
            "description_key": hk.description_key,
            "kind": hk.kind,
            "dispatch": hk.dispatch,
        })
    return out


def resolve_key_name(name: str) -> str:
    """和弦键名别名归一（`esc` → `escape`；供编辑器侧的 ImGui 匹配器使用）。"""
    return _KEY_ALIASES.get(str(name or "").lower(), str(name or "").lower())


def is_dispatchable(hotkey: Hotkey) -> bool:
    """`dispatch=global` 的键位绑定（`poll()` 负责派发）。"""
    return hotkey.dispatch == "global" and hotkey.kind == "key" and hotkey.impl is not None
