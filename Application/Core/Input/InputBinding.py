"""输入绑定解析 — 节点属性里的键/鼠标按钮/修饰键名称 → 代码/位掩码。

放在 Core 层，供节点求值器与 RuntimeInputLayer 共用，避免 Core 反向依赖
Runtime 或 Editor。
"""

from __future__ import annotations

from typing import Any

from Application.Core.Events.Enum.InputEnum import (
    KeyButtonCode,
    KeyModifier,
    MouseButtonCode,
)


_KEY_ALIASES: dict[str, int] = {
    "space": int(KeyButtonCode.Space),
    "escape": int(KeyButtonCode.Escape),
    "esc": int(KeyButtonCode.Escape),
    "enter": int(KeyButtonCode.Enter),
    "return": int(KeyButtonCode.Enter),
    "tab": int(KeyButtonCode.Tab),
    "backspace": int(KeyButtonCode.Backspace),
    "delete": int(KeyButtonCode.Delete),
    "left": int(KeyButtonCode.Left),
    "right": int(KeyButtonCode.Right),
    "up": int(KeyButtonCode.Up),
    "down": int(KeyButtonCode.Down),
    "shift": int(KeyButtonCode.LeftShift),
    "ctrl": int(KeyButtonCode.LeftControl),
    "control": int(KeyButtonCode.LeftControl),
    "alt": int(KeyButtonCode.LeftAlt),
    "leftshift": int(KeyButtonCode.LeftShift),
    "rightshift": int(KeyButtonCode.RightShift),
    "leftctrl": int(KeyButtonCode.LeftControl),
    "rightctrl": int(KeyButtonCode.RightControl),
    "leftcontrol": int(KeyButtonCode.LeftControl),
    "rightcontrol": int(KeyButtonCode.RightControl),
    "leftalt": int(KeyButtonCode.LeftAlt),
    "rightalt": int(KeyButtonCode.RightAlt),
}
for _i in range(10):
    _KEY_ALIASES[str(_i)] = int(KeyButtonCode.Num0) + _i
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _KEY_ALIASES[_ch.lower()] = int(getattr(KeyButtonCode, _ch))
for _i in range(1, 13):
    _KEY_ALIASES[f"f{_i}"] = int(getattr(KeyButtonCode, f"F{_i}"))


def resolve_key_code(value: Any, default: int = int(KeyButtonCode.Space)) -> int:
    """把 "Space" / "A" / 32 / KeyButtonCode.Space 解析为 GLFW key code。"""
    if isinstance(value, KeyButtonCode):
        return int(value)
    if isinstance(value, int):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return int(default)
    try:
        return int(text, 0)
    except ValueError:
        pass
    low = text.lower()
    if low in _KEY_ALIASES:
        return _KEY_ALIASES[low]
    try:
        return int(KeyButtonCode[text])
    except KeyError:
        return int(default)


def resolve_key_name(value: Any) -> str:
    code = resolve_key_code(value)
    if int(KeyButtonCode.Num0) <= code <= int(KeyButtonCode.Num9):
        return str(code - int(KeyButtonCode.Num0))
    try:
        return KeyButtonCode(code).name
    except ValueError:
        return str(code)


def resolve_mod_mask(value: Any) -> int:
    """解析 "any" / "none" / "Shift" / "Ctrl+Shift" / 3 → 位掩码。

    返回 -1 表示 any（不限制）。
    """
    if isinstance(value, int):
        return int(value)
    text = str(value or "").strip().lower()
    if not text or text == "any":
        return -1
    if text == "none":
        return 0
    mask = 0
    for part in text.replace("|", "+").replace(",", "+").split("+"):
        part = part.strip()
        if part in ("shift", "shft"):
            mask |= int(KeyModifier.SHIFT)
        elif part in ("ctrl", "control"):
            mask |= int(KeyModifier.CTRL)
        elif part in ("alt",):
            mask |= int(KeyModifier.ALT)
    return mask


def resolve_mod_name(value: Any) -> str:
    mask = resolve_mod_mask(value)
    if mask < 0:
        return "any"
    if mask == 0:
        return "none"
    parts = []
    if mask & int(KeyModifier.CTRL):
        parts.append("Ctrl")
    if mask & int(KeyModifier.SHIFT):
        parts.append("Shift")
    if mask & int(KeyModifier.ALT):
        parts.append("Alt")
    return "+".join(parts) or "none"


def resolve_mouse_button(value: Any, default: int = int(MouseButtonCode.Left)) -> int:
    if isinstance(value, MouseButtonCode):
        return int(value)
    if isinstance(value, int):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return int(default)
    low = text.lower()
    if low in ("any", "*"):
        return -1
    try:
        return int(text, 0)
    except ValueError:
        pass
    for name in ("Left", "Right", "Middle", "Button4", "Button5",
                 "Button6", "Button7", "Button8"):
        if low == name.lower():
            return int(getattr(MouseButtonCode, name))
    try:
        return int(MouseButtonCode[text])
    except KeyError:
        return int(default)


def resolve_mouse_button_name(value: Any) -> str:
    code = resolve_mouse_button(value)
    if code < 0:
        return "any"
    try:
        return MouseButtonCode(code).name
    except ValueError:
        return str(code)
