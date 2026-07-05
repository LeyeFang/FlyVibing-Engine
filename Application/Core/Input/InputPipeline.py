"""
InputPipeline — 可复用的输入管线 (窗口后端无关)
══════════════════════════════════════════════

将回调注册 + InputState 管理 + 拖拽/移动分流 抽取为独立组件。
通过 InputBackend 抽象层与具体窗口系统 (GLFW / SDL2 / ...) 解耦。

主线 (glfwWindow) 和 test 框架共用同一套输入基础设施，
通过覆写钩子 (on_key / on_mouse_button / on_drag / on_move / on_scroll)
分别接入 Engine 事件系统或 test 自定义逻辑。

架构:
  窗口后端 (GLFW / SDL2 / ...)
      │
      ▼
  InputBackend (抽象: 回调注册 + 光标查询 + 事件常量)
      │
      ▼
  InputPipeline (内部回调)
      ├─ 更新 InputState (修饰键/按键/鼠标按钮状态)
      ├─ 追踪鼠标位置 (last / press / current)
      ├─ 检测 拖拽 vs 移动 (基于 InputState.current_mouse_button_code)
      │
      ▼
  可覆写钩子 (默认 no-op)
      on_key(key, scancode, action, mods)
      on_mouse_button(button, action, mods, x, y)
      on_drag(button, dx, dy, x, y)
      on_move(x, y)
      on_scroll(xoff, yoff)

使用示例 (test, GLFW 后端):
    pipeline = InputPipeline(glfw_window)           # 自动使用 GLFWInputBackend
    pipeline = InputPipeline(GLFWInputBackend(win)) # 显式指定后端

使用示例 (未来 SDL2 后端):
    pipeline = InputPipeline(SDL2InputBackend(sdl_window))

    pipeline.on_key = lambda k, sc, act, mods: print(f"Key {k}")
    pipeline.on_drag = lambda btn, dx, dy, x, y: cam.orbit(dx, dy)
    # InputState 自动管理, 拖拽检测自动处理
"""

from __future__ import annotations

from typing import Optional, Union

from Application.Core.Input.InputState import InputState
from Application.Core.Input.InputBackend import InputBackend, GLFWInputBackend


class InputPipeline:
    """输入管线 — 回调注册 + InputState + 拖拽状态机 + 可覆写钩子。

    通过 InputBackend 与具体窗口系统解耦。
    当前仅提供 GLFWInputBackend, 未来可扩展 SDL2InputBackend 等。

    职责:
      - 通过后端注册/注销输入回调
      - 管理 InputState 实例 (修饰键/按键/鼠标按钮状态)
      - 追踪鼠标位置并检测 拖拽 vs 纯移动
      - 提供 5 个可覆写钩子, 供上层接入不同的事件系统

    不负责:
      - 事件派发 (由钩子实现方决定 — Engine 事件系统 / 直接 handler 调用)
      - 主循环 (由调用方控制 poll_events 时机)
    """

    def __init__(
        self,
        window_or_backend: Union[object, InputBackend],
        input_state: Optional[InputState] = None,
    ):
        """创建输入管线并注册后端回调。

        Args:
            window_or_backend: GLFW 窗口句柄 (自动包装为 GLFWInputBackend)
                               或 InputBackend 实例 (显式指定后端)
            input_state:       外部传入的 InputState 实例。
                               为 None 时自动创建独立实例 (test 模式)。
                               主线 (glfwWindow) 应传入 Engine 持有的 InputState。
        """
        # ── 解析后端 ──
        if isinstance(window_or_backend, InputBackend):
            self.backend: InputBackend = window_or_backend
        else:
            # 兼容旧用法: 传入 GLFW 窗口 → 自动包装
            self.backend = GLFWInputBackend(window_or_backend)

        self.input_state = input_state or InputState()

        # ── 鼠标位置追踪 ──
        self._last_mx: float = 0.0
        self._last_my: float = 0.0
        self._press_mx: float = 0.0
        self._press_my: float = 0.0

        # ── 注册后端回调 (保存旧回调以便 detach 恢复) ──
        self._prev_key_cb = self.backend.set_key_callback(self._on_key)
        self._prev_mouse_cb = self.backend.set_mouse_button_callback(self._on_mouse_button)
        self._prev_cursor_cb = self.backend.set_cursor_pos_callback(self._on_cursor)
        self._prev_scroll_cb = self.backend.set_scroll_callback(self._on_scroll)

    # ══════════════════════════════════════════════════════════
    # 生命周期
    # ══════════════════════════════════════════════════════════

    def detach(self) -> None:
        """注销后端回调并恢复之前的回调 (如果有)。"""
        if self._prev_key_cb is not None:
            self.backend.set_key_callback(self._prev_key_cb)
        if self._prev_mouse_cb is not None:
            self.backend.set_mouse_button_callback(self._prev_mouse_cb)
        if self._prev_cursor_cb is not None:
            self.backend.set_cursor_pos_callback(self._prev_cursor_cb)
        if self._prev_scroll_cb is not None:
            self.backend.set_scroll_callback(self._prev_scroll_cb)

    # ══════════════════════════════════════════════════════════
    # 内部回调 → InputState 更新 + 拖拽检测 → 钩子
    # ══════════════════════════════════════════════════════════

    def _on_key(self, win, key: int, scancode: int, action: int, mods: int):
        """键盘回调 — 更新 InputState 后调用 on_key 钩子。"""
        # ── InputState 更新 ──
        if action == self.backend.PRESS:
            self.input_state.set_key_held(key, True)
            self.input_state.update_modifier_state(key, True)
        elif action == self.backend.RELEASE:
            self.input_state.set_key_held(key, False)
            self.input_state.update_modifier_state(key, False)
        # Repeat 不改变 InputState

        # ── 钩子 ──
        self.on_key(key, scancode, action, mods)

    def _on_mouse_button(self, win, button: int, action: int, mods: int):
        """鼠标按键回调 — 更新 InputState + 位置追踪 + 调用 on_mouse_button 钩子。"""
        x, y = self.backend.get_cursor_pos()

        # ── InputState 更新 ──
        if action == self.backend.PRESS:
            self.input_state.set_mouse_button(button)
            self.input_state.set_button_press_pos(int(x), int(y))
            self._press_mx, self._press_my = x, y
            self._last_mx, self._last_my = x, y
        elif action == self.backend.RELEASE:
            self.input_state.set_mouse_button(None)
            self.input_state.set_button_release_pos(int(x), int(y))

        # ── 钩子 ──
        self.on_mouse_button(button, action, mods, x, y)

    def _on_cursor(self, win, x: float, y: float):
        """光标移动回调 — 根据 InputState 分流: 拖拽 vs 纯移动。"""
        btn = self.input_state.current_mouse_button_code
        if btn is not None:
            dx = x - self._last_mx
            dy = y - self._last_my
            self.on_drag(btn, dx, dy, x, y)
        else:
            self.on_move(x, y)

        self._last_mx, self._last_my = x, y

    def _on_scroll(self, win, xoff: float, yoff: float):
        """滚轮回调 — 直接调用 on_scroll 钩子。"""
        self.on_scroll(xoff, yoff)

    # ══════════════════════════════════════════════════════════
    # 可覆写钩子 (默认 no-op)
    # ══════════════════════════════════════════════════════════

    def on_key(self, key: int, scancode: int, action: int, mods: int) -> None:
        pass

    def on_mouse_button(self, button: int, action: int, mods: int, x: float, y: float) -> None:
        pass

    def on_drag(self, button: int, dx: float, dy: float, x: float, y: float) -> None:
        pass

    def on_move(self, x: float, y: float) -> None:
        pass

    def on_scroll(self, xoff: float, yoff: float) -> None:
        pass

    # ══════════════════════════════════════════════════════════
    # 便利属性 / 查询
    # ══════════════════════════════════════════════════════════

    @property
    def is_dragging(self) -> bool:
        return self.input_state.current_mouse_button_code is not None

    @property
    def drag_button(self) -> int | None:
        return self.input_state.current_mouse_button_code

    @property
    def mouse_pos(self) -> tuple[float, float]:
        return self._last_mx, self._last_my

    @property
    def press_pos(self) -> tuple[float, float]:
        return self._press_mx, self._press_my

    def click_detected(self, release_x: float, release_y: float, threshold: float = 4.0) -> bool:
        """检测最近一次鼠标释放是否为 '点击'。

        应在 on_mouse_button 钩子中、action==RELEASE 时调用。
        """
        dx = release_x - self._press_mx
        dy = release_y - self._press_my
        return (dx * dx + dy * dy) < (threshold * threshold)

    # ══════════════════════════════════════════════════════════
    # 预设: 主线编辑器摄像机操作 (与 EditorLayer 行为一致)
    # ══════════════════════════════════════════════════════════

    def setup_editor_camera(self, camera, after_camera=None) -> None:
        """配置 on_drag / on_scroll 钩子, 使摄像机行为与主线 EditorLayer 一致。

        主线约定 (EditorLayer.OnEvent):
          - 中键拖拽 → 轨道旋转 (orbit)
          - 中键+Shift 拖拽 → 平移注视点 (pan)
          - 左键拖拽 → 无操作 (预留给 Gizmo/Pick)
          - 滚轮 → 缩放 (zoom)

        通过调用 camera.on_mouse_drag() 和 camera.on_scroll() 与主线
        EditorLayer 保持完全一致的输入映射路径。
        使用 MouseButtonCode 枚举 (窗口后端无关)。

        Args:
            camera:        EditorCamera 或 TestEditorCamera 实例
            after_camera:  可选回调, 每次摄像机操作后调用, 签名 ()
        """
        pipeline = self
        from Application.Core.Events.Enum.InputEnum import MouseButtonCode

        def on_drag(button, dx, dy, x, y):
            if button != MouseButtonCode.Middle:
                return  # 仅中键操作摄像机
            shift = pipeline.input_state.is_shift_pressed()
            camera.on_mouse_drag(MouseButtonCode.Middle, dx, dy, shift)
            if after_camera:
                after_camera()

        def on_scroll(xoff, yoff):
            camera.on_scroll(yoff)
            if after_camera:
                after_camera()

        self.on_drag = on_drag
        self.on_scroll = on_scroll
