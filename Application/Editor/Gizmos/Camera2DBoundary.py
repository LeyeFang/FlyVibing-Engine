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

COLOR_SELECTED = np.array([0.2, 0.8, 1.0, 0.9], dtype=np.float32)   # 浅蓝
COLOR_UNSELECTED = np.array([0.7, 0.7, 0.7, 0.5], dtype=np.float32)  # 半透明白

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
            depth_test=True,
            blend=True,
            line_width=1.5,
            uniforms={
                'uColor': color,
            },
            pick_type=0,
            render_layer=0,
        )

    @staticmethod
    def _build_boundary_geometry(
        cam_data: CameraGizmoData,
    ) -> tuple[np.ndarray, np.ndarray]:
        """构建正交视口矩形 + 方向箭头的顶点和索引。

        矩形在摄像机的 local XZ 平面 (y=0, GL XZ = Editor XY 地面) 上，
        覆盖 ortho_size 范围。对于俯视 2D 摄像机，矩形自然落在世界地面。

        Returns:
            (vertices: (N, 3) float32, indices: (M,) uint32)
        """
        half_h = cam_data.ortho_size
        half_w = half_h * cam_data.aspect_ratio

        # ── local 空间: 矩形四角在 XZ 平面 (y=0) ──
        # 摄像机看向 local -Z, 矩形在垂直于 forward 的 XZ 平面
        tl = np.array([-half_w, 0.0,  half_h], dtype=np.float32)  # XZ: top-left
        tr = np.array([ half_w, 0.0,  half_h], dtype=np.float32)  # XZ: top-right
        br = np.array([ half_w, 0.0, -half_h], dtype=np.float32)  # XZ: bottom-right
        bl = np.array([-half_w, 0.0, -half_h], dtype=np.float32)  # XZ: bottom-left

        # ── 方向箭头 (朝向 local -Z, 在矩形中心前方) ──
        arrow_base = np.array([0.0, 0.0,  half_h * 0.85], dtype=np.float32)
        arrow_tip  = np.array([0.0, 0.0,  half_h * 1.15], dtype=np.float32)

        # ── TRS 模型矩阵 ──
        model = calculate_entity_model(
            position=cam_data.position,
            rotation=cam_data.rotation,
            scale=cam_data.scale,
        )

        def _transform(pt: np.ndarray) -> np.ndarray:
            p4 = np.append(pt, 1.0).astype(np.float32)
            wp = p4 @ model
            return wp[:3]

        # ── 变换到世界空间 ──
        corners_w = np.array([_transform(p) for p in (tl, tr, br, bl)], dtype=np.float32)
        arrow_w = np.array([_transform(arrow_base), _transform(arrow_tip)], dtype=np.float32)

        # ── 顶点布局 ──
        # 0-3: rect corners, 4-5: arrow base/tip
        vertices = np.vstack([corners_w, arrow_w], dtype=np.float32)

        # ── 索引: 4 条矩形边 + 2 条箭头线 ──
        indices = np.array([
            0, 1,   1, 2,   2, 3,   3, 0,    # rect
            4, 5,                               # arrow
        ], dtype=np.uint32)

        return vertices, indices

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        """为指定 entity 生成 overlay key。"""
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"
