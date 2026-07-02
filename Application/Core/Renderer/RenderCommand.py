"""
RenderCommand — 渲染命令基类 + 具体命令。

设计:
  - 命令由主线程创建 (enqueue)，渲染线程执行 (execute)
  - 命令是无状态 dataclass — 所有数据由字段携带
  - execute(renderer) 接收渲染器实例，调用其已有的方法

当前命令:
  ResizeCommand               — 窗口尺寸变更
  CameraUpdateCommand         — 相机矩阵更新
  EntityRegistrationCommand   — 实体 MeshRenderer 注册/注销
  OverlayRegistrationCommand  — Overlay 可绘制对象 GPU 资源注册
  OverlayUnregistrationCommand— Overlay 可绘制对象 GPU 资源解注册
  PickMouseMoveCommand        — 拾取系统鼠标位置
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class RenderCommand(ABC):
    """渲染命令基类。"""

    @abstractmethod
    def execute(self, renderer: Any) -> None:
        """在渲染线程执行此命令。"""
        ...


@dataclass
class ResizeCommand(RenderCommand):
    """窗口尺寸变更 — 等效于 renderer._on_window_resize(w, h)。"""
    width: int
    height: int

    def execute(self, renderer: Any) -> None:
        renderer._on_window_resize(self.width, self.height)


@dataclass
class CameraUpdateCommand(RenderCommand):
    """相机矩阵更新 — 等效于 renderer._on_camera_update()。"""
    def execute(self, renderer: Any) -> None:
        renderer._on_camera_update()


@dataclass
class EntityRegistrationCommand(RenderCommand):
    """实体注册/注销 — 等效于 register_entity / unregister_entity。"""
    entity_id: int
    register: bool  # True=注册, False=注销

    def execute(self, renderer: Any) -> None:
        if self.register:
            renderer.register_entity(self.entity_id)
        else:
            renderer.unregister_entity(self.entity_id)


@dataclass
class OverlayRegistrationCommand(RenderCommand):
    """Overlay 可绘制对象 GPU 资源注册。

    调用方 (Grid / ViewGizmo / TransformGizmo 等) 创建 overlay_drawable_struct
    纯数据后，通过此命令提交到渲染线程执行 GPU 资源创建。
    """
    overlay: Any  # RenderResourceManger.overlay_drawable_struct

    def execute(self, renderer: Any) -> None:
        renderer.register_overlay_drawable(self.overlay)


@dataclass
class OverlayUnregistrationCommand(RenderCommand):
    """Overlay 可绘制对象 GPU 资源解注册。"""
    key: str

    def execute(self, renderer: Any) -> None:
        renderer.unregister_overlay_drawable(self.key)


@dataclass
class PickMouseMoveCommand(RenderCommand):
    """拾取鼠标位置更新。"""
    x: int
    y: int

    def execute(self, renderer: Any) -> None:
        renderer.update_pick_mouse(self.x, self.y)
