from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.InputEvent import *
from Application.Core.Window.Window import Window

import glfw


class glfwWindow(Window):

    glfw_window = None

    @classmethod
    def Create(
        cls
    ):
        cls.glfw_window = cls._create_window()
        glfw.set_window_size_callback(cls.glfw_window, cls._window_resize_event_callback)
        glfw.set_scroll_callback(cls.glfw_window, cls._scroll_callback)
        glfw.set_mouse_button_callback(cls.glfw_window, cls._mouse_callback)
        glfw.set_key_callback(cls.glfw_window, cls._key_callback)
        glfw.set_cursor_pos_callback(cls.glfw_window, cls._mouse_move_callbakc)
        return cls

    @classmethod
    def Update(
        cls
    ) -> None:
        glfw.poll_events()
        if glfw.window_should_close(cls.glfw_window):
            WindowCloseEvent.Pack()

    @classmethod
    def GetSize(
        cls
    ) -> tuple[int, int]:
        return glfw.get_framebuffer_size(cls.glfw_window)

    @classmethod
    def Therminate(
        cls
    ):
        glfw.terminate()

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is WindowCloseEvent:
            pass

    @classmethod
    def _create_window(cls):
        # 1. 初始化 GLFW
        if not glfw.init():
            print("无法初始化 GLFW")
            return
        # 3. 创建窗口
        glfw_window = glfw.create_window(
            800, 600,
            "Test Window",
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

    #
    #
    # Above is callback functions --------------------------------------------
    @classmethod
    def _window_resize_event_callback(
        cls,
        window,
        width,
        height
    ):
        WindowResizeEvent.Pack(width, height)

    @classmethod
    def _key_callback(
        cls,
        window,
        key,
        scancode,
        action,
        mods
    ) -> None:
        if key == glfw.KEY_ESCAPE and action == glfw.RELEASE:
            WindowCloseEvent.Pack()
        KeyboardButtonEvent.Pack(key, scancode, action, mods)

    @classmethod
    def _mouse_callback(
        cls,
        window,
        button,
        action,
        mods
    ) -> None:
        pos_x, pos_y = glfw.get_cursor_pos(cls.glfw_window)
        MouseButtonEvent.Pack(
            button=button,
            action=action,
            mods=mods,
            pos_x=pos_x,
            pos_y=pos_y)

    @classmethod
    def _mouse_move_callbakc(
        cls,
        window,
        pos_x,
        pos_y
    ) -> None:
        MouseGragEvent.Pack(pos_x, pos_y)

    @classmethod
    def _scroll_callback(
        cls,
        window,
        x_offset,
        y_offset
    ) -> None:
        ScrollerEvent.Pack(x_offset=x_offset, y_offset=y_offset)
