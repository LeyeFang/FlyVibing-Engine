"""Core/Input — 输入状态管理 (键盘/鼠标/修饰键追踪 & 查询)。

Usage:
    from Application.Core.Input import (
        IsCtrlPressed, IsShiftPressed, IsKeyDown,
        GetModifierMask, GetHeldKeys,
        IsComboJustPressed, IsComboDown, GetMouseModifiers,
        IsMouseButtonDown, GetMouseButtonLabel,
    )
"""

from Application.Core.Input.InputState import *
from Application.Core.Input.InputBinding import (
    resolve_key_code, resolve_key_name,
    resolve_mod_mask, resolve_mod_name,
    resolve_mouse_button, resolve_mouse_button_name,
)
from Application.Core.Input.Gesture import (
    CLICK_MOVE_THRESHOLD, is_click, moved,
)

