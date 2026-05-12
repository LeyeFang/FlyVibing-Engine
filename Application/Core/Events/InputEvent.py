from Application.Core.Events.Event import Event

from Application.Core.Events.Enum.InputEnum import *


#
#
# Mouse State
left_is_press: bool = False
right_is_press: bool = False
mid_is_press: bool = False
current_mouse_button_code: int = None
button_press_pos_x: int = 0
button_press_pos_y: int = 0


#
#
# Input Events
class MouseGragEvent(Event):
    last_x: int = 0
    last_y: int = 0
    offset_x: int = 0
    offset_y: int = 0

    @classmethod
    def Pack(
        cls,
        pos_x: int,
        pos_y: int
    ) -> None:
        global current_mouse_button_code
        if current_mouse_button_code is not None:
            cls.log_info = f"Mouse Grag Button={MouseButtonCode[current_mouse_button_code]}, Offset=({cls.offset_x, cls.offset_y})"
            cls.offset_x = pos_x - cls.last_x
            cls.offset_y = pos_y - cls.last_y
            cls.last_x = pos_x
            cls.last_y = pos_y
            super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return cls.pos_x, cls.pos_y


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
        global current_mouse_button_code, button_press_pos_y, button_press_pos_x
        cls.button = button
        cls.action = action
        cls.mods = mods
        cls.log_info = f"Mouse Button={MouseButtonCode[button]}, Action={MouseActionCode[action]}"
        if action == MouseActionCode.Press:
            current_mouse_button_code = button
            button_press_pos_x = pos_x
            button_press_pos_y = pos_y
            MouseGragEvent.last_x = pos_x
            MouseGragEvent.last_y = pos_y
        elif action == MouseActionCode.Release:
            current_mouse_button_code = None
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

