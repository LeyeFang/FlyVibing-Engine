"""
CameraIconGizmo — 摄像机实体原点图标 (固定屏幕大小)
====================================================

在每个场景 Camera entity 的原点 (frustum 锥顶点) 绘制一个小型摄像机图标。
图标在屏幕上保持固定像素大小，始终覆盖所有场景内容 + outliner。

职责:
  - 将 camera.svg 渲染为 RGBA 纹理 (cairosvg + PIL)
  - 生成带纹理坐标的 quad 几何
  - 通过 overlay 机制注册到渲染器，使用 model_matrix_cb 实现恒定屏幕大小

坐标约定 (与 TransformGizmo/ViewGizmo 对齐):
  - 编辑器 X = GL +X (右)
  - 编辑器 Y = GL -Z (前)
  - 编辑器 Z = GL +Y (上)

架构:
  - 零 GL 调用: 仅提供数据，GPU 资源由渲染器管理
  - ignore_scene_matrices=True, model_is_ndc=True — 直接输出 clip-space 坐标
  - render_layer=1 — screen-space overlay

使用方式:
  from Application.Editor.Gizmos.CameraIconGizmo import CameraIconGizmo

  icon_overlay = CameraIconGizmo.build_icon_overlay(entity_id, world_position)
  renderer.enqueue(OverlayRegistrationCommand(icon_overlay))
"""

from __future__ import annotations

import math
import numpy as np

from Application.Core.Renderer.Renderer import RenderResourceManger
from Application.Core.Renderer.VertexLayout import VertexLayout

# ════════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════════

ICON_SCREEN_FRACTION: float = 0.035      # 图标占视口高度的 3.5%
OVERLAY_KEY_PREFIX: str = "editor_camera_icon"

# ════════════════════════════════════════════════════════════════
# 图标顶点布局: pos(3f) + texcoord(2f) = 5 floats = 20 bytes
# ════════════════════════════════════════════════════════════════

_ICON_LAYOUT: VertexLayout = VertexLayout(
    attributes=(
        (0, 3, 0),   # aPos      — location 0, vec3, byte offset 0
        (1, 2, 12),  # aTexCoord — location 1, vec2, byte offset 12
    ),
    stride=20,
)


# ════════════════════════════════════════════════════════════════
# 着色器
# ════════════════════════════════════════════════════════════════

_ICON_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec2 aTexCoord;
uniform mat4 uModel;
out vec2 vTexCoord;
void main() {
    gl_Position = uModel * vec4(aPos, 1.0);
    vTexCoord = aTexCoord;
}
"""

_ICON_FS: str = """#version 440 core
in vec2 vTexCoord;
uniform sampler2D uIconTex;
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    vec4 texColor = texture(uIconTex, vTexCoord);
    fragColor = vec4(uColor.rgb, texColor.a * uColor.a);
}
"""


# ════════════════════════════════════════════════════════════════
# 纹理加载 (模块级缓存)
# ════════════════════════════════════════════════════════════════

_cached_icon_pixels: np.ndarray | None = None


def _load_icon_texture() -> np.ndarray:
    """加载 Resource/Icons/camera.png 为 RGBA 纹理。

    Returns:
        (H, W, 4) uint8 RGBA numpy 数组
    """
    global _cached_icon_pixels
    if _cached_icon_pixels is not None:
        return _cached_icon_pixels

    from PIL import Image

    # 定位 PNG 文件 (与 camera.svg 同目录)
    import os
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _png_path = os.path.normpath(
        os.path.join(_this_dir, '..', '..', '..', 'Resource', 'Icons', 'camera.png')
    )
    if not os.path.exists(_png_path):
        _png_path = os.path.join('Resource', 'Icons', 'camera.png')

    _img = Image.open(_png_path).convert('RGBA')
    _pixels = np.array(_img, dtype=np.uint8)  # (H, W, 4)
    _cached_icon_pixels = _pixels
    return _pixels


# ════════════════════════════════════════════════════════════════
# CameraIconGizmo
# ════════════════════════════════════════════════════════════════

class CameraIconGizmo:
    """摄像机原点图标 — 纯数据生成器。"""

    @staticmethod
    def build_icon_overlay(
        entity_id: int,
        world_position: tuple[float, float, float],
    ) -> 'RenderResourceManger.overlay_drawable_struct':
        """为指定 camera entity 构建图标 overlay。

        Args:
            entity_id:      摄像机 entity ID
            world_position: 摄像机在 world space 中的位置 (frustum apex)

        Returns:
            可直接传入 OverlayRegistrationCommand 的 overlay_drawable_struct
        """
        vertices, indices = _build_icon_quad()
        tex_pixels = _load_icon_texture()
        key = f"{OVERLAY_KEY_PREFIX}_{entity_id}"

        # 闭包捕获 world_position，供 model_matrix_cb 每帧使用
        _pos = np.array(world_position, dtype=np.float32)

        def _icon_mvp_cb(vp_w: int, vp_h: int) -> np.ndarray:
            """NDC 空间 billboard — 图标始终正面朝向摄像机，不受透视/旋转影响。

            1. 将 entity 世界坐标投影到 NDC
            2. 在 NDC 位置放置固定大小的 quad
            3. 返回 clip-space 矩阵 (model_is_ndc=True, 无需额外 view/proj)
            """
            from Application.Editor.EditorCamera import EditorCamera
            cam = EditorCamera.get_instance()
            aspect = vp_w / max(vp_h, 1)

            view_pyrr = cam.get_view_matrix()
            proj_pyrr = cam.get_projection_matrix(aspect)

            V = np.array(view_pyrr, dtype=np.float32).T
            P = np.array(proj_pyrr, dtype=np.float32).T

            # ── 投影 entity 世界坐标 → clip space → NDC ──
            pos4 = np.array([_pos[0], _pos[1], _pos[2], 1.0], dtype=np.float32)
            clip = P @ V @ pos4

            # 在摄像机后方或极端远处 → 零矩阵隐藏
            if clip[3] <= 0.0:
                return np.zeros((4, 4), dtype=np.float32)

            ndc_x = clip[0] / clip[3]
            ndc_y = clip[1] / clip[3]

            # ── 图标 NDC 大小 (基于视口高度比例, 校正宽高比) ──
            ndc_h = ICON_SCREEN_FRACTION * 2.0             # NDC 全高 = 2.0
            ndc_w = ndc_h * (vp_h / max(vp_w, 1))         # 保持正方形

            # ── 构建 clip-space 矩阵: 仅缩放+平移, w=1 → 无透视除法 ──
            M = np.identity(4, dtype=np.float32)
            M[0, 0] = ndc_w
            M[1, 1] = ndc_h
            M[0, 3] = ndc_x
            M[1, 3] = ndc_y
            return M

        return RenderResourceManger.overlay_drawable_struct(
            key=key,
            vertices=vertices,
            indices=indices,
            vs_src=_ICON_VS,
            fs_src=_ICON_FS,
            draw_mode='triangles',
            depth_test=False,
            blend=True,
            cull_face=False,
            ignore_scene_matrices=True,
            model_matrix_cb=_icon_mvp_cb,
            model_is_ndc=True,           # 回调返回完整 MVP
            texture_pixels=tex_pixels,
            texture_uniform='uIconTex',
            layout=_ICON_LAYOUT,
            uniforms={
                'uColor': np.array([0.55, 0.55, 0.55, 0.85], dtype=np.float32),
            },
            pick_type=0,                 # 不可拾取
            pick_id=0,
            render_layer=1,              # screen-space, 始终最前
        )

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        """为指定 entity 生成 overlay key。"""
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"


# ════════════════════════════════════════════════════════════════
# quad 几何生成
# ════════════════════════════════════════════════════════════════

def _build_icon_quad() -> tuple[np.ndarray, np.ndarray]:
    """生成单位 quad (XY 平面, 中心在原点)。

    Returns:
        (vertices (4, 5) float32, indices (6,) uint32)
        顶点格式: [px, py, pz,  u, v]
    """
    h = 0.5
    vertices = np.array([
        [-h,  h, 0.0,  0.0, 0.0],   # TL
        [ h,  h, 0.0,  1.0, 0.0],   # TR
        [ h, -h, 0.0,  1.0, 1.0],   # BR
        [-h, -h, 0.0,  0.0, 1.0],   # BL
    ], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    return vertices, indices
