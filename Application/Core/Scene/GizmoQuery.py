"""
GizmoQuery — ECS 世界查询层，供编辑器 Gizmo 使用。

职责:
  - 从 ECS World (esper) 中查询含特定 Component 的 entity
  - 返回纯 Python dataclass 列表，不依赖任何图形 API 或编辑器模块

设计原则:
  - 零依赖: 只依赖 esper + Python stdlib
  - 纯数据: 不持有引用，不修改 ECS 状态
  - 编辑器与 Runtime 均可使用 (Runtime debug 层复用)

使用方式:
  from Application.Core.Scene.GizmoQuery import GizmoQuery, CameraGizmoData

  for info in GizmoQuery.get_camera_gizmos(world, selected_ids={42}):
      if info.is_perspective:
          verts = CameraFrustum.build_frustum_vertices(info)
      else:
          verts = Camera2DBoundary.build_boundary_vertices(info)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import esper

from Application.Core.Scene.BasicComponents import Camera, Transform


# ═══════════════════════════════════════════════════════════════
# 纯数据 dataclass — 摄像机 Gizmo 所需的所有信息
# ═══════════════════════════════════════════════════════════════

@dataclass
class CameraGizmoData:
    """单个 Camera entity 的 Gizmo 渲染所需数据，纯值类型。"""

    entity_id: int
    entity_name: str

    # ── Transform (世界空间) ──
    position: tuple[float, float, float]     # (px, py, pz)
    rotation: tuple[float, float, float]     # (rx, ry, rz) — 欧拉角 (角度制)
    scale: tuple[float, float, float]        # (sx, sy, sz)

    # ── Camera 参数 ──
    is_perspective: bool
    fov: float                               # 视场角 (角度制, 仅透视)
    aspect_ratio: float
    ortho_size: float                        # 正交半高 (仅正交)
    near_plane: float
    far_plane: float
    local_forward: tuple[float, float, float]
    up_vector: tuple[float, float, float]
    is_primary: bool

    # ── 编辑器状态 ──
    is_selected: bool
    is_editor_visible: bool = True  # 眼图标控制


# ═══════════════════════════════════════════════════════════════
# GizmoQuery — 静态查询方法集
# ═══════════════════════════════════════════════════════════════

class GizmoQuery:
    """ECS 世界查询 — 为编辑器 Gizmo 提供纯数据。"""

    @staticmethod
    def get_camera_gizmos(
        selected_ids: Optional[set[int]] = None,
    ) -> list[CameraGizmoData]:
        """遍历 ECS World 中所有含 Camera + Transform 的 entity。"""
        if selected_ids is None:
            selected_ids = set()

        results: list[CameraGizmoData] = []

        # ── 读取编辑器可见性 ──
        editor_visible: set[int] = set()
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            st = SceneManager._current()
            editor_visible = st._editor_visible
        except Exception:
            pass

        for ent, (cam, xform) in esper.get_components(Camera, Transform):
            results.append(CameraGizmoData(
                entity_id=ent,
                entity_name=getattr(cam, '_entity_name', ''),
                position=(xform.position_x, xform.position_y, xform.position_z),
                rotation=(xform.rotation_x, xform.rotation_y, xform.rotation_z),
                scale=(xform.scale_x, xform.scale_y, xform.scale_z),
                is_perspective=(cam.projection_type.value == 'perspective'),
                fov=cam.fov,
                aspect_ratio=cam.aspect_ratio,
                ortho_size=cam.ortho_size,
                near_plane=cam.near_plane,
                far_plane=cam.far_plane,
                local_forward=cam.local_forward,
                up_vector=cam.up_vector,
                is_primary=cam.is_primary,
                is_selected=(ent in selected_ids),
                is_editor_visible=(ent in editor_visible),
            ))

        results.sort(key=lambda d: d.entity_id)
        return results
