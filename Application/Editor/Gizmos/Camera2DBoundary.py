"""
Camera2DBoundary — 正交(2D)摄像机视口边界线框几何生成器。

职责:
  - 根据 Camera + Transform 数据计算世界空间矩形边界 + 方向箭头
  - 纯数学计算，零图形 API 依赖
  - 生成 overlay_drawable_struct 供渲染器使用

生成的几何:
  - 4 条线: 正交视口矩形边框 (白色)
  - 2 条线: 方向指示箭头 (摄像机朝向角标)
  共 6 条线段 = 12 个顶点

与 CameraFrustum 的区分:
  - Frustum: 四棱锥线框 (透视摄像机)
  - Boundary: 平面矩形 (正交摄像机, 无锥顶)

使用方式:
  from Application.Editor.Gizmos.Camera2DBoundary import Camera2DBoundary

  overlay = Camera2DBoundary.build_overlay(cam_data)
  renderer.enqueue(OverlayRegistrationCommand(overlay))
"""

from __future__ import annotations

import numpy as np

from Application.Core.Scene.GizmoQuery import CameraGizmoData
from Application.Core.Math.Transform import calculate_entity_model
from Application.Core.Renderer.Renderer import RenderResourceManger


# ════════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════════

# 2D 边界框颜色 (绿色调，区别于 3D frustum 白色)
COLOR_SELECTED = np.array([0.35, 1.0, 0.55, 0.95], dtype=np.float32)    # 亮绿
COLOR_UNSELECTED = np.array([0.4, 0.85, 0.5, 0.5], dtype=np.float32)    # 半透绿

OVERLAY_KEY_PREFIX = "editor_camera_boundary_2d"


# ════════════════════════════════════════════════════════════════
# 着色器 (与 CameraFrustum 共用同一套简单 VS/FS)
# ════════════════════════════════════════════════════════════════

_BOUNDARY_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

_BOUNDARY_FS: str = """#version 440 core
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    fragColor = uColor;
}
"""


# ════════════════════════════════════════════════════════════════
# Camera2DBoundary
# ════════════════════════════════════════════════════════════════

class Camera2DBoundary:
    """正交摄像机视口边界 — 纯几何计算 + overlay 数据生成。"""

    VIS_DEPTH: float = 1.5   # 矩形距摄像机的固定可视化距离 (世界单位)

    @staticmethod
    def build_overlay(
        cam_data: CameraGizmoData,
    ) -> 'RenderResourceManger.overlay_drawable_struct':
        """从 CameraGizmoData 构建 overlay drawable。

        Args:
            cam_data: GizmoQuery 产生的摄像机纯数据

        Returns:
            可直接传入 OverlayRegistrationCommand 的 overlay_drawable_struct
        """
        vertices, indices = Camera2DBoundary._build_boundary_geometry(cam_data)
        key = f"{OVERLAY_KEY_PREFIX}_{cam_data.entity_id}"
        color = COLOR_SELECTED if cam_data.is_selected else COLOR_UNSELECTED

        return RenderResourceManger.overlay_drawable_struct(
            key=key,
            vertices=vertices,
            indices=indices,
            vs_src=_BOUNDARY_VS,
            fs_src=_BOUNDARY_FS,
            draw_mode='lines',
            depth_test=False,
            blend=True,
            line_width=2.0,
            uniforms={
                'uColor': color,
            },
            pick_type=0,
            render_layer=1,   # screen-space，始终覆盖实体
        )

    @staticmethod
    def _build_boundary_geometry(
        cam_data: CameraGizmoData,
    ) -> tuple[np.ndarray, np.ndarray]:
        """构建正交视口矩形的 4 个角点 + 8 个索引 (4 条线段)。

        矩形落在世界地面 (GL XZ 平面, Y=0, = 编辑器 XY 平面)。
        T@R 约定: world_Y = local_z + position[2] (当 Rx=90° 俯视时)。
        令 world_Y=0 → local_z = -position[2]。

        Returns:
            (vertices: (4, 3) float32, indices: (8,) uint32)
        """
        half_h = cam_data.ortho_size
        half_w = half_h * cam_data.aspect_ratio
        # 抵消预旋转位移，使 world Y = 0 (地面)
        ground_z = -cam_data.position[2]

        # ── local 空间: 矩形四角在 XY 平面, z = ground_z ──
        local_corners = np.array([
            [-half_w,  half_h, ground_z],   # TL
            [ half_w,  half_h, ground_z],   # TR
            [ half_w, -half_h, ground_z],   # BR
            [-half_w, -half_h, ground_z],   # BL
        ], dtype=np.float32)

        # ── TRS 模型矩阵 (local → world) ──
        model = calculate_entity_model(
            position=cam_data.position,
            rotation=cam_data.rotation,
            scale=cam_data.scale,
        )

        def _transform(pt: np.ndarray) -> np.ndarray:
            p4 = np.append(pt, 1.0).astype(np.float32)
            wp = p4 @ model
            return wp[:3]

        corners_world = np.array([_transform(c) for c in local_corners], dtype=np.float32)

        # ── 4 条边: TL→TR, TR→BR, BR→BL, BL→TL ──
        indices = np.array([0, 1, 1, 2, 2, 3, 3, 0], dtype=np.uint32)

        return corners_world, indices

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        """为指定 entity 生成 overlay key。"""
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"
