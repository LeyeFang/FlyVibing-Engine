from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.InputEvent import *
from Application.Core.Window.Window import Window
from Application.Core.Renderer.RenderCommand import ResizeCommand
from Application.Core.Input.InputPipeline import InputPipeline

import glfw


class glfwWindow(Window):

    glfw_window = None

    @classmethod
    def Create(
        cls
    ):
        cls.glfw_window = cls._create_window()
        glfw.set_window_size_callback(cls.glfw_window, cls._window_resize_event_callback)
        # ── 输入管线: GLFW 回调 + InputState + 拖拽/移动分流 ──
        cls._input_pipeline = InputPipeline(cls.glfw_window)
        cls._input_pipeline.on_key = cls._make_key_hook()
        cls._input_pipeline.on_mouse_button = cls._make_mouse_button_hook()
        cls._input_pipeline.on_drag = cls._make_drag_hook()
        cls._input_pipeline.on_move = cls._make_move_hook()
        cls._input_pipeline.on_scroll = cls._make_scroll_hook()
        return cls

    @classmethod
    def Update(
        cls
    ) -> None:
        glfw.poll_events()
        if glfw.window_should_close(cls.glfw_window):
            WindowCloseEvent.Pack(engine=cls._engine)

    @classmethod
    def GetSize(
        cls
    ) -> tuple[int, int]:
        return glfw.get_framebuffer_size(cls.glfw_window)

    @classmethod
    def Therminate(
        cls
    ):
        """销毁自身 GLFW 窗口。

        不调用 glfw.terminate() — 该操作由子类 (如 EditorWindow) 根据自身角色决定。
        RuntimeWindow / PreviewRuntimeWindow 不应终止整个 GLFW，
        因为编辑器窗口仍需要 GLFW 处于初始化状态。
        """
        if cls.glfw_window is not None:
            glfw.destroy_window(cls.glfw_window)
            cls.glfw_window = None

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if isinstance(event, WindowCloseEvent):
            pass

    # ════════════════════════════════════════════════════════════
    # 系统分辨率查询（GLFW 实现）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _get_system_resolution(cls) -> tuple[int, int]:
        """获取主显示器当前分辨率（通过 GLFW）。"""
        monitor = glfw.get_primary_monitor()
        if monitor is None:
            # 回退默认
            return 1920, 1080
        video_mode = glfw.get_video_mode(monitor)
        if video_mode is None:
            return 1920, 1080
        return video_mode.size.width, video_mode.size.height

    # ════════════════════════════════════════════════════════════
    # 窗口创建
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls):
        # 1. 初始化 GLFW
        if not glfw.init():
            print("无法初始化 GLFW")
            return
        # 2. 设置窗口提示 (子类重写 _set_window_hints)
        cls._set_window_hints()
        # 3. 取比当前显示器小一圈的常见分辨率（保持同比例）
        width, height = cls._compute_default_size()
        # 4. 创建窗口
        glfw_window = glfw.create_window(
            width, height,
            "MyGameEngine",
            None,
            None
        )
        if not glfw_window:
            print("无法创建窗口")
            glfw.terminate()
            return
        return glfw_window

    @classmethod
    def _set_window_hints(
        cls
    ) -> None:
        """子类重写以设置 GLFW 窗口提示 (OpenGL 上下文 / Vulkan NO_API 等)。

        默认不做任何设置，由 EditorWindow (OpenGL) 或 PreviewRuntimeWindow (Vulkan)
        等子类根据需要覆盖。
        """
        pass

    # ════════════════════════════════════════════════════════════
    # 输入钩子工厂 — 为 InputPipeline 提供与原有行为一致的钩子
    # 通过闭包捕获 cls (类引用), 使 cls._engine 在回调时动态解析
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _make_key_hook(cls):
        """键盘钩子 — 与原有 _key_callback 行为一致。"""
        _kls = cls
        def hook(key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.RELEASE:
                WindowCloseEvent.Pack(engine=_kls._engine)
            KeyboardButtonEvent.Pack(key, scancode, action, mods, engine=_kls._engine)
        return hook

    @classmethod
    def _make_mouse_button_hook(cls):
        """鼠标按键钩子 — 与原有 _mouse_callback 行为一致。"""
        _kls = cls
        def hook(button, action, mods, x, y):
            MouseButtonEvent.Pack(
                button=button, action=action, mods=mods,
                pos_x=int(x), pos_y=int(y), engine=_kls._engine,
            )
        return hook

    @classmethod
    def _make_drag_hook(cls):
        """鼠标拖拽钩子 — 与原有 _mouse_move_callbakc 拖拽分支一致。"""
        _kls = cls
        def hook(button, dx, dy, x, y):
            MouseGragEvent.Pack(int(x), int(y), engine=_kls._engine)
        return hook

    @classmethod
    def _make_move_hook(cls):
        """鼠标移动钩子 — 与原有 _mouse_move_callbakc 纯移动分支一致。"""
        _kls = cls
        def hook(x, y):
            MouseMoveEvent.Pack(int(x), int(y), engine=_kls._engine)
        return hook

    @classmethod
    def _make_scroll_hook(cls):
        """滚轮钩子 — 与原有 _scroll_callback 行为一致。"""
        _kls = cls
        def hook(xoff, yoff):
            ScrollerEvent.Pack(x_offset=int(xoff), y_offset=int(yoff), engine=_kls._engine)
        return hook

    # ════════════════════════════════════════════════════════════
    # 窗口 resize (非输入事件, 保持直接 GLFW 回调注册)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _window_resize_event_callback(
        cls,
        window,
        width,
        height
    ):
        # 直接通知渲染器 (GPU 资源重建走 Command, 不经过 Event)
        engine = cls._engine
        if engine is not None and engine.renderer is not None:
            engine.renderer.enqueue(ResizeCommand(width, height))
        # 通知其他层 (ImGui display_size 等)
        WindowResizeEvent.Pack(width, height, engine=cls._engine)
