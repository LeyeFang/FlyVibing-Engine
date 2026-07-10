"""
ZenGLCore — ZenGL 核心上下文 (Context / 视口 / 清屏 / Image 管理)。
对应主线: Application/Core/Renderer/OpenGL/OpenGLCore.py
"""

from __future__ import annotations
import zengl
import numpy as np


class ZenGLCore:

    def __init__(self) -> None:
        super().__init__()
        self.ctx: 'zengl.Context | None' = None
        self._color_image = None
        self._depth_image = None
        self._overlay_image = None
        self._overlay_depth = None
        self._samples: int = 0

    def init_core(self, window_size: tuple[int, int]) -> None:
        self.ctx = zengl.context()
        info = self.ctx.info
        print(f"[ZenGL] GPU Vendor : {info.get('GL_VENDOR','N/A')}")
        print(f"[ZenGL] GPU Renderer: {info.get('GL_RENDERER','N/A')}")
        print(f"[ZenGL] GL Version  : {info.get('GL_VERSION','N/A')}")
        self._create_images(window_size)

    def _create_images(self, size: tuple[int, int]) -> None:
        w, h = size
        if self._samples > 0:
            self._color_image = self.ctx.image((w, h), 'rgba8unorm', samples=self._samples)
            self._depth_image = self.ctx.image((w, h), 'depth24plus', samples=self._samples)
        else:
            self._color_image = self.ctx.image((w, h), 'rgba8unorm')
            self._depth_image = self.ctx.image((w, h), 'depth24plus')
        self._color_image.clear_value = (0.2, 0.2, 0.2, 1.0)
        self._overlay_image = self.ctx.image((w, h), 'rgba8unorm')
        self._overlay_depth = self.ctx.image((w, h), 'depth24plus')

    def rebuild_images(self, width: int, height: int) -> None:
        self._create_images((width, height))

    def clear_frame(self, r=0.2, g=0.2, b=0.2, a=1.0) -> None:
        self._color_image.clear_value = (r, g, b, a)
        if self._color_image: self._color_image.clear()
        if self._depth_image: self._depth_image.clear()

    def clear_overlay(self) -> None:
        if self._overlay_image:
            self._overlay_image.clear_value = (0.0, 0.0, 0.0, 0.0)
            self._overlay_image.clear()
        if self._overlay_depth: self._overlay_depth.clear()

    def composite_overlay_to_screen(self) -> None:
        pass  # TODO: overlay 合成需要独立的合成 shader

    def get_framebuffer(self) -> list:
        return [self._color_image, self._depth_image]

    def get_overlay_framebuffer(self) -> list:
        # ★ 直接渲染到主颜色图像，overlay 自带 blend，合成到场景上
        return [self._color_image, self._depth_image]

    def get_color_image(self): return self._color_image

    def _clear_depth_for_overlays(self) -> None:
        """清理深度图像 (为 screen-space overlay 准备)."""
        if self._depth_image:
            self._depth_image.clear()

    def destroy_core(self) -> None:
        """销毁 ZenGL 核心 GPU 资源 — 渲染线程、GL 上下文有效时调用。"""
        self._color_image = None
        self._depth_image = None
        self._overlay_image = None
        self._overlay_depth = None
        self.ctx = None
