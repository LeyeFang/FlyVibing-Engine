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

