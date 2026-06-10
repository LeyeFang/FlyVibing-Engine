"""
OpenGLCore — PyOpenGL 核心上下文 (GL Context / 视口 / 清屏)。

职责:
  - GL 状态初始化 (视口、深度测试、面剔除等)
  - GPU 信息打印
  - 视口设置 & 延迟 resize
  - 清屏

说明:
  - GL 上下文由 GLFW (EditorWindow) 创建，本模块不负责 Context 创建
  - 与 ModernGLCore 不同，不需要 mgl.create_context()，只需配置 GL 状态

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl


class OpenGLCore:
    """PyOpenGL 核心 — GL 状态管理与基础渲染配置。"""

    @classmethod
    def init_core(cls, window_size: tuple[int, int]) -> None:
        """初始化 OpenGL 渲染状态。

        调用时机: 渲染线程，GL 上下文已由 GLFW 绑定。

        Args:
            window_size: (width, height) 初始窗口尺寸
        """
        # ── 打印 GPU 信息 ──
        vendor = gl.glGetString(gl.GL_VENDOR)
        renderer = gl.glGetString(gl.GL_RENDERER)
        version = gl.glGetString(gl.GL_VERSION)
        if vendor:
            print(f"[OpenGL] GPU Vendor : {vendor.decode() if isinstance(vendor, bytes) else vendor}")
        if renderer:
            print(f"[OpenGL] GPU Renderer: {renderer.decode() if isinstance(renderer, bytes) else renderer}")
        if version:
            print(f"[OpenGL] GL Version  : {version.decode() if isinstance(version, bytes) else version}")

        # ── 视口 ──
        gl.glViewport(0, 0, window_size[0], window_size[1])

        # ── 全局渲染状态 (与 ModernGL 保持一致: 仅 DEPTH_TEST) ──
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)

        # ── 清屏颜色默认值 ──
        gl.glClearColor(0.2, 0.2, 0.2, 1.0)

    @classmethod
    def update_viewport(cls, width: int, height: int) -> None:
        """更新视口尺寸 (渲染线程调用)。"""
        gl.glViewport(0, 0, width, height)

    @classmethod
    def clear_frame(cls, r: float = 0.2, g: float = 0.2, b: float = 0.2, a: float = 1.0) -> None:
        """清屏 (深灰色默认)。

        Args:
            r, g, b, a: 清屏颜色 RGBA 分量
        """
        gl.glClearColor(r, g, b, a)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
