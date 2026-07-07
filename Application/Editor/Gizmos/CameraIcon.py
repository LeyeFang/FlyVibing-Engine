"""
CameraIcon — 摄像机 entity 位置图标 (3D 线框, Blender 风格)。

职责:
  - 在 Camera entity 的世界位置绘制一个小型摄像机形状 (3D 线框)
  - 始终面朝摄像机 local forward 方向
  - 纯几何计算，零图形 API 依赖
  - 生成 overlay_drawable_struct 供渲染器使用

图标几何 (在 local 空间中，摄像机看向 -Z):
  - 矩形机身:  4 条线 (宽 0.4, 高 0.25, 深 0.2)
  - 镜头圆圈:  4 条线 (菱形近似，在机身前方 -Z)
  - 取景器三角: 3 条线 (机身顶部)

尺寸: 图标总长约 0.6 世界单位，适合在编辑器 3D 视口中识别。

与 CameraFrustum 的关系:
  - Frustum: 选中时显示，表示摄像机的视锥范围
  - Icon:    始终显示，标记 entity 的位置和朝向

使用方式:
  from Application.Editor.Gizmos.CameraIcon import CameraIcon

  overlay = CameraIcon.build_overlay(cam_data)
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

COLOR_SELECTED = np.array([0.2, 0.8, 1.0, 1.0], dtype=np.float32)   # 浅蓝
COLOR_UNSELECTED = np.array([0.6, 0.6, 0.6, 0.7], dtype=np.float32)  # 半透明灰

# 图标几何尺寸 (local 空间，摄像机看向 -Z)
BODY_W = 0.20     # 机身半宽 (X)
BODY_H = 0.125    # 机身半高 (Y)
BODY_D = 0.10     # 机身半深 (Z)
LENS_R = 0.07     # 镜头半径
LENS_Z = -0.12    # 镜头 Z 位置 (在机身前)
VF_Y  = 0.15      # 取景器顶点高度
VF_Z  = 0.03      # 取景器顶点 Z 偏移

OVERLAY_KEY_PREFIX = "editor_camera_icon"


# ════════════════════════════════════════════════════════════════
# 着色器
# ════════════════════════════════════════════════════════════════

_ICON_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

_ICON_FS: str = """#version 440 core
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    fragColor = uColor;
}
"""


# ════════════════════════════════════════════════════════════════
# CameraIcon
# ════════════════════════════════════════════════════════════════

class CameraIcon:
    """摄像机位置图标 — 3D 线框几何 + overlay 数据生成。"""

    @staticmethod
    def build_overlay(
        cam_data: CameraGizmoData,
    ) -> 'RenderResourceManger.overlay_drawable_struct':
        """从 CameraGizmoData 构建图标 overlay。

        Args:
            cam_data: GizmoQuery 产生的摄像机纯数据

        Returns:
            可直接传入 OverlayRegistrationCommand 的 overlay_drawable_struct
        """
        vertices, indices = CameraIcon._build_icon_geometry(cam_data)
        key = f"{OVERLAY_KEY_PREFIX}_{cam_data.entity_id}"
        color = COLOR_SELECTED if cam_data.is_selected else COLOR_UNSELECTED

        return RenderResourceManger.overlay_drawable_struct(
            key=key,
            vertices=vertices,
            indices=indices,
            vs_src=_ICON_VS,
            fs_src=_ICON_FS,
            draw_mode='lines',
            depth_test=True,
            blend=True,
            line_width=2.0,
            uniforms={
                'uColor': color,
            },
            pick_type=0,
            render_layer=0,
        )

    @staticmethod
    def _build_icon_geometry(
        cam_data: CameraGizmoData,
    ) -> tuple[np.ndarray, np.ndarray]:
        """构建摄像机图标的世界空间线框几何。

        Returns:
            (vertices: (N, 3) float32, indices: (M,) uint32)
        """
        bw, bh, bd = BODY_W, BODY_H, BODY_D
        lr, lz = LENS_R, LENS_Z

        # ── local 空间顶点 ──
        local_verts = np.array([
            # 0-7: 机身 8 角 (front: -Z, back: +Z)
            # front face (z = -bd)
            [-bw, -bh, -bd],  # 0: FLB (front-left-bottom)
            [ bw, -bh, -bd],  # 1: FRB
            [ bw,  bh, -bd],  # 2: FRT
            [-bw,  bh, -bd],  # 3: FLT
            # back face (z = +bd)
            [-bw, -bh,  bd],  # 4: BLB
            [ bw, -bh,  bd],  # 5: BRB
            [ bw,  bh,  bd],  # 6: BRT
            [-bw,  bh,  bd],  # 7: BLT
            # 8-11: 镜头菱形 (在 z = lz 平面)
            [ 0.0, -lr, lz],  # 8:  lens bottom
            [ lr,  0.0, lz],  # 9:  lens right
            [ 0.0,  lr, lz],  # 10: lens top
            [-lr,  0.0, lz],  # 11: lens left
            # 12-13: 取景器三角 (在 z = vf_z 平面, 机身顶部)
            [ 0.0, VF_Y, VF_Z],     # 12: viewfinder tip
            [ 0.0,  bh, VF_Z],     # 13: viewfinder base
        ], dtype=np.float32)

        # ── 索引: 机身 12 条边 + 镜头 4 条边 + 取景器 3 条边 ──
        local_indices = np.array([
            # 机身前面 (4 条边)
            0, 1,   1, 2,   2, 3,   3, 0,
            # 机身后面 (4 条边)
            4, 5,   5, 6,   6, 7,   7, 4,
            # 机身连接 (4 条边)
            0, 4,   1, 5,   2, 6,   3, 7,
            # 镜头菱形 (4 条边)
            8, 9,   9, 10,   10, 11,   11, 8,
            # 取景器三角 (3 条边)
            3, 12,   12, 13,   13, 2,
        ], dtype=np.uint32)

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
            return (p4 @ model)[:3]

        world_verts = np.array([_transform(v) for v in local_verts], dtype=np.float32)

        return world_verts, local_indices

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        """为指定 entity 生成 overlay key。"""
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"
