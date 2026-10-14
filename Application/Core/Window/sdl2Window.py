from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine
from Application.Core.Window.Window import Window
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *

import sdl2
from sdl2 import SDL_Window, SDL_DisplayMode

import ctypes


class sdl2Window(Window):

    sdl2_window: SDL_Window = None

    @classmethod
    def Create(
        cls,
        app: Application
    ) -> sdl2Window:
        cls.app = app
        cls._create_window()
        return cls

    @classmethod
    def Update(
        cls
    ) -> None:
        """每帧调用，轮询并分发所有 SDL 事件"""
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            match event.type:
                case sdl2.SDL_QUIT:
                    WindowCloseEvent.Pack(engine=cls._engine)
        # OpenGL 交换缓冲区
        if cls.app.renderer_type in ('OpenGL',):
            sdl2.SDL_GL_SwapWindow(cls.sdl2_window)

    @classmethod
    def GetSize(cls):
        """返回窗口的帧缓冲大小（逻辑像素）"""
        w = ctypes.c_int()
        h = ctypes.c_int()
        sdl2.SDL_GetWindowSize(
            cls.sdl2_window,
            ctypes.byref(w),
            ctypes.byref(h)
        )
        return (w.value, h.value)

    @classmethod
    def SetTitle(cls, title: str) -> None:
        """设置窗口标题。"""
        if cls.sdl2_window is not None:
            sdl2.SDL_SetWindowTitle(cls.sdl2_window, title.encode('utf-8'))

    @classmethod
    def GetNativeHandle(cls):
        """返回 SDL2 原生窗口句柄 (SDL_Window 指针)。"""
        return cls.sdl2_window

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if isinstance(event, WindowCloseEvent):
            cls.Therminate()

    @classmethod
    def Therminate(cls):
        sdl2.SDL_DestroyWindow(cls.sdl2_window)
        sdl2.SDL_Quit()

    # ════════════════════════════════════════════════════════════
    # 系统分辨率查询（SDL2 实现）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _get_system_resolution(cls) -> tuple[int, int]:
        """获取主显示器当前分辨率（通过 SDL2）。"""
        display_mode = SDL_DisplayMode()
        ret = sdl2.SDL_GetCurrentDisplayMode(0, ctypes.byref(display_mode))
        if ret != 0:
            # 回退默认
            return 1920, 1080
        return display_mode.w, display_mode.h

    @classmethod
    def _create_window(
        cls
    ) -> SDL_Window:
        renderer_type = cls.app.renderer_type
        sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
        # 取比当前显示器小一圈的常见分辨率（保持同比例）
        width, height = cls._compute_default_size()
        if renderer_type in ('OpenGL',):
            # OpenGL 需要 OpenGL 上下文
            cls.sdl2_window: SDL_Window = sdl2.SDL_CreateWindow(
                b"FlyVibingEngine",
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                width, height,
                sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_SHOWN
            )
            gl_context = sdl2.SDL_GL_CreateContext(cls.sdl2_window)
            if not gl_context:
                sdl2.SDL_DestroyWindow(cls.sdl2_window)
                sdl2.SDL_Quit()
                raise RuntimeError("OpenGL context creation failed")
        elif renderer_type == 'Vulkan':
            cls.sdl2_window: SDL_Window = sdl2.SDL_CreateWindow(
                b"FlyVibingEngine",
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                width, height,
                sdl2.SDL_WINDOW_VULKAN | sdl2.SDL_WINDOW_SHOWN
            )
