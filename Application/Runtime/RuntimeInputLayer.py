"""RuntimeInputLayer — GameRuntime 输入采集层。

职责:
  - 主/渲染线程接收窗口输入事件，写入线程安全队列；
  - 逻辑线程每帧 `drain_frame()` 得到不可变 `RuntimeInputFrame`；
  - RuntimeNodeLayer 用该快照触发 OnKeyPressed / OnKeyReleased /
    OnMouseClicked 事件节点；
  - 鼠标点击语义 = 按下后释放位移 <= 6px；拖拽只保留 press/release，
    不会误触发 OnMouseClicked；
  - 数据节点 IsKeyDown / IsMouseButtonDown / GetMousePosition 读取 ctx.input。

设计边界:
  - 层本身不依赖 Editor；PIE 与导出成品共用；
  - 不直接操作 ECS/GL，只提供输入快照；
  - 事件默认不 consume，让 Debug/Overlay/引擎继续看到；ESC 关闭决策
    通过 `exit_on_escape` + `WindowCloseEvent.consumed` 实现。

层顺序:
  - 事件派发是栈顶→栈底，`RuntimeInputLayer` 应最后 push（最上层），
    保证 DebugLayer/Overlay 不会先吞掉键鼠事件；
  - OnUpdate 的顺序不重要：由 RuntimeNodeLayer 主动 drain。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from Application.Core.Events.Enum.InputEnum import (
    KeyActionCode,
    MouseActionCode,
)
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import (
    KeyboardButtonEvent,
    MouseButtonEvent,
    MouseGragEvent,
    MouseMoveEvent,
    ScrollerEvent,
)
from Application.Core.Events.WindowEvent import WindowCloseEvent
from Application.Core.Input.Gesture import is_click
from Application.Core.Input.InputBinding import (
    resolve_key_code,
    resolve_mouse_button,
)
from Application.Core.Layers.Layer import Layer


# ═══════════════════════════════════════════════════════════════
# 不可变输入记录/快照
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InputEventRecord:
    """一条输入事件（逻辑线程只读）。"""
    kind: str                    # key_press / key_release / key_repeat /
                                 # mouse_press / mouse_release / mouse_click / scroll
    key: int = 0
    button: int = 0
    action: int = 0
    mods: int = 0
    x: int = 0
    y: int = 0
    scroll_x: int = 0
    scroll_y: int = 0


@dataclass(frozen=True)
class RuntimeInputFrame:
    """单帧输入快照 — 事件 + 当前持续状态。"""
    key_presses: tuple[InputEventRecord, ...] = ()
    key_releases: tuple[InputEventRecord, ...] = ()
    key_repeats: tuple[InputEventRecord, ...] = ()
    mouse_presses: tuple[InputEventRecord, ...] = ()
    mouse_releases: tuple[InputEventRecord, ...] = ()
    # click = 原地按下+释放；drag 只出现在 press/release，不在 clicks。
    mouse_clicks: tuple[InputEventRecord, ...] = ()
    scrolls: tuple[InputEventRecord, ...] = ()
    mouse_x: int = 0
    mouse_y: int = 0
    held_keys: frozenset[int] = frozenset()
    mouse_buttons: frozenset[int] = frozenset()

    @property
    def has_events(self) -> bool:
        return bool(
            self.key_presses or self.key_releases or self.key_repeats
            or self.mouse_presses or self.mouse_releases or self.mouse_clicks
            or self.scrolls
        )

    def is_key_down(self, key: int) -> bool:
        return int(key) in self.held_keys

    def is_mouse_button_down(self, button: int) -> bool:
        return int(button) in self.mouse_buttons


# ═══════════════════════════════════════════════════════════════
# RuntimeInputLayer
# ═══════════════════════════════════════════════════════════════

class RuntimeInputLayer(Layer):
    """输入采集层 — 只缓存事件，由 RuntimeNodeLayer 在逻辑帧 drain。"""

    _lock = threading.Lock()
    _queue: list[InputEventRecord] = []
    _held_keys: set[int] = set()
    _mouse_buttons: set[int] = set()
    # 鼠标按下起点（用于区分 click 与 drag；右键拖拽不能触发 click）
    _mouse_press_pos: dict[int, tuple[int, int]] = {}
    _mouse_x: int = 0
    _mouse_y: int = 0
    _active: bool = False

    # ── ESC 策略 ──
    # True: ESC 触发的 WindowCloseEvent 继续传递 → 引擎退出；
    # False: 输入层 consume 关闭事件，交给节点/弹窗自行处理。
    exit_on_escape: bool = True

    _MAX_QUEUE = 4096

    # ════════════════════════════════════════════════════════════
    # Layer 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls) -> None:
        cls._reset_state()
        cls._active = True

    @classmethod
    def OnDetach(cls) -> None:
        cls._active = False
        cls._reset_state()

    @classmethod
    def OnUpdate(cls) -> None:
        # 队列由 RuntimeNodeLayer 主动 drain；这里保持空实现。
        pass

    @classmethod
    def OnRender(cls) -> None:
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        if not cls._active:
            return

        if isinstance(event, KeyboardButtonEvent):
            cls._on_key(event.key, event.action, event.mods)
            return

        if isinstance(event, MouseButtonEvent):
            cls._on_mouse_button(event.button, event.action, event.mods,
                                 event.pos_x, event.pos_y)
            return

        if isinstance(event, MouseMoveEvent):
            cls._on_mouse_move(event.pos_x, event.pos_y)
            return

        if isinstance(event, MouseGragEvent):
            cls._on_mouse_move(event.pos_x, event.pos_y)
            return

        if isinstance(event, ScrollerEvent):
            cls._push(InputEventRecord(
                kind="scroll",
                x=cls._mouse_x, y=cls._mouse_y,
                scroll_x=int(event.x_offset), scroll_y=int(event.y_offset),
            ))
            return

        if isinstance(event, WindowCloseEvent):
            # 默认保留 ESC 安全退出；工程关闭此策略时由节点处理 ESC。
            if getattr(event, "source", "window") == "escape" and not cls.exit_on_escape:
                event.consume()
            return

    # ════════════════════════════════════════════════════════════
    # 策略 / 注入
    # ════════════════════════════════════════════════════════════

    @classmethod
    def set_escape_exit(cls, enabled) -> None:
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ("", "0", "false", "no", "off")
        cls.exit_on_escape = bool(enabled)

    @classmethod
    def inject_key(cls, key, action: int = KeyActionCode.Press,
                   mods: int = 0) -> None:
        """注入键盘事件（Utils 虚拟输入 / 测试用）。key 可为名称或代码。"""
        cls._on_key(resolve_key_code(key), int(action), int(mods))

    @classmethod
    def inject_mouse_move(cls, x: int, y: int) -> None:
        cls._on_mouse_move(int(x), int(y))

    @classmethod
    def inject_mouse_button(cls, button,
                            action: int = MouseActionCode.Press,
                            mods: int = 0, x: int | None = None,
                            y: int | None = None) -> None:
        cls._on_mouse_button(
            resolve_mouse_button(button), int(action), int(mods),
            cls._mouse_x if x is None else int(x),
            cls._mouse_y if y is None else int(y),
        )

    @classmethod
    def inject_scroll(cls, x_offset: int, y_offset: int) -> None:
        with cls._lock:
            cls._push_locked(InputEventRecord(
                kind="scroll", x=cls._mouse_x, y=cls._mouse_y,
                scroll_x=int(x_offset), scroll_y=int(y_offset),
            ))

    # ════════════════════════════════════════════════════════════
    # 逻辑线程接口
    # ════════════════════════════════════════════════════════════

    @classmethod
    def drain_frame(cls) -> RuntimeInputFrame:
        """取走队列并生成快照；无事件时仍返回当前鼠标/按住状态。"""
        with cls._lock:
            records = cls._queue
            cls._queue = []
            pressed = tuple(r for r in records if r.kind == "key_press")
            released = tuple(r for r in records if r.kind == "key_release")
            repeated = tuple(r for r in records if r.kind == "key_repeat")
            mouse_pressed = tuple(r for r in records if r.kind == "mouse_press")
            mouse_released = tuple(r for r in records if r.kind == "mouse_release")
            mouse_clicked = tuple(r for r in records if r.kind == "mouse_click")
            scrolls = tuple(r for r in records if r.kind == "scroll")
            return RuntimeInputFrame(
                key_presses=pressed,
                key_releases=released,
                key_repeats=repeated,
                mouse_presses=mouse_pressed,
                mouse_releases=mouse_released,
                mouse_clicks=mouse_clicked,
                scrolls=scrolls,
                mouse_x=cls._mouse_x,
                mouse_y=cls._mouse_y,
                held_keys=frozenset(cls._held_keys),
                mouse_buttons=frozenset(cls._mouse_buttons),
            )

    @classmethod
    def current_frame(cls) -> RuntimeInputFrame:
        """不取走队列的当前快照（诊断用）。"""
        with cls._lock:
            return RuntimeInputFrame(
                mouse_x=cls._mouse_x,
                mouse_y=cls._mouse_y,
                held_keys=frozenset(cls._held_keys),
                mouse_buttons=frozenset(cls._mouse_buttons),
            )

    @classmethod
    def reset(cls) -> None:
        cls._reset_state()

    # ════════════════════════════════════════════════════════════
    # 内部
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _reset_state(cls) -> None:
        with cls._lock:
            cls._queue = []
            cls._held_keys = set()
            cls._mouse_buttons = set()
            cls._mouse_press_pos.clear()
            cls._mouse_x = 0
            cls._mouse_y = 0

    @classmethod
    def _on_key(cls, key: int, action: int, mods: int) -> None:
        with cls._lock:
            if action == KeyActionCode.Press:
                cls._held_keys.add(int(key))
                kind = "key_press"
            elif action == KeyActionCode.Release:
                cls._held_keys.discard(int(key))
                kind = "key_release"
            elif action == KeyActionCode.Repeat:
                kind = "key_repeat"
            else:
                return
            cls._push_locked(InputEventRecord(
                kind=kind, key=int(key), action=int(action), mods=int(mods),
                x=cls._mouse_x, y=cls._mouse_y,
            ))

    @classmethod
    def _on_mouse_button(cls, button: int, action: int, mods: int,
                         x: int, y: int) -> None:
        with cls._lock:
            cls._mouse_x = int(x)
            cls._mouse_y = int(y)
            if action == MouseActionCode.Press:
                cls._mouse_buttons.add(int(button))
                cls._mouse_press_pos[int(button)] = (int(x), int(y))
                kind = "mouse_press"
            elif action == MouseActionCode.Release:
                cls._mouse_buttons.discard(int(button))
                kind = "mouse_release"
                start = cls._mouse_press_pos.pop(int(button), None)
                if start is not None and is_click(start, (int(x), int(y))):
                    cls._push_locked(InputEventRecord(
                        kind="mouse_click", button=int(button),
                        action=int(MouseActionCode.Release), mods=int(mods),
                        x=int(x), y=int(y),
                    ))
            else:
                return
            cls._push_locked(InputEventRecord(
                kind=kind, button=int(button), action=int(action),
                mods=int(mods), x=int(x), y=int(y),
            ))

    @classmethod
    def _on_mouse_move(cls, x: int, y: int) -> None:
        with cls._lock:
            cls._mouse_x = int(x)
            cls._mouse_y = int(y)

    @classmethod
    def _push(cls, record: InputEventRecord) -> None:
        with cls._lock:
            cls._push_locked(record)

    @classmethod
    def _push_locked(cls, record: InputEventRecord) -> None:
        if len(cls._queue) >= cls._MAX_QUEUE:
            # 防止无人消费时无限增长（丢弃最旧事件）。
            del cls._queue[: len(cls._queue) - cls._MAX_QUEUE + 1]
        cls._queue.append(record)

