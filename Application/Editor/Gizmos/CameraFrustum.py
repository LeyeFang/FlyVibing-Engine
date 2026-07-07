"""
CameraFrustum — 透视摄像机椎体线框几何生成器。

职责:
  - 根据 Camera + Transform 数据计算世界空间 frustum 线框顶点
  - 纯数学计算，零图形 API 依赖
  - 生成 overlay_drawable_struct 供渲染器使用

生成的几何:
  - 4 条棱线: 摄像机位置 → 远平面四角
  - 4 条线: 近平面矩形
  - 4 条线: 远平面矩形
  共 12 条线段 = 24 个顶点 (每线段 2 端点)

使用方式:
  from Application.Editor.Gizmos.CameraFrustum import CameraFrustum

  overlay = CameraFrustum.build_overlay(cam_data)
  renderer.enqueue(OverlayRegistrationCommand(overlay))
"""

from __future__ import annotations

import math
import numpy as np

from Application.Core.Scene.GizmoQuery import CameraGizmoData
from Application.Core.Math.Transform import calculate_entity_model
from Application.Core.Renderer.Renderer import RenderResourceManger


# ════════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════════

# 选中 / 未选中颜色
COLOR_SELECTED = np.array([0.2, 0.8, 1.0, 0.9], dtype=np.float32)   # 浅蓝
COLOR_UNSELECTED = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)  # 半透明灰

OVERLAY_KEY_PREFIX = "editor_camera_frustum"


# ════════════════════════════════════════════════════════════════
# 着色器
# ════════════════════════════════════════════════════════════════

_FRUSTUM_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

_FRUSTUM_FS: str = """#version 440 core
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    fragColor = uColor;
}
"""


# ════════════════════════════════════════════════════════════════
# CameraFrustum
# ════════════════════════════════════════════════════════════════

class CameraFrustum:
    """透视摄像机椎体线框 — 纯几何计算 + overlay 数据生成。"""

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
        vertices, indices = CameraFrustum._build_frustum_geometry(cam_data)
        key = f"{OVERLAY_KEY_PREFIX}_{cam_data.entity_id}"
        color = COLOR_SELECTED if cam_data.is_selected else COLOR_UNSELECTED

        return RenderResourceManger.overlay_drawable_struct(
            key=key,
            vertices=vertices,
            indices=indices,
            vs_src=_FRUSTUM_VS,
            fs_src=_FRUSTUM_FS,
            draw_mode='lines',
            depth_test=False,
            blend=True,
            line_width=1.5,
            uniforms={
                'uColor': color,
            },
            pick_type=0,
            render_layer=1,  # 屏幕空间，始终覆盖 entity + outliner
        )

    @staticmethod
    def _build_frustum_geometry(
        cam_data: CameraGizmoData,
    ) -> tuple[np.ndarray, np.ndarray]:
        """构建 frustum 的 5 个顶点 + 16 个索引 (8 条线段)。

        椎体使用固定的小型可视化深度 (1.5 世界单位)，
        仅通过 fov 和 aspect_ratio 决定矩形面形状，
        不随 near/far plane 变化。

        几何:
          - 1 个锥顶点 (摄像机位置)
          - 4 个底面角点 (矩形，在 local -Z 方向 VIS_DEPTH 处)
          - 4 条棱线: apex → 底面四角
          - 4 条边: 底面矩形

        Returns:
            (vertices: (5, 3) float32, indices: (16,) uint32)
        """
        VIS_DEPTH = 1.5  # 固定可视化深度 (世界单位)

        fov_rad = math.radians(cam_data.fov)

        # ── 在 VIS_DEPTH 处的矩形半高半宽 ──
        half_h = VIS_DEPTH * math.tan(fov_rad / 2.0)
        half_w = half_h * cam_data.aspect_ratio

        # ── local 空间: 锥顶点 (原点) + 底面四角 (在 z = -VIS_DEPTH) ──
        # 顺序: TL, TR, BR, BL
        local_corners = np.array([
            [-half_w,  half_h, -VIS_DEPTH],   # TL
            [ half_w,  half_h, -VIS_DEPTH],   # TR
            [ half_w, -half_h, -VIS_DEPTH],   # BR
            [-half_w, -half_h, -VIS_DEPTH],   # BL
        ], dtype=np.float32)

        apex_local = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        # ── TRS 模型矩阵 (local → world) ──
        model = calculate_entity_model(
            position=cam_data.position,
            rotation=cam_data.rotation,
            scale=cam_data.scale,
        )

        # ── 变换到世界空间 ──
        # pyrr 矩阵是 row-vector 约定: v_world = v_local @ model
        def _transform(pt: np.ndarray) -> np.ndarray:
            p4 = np.append(pt, 1.0).astype(np.float32)
            wp = p4 @ model
            return wp[:3]

        apex_world = _transform(apex_local)
        corners_world = np.array([_transform(c) for c in local_corners], dtype=np.float32)

        # ── 组装: 5 个顶点 (apex + 4 corners) ──
        vertices = np.vstack([
            apex_world.reshape(1, 3),
            corners_world,
        ], dtype=np.float32)

        # ── 8 条线段: 4 棱 + 4 底面 ──
        # 0 = apex, 1-4 = TL, TR, BR, BL
        indices = np.array([
            0, 1,   0, 2,   0, 3,   0, 4,    # apex → corners
            1, 2,   2, 3,   3, 4,   4, 1,    # base rect
        ], dtype=np.uint32)

        return vertices, indices

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        """为指定 entity 生成 overlay key。"""
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"
