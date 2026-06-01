"""
ModernGLCore — ModernGL 核心上下文 (GL Context / 视口 / 清屏)。

职责:
  - moderngl Context 创建
  - GPU 信息打印
  - 视口设置 & 延迟 resize
  - 清屏 & 深度测试

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import moderngl as mgl
import numpy as np


class ModernGLCore:
    """ModernGL 核心 — Context 管理与基础渲染状态。"""

    ctx: mgl.Context = None

    @classmethod
    def init_core(cls, window_size: tuple[int, int]) -> None:
        """初始化 ModernGL 上下文。

        Args:
            window_size: (width, height) 初始窗口尺寸
        """
        cls.ctx = mgl.create_context()
        print(f"[ModernGL] GPU Vendor : {cls.ctx.info['GL_VENDOR']}")
        print(f"[ModernGL] GPU Renderer: {cls.ctx.info['GL_RENDERER']}")
        print(f"[ModernGL] GL Version  : {cls.ctx.info['GL_VERSION']}")
        cls.ctx.viewport = (0, 0, window_size[0], window_size[1])
        cls.ctx.enable(mgl.DEPTH_TEST)

    @classmethod
    def update_viewport(cls, width: int, height: int) -> None:
        """更新视口尺寸 (渲染线程调用)。"""
        cls.ctx.viewport = (0, 0, width, height)

    @classmethod
    def clear_frame(cls, r: float = 0.2, g: float = 0.2, b: float = 0.2, a: float = 1.0) -> None:
        """清屏 (深灰色默认)。"""
        cls.ctx.clear(r, g, b, a)
