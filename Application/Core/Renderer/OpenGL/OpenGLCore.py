"""
OpenGLCore — PyOpenGL 核心上下文 (GL Context / 视口 / 清屏)。

职责:
  - GL 状态初始化 (视口、深度测试、面剔除等)
  - GPU 信息打印
  - 视口设置 & 延迟 resize
  - 清屏

说明:
  - GL 上下文由 GLFW (EditorWindow) 创建，本模块不负责 Context 创建
  - GL 上下文由 GLFW (EditorWindow) 创建，本模块不负责 Context 创建

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl


class OpenGLCore:
    """PyOpenGL 核心 — GL 状态管理与基础渲染配置。"""

    def init_core(self, window_size: tuple[int, int]) -> None:
        """初始化 OpenGL 渲染状态。

        调用时机: 渲染线程，GL 上下文已由 GLFW 绑定。

        Args:
            window_size: (width, height) 初始窗口尺寸
        """
        # ── 视口 ──
        gl.glViewport(0, 0, window_size[0], window_size[1])

        # ── 全局渲染状态 (仅 DEPTH_TEST) ──
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)

        # ── 清屏颜色默认值 ──
        self._clear_color = (0.2, 0.2, 0.2, 1.0)
        gl.glClearColor(*self._clear_color)

    def update_viewport(self, width: int, height: int) -> None:
        """更新视口尺寸 (渲染线程调用)。"""
        gl.glViewport(0, 0, width, height)

    def clear_frame(self, r: float = None, g: float = None, b: float = None, a: float = None) -> None:
        """清屏 — 使用存储的默认颜色或传入的覆盖值。"""
        cr = r if r is not None else self._clear_color[0]
        cg = g if g is not None else self._clear_color[1]
        cb = b if b is not None else self._clear_color[2]
        ca = a if a is not None else self._clear_color[3]
        gl.glClearColor(cr, cg, cb, ca)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def set_clear_color(self, r: float, g: float, b: float, a: float) -> None:
        """更新存储的清屏颜色 (下一帧生效)。"""
        self._clear_color = (r, g, b, a)

    def _clear_depth_for_overlays(self) -> None:
        """清理深度缓冲 (为 screen-space overlay 准备)."""
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
