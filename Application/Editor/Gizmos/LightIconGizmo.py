"""LightIconGizmo — 方向光实体原点图标 (固定屏幕大小; 与 CameraIconGizmo 同范式)。

职责:
  - 将 Resource/Icons/Light.png 加载为 RGBA 纹理
  - 生成带纹理坐标的 unit quad 几何
  - 通过 overlay 机制注册; model_matrix_cb 投影实体世界坐标 → NDC billboard

可见性 (与 camera 图标一致):
  - 由 EditorGizmoLayer._refresh_light_gizmos 驱动;
  - entity 的眼图标 (editor_visible) 关闭 → 图标隐藏;
  - 选中态 → 更亮的暖色 tint。

架构: 零 GL 调用; ignore_scene_matrices=True + model_is_ndc=True; render_layer=1 (screen-space)。
"""

from __future__ import annotations

import math
import numpy as np

from Application.Core.Renderer.Renderer import RenderResourceManger
from Application.Core.Renderer.VertexLayout import VertexLayout

# ════════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════════

ICON_SCREEN_FRACTION: float = 0.045      # 图标占视口高度的 4.5%
OVERLAY_KEY_PREFIX: str = "editor_light_icon"
RAY_KEY_PREFIX: str = "editor_light_ray"
RAY_LENGTH: float = 3.5                  # 方向线世界长度 (GL 单位)

COLOR_UNSELECTED = np.array([1.00, 0.85, 0.40, 0.92], dtype=np.float32)  # 暖黄
COLOR_SELECTED = np.array([1.00, 0.95, 0.55, 1.00], dtype=np.float32)    # 亮黄
COLOR_RAY_UNSELECTED = np.array([1.00, 0.85, 0.40, 0.80], dtype=np.float32)
COLOR_RAY_SELECTED = np.array([1.00, 0.95, 0.55, 0.95], dtype=np.float32)

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

# 射线顶点: 单位段 (0,0,0)-(1,0,0); 4×4 回调把它映射到两端点的 NDC
_RAY_LAYOUT: VertexLayout = VertexLayout(
    attributes=((0, 3, 0),),
    stride=12,
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

# ── 方向射线 (NDC 屏幕段: 两端点经与图标相同的相机投影 — 永远从图标出发且可见) ──

_RAY_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uModel;
void main() {
    gl_Position = uModel * vec4(aPos, 1.0);
}
"""

_RAY_FS: str = """#version 440 core
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    fragColor = uColor;
}
"""


# ════════════════════════════════════════════════════════════════
# 纹理加载 (模块级缓存)
# ════════════════════════════════════════════════════════════════

_cached_icon_pixels: np.ndarray | None = None


def _project_pos_to_ndc(cam, pos, vp_w: int, vp_h: int):
    """世界点 → NDC (与图标 billboard 同一投影约定; 相机后返回 None)."""
    aspect = vp_w / max(vp_h, 1)
    V = np.array(cam.get_view_matrix(), dtype=np.float32).T
    P = np.array(cam.get_projection_matrix(aspect), dtype=np.float32).T
    clip = P @ V @ np.array([pos[0], pos[1], pos[2], 1.0], dtype=np.float32)
    if clip[3] <= 1e-6:
        return None
    return float(clip[0] / clip[3]), float(clip[1] / clip[3])


def _load_icon_texture() -> np.ndarray:
    """加载 Resource/Icons/Light.png 为 RGBA 纹理 (缺失时回退实心方块)。"""
    global _cached_icon_pixels
    if _cached_icon_pixels is not None:
        return _cached_icon_pixels
    import os
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _png_path = os.path.normpath(
        os.path.join(_this_dir, '..', '..', '..', 'Resource', 'Icons', 'Light.png')
    )
    if not os.path.exists(_png_path):
        _png_path = os.path.join('Resource', 'Icons', 'Light.png')

    try:
        from PIL import Image
        _img = Image.open(_png_path).convert('RGBA')
        _pixels = np.array(_img, dtype=np.uint8)  # (H, W, 4)
    except Exception:  # noqa: BLE001 — 图标缺失不阻塞编辑器
        _pixels = np.full((8, 8, 4), 255, dtype=np.uint8)
    _cached_icon_pixels = _pixels
    return _pixels


# ════════════════════════════════════════════════════════════════
# LightIconGizmo
# ════════════════════════════════════════════════════════════════

class LightIconGizmo:
    """方向光原点图标 — 纯数据生成器。"""

    @staticmethod
    def build_icon_overlay(
        entity_id: int,
        world_position: tuple[float, float, float],
        is_selected: bool = False,
    ) -> 'RenderResourceManger.overlay_drawable_struct':
        """为指定 light entity 构建图标 overlay。"""
        vertices, indices = _build_icon_quad()
        tex_pixels = _load_icon_texture()
        key = f"{OVERLAY_KEY_PREFIX}_{entity_id}"
        color = COLOR_SELECTED if is_selected else COLOR_UNSELECTED

        _pos = np.array(world_position, dtype=np.float32)

        def _icon_mvp_cb(vp_w: int, vp_h: int) -> np.ndarray:
            """NDC 空间 billboard — 投影实体世界坐标, 固定屏幕大小 quad。"""
            from Application.Editor.EditorCamera import EditorCamera
            cam = EditorCamera.get_instance()
            aspect = vp_w / max(vp_h, 1)

            view_pyrr = cam.get_view_matrix()
            proj_pyrr = cam.get_projection_matrix(aspect)

            V = np.array(view_pyrr, dtype=np.float32).T
            P = np.array(proj_pyrr, dtype=np.float32).T

            pos4 = np.array([_pos[0], _pos[1], _pos[2], 1.0], dtype=np.float32)
            clip = P @ V @ pos4

            if clip[3] <= 0.0:
                return np.zeros((4, 4), dtype=np.float32)

            ndc_x = clip[0] / clip[3]
            ndc_y = clip[1] / clip[3]

            ndc_h = ICON_SCREEN_FRACTION * 2.0
            ndc_w = ndc_h * (vp_h / max(vp_w, 1))

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
            model_is_ndc=True,
            texture_pixels=tex_pixels,
            texture_uniform='uIconTex',
            layout=_ICON_LAYOUT,
            uniforms={'uColor': color},
            pick_type=0,
            pick_id=0,
            render_layer=1,
        )

    @staticmethod
    def overlay_key_for(entity_id: int) -> str:
        return f"{OVERLAY_KEY_PREFIX}_{entity_id}"

    @staticmethod
    def ray_key_for(entity_id: int) -> str:
        return f"{RAY_KEY_PREFIX}_{entity_id}"

    @staticmethod
    def build_ray_overlay(
        entity_id: int,
        world_position: tuple[float, float, float],
        direction: tuple[float, float, float],
        is_selected: bool = False,
    ) -> 'RenderResourceManger.overlay_drawable_struct':
        """从光位沿光传播方向的屏幕空间方向线 (直观看清照射方向).

        - 两端点 (起点=光位, 终点=光位+方向×长度) 经与图标相同的
          EditorCamera 投影 → NDC 段; 保证: 从图标出发、永远可见、方向与
          实际光照 (GL 世界空间) 一致。
        """
        pos = np.array(world_position, dtype=np.float32)
        d = np.array(direction, dtype=np.float32)
        n = float(np.linalg.norm(d))
        d = d / n if n > 1e-8 else np.array([0.0, -1.0, 0.0], dtype=np.float32)
        tip = pos + d * RAY_LENGTH

        vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
        indices = np.array([0, 1], dtype=np.uint32)
        color = COLOR_RAY_SELECTED if is_selected else COLOR_RAY_UNSELECTED
        _pos = tuple(float(v) for v in pos)
        _tip = tuple(float(v) for v in tip)

        def _ray_ndc_cb(vp_w: int, vp_h: int) -> np.ndarray:
            from Application.Editor.EditorCamera import EditorCamera
            cam = EditorCamera.get_instance()
            p0 = _project_pos_to_ndc(cam, _pos, vp_w, vp_h)
            p1 = _project_pos_to_ndc(cam, _tip, vp_w, vp_h)
            if p0 is None or p1 is None:
                return np.zeros((4, 4), dtype=np.float32)
            M = np.zeros((4, 4), dtype=np.float32)
            M[0, 0] = p1[0] - p0[0]
            M[1, 0] = p1[1] - p0[1]
            M[0, 3] = p0[0]
            M[1, 3] = p0[1]
            M[3, 3] = 1.0
            return M

        return RenderResourceManger.overlay_drawable_struct(
            key=f"{RAY_KEY_PREFIX}_{entity_id}",
            vertices=vertices,
            indices=indices,
            vs_src=_RAY_VS,
            fs_src=_RAY_FS,
            draw_mode='lines',
            depth_test=False,
            blend=True,
            cull_face=False,
            ignore_scene_matrices=True,
            model_matrix_cb=_ray_ndc_cb,
            model_is_ndc=True,
            line_width=2.0,
            layout=_RAY_LAYOUT,
            uniforms={'uColor': color},
            pick_type=0,
            render_layer=1,
        )


# ════════════════════════════════════════════════════════════════
# quad 几何生成
# ════════════════════════════════════════════════════════════════

def _build_icon_quad() -> tuple[np.ndarray, np.ndarray]:
    h = 0.5
    vertices = np.array([
        [-h,  h, 0.0,  0.0, 0.0],
        [ h,  h, 0.0,  1.0, 0.0],
        [ h, -h, 0.0,  1.0, 1.0],
        [-h, -h, 0.0,  0.0, 1.0],
    ], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    return vertices, indices
