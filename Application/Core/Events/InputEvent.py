"""输入事件定义 — 鼠标/键盘/滚轮事件的 Pack/unpack (实例级别)。

状态追踪由 Application.Core.Input.InputState 负责,
本模块仅保留事件类本身, Pack 时调用 InputState 更新全局状态。

注意:
  - MouseGragEvent._last_x / _last_y: 类级别持久追踪状态 (非事件数据)
  - MouseButtonEvent._last_mods:      类级别缓存, 供 InputState.GetMouseModifiers() 读取
"""

from Application.Core.Events.Event import Event
from Application.Core.Events.Enum.InputEnum import *
from Application.Core.Input.InputState import (
    InputState,
    _get_default_input_state,
)


#
#
# Input Events
class MouseMoveEvent(Event):
    """鼠标移动事件 — 每次光标位置变化时触发 (无论按钮状态)。"""

    def __init__(self, pos_x: int, pos_y: int) -> None:
        super().__init__()
        self.pos_x: int = pos_x
        self.pos_y: int = pos_y

    @classmethod
    def Pack(cls, pos_x: int, pos_y: int, **kwargs) -> None:
        super().Pack(pos_x, pos_y, **kwargs)

    def unpack(self) -> tuple[int, int]:
        return self.pos_x, self.pos_y


class MouseGragEvent(Event):
    """鼠标拖拽事件 — 按住按钮时移动触发。

    类级别追踪状态 (非事件数据):
        _last_x, _last_y: 上一帧鼠标位置, 用于计算位移增量。
        由 MouseButtonEvent.Pack 在按下时初始化, 由 Pack 在每帧更新。
    """

    _last_x: int = 0   # 持久追踪状态 (非事件数据)
    _last_y: int = 0   # 持久追踪状态 (非事件数据)

    def __init__(self, offset_x: int, offset_y: int, press_button: int,
                 pos_x: int = 0, pos_y: int = 0) -> None:
        super().__init__()
        self.offset_x: int = offset_x
        self.offset_y: int = offset_y
        self.press_button: int = press_button
        self.pos_x: int = pos_x      # 当前鼠标绝对坐标 (供 gizmo 拖拽等使用)
        self.pos_y: int = pos_y

    @property
    def log_info(self) -> str:
        return (
            f"Mouse Grag Button={MouseButtonCode[self.press_button]}, "
            f"Offset=({self.offset_x}, {self.offset_y}), "
            f"Pos=({self.pos_x}, {self.pos_y})"
        )

    @classmethod
    def Pack(cls, pos_x: int, pos_y: int, **kwargs) -> None:
        # 读取当前 Engine 的 InputState 判断是否有按钮按下
        engine = kwargs.get('engine')
        inp = engine._get_input_state() if engine is not None else _get_default_input_state()
        btn = inp.current_mouse_button_code if inp is not None else None
        if btn is not None:
            instance = cls(
                offset_x=pos_x - cls._last_x,
                offset_y=pos_y - cls._last_y,
                press_button=btn,
                pos_x=pos_x,
                pos_y=pos_y,
            )
            cls._last_x = pos_x
            cls._last_y = pos_y
            cls._dispatch(instance, engine=engine)

    def unpack(self) -> tuple[int, int, int]:
        return self.press_button, self.offset_x, self.offset_y


class MouseButtonEvent(Event):
    """鼠标按钮事件 — 按下/释放时触发。

    类级别缓存:
        _last_mods: 最近一次按钮事件的修饰键掩码,
                    供 InputState.GetMouseModifiers() 读取。
    """

    _last_mods: int = 0   # 类级别缓存, 供 GetMouseModifiers() 使用

    def __init__(self, button: int, action: int, mods: int, pos_x: int, pos_y: int) -> None:
        super().__init__()
        self.button: int = button
        self.action: int = action
        self.mods: int = mods
        self.pos_x: int = pos_x
        self.pos_y: int = pos_y

    @property
    def log_info(self) -> str:
        return f"Mouse Button={MouseButtonCode[self.button]}, Action={MouseActionCode[self.action]}"

    @classmethod
    def Pack(
        cls,
        button: int,
        action: int,
        mods: int,
        pos_x: int,
        pos_y: int,
        **kwargs
    ) -> None:
        cls._last_mods = mods
        # 获取当前 Engine 的 InputState
        engine = kwargs.get('engine')
        inp = engine._get_input_state() if engine is not None else _get_default_input_state()
        if action == MouseActionCode.Press:
            if inp: inp.set_mouse_button(button)
            if inp: inp.set_button_press_pos(pos_x, pos_y)
            MouseGragEvent._last_x = pos_x
            MouseGragEvent._last_y = pos_y
        elif action == MouseActionCode.Release:
            if inp: inp.set_mouse_button(None)
            if inp: inp.set_button_release_pos(pos_x, pos_y)
        super().Pack(button, action, mods, pos_x, pos_y, **kwargs)

    def unpack(self) -> tuple:
        return self.button, self.action, self.mods, self.pos_x, self.pos_y


class KeyboardButtonEvent(Event):
    """键盘按钮事件 — 按下/释放/重复时触发。"""

    def __init__(self, key: int, scancode: int, action: int, mods: int) -> None:
        super().__init__()
        self.key: int = key
        self.scancode: int = scancode
        self.action: int = action
        self.mods: int = mods

    @property
    def log_info(self) -> str:
        return f"Key Button Code={KeyButtonCode[self.key]} Action={KeyActionCode[self.action]}"

    @classmethod
    def Pack(cls, key: int, scancode: int, action: int, mods: int, **kwargs) -> None:
        # ── 更新当前 Engine 的按键状态 & 修饰键状态 ──
        engine = kwargs.get('engine')
        inp = engine._get_input_state() if engine is not None else _get_default_input_state()
        if action == KeyActionCode.Press:
            if inp: inp.set_key_held(key, True)
            if inp: inp.update_modifier_state(key, True)
        elif action == KeyActionCode.Release:
            if inp: inp.set_key_held(key, False)
            if inp: inp.update_modifier_state(key, False)
        # Repeat 不改变状态
        super().Pack(key, scancode, action, mods, **kwargs)

    def unpack(self) -> tuple:
        return self.key, self.scancode, self.action, self.mods


class ScrollerEvent(Event):
    """滚轮事件 — 滚轮滚动时触发。"""

    def __init__(self, x_offset: int, y_offset: int) -> None:
        super().__init__()
        self.x_offset: int = x_offset
        self.y_offset: int = y_offset

    @property
    def log_info(self) -> str:
        return f"Scroll offset x={self.x_offset}, y={self.y_offset}"

    @classmethod
    def Pack(cls, x_offset: int, y_offset: int, **kwargs) -> None:
        super().Pack(x_offset, y_offset, **kwargs)

    def unpack(self) -> tuple[int, int]:
        return self.x_offset, self.y_offset


