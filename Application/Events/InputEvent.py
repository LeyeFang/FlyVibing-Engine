from Application.Events.Event import Event

from Application.Events.Enum.InputEnum import *


#
#
# Input Events
class MouseMoveEvent(Event):
    pos_x: int = 0
    pos_y: int = 0

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return cls.pos_x, cls.pos_y


class MouseButtonEvent(Event):
    button: int = 0
    action: int = 0
    mods: int = 0

    @classmethod
    def Pack(
        cls,
        button: int,
        action: int,
        mods: int
    ) -> None:
        cls.button = button
        cls.action = action
        cls.mods = mods
        cls.log_info = f"Mouse Button={MouseButtonCode[button]}, Action={MouseActionCode[action]}"
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

