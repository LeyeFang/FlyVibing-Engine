"""输入事件定义 — 鼠标/键盘/滚轮事件的 Pack/UnPack。

状态追踪已移入 Application.Core.Input.InputState,
本模块仅保留事件类本身, Pack 时调用 InputState 更新全局状态。
"""

from Application.Core.Events.Event import Event
from Application.Core.Events.Enum.InputEnum import *

# ── 状态层 (所有可变状态 & 查询函数移入此模块) ──
from Application.Core.Input.InputState import (
    _key_held,
    _update_modifier_state, _set_key_held,
    _set_mouse_button, _set_button_press_pos, _set_button_release_pos,
    # 读取 MouseGragEvent.last_x/y 时不需要 setter (直接引用)
)


#
#
# Input Events
class MouseGragEvent(Event):
    last_x: int = 0
    last_y: int = 0
    press_button: int = 0
    offset_x: int = 0
    offset_y: int = 0

    @classmethod
    def Pack(
        cls,
        pos_x: int,
        pos_y: int
    ) -> None:
        # current_mouse_button_code 由 MouseButtonEvent 通过 _set_mouse_button 维护
        from Application.Core.Input.InputState import current_mouse_button_code
        if current_mouse_button_code is not None:
            cls.log_info = f"Mouse Grag Button={MouseButtonCode[current_mouse_button_code]}, Offset=({cls.offset_x, cls.offset_y})"
            cls.offset_x = pos_x - cls.last_x
            cls.offset_y = pos_y - cls.last_y
            cls.last_x = pos_x
            cls.last_y = pos_y
            cls.press_button = current_mouse_button_code
            super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int, int, int]:
        return cls.press_button, cls.offset_x, cls.offset_y


class MouseButtonEvent(Event):
    pos_x: int = 0
    pos_y: int = 0
    button: int = 0
    action: int = 0
    mods: int = 0

    @classmethod
    def Pack(
        cls,
        button: int,
        action: int,
        mods: int,
        pos_x: int,
        pos_y: int
    ) -> None:
        cls.button = button
        cls.action = action
        cls.mods = mods
        cls.log_info = f"Mouse Button={MouseButtonCode[button]}, Action={MouseActionCode[action]}"
        if action == MouseActionCode.Press:
            _set_mouse_button(button)
            _set_button_press_pos(pos_x, pos_y)
            MouseGragEvent.last_x = pos_x
            MouseGragEvent.last_y = pos_y
        elif action == MouseActionCode.Release:
            _set_mouse_button(None)
            _set_button_release_pos(pos_x, pos_y)
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return


class KeyboardButtonEvent(Event):

    key: int
    scancode: int
    action: int
    mods: int

    @classmethod
    def Pack(
        cls,
        key,
        scancode,
        action,
        mods
    ) -> None:
        cls.key = key
        cls.scancode = scancode
        cls.action = action
        cls.mods = mods
        cls.log_info = f"Key Button Code={KeyButtonCode[key]} Action={KeyActionCode[action]}"
        # ── 更新全局按键状态 & 修饰键状态 (委托 InputState) ──
        if action == KeyActionCode.Press:
            _set_key_held(key, True)
            _update_modifier_state(key, True)
        elif action == KeyActionCode.Release:
            _set_key_held(key, False)
            _update_modifier_state(key, False)
        # Repeat 不改变状态
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return


class ScrollerEvent(Event):

    x_offset: int = 0
    y_offset: int = 0

    @classmethod
    def Pack(
        cls,
        x_offset: int,
        y_offset: int
    ) -> None:
        cls.x_offset = x_offset
        cls.y_offset = y_offset
        cls.log_info = f"Scroll offset x={x_offset}, y={y_offset}"
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int, int]:
        return cls.x_offset, cls.y_offset


