"""
RenderCommand — 渲染命令基类 + 具体命令。

设计:
  - 命令由主线程创建 (enqueue)，渲染线程执行 (execute)
  - 命令是无状态 dataclass — 所有数据由字段携带
  - execute(renderer) 接收渲染器实例，调用其已有的方法

当前命令:
  ResizeCommand                 — 窗口尺寸变更
  SetViewProjectionCommand      — 设置 view/proj 矩阵 (由逻辑线程计算后推送给渲染器)
  EntityRegistrationCommand     — 实体 MeshRenderer 注册/注销
  OverlayRegistrationCommand    — Overlay 可绘制对象 GPU 资源注册
  OverlayUnregistrationCommand  — Overlay 可绘制对象 GPU 资源解注册
  RegisterHighlightEffectCommand   — 轮廓高亮后处理注册
  UnregisterHighlightEffectCommand — 轮廓高亮后处理注销
  UpdateHighlightSelectionCommand  — 更新选中实体集合
  UpdateHighlightConfigCommand     — 更新轮廓渲染参数
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


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
        if self.width <= 0 or self.height <= 0:
            return  # 忽略无效尺寸 (窗口初始化时可能收到 (0,0))
        renderer._on_window_resize(self.width, self.height)


@dataclass
class SetViewProjectionCommand(RenderCommand):
    """设置 view/proj 矩阵 — 由逻辑线程计算后推送给渲染器。

    渲染器不再持有相机引用，仅接收已计算好的矩阵数据。
    view/proj 可为 None 表示不更新对应矩阵。

    同时携带渲染器需要的相机元数据 (用于 overlay 动态 uniform 解析等)。

    使用方式:
      cam = EditorCamera.get_instance()
      renderer.enqueue(SetViewProjectionCommand(
          view=cam.get_view_matrix(),
          proj=cam.get_projection_matrix(aspect_ratio),
          orbit_target=cam.orbit_target,
          orbit_distance=cam.orbit_distance,
          is_orthographic=cam.is_orthographic,
          ortho_size=cam.ortho_size,
      ))
    """
    view: 'np.ndarray | None' = None       # 4x4 float32 view matrix
    proj: 'np.ndarray | None' = None       # 4x4 float32 projection matrix
    # ── 相机元数据 (供渲染器动态 uniform 解析等使用) ──
    orbit_target: 'np.ndarray | None' = None   # 轨道注视点 (世界坐标)
    orbit_distance: float | None = None        # 摄像机到注视点的距离
    is_orthographic: bool = False              # 是否正交投影模式
    ortho_size: float = 10.0                   # 正交半高

    def execute(self, renderer: Any) -> None:
        if self.view is not None:
            renderer._cached_view = self.view
        if self.proj is not None:
            renderer._cached_proj = self.proj
        # 更新相机元数据缓存 (供动态 uniform 解析)
        if self.orbit_target is not None:
            renderer._cam_orbit_target = self.orbit_target
        if self.orbit_distance is not None:
            renderer._cam_orbit_distance = self.orbit_distance
        renderer._cam_is_orthographic = self.is_orthographic
        renderer._cam_ortho_size = self.ortho_size


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
class EntityVisibilityCommand(RenderCommand):
    """实体可见性控制 (编辑器眼图标) — 控制 _visible_entities set。

    与 EntityRenderVisibleCommand 的区别:
      - EntityVisibilityCommand:      编辑器眼图标 → 控制渲染 + Pick + Gizmo
      - EntityRenderVisibleCommand:   MeshRenderer.visible → 仅控制主渲染, 不影响 Pick
    """
    entity_id: int
    visible: bool

    def execute(self, renderer: Any) -> None:
        if self.visible:
            renderer.show_entity(self.entity_id)
        else:
            renderer.hide_entity(self.entity_id)


@dataclass
class EntityRenderVisibleCommand(RenderCommand):
    """实体渲染可见性 (MeshRenderer.visible) — 仅更新 GPU 实体数据的 render_visible 字段。

    不影响 _visible_entities set，因此不影响 Pick pass 和 Gizmo/Outline。
    """
    entity_id: int
    visible: bool

    def execute(self, renderer: Any) -> None:
        renderer.set_entity_render_visible(self.entity_id, self.visible)


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
class RegisterHighlightEffectCommand(RenderCommand):
    """注册轮廓高亮后处理效果 — 编译 shader、创建 FBO/VAO。

    调用方: OutlinerID.register_to()
    """
    config: Any  # HighlightEffectConfig

    def execute(self, renderer: Any) -> None:
        renderer.register_highlight_effect(self.config)


@dataclass
class UnregisterHighlightEffectCommand(RenderCommand):
    """注销轮廓高亮效果，释放全部 GPU 资源。

    调用方: OutlinerID.unregister_from()
    """

    def execute(self, renderer: Any) -> None:
        renderer.unregister_highlight_effect()


@dataclass
class UpdateHighlightSelectionCommand(RenderCommand):
    """更新选中实体 ID 集合 — 下一帧 PostProcess._sync_selection() 生效。

    调用方: OutlinerID.set_selected_entities() / OutlinerID.clear()
    线程安全: 主线程 enqueue，渲染线程 execute，无需加锁。
    """
    entity_ids: set[int]

    def execute(self, renderer: Any) -> None:
        renderer.update_highlight_selection(self.entity_ids)


@dataclass
class UpdateHighlightConfigCommand(RenderCommand):
    """更新轮廓渲染参数 — 不重建 GPU 资源。

    调用方: OutlinerID.configure()
    """
    color: 'tuple[float, float, float] | None' = None
    width: 'int | None' = None
    xray: 'bool | None' = None

    def execute(self, renderer: Any) -> None:
        renderer.update_highlight_config(
            color=self.color,
            width=self.width,
            xray=self.xray,
        )



