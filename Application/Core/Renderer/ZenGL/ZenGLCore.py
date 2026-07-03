"""
ZenGLCore — ZenGL 核心上下文 (Context / 视口 / 清屏 / Image 管理)。
对应主线: Application/Core/Renderer/OpenGL/OpenGLCore.py
"""

from __future__ import annotations
import zengl
import numpy as np


class ZenGLCore:
    ctx: zengl.Context = None
    _color_image = None
    _depth_image = None
    _overlay_image = None
    _overlay_depth = None
    _samples: int = 0      # 0 = 关闭 MSAA

    @classmethod
    def init_core(cls, window_size: tuple[int, int]) -> None:
        cls.ctx = zengl.context()
        info = cls.ctx.info
        print(f"[ZenGL] GPU Vendor : {info.get('GL_VENDOR','N/A')}")
        print(f"[ZenGL] GPU Renderer: {info.get('GL_RENDERER','N/A')}")
        print(f"[ZenGL] GL Version  : {info.get('GL_VERSION','N/A')}")
        cls._create_images(window_size)

    @classmethod
    def _create_images(cls, size: tuple[int, int]) -> None:
        w, h = size
        if cls._samples > 0:
            cls._color_image = cls.ctx.image((w, h), 'rgba8unorm', samples=cls._samples)
            cls._depth_image = cls.ctx.image((w, h), 'depth24plus', samples=cls._samples)
        else:
            cls._color_image = cls.ctx.image((w, h), 'rgba8unorm')
            cls._depth_image = cls.ctx.image((w, h), 'depth24plus')
        cls._color_image.clear_value = (0.2, 0.2, 0.2, 1.0)
        cls._overlay_image = cls.ctx.image((w, h), 'rgba8unorm')
        cls._overlay_depth = cls.ctx.image((w, h), 'depth24plus')

    @classmethod
    def rebuild_images(cls, width: int, height: int) -> None:
        cls._create_images((width, height))

    @classmethod
    def clear_frame(cls, r=0.2, g=0.2, b=0.2, a=1.0) -> None:
        cls._color_image.clear_value = (r, g, b, a)
        if cls._color_image: cls._color_image.clear()
        if cls._depth_image: cls._depth_image.clear()

    @classmethod
    def clear_overlay(cls) -> None:
        if cls._overlay_image:
            cls._overlay_image.clear_value = (0.0, 0.0, 0.0, 0.0)
            cls._overlay_image.clear()
        if cls._overlay_depth: cls._overlay_depth.clear()

    @classmethod
    def composite_overlay_to_screen(cls) -> None:
        pass  # TODO: overlay 合成需要独立的合成 shader

    @classmethod
    def get_framebuffer(cls) -> list:
        return [cls._color_image, cls._depth_image]

    @classmethod
    def get_overlay_framebuffer(cls) -> list:
        # ★ 直接渲染到主颜色图像，overlay 自带 blend，合成到场景上
        return [cls._color_image, cls._depth_image]

    @classmethod
    def get_color_image(cls): return cls._color_image

    @classmethod
    def _clear_depth_for_overlays(cls) -> None:
        """清理深度图像 (为 screen-space overlay 准备)."""
        if cls._depth_image:
            cls._depth_image.clear()

    @classmethod
    def destroy_core(cls) -> None:
        """销毁 ZenGL 核心 GPU 资源 — 渲染线程、GL 上下文有效时调用。"""
        cls._color_image = None
        cls._depth_image = None
        cls._overlay_image = None
        cls._overlay_depth = None
        cls.ctx = None
