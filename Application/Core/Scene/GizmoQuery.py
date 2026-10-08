"""
GizmoQuery — ECS 世界查询层，供编辑器 Gizmo 使用。

职责:
  - 从 ECS World (esper) 中查询含特定 Component 的 entity
  - 返回纯 Python dataclass 列表，不依赖任何图形 API 或编辑器模块

设计原则:
  - 零图形依赖: 只依赖 esper + numpy + Python stdlib
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
import numpy as np

from Application.Core.Scene.BasicComponents import Camera, Transform, Light


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


@dataclass
class LightGizmoData:
    """单个 Light entity 的 Gizmo 渲染所需数据，纯值类型。"""

    entity_id: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    light_type: str
    color_r: float
    color_g: float
    color_b: float
    intensity: float
    range: float
    is_selected: bool
    is_editor_visible: bool = True  # 眼图标控制 (与 camera 同规则)
    direction: tuple[float, float, float] = (0.0, -1.0, 0.0)  # 仅平面光有效 (点光=(0,0,0))


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

    @staticmethod
    def get_light_gizmos(
        selected_ids: Optional[set[int]] = None,
    ) -> list[LightGizmoData]:
        """遍历 ECS 中所有含 Light + Transform 的 entity (光位图标用)。"""
        if selected_ids is None:
            selected_ids = set()

        editor_visible: set[int] = set()
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            st = SceneManager._current()
            editor_visible = st._editor_visible
        except Exception:
            pass

        results: list[LightGizmoData] = []
        from Application.Core.Math.Transform import calculate_entity_model
        for ent, (light, xform) in esper.get_components(Light, Transform):
            light_type = str(getattr(light, 'light_type', 'directional')).lower()
            if light_type == 'point':
                direction = (0.0, 0.0, 0.0)   # 点光无方向 (方向线不绘制)
            else:
                # 光传播方向 d = -model[2,:3] 归一化 (与 OpenGLEntities._collect_light_frame 同式)
                try:
                    model = calculate_entity_model(
                        position=(xform.position_x, xform.position_y, xform.position_z),
                        rotation=(xform.rotation_x, xform.rotation_y, xform.rotation_z),
                        scale=(xform.scale_x, xform.scale_y, xform.scale_z),
                    )
                    dv = -model[2, :3]
                    norm = float(np.linalg.norm(dv))
                    direction = (tuple((dv / norm).tolist()) if norm > 1e-8
                                 else (0.0, -1.0, 0.0))
                except Exception as _e:  # noqa: BLE001 — 显式告警, 不静默
                    print(f"[GizmoQuery] light direction fallback: {type(_e).__name__}: {_e}")
                    direction = (0.0, -1.0, 0.0)
            results.append(LightGizmoData(
                entity_id=ent,
                position=(xform.position_x, xform.position_y, xform.position_z),
                rotation=(xform.rotation_x, xform.rotation_y, xform.rotation_z),
                scale=(xform.scale_x, xform.scale_y, xform.scale_z),
                light_type=light_type,
                color_r=light.color_r,
                color_g=light.color_g,
                color_b=light.color_b,
                intensity=light.intensity,
                range=light.range,
                is_selected=(ent in selected_ids),
                is_editor_visible=(ent in editor_visible),
                direction=direction,
            ))

        results.sort(key=lambda d: d.entity_id)
        return results
