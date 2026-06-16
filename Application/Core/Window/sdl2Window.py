from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application
from Application.Core.Window.Window import Window
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *

import sdl2
from sdl2 import SDL_Window

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
                    WindowCloseEvent.Pack()
        # ModernGL / OpenGL 交换缓冲区
        if cls.app.renderer_type in ('ModernGL',):
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


    @classmethod
    def _create_window(
        cls
    ) -> SDL_Window:
        renderer_type = cls.app.renderer_type
        sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
        if renderer_type in ('ModernGL',):
            # ModernGL 需要 OpenGL 上下文
            cls.sdl2_window: SDL_Window = sdl2.SDL_CreateWindow(
                b"SDL2 window",
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                800, 600,
                sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_SHOWN
            )
            gl_context = sdl2.SDL_GL_CreateContext(cls.sdl2_window)
            if not gl_context:
                sdl2.SDL_DestroyWindow(cls.sdl2_window)
                sdl2.SDL_Quit()
                raise RuntimeError("OpenGL context creation failed")
        elif renderer_type == 'Vulkan':
            cls.sdl2_window: SDL_Window = sdl2.SDL_CreateWindow(
                b"SDL2 window",
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                sdl2.SDL_WINDOWPOS_UNDEFINED,
                800, 600,
                sdl2.SDL_WINDOW_VULKAN | sdl2.SDL_WINDOW_SHOWN
            )
