"""输入状态管理 — 鼠标/键盘全局状态追踪 & 修饰键查询 API。

本模块独立于 Event 系统，只负责:
  1. 跟踪当前哪些按键/鼠标按钮被按住
  2. 跟踪修饰键 (Ctrl/Shift/Alt) 的按下/释放状态
  3. 提供组合键查询工具函数

依赖方向: InputState ← InputEvent.Pack() 更新状态, 不反向依赖。
"""

from Application.Core.Events.Enum.InputEnum import (
    KeyModifier, KeyButtonCode, KeyActionCode,
)


# ════════════════════════════════════════════════════════════════
# 鼠标状态 (由 MouseButtonEvent.Pack 更新)
# ════════════════════════════════════════════════════════════════

current_mouse_button_code: int = None    # 当前按住的鼠标按钮 (MouseButtonCode), None=无
button_press_pos_x: int = 0
button_press_pos_y: int = 0
button_release_pos_x: int = 0
button_release_pos_y: int = 0


# ════════════════════════════════════════════════════════════════
# 修饰键状态 (由 KeyboardButtonEvent.Pack 更新)
# ════════════════════════════════════════════════════════════════

_modifier_state: int = KeyModifier.NONE    # 当前按下的修饰键位掩码
_key_held: dict[int, bool] = {}            # 所有按键的按下状态: key_code → bool

# 修饰键 KeyCode → KeyModifier 掩码映射
_MODIFIER_KEY_MAP: dict[int, int] = {
    KeyButtonCode.LeftControl:  KeyModifier.CTRL,
    KeyButtonCode.RightControl: KeyModifier.CTRL,
    KeyButtonCode.LeftShift:    KeyModifier.SHIFT,
    KeyButtonCode.RightShift:   KeyModifier.SHIFT,
    KeyButtonCode.LeftAlt:      KeyModifier.ALT,
    KeyButtonCode.RightAlt:     KeyModifier.ALT,
}


# ════════════════════════════════════════════════════════════════
# 内部更新函数 (由 InputEvent 中的 Event.Pack 调用)
# ════════════════════════════════════════════════════════════════

def _update_modifier_state(key: int, pressed: bool) -> None:
    """内部: 根据修饰键的按下/释放更新全局状态。"""
    global _modifier_state
    mask = _MODIFIER_KEY_MAP.get(key)
    if mask is not None:
        if pressed:
            _modifier_state |= mask
        else:
            _modifier_state &= ~mask


def _set_key_held(key: int, held: bool) -> None:
    """内部: 更新按键按下状态。"""
    if held:
        _key_held[key] = True
    else:
        _key_held[key] = False


# ════════════════════════════════════════════════════════════════
# 标量状态 setter (供 InputEvent 跨模块修改, 避免 from-import 本地副本)
# ════════════════════════════════════════════════════════════════

def _set_mouse_button(button: int | None) -> None:
    """内部: 设置当前按住的鼠标按钮。"""
    global current_mouse_button_code
    current_mouse_button_code = button


def _set_button_press_pos(x: int, y: int) -> None:
    """内部: 记录鼠标按下位置。"""
    global button_press_pos_x, button_press_pos_y
    button_press_pos_x = x
    button_press_pos_y = y


def _set_button_release_pos(x: int, y: int) -> None:
    """内部: 记录鼠标释放位置。"""
    global button_release_pos_x, button_release_pos_y
    button_release_pos_x = x
    button_release_pos_y = y


# ════════════════════════════════════════════════════════════════
# 修饰键查询 API
# ════════════════════════════════════════════════════════════════

def IsCtrlPressed() -> bool:
    """Ctrl 键当前是否按下。"""
    return bool(_modifier_state & KeyModifier.CTRL)


def IsShiftPressed() -> bool:
    """Shift 键当前是否按下。"""
    return bool(_modifier_state & KeyModifier.SHIFT)


def IsAltPressed() -> bool:
    """Alt 键当前是否按下。"""
    return bool(_modifier_state & KeyModifier.ALT)


def GetModifierMask() -> int:
    """返回当前修饰键位掩码 (KeyModifier 组合值)。"""
    return _modifier_state


def IsKeyDown(key: int) -> bool:
    """检查任意按键是否当前被按住。

    Args:
        key: KeyButtonCode 枚举值
    """
    return _key_held.get(key, False)


def IsModifierKey(key: int) -> bool:
    """判断一个 KeyButtonCode 是否为修饰键 (Ctrl/Shift/Alt)。"""
    return key in _MODIFIER_KEY_MAP


def GetHeldKeys() -> list[int]:
    """返回当前所有被按住的非修饰键列表 (KeyButtonCode 值)。

    修饰键 (Ctrl/Shift/Alt) 会被过滤掉, 用 GetModifierMask() 查询。
    常用于状态栏显示 "Ctrl + G" 等组合提示。
    """
    return [k for k, v in _key_held.items() if v and k not in _MODIFIER_KEY_MAP]


# ════════════════════════════════════════════════════════════════
# 鼠标状态查询 (函数接口, 避免 from-import 标量本地副本)
# ════════════════════════════════════════════════════════════════

def IsMouseButtonDown() -> bool:
    """是否有鼠标按钮当前被按住。"""
    return current_mouse_button_code is not None


def GetMouseButtonCode() -> int | None:
    """返回当前按住的鼠标按钮代码 (MouseButtonCode), 无按下时返回 None。"""
    return current_mouse_button_code


def GetMouseButtonLabel() -> str:
    """返回当前按住的鼠标按钮的显示名称, 如 "Mouse Button 1"。无按下时返回空字符串。"""
    btn = current_mouse_button_code
    if btn is None:
        return ""
    return f"Mouse Button {btn + 1}"


def GetButtonPressPos() -> tuple[int, int]:
    """返回鼠标按下位置的 (x, y), 默认 (0, 0)。"""
    return button_press_pos_x, button_press_pos_y


def GetButtonReleasePos() -> tuple[int, int]:
    """返回鼠标释放位置的 (x, y), 默认 (0, 0)。"""
    return button_release_pos_x, button_release_pos_y


# ════════════════════════════════════════════════════════════════
# 组合键查询
# ════════════════════════════════════════════════════════════════

def IsComboJustPressed(key: int, modifiers: int) -> bool:
    """检查最近一次 KeyboardButtonEvent 是否匹配 键+修饰键 组合按下。

    使用事件自身的 mods 字段 (GLFW 传入), 与 KeyModifier 值兼容。
    仅在 Press 事件时返回 True, Release/Repeat 返回 False。

    Args:
        key:       目标键 (KeyButtonCode)
        modifiers: 期望的修饰键位掩码 (KeyModifier 组合)

    Example:
        if IsComboJustPressed(KeyButtonCode.Z, KeyModifier.CTRL):
            undo()  # Ctrl+Z 刚被按下
        if IsComboJustPressed(KeyButtonCode.W, KeyModifier.CTRL | KeyModifier.SHIFT):
            close_all()  # Ctrl+Shift+W
    """
    # 延迟导入避免循环依赖 (InputState ← InputEvent → InputState)
    from Application.Core.Events.InputEvent import KeyboardButtonEvent
    ev = KeyboardButtonEvent
    if ev.action != KeyActionCode.Press:
        return False
    if ev.key != key:
        return False
    # GLFW mods 字段与 KeyModifier 位值一致, 直接比较
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
