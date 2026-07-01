"""输入状态管理 — 每个 Engine 持有自己的 InputState 实例。

原先的模块级全局变量全部移入 InputState 类。
每个 Engine (EditorHost / GameRuntime) 在 _state() 中持有自己的 InputState 实例。

模块级便利函数 (IsShiftPressed 等) 读取 _default_input_state（默认为 EditorHost）。
InputEvent.Pack() 通过 engine= 参数路由到对应 Engine 的 InputState。
"""

from __future__ import annotations

from typing import Optional

from Application.Core.Events.Enum.InputEnum import (
    KeyModifier, KeyButtonCode, KeyActionCode,
)


# 修饰键 KeyCode → KeyModifier 掩码映射（与实例无关，保持在模块级）
_MODIFIER_KEY_MAP: dict[int, int] = {
    KeyButtonCode.LeftControl:  KeyModifier.CTRL,
    KeyButtonCode.RightControl: KeyModifier.CTRL,
    KeyButtonCode.LeftShift:    KeyModifier.SHIFT,
    KeyButtonCode.RightShift:   KeyModifier.SHIFT,
    KeyButtonCode.LeftAlt:      KeyModifier.ALT,
    KeyButtonCode.RightAlt:     KeyModifier.ALT,
}


# ════════════════════════════════════════════════════════════════
# InputState 类 — 每个 Engine 各自持有一个实例
# ════════════════════════════════════════════════════════════════

class InputState:
    """每个 Engine 独立的输入状态。

    由 Engine._get_input_state() 创建，存储在 Engine._state()['_input_state'] 中。
    """

    def __init__(self) -> None:
        # ── 鼠标状态 ──
        self.current_mouse_button_code: int | None = None
        self.button_press_pos_x: int = 0
        self.button_press_pos_y: int = 0
        self.button_release_pos_x: int = 0
        self.button_release_pos_y: int = 0
        # ── 修饰键 & 按键状态 ──
        self._modifier_state: int = KeyModifier.NONE
        self._key_held: dict[int, bool] = {}

    # ── 内部更新方法 (由 InputEvent.Pack 调用) ──

    def update_modifier_state(self, key: int, pressed: bool) -> None:
        """根据修饰键的按下/释放更新状态。"""
        mask = _MODIFIER_KEY_MAP.get(key)
        if mask is not None:
            if pressed:
                self._modifier_state |= mask
            else:
                self._modifier_state &= ~mask

    def set_key_held(self, key: int, held: bool) -> None:
        """更新按键按下状态。"""
        self._key_held[key] = held

    def set_mouse_button(self, button: int | None) -> None:
        """设置当前按住的鼠标按钮。"""
        self.current_mouse_button_code = button

    def set_button_press_pos(self, x: int, y: int) -> None:
        """记录鼠标按下位置。"""
        self.button_press_pos_x = x
        self.button_press_pos_y = y

    def set_button_release_pos(self, x: int, y: int) -> None:
        """记录鼠标释放位置。"""
        self.button_release_pos_x = x
        self.button_release_pos_y = y

    # ── 修饰键查询 ──

    def is_ctrl_pressed(self) -> bool:
        return bool(self._modifier_state & KeyModifier.CTRL)

    def is_shift_pressed(self) -> bool:
        return bool(self._modifier_state & KeyModifier.SHIFT)

    def is_alt_pressed(self) -> bool:
        return bool(self._modifier_state & KeyModifier.ALT)

    def get_modifier_mask(self) -> int:
        return self._modifier_state

    def is_key_down(self, key: int) -> bool:
        return self._key_held.get(key, False)

    def get_held_keys(self) -> list[int]:
        """返回所有被按住的非修饰键列表。"""
        return [k for k, v in self._key_held.items() if v and k not in _MODIFIER_KEY_MAP]

    # ── 鼠标状态查询 ──

    def is_mouse_button_down(self) -> bool:
        return self.current_mouse_button_code is not None

    def get_mouse_button_code(self) -> int | None:
        return self.current_mouse_button_code

    def get_mouse_button_label(self) -> str:
        btn = self.current_mouse_button_code
        if btn is None:
            return ""
        return f"Mouse Button {btn + 1}"

    def get_button_press_pos(self) -> tuple[int, int]:
        return self.button_press_pos_x, self.button_press_pos_y

    def get_button_release_pos(self) -> tuple[int, int]:
        return self.button_release_pos_x, self.button_release_pos_y


# ════════════════════════════════════════════════════════════════
# 默认 InputState（由 Engine.init() 设为首个 Engine 的实例）
# 模块级便利函数从此读取，保证现有的 EditorLayer/UIManager 代码无需改动。
# ════════════════════════════════════════════════════════════════

_default_input_state: Optional[InputState] = None


def _set_default_input_state(state: InputState) -> None:
    """设置默认 InputState（由 Engine.init 调用）。"""
    global _default_input_state
    _default_input_state = state


def _get_default_input_state() -> Optional[InputState]:
    """获取默认 InputState（供 InputEvent 等模块使用，避免直接 import 变量）。"""
    return _default_input_state


# ── 修饰键查询 API ──

def IsCtrlPressed() -> bool:
    return _default_input_state.is_ctrl_pressed() if _default_input_state else False


def IsShiftPressed() -> bool:
    return _default_input_state.is_shift_pressed() if _default_input_state else False


def IsAltPressed() -> bool:
    return _default_input_state.is_alt_pressed() if _default_input_state else False


def GetModifierMask() -> int:
    return _default_input_state.get_modifier_mask() if _default_input_state else KeyModifier.NONE


def IsKeyDown(key: int) -> bool:
    return _default_input_state.is_key_down(key) if _default_input_state else False


def IsModifierKey(key: int) -> bool:
    return key in _MODIFIER_KEY_MAP


def GetHeldKeys() -> list[int]:
    return _default_input_state.get_held_keys() if _default_input_state else []


# ── 鼠标状态查询 API ──

def IsMouseButtonDown() -> bool:
    return _default_input_state.is_mouse_button_down() if _default_input_state else False


def GetMouseButtonCode() -> int | None:
    return _default_input_state.get_mouse_button_code() if _default_input_state else None


def GetMouseButtonLabel() -> str:
    return _default_input_state.get_mouse_button_label() if _default_input_state else ""


def GetButtonPressPos() -> tuple[int, int]:
    return _default_input_state.get_button_press_pos() if _default_input_state else (0, 0)


def GetButtonReleasePos() -> tuple[int, int]:
    return _default_input_state.get_button_release_pos() if _default_input_state else (0, 0)


# ════════════════════════════════════════════════════════════════
# 组合键查询（依赖 InputEvent 类级别缓存）
# ════════════════════════════════════════════════════════════════

def IsComboJustPressed(key: int, modifiers: int) -> bool:
    """检查最近一次 KeyboardButtonEvent 是否匹配 键+修饰键 组合按下。"""
    from Application.Core.Events.InputEvent import KeyboardButtonEvent
    ev = KeyboardButtonEvent
    if ev.action != KeyActionCode.Press:
        return False
    if ev.key != key:
        return False
    return (ev.mods & (KeyModifier.CTRL | KeyModifier.SHIFT | KeyModifier.ALT)) == modifiers


def IsComboDown(key: int, modifiers: int) -> bool:
    """检查 键+修饰键 组合当前是否按住 (持久状态查询)。

    与 IsComboJustPressed 不同: 本方法检查实时按住状态,
    适用于连续操作 (如拖拽时检测 Shift 是否按住以启用吸附)。

    Args:
        key:       目标键 (KeyButtonCode)
        modifiers: 期望的修饰键位掩码 (KeyModifier 组合)
    """
    return IsKeyDown(key) and (_modifier_state == modifiers)


def GetMouseModifiers() -> int:
    """返回最近一次鼠标事件发生时的修饰键位掩码。

    用于鼠标拖拽/点击时判断是否同时按住了 Ctrl/Shift/Alt。
    返回值直接兼容 KeyModifier 枚举。

    Example:
        if GetMouseModifiers() & KeyModifier.SHIFT:
            snap_to_grid()  # Shift+拖拽 → 吸附
    """
    from Application.Core.Events.InputEvent import MouseButtonEvent
    return MouseButtonEvent._last_mods
