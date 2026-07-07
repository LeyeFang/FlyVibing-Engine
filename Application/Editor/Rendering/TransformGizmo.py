"""
TransformGizmo — 变换 Gizmo (三轴箭头 + 三平面平移手柄)
========================================================

点击物体后出现三条轴的箭头和三个平面手柄，用以拖动 entity 进行平移。

坐标约定 (编辑器 ←→ GL):
  - 编辑器 X = GL +X  (+X 右)
  - 编辑器 Y = GL -Z  (-Z 前)
  - 编辑器 Z = GL +Y  (+Y 上)

Gizmo 组成部分:
  - X 轴箭头 (红色,   GL +X 方向, pick_id=1)
  - Y 轴箭头 (绿色,   GL -Z 方向, pick_id=2)
  - Z 轴箭头 (蓝色,   GL +Y 方向, pick_id=3)
  - XY 平面手柄 (黄色   255,255,0,  GL XZ 平面, pick_id=4)
  - XZ 平面手柄 (品红   255,0,255,  GL XY 平面, pick_id=5)
  - YZ 平面手柄 (青色   0,255,255,  GL -ZY 平面, pick_id=6)

架构:
  - ignore_scene_matrices=True, model_matrix_cb 计算完整 MVP
  - 视觉 pass 与拾取 pass 共用同一 model_matrix_cb, 保证拾取位置正确
  - 顶点着色器直接输出 clip-space 坐标 (gl_Position = uModel * aPos)
  - 片段着色器纯色输出 (标准 transform gizmo 风格)

使用方式:
  TransformGizmo.set_target_position(pos)     # 设置 gizmo 世界位置
  TransformGizmo.register_to(renderer)        # OnAttach
  TransformGizmo.unregister_from(renderer)    # OnDetach
  TransformGizmo.get_pick_data()              # 拾取数据
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import math
import numpy as np

if TYPE_CHECKING:
    from Application.Core.Renderer.Renderer import Renderer

from Application.Core.Renderer.RenderCommand import (
    OverlayRegistrationCommand,
    OverlayUnregistrationCommand,
)
from Application.Editor.EditorEvent import (
    OverlayRegisteredEvent,
    OverlayUnregisteredEvent,
)


# ════════════════════════════════════════════════════════════════
# 内联着色器
# ════════════════════════════════════════════════════════════════

_GIZMO_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aColor;
uniform mat4 uModel;
out vec3 vColor;
void main() {
    gl_Position = uModel * vec4(aPos, 1.0);
    vColor = aColor;
}
"""

_GIZMO_FS: str = """#version 440 core
in vec3 vColor;
uniform float uBrightness;
out vec4 fragColor;
void main() {
    fragColor = vec4(vColor * uBrightness, 1.0);
}
"""

# ════════════════════════════════════════════════════════════════
# 拾取着色器 (与实体拾取共用 _PICK_VS / _PICK_FS, 此处仅记录)
# pick_type=2  → TransformGizmo
# pick_id=1~3  → X/Y/Z 轴
# pick_id=4~6  → XY/XZ/YZ 平面
# ════════════════════════════════════════════════════════════════


class TransformGizmo:
    """变换 Gizmo — 三轴箭头 + 三面平移手柄 (纯数据层, 零 GL)。"""

    OVERLAY_KEY_PREFIX: str = "editor_transform_gizmo"

    # ── 轴定义 ────────────────────────────────────────────
    #   axis_name → { gl_dir, color, pick_id }
    AXIS_DEFS: dict[str, dict] = {
        'x': {
            'gl_dir':   np.array([1.0, 0.0, 0.0], dtype=np.float32),   # GL +X = Editor +X
            'color':    (1.0, 0.15, 0.10),                               # 红色
            'pick_id':  1,
        },
        'y': {
            'gl_dir':   np.array([0.0, 0.0, -1.0], dtype=np.float32),  # GL -Z = Editor +Y
            'color':    (0.15, 1.0, 0.15),                               # 绿色
            'pick_id':  2,
        },
        'z': {
            'gl_dir':   np.array([0.0, 1.0, 0.0], dtype=np.float32),   # GL +Y = Editor +Z
            'color':    (0.15, 0.25, 1.0),                               # 蓝色
            'pick_id':  3,
        },
    }

    # ── 平面定义 ──────────────────────────────────────────
    #   plane_name → { gl_dirs, color, pick_id }
    PLANE_DEFS: dict[str, dict] = {
        'xy': {
            # Editor XY = GL XZ 平面: 由 GL +X 和 GL -Z 张成
            'gl_dirs': (
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
                np.array([0.0, 0.0, -1.0], dtype=np.float32),
            ),
            'color':    (1.0, 1.0, 0.0),    # 黄色 255,255,0
            'pick_id':  4,
        },
        'xz': {
            # Editor XZ = GL XY 平面: 由 GL +X 和 GL +Y 张成
            'gl_dirs': (
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
                np.array([0.0, 1.0, 0.0], dtype=np.float32),
            ),
            'color':    (1.0, 0.0, 1.0),    # 品红 255,0,255
            'pick_id':  5,
        },
        'yz': {
            # Editor YZ = GL -ZY 平面: 由 GL -Z 和 GL +Y 张成
            'gl_dirs': (
                np.array([0.0, 0.0, -1.0], dtype=np.float32),
                np.array([0.0, 1.0, 0.0], dtype=np.float32),
            ),
            'color':    (0.0, 1.0, 1.0),    # 青色 0,255,255
            'pick_id':  6,
        },
    }

    # ── 尺寸常量 ──────────────────────────────────────────
    GIZMO_SCREEN_FRACTION: float = 0.30  # gizmo 占视口高度的 30%
    ARROW_SHAFT_LENGTH: float = 0.70
    ARROW_SHAFT_RADIUS: float = 0.025
    ARROW_TIP_LENGTH: float = 0.30
    ARROW_TIP_RADIUS: float = 0.07
    PLANE_HALF_SIZE: float = 0.12
    PLANE_OFFSET: float = 0.35          # 平面中心沿两轴各偏移量

    # ── 内部状态 ──────────────────────────────────────────
    _target_pos: np.ndarray = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    _active_drag_key: str | None = None  # 当前被拖拽的 overlay key
    _visible: bool = False               # 无选中实体时隐藏
    _VERBOSE: bool = False               # 拖拽细节日志（调试时改为 True）

    # ════════════════════════════════════════════════════════════
    # 手柄亮度 (供 renderer via callable uniform 每帧读取)
    # ════════════════════════════════════════════════════════════

    BRIGHTNESS_DIM: float = 0.35
    BRIGHTNESS_ACTIVE: float = 1.0

    @classmethod
    def get_handle_brightness(cls, key: str) -> float:
        """返回指定 overlay 手柄的当前亮度 (供 renderer 每帧读取)。"""
        return cls.BRIGHTNESS_ACTIVE if key == cls._active_drag_key else cls.BRIGHTNESS_DIM

    # ════════════════════════════════════════════════════════════
    # 目标位置管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def set_target_position(cls, pos) -> None:
        """设置 gizmo 的世界空间位置。

        Args:
            pos: (3,) array-like, 世界坐标
        """
        cls._target_pos = np.array(pos, dtype=np.float32)

    @classmethod
    def get_target_position(cls) -> np.ndarray:
        """获取当前 gizmo 世界位置。"""
        return cls._target_pos.copy()

    # ════════════════════════════════════════════════════════════
    # Model 矩阵回调 (ignore_scene_matrices=True)
    # 计算完整 MVP: v_clip = P @ V @ M @ v_local
    # 返回 numpy column-vector 矩阵, 上传用 GL_TRUE (对齐 ViewGizmo)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _compute_mvp_cb(cls, vp_w: int, vp_h: int) -> np.ndarray:
        """计算完整 MVP 矩阵 (含恒定屏幕空间缩放)。

        视觉 pass 与拾取 pass 共用此回调, 保证拾取位置正确。
        gizmo 在屏幕上始终占据固定比例 (GIZMO_SCREEN_FRACTION), 不随镜头拉远拉近变化。
        """
        if not cls._visible:
            return np.zeros((4, 4), dtype=np.float32)  # 不渲染: 零矩阵
        from Application.Editor.EditorCamera import EditorCamera

        cam = EditorCamera.get_instance()
        pos = cls._target_pos
        aspect = vp_w / max(vp_h, 1)

        # 获取 pyrr 视图/投影矩阵
        view_pyrr = cam.get_view_matrix()
        proj_pyrr = cam.get_projection_matrix(aspect)

        # pyrr → numpy column-vector
        V = np.array(view_pyrr, dtype=np.float32).T
        P = np.array(proj_pyrr, dtype=np.float32).T

        # ── 恒定屏幕空间缩放 ──
        # gizmo 几何体局部空间 max extent ≈ 1.0
        # 透视: NDC_y = (world_y / dist) / tan(fov/2)
        #         scale = GIZMO_SCREEN_FRACTION * dist * tan(fov/2)
        # 正交: NDC_y = world_y / ortho_size
        #         scale = GIZMO_SCREEN_FRACTION * ortho_size
        if cam.is_orthographic:
            scale = cls.GIZMO_SCREEN_FRACTION * cam.ortho_size
        else:
            cam_pos = cam.position
            dist = float(np.linalg.norm(cam_pos - pos))
            dist = max(dist, 0.01)
            fov_half = math.radians(cam.fov / 2.0)
            scale = cls.GIZMO_SCREEN_FRACTION * dist * math.tan(fov_half)

        # Model: S(scale) @ T(pos) — 先缩放再平移 (column-vector)
        M = np.identity(4, dtype=np.float32)
        M[0, 0] = scale
        M[1, 1] = scale
        M[2, 2] = scale
        M[0, 3] = pos[0]
        M[1, 3] = pos[1]
        M[2, 3] = pos[2]

        # MVP = P @ V @ M (column-vector convention)
        MVP = P @ V @ M
        return MVP.astype(np.float32)

    # ════════════════════════════════════════════════════════════
    # 几何生成
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _build_arrow_geometry(
        cls,
        gl_dir: np.ndarray,
        color: tuple,
    ) -> tuple[np.ndarray, np.ndarray]:
        """生成箭头几何 (轴杆圆柱 + 锥尖)。

        Args:
            gl_dir: GL 空间中的轴方向 (单位向量)
            color:  RGB 颜色元组 (r, g, b)

        Returns:
            (vertices (N, 11), indices (M,)) — float32 / uint32
        """
        fwd = gl_dir.astype(np.float32)
        fwd = fwd / max(np.linalg.norm(fwd), 1e-8)

        # 局部坐标系: right, up 与 fwd 正交
        ref = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        if abs(np.dot(fwd, ref)) > 0.99:
            ref = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        right = np.cross(fwd, ref)
        right = right / max(np.linalg.norm(right), 1e-8)
        up = np.cross(right, fwd)

        shaft_len = cls.ARROW_SHAFT_LENGTH
        shaft_r = cls.ARROW_SHAFT_RADIUS
        tip_len = cls.ARROW_TIP_LENGTH
        tip_r = cls.ARROW_TIP_RADIUS
        N_SEG = 10  # 圆周分段

        verts: list[float] = []
        indices: list[int] = []
        vi = 0

        def _add_v(pos, col, nrm):
            verts.extend([
                pos[0], pos[1], pos[2],
                col[0], col[1], col[2],
            ])

        # ── 轴杆 (圆柱侧面) ──
        for i in range(N_SEG):
            angle = 2.0 * math.pi * i / N_SEG
            rdir = right * math.cos(angle) + up * math.sin(angle)
            nrm = rdir.copy()
            # 底圈
            _add_v(rdir * shaft_r, color, nrm)
            # 顶圈 (shaft_len 处)
            _add_v(fwd * shaft_len + rdir * shaft_r, color, nrm)

        for i in range(N_SEG):
            i0 = i * 2
            i1 = i * 2 + 1
            j0 = ((i + 1) % N_SEG) * 2
            j1 = ((i + 1) % N_SEG) * 2 + 1
            indices.extend([i0, i1, j0, i1, j1, j0])

        vi = N_SEG * 2

        # ── 锥尖侧面 ──
        tip_base = fwd * shaft_len
        tip_apex = fwd * (shaft_len + tip_len)

        for i in range(N_SEG):
            angle = 2.0 * math.pi * i / N_SEG
            rdir = right * math.cos(angle) + up * math.sin(angle)
            pos = tip_base + rdir * tip_r
            # 锥面法线: 沿斜面方向
            side_dir = tip_apex - pos
            side_dir = side_dir / max(np.linalg.norm(side_dir), 1e-8)
            # 使用径向分量 mixed with 前向
            cone_nrm = rdir * 0.7 + fwd * 0.3
            cone_nrm = cone_nrm / max(np.linalg.norm(cone_nrm), 1e-8)
            _add_v(pos, color, cone_nrm)

        apex_idx = vi + N_SEG
        _add_v(tip_apex, color, fwd)

        for i in range(N_SEG):
            j = (i + 1) % N_SEG
            indices.extend([vi + i, vi + j, apex_idx])

        # ── 锥底盖 (封闭) ──
        base_center_idx = apex_idx + 1
        _add_v(tip_base, color, -fwd)

        for i in range(N_SEG):
            j = (i + 1) % N_SEG
            # 锥底三角形: 中心 → 边 (注意逆时针以保证法线朝外)
            indices.extend([vi + j, vi + i, base_center_idx])

        vertices = np.array(verts, dtype=np.float32).reshape(-1, 6)
        idx_arr = np.array(indices, dtype=np.uint32)
        return vertices, idx_arr

    @classmethod
    def _build_plane_geometry(
        cls,
        dir1: np.ndarray,
        dir2: np.ndarray,
        color: tuple,
    ) -> tuple[np.ndarray, np.ndarray]:
        """生成平面手柄几何 (小正方形)。

        Args:
            dir1, dir2: 平面张成的两个正交方向 (GL 空间)
            color:      RGB 颜色

        Returns:
            (vertices (4, 6), indices (6,))
        """
        d1 = dir1.astype(np.float32)
        d1 = d1 / max(np.linalg.norm(d1), 1e-8)
        d2 = dir2.astype(np.float32)
        d2 = d2 / max(np.linalg.norm(d2), 1e-8)

        normal = np.cross(d1, d2)
        normal = normal / max(np.linalg.norm(normal), 1e-8)
        half = cls.PLANE_HALF_SIZE
        offset = cls.PLANE_OFFSET

        center = (d1 + d2) * offset

        corners = [
            center - d1 * half - d2 * half,
            center + d1 * half - d2 * half,
            center + d1 * half + d2 * half,
            center - d1 * half + d2 * half,
        ]

        verts = []
        for pos in corners:
            verts.extend([
                pos[0], pos[1], pos[2],
                color[0], color[1], color[2],
            ])

        vertices = np.array(verts, dtype=np.float32).reshape(4, 6)
        indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
        return vertices, indices

    # ════════════════════════════════════════════════════════════
    # 注册 / 注销 (纯数据, 零 GL, 对齐 ViewGizmo/Grid 模式)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_to(cls, renderer: 'Renderer') -> None:
        """注册 6 个 overlay (3 轴 + 3 面)。"""
        from Application.Core.Renderer.Renderer import RenderResourceManger as RRM
        from Application.Core.Renderer.VertexLayout import STD_LAYOUT

        # ── 3 轴箭头 ──
        for axis_name, ad in cls.AXIS_DEFS.items():
            verts, indices = cls._build_arrow_geometry(ad['gl_dir'], ad['color'])
            overlay_key = f"{cls.OVERLAY_KEY_PREFIX}_axis_{axis_name}"
            overlay = RRM.overlay_drawable_struct(
                key=overlay_key,
                vertices=verts,
                indices=indices,
                vs_src=_GIZMO_VS,
                fs_src=_GIZMO_FS,
                draw_mode='triangles',
                depth_test=True,
                blend=False,
                cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=cls._compute_mvp_cb,
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=2,            # 2 = TransformGizmo
                pick_id=ad['pick_id'],  # 1/2/3
                render_layer=1,         # screen-space overlay
                model_is_ndc=True,      # _compute_mvp_cb 返回完整 MVP
                uniforms={
                    'uBrightness': (lambda k=overlay_key: np.array(
                        [cls.get_handle_brightness(k)], 'f4')),
                },
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))

        # ── 3 平面手柄 ──
        for plane_name, pd in cls.PLANE_DEFS.items():
            d1, d2 = pd['gl_dirs']
            verts, indices = cls._build_plane_geometry(d1, d2, pd['color'])
            overlay_key = f"{cls.OVERLAY_KEY_PREFIX}_plane_{plane_name}"
            overlay = RRM.overlay_drawable_struct(
                key=overlay_key,
                vertices=verts,
                indices=indices,
                vs_src=_GIZMO_VS,
                fs_src=_GIZMO_FS,
                draw_mode='triangles',
                depth_test=True,
                blend=True,
                cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=cls._compute_mvp_cb,
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=2,            # 2 = TransformGizmo
                pick_id=pd['pick_id'],  # 4/5/6
                render_layer=1,         # screen-space overlay
                model_is_ndc=True,      # _compute_mvp_cb 返回完整 MVP
                uniforms={
                    'uBrightness': (lambda k=overlay_key: np.array(
                        [cls.get_handle_brightness(k)], 'f4')),
                },
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))

        from Application.Editor.EditorHost import EditorHost
        OverlayRegisteredEvent.Pack('TransformGizmo', engine=EditorHost)

    @classmethod
    def unregister_from(cls, renderer: 'Renderer') -> None:
        """注销所有 6 个 overlay。"""
        for axis_name in cls.AXIS_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{cls.OVERLAY_KEY_PREFIX}_axis_{axis_name}"
            ))
        for plane_name in cls.PLANE_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{cls.OVERLAY_KEY_PREFIX}_plane_{plane_name}"
            ))
        cls._renderer = None
        from Application.Editor.EditorHost import EditorHost
        OverlayUnregisteredEvent.Pack('TransformGizmo', engine=EditorHost)

    _renderer: any = None  # 记录当前绑定的渲染器，供 show/hide 使用

    @classmethod
    def show(cls, renderer: 'Renderer', entity_id: int) -> None:
        """在实体位置显示 gizmo — 按需注册。"""
        from Application.Core.Scene.SceneManager import SceneManager
        if cls._renderer is None:
            cls.register_to(renderer)
            cls._renderer = renderer
        try:
            t = SceneManager.GetEntityTransform(entity_id)
            cls.set_target_position((t.position_x, t.position_y, t.position_z))
        except Exception:
            pass

    @classmethod
    def hide(cls) -> None:
        """隐藏 gizmo — 注销干净。"""
        if cls._renderer is not None:
            cls.unregister_from(cls._renderer)
            cls._renderer = None

    # ════════════════════════════════════════════════════════════
    # 拾取数据导出
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_pick_data(cls) -> dict:
        """返回 FBO 拾取所需的元数据。

        Returns:
            {
                'axis_defs':   AXIS_DEFS,
                'plane_defs':  PLANE_DEFS,
                'key_prefix':  OVERLAY_KEY_PREFIX,
            }
        """
        return {
            'axis_defs':   cls.AXIS_DEFS,
            'plane_defs':  cls.PLANE_DEFS,
            'key_prefix':  cls.OVERLAY_KEY_PREFIX,
        }

    # ════════════════════════════════════════════════════════════
    # 拾取解析辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def parse_pick_key(cls, pick_value: str) -> dict | None:
        """解析拾取返回的 overlay key。

        Args:
            pick_value: 如 "editor_transform_gizmo_axis_x"

        Returns:
            {'kind': 'axis'|'plane', 'name': 'x'|'xy', 'pick_id': int} 或 None
        """
        prefix = cls.OVERLAY_KEY_PREFIX
        if not pick_value.startswith(prefix):
            return None

        rest = pick_value[len(prefix) + 1:]  # skip prefix + '_'
        if rest.startswith('axis_'):
            name = rest[5:]  # skip 'axis_'
            ad = cls.AXIS_DEFS.get(name)
            if ad:
                return {
                    'kind': 'axis',
                    'name': name,
                    'pick_id': ad['pick_id'],
                    'gl_dir': ad['gl_dir'].copy(),
                    'color': ad['color'],
                }
        elif rest.startswith('plane_'):
            name = rest[6:]  # skip 'plane_'
            pd = cls.PLANE_DEFS.get(name)
            if pd:
                return {
                    'kind': 'plane',
                    'name': name,
                    'pick_id': pd['pick_id'],
                    'gl_dirs': (pd['gl_dirs'][0].copy(), pd['gl_dirs'][1].copy()),
                    'color': pd['color'],
                }
        return None

    # ════════════════════════════════════════════════════════════
    # 拖拽数学工具 (从测试文件搬运, 已验证)
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def screen_to_world_ray(
        mx: float, my: float,
        vp_w: int, vp_h: int,
        view_mat: np.ndarray,
        proj_mat: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """屏幕坐标 → 世界空间射线 (origin, direction)。"""
        ndc_x = (2.0 * mx / vp_w) - 1.0
        ndc_y = 1.0 - (2.0 * my / vp_h)

        near_clip = np.array([ndc_x, ndc_y, -1.0, 1.0], dtype=np.float32)
        far_clip = np.array([ndc_x, ndc_y, 1.0, 1.0], dtype=np.float32)

        V = np.array(view_mat, dtype=np.float32).T
        P = np.array(proj_mat, dtype=np.float32).T
        VP = P @ V
        inv_VP = np.linalg.inv(VP)

        near_world = inv_VP @ near_clip
        far_world = inv_VP @ far_clip
        near_world /= near_world[3]
        far_world /= far_world[3]

        origin = near_world[:3].copy()
        direction = far_world[:3] - near_world[:3]
        direction = direction / np.linalg.norm(direction)
        return origin, direction

    @staticmethod
    def ray_plane_intersection(
        ray_origin: np.ndarray, ray_dir: np.ndarray,
        plane_point: np.ndarray, plane_normal: np.ndarray,
    ) -> np.ndarray | None:
        """射线与平面求交。"""
        denom = np.dot(ray_dir, plane_normal)
        if abs(denom) < 1e-8:
            if TransformGizmo._VERBOSE:
                print(f"  [DBG-GIZMO] ray_plane_intersection FAIL: denom={denom:.6f}")
            return None
        t = np.dot(plane_point - ray_origin, plane_normal) / denom
        if t < 0:
            if TransformGizmo._VERBOSE:
                print(f"  [DBG-GIZMO] ray_plane_intersection FAIL: t={t:.3f}<0")
            return None
        hit = ray_origin + ray_dir * t
        if TransformGizmo._VERBOSE:
            print(f"  [DBG-GIZMO] ray_plane_intersection OK: denom={denom:.4f} t={t:.3f} hit=({hit[0]:.2f},{hit[1]:.2f},{hit[2]:.2f})")
        return hit

    @staticmethod
    def closest_point_on_axis(
        point: np.ndarray, axis_origin: np.ndarray, axis_dir: np.ndarray,
    ) -> np.ndarray:
        """点到轴线的最近点。"""
        v = point - axis_origin
        t = np.dot(v, axis_dir)
        return axis_origin + axis_dir * t

    # ════════════════════════════════════════════════════════════
    # 拖拽状态机 (纯数据, 零 GL)
    # ════════════════════════════════════════════════════════════

    _drag_state: dict | None = None

    @classmethod
    def begin_axis_drag(
        cls,
        entity_pos: np.ndarray,
        axis_dir: np.ndarray,
        cam_pos: np.ndarray,
        ray_o: np.ndarray,
        ray_d: np.ndarray,
    ) -> None:
        """开始沿轴拖拽 — 计算起始状态。"""
        axis_dir = axis_dir / max(np.linalg.norm(axis_dir), 1e-8)
        entity_pos = np.asarray(entity_pos, dtype=np.float32)
        cam_arr = np.asarray(cam_pos, dtype=np.float32)

        if cls._VERBOSE:
            print(f"  [DBG-GIZMO] begin_axis_drag: entity=({entity_pos[0]:.2f},{entity_pos[1]:.2f},{entity_pos[2]:.2f})")
            print(f"    axis_dir=({axis_dir[0]:.3f},{axis_dir[1]:.3f},{axis_dir[2]:.3f})")
            print(f"    cam_pos=({cam_arr[0]:.2f},{cam_arr[1]:.2f},{cam_arr[2]:.2f})")
            print(f"    ray_o=({ray_o[0]:.2f},{ray_o[1]:.2f},{ray_o[2]:.2f}) ray_d=({ray_d[0]:.3f},{ray_d[1]:.3f},{ray_d[2]:.3f})")

        # 构建拖拽平面: 法线 = axis × camera_right (面朝摄像机, 射线不会退化)
        view_dir = entity_pos - cam_arr
        view_dir = view_dir / max(np.linalg.norm(view_dir), 1e-8)
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        camera_right = np.cross(view_dir, world_up)
        if np.linalg.norm(camera_right) < 1e-6:
            camera_right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        camera_right = camera_right / max(np.linalg.norm(camera_right), 1e-8)

        plane_normal = np.cross(axis_dir, camera_right)
        if np.linalg.norm(plane_normal) < 1e-6:
            # 轴平行于 camera_right → 回退用 world_up
            plane_normal = np.cross(axis_dir, world_up)
        plane_normal = plane_normal / max(np.linalg.norm(plane_normal), 1e-8)

        if cls._VERBOSE:
            print(f"    view_dir=({view_dir[0]:.3f},{view_dir[1]:.3f},{view_dir[2]:.3f})")
            print(f"    plane_normal=({plane_normal[0]:.3f},{plane_normal[1]:.3f},{plane_normal[2]:.3f})")

        hit = cls.ray_plane_intersection(ray_o, ray_d, entity_pos, plane_normal)
        mouse_start = (
            cls.closest_point_on_axis(hit, entity_pos, axis_dir)
            if hit is not None else entity_pos.copy())

        cls._drag_state = {
            'mode': 'axis',
            'axis_dir': axis_dir,
            'plane_normal': plane_normal,
            'plane_point': entity_pos.copy(),
            'start_pos': entity_pos.copy(),
            'mouse_start': mouse_start,
        }

        # ── 查找 overlay key 用于亮度高亮 ──
        for name, ad in cls.AXIS_DEFS.items():
            if np.allclose(ad['gl_dir'], axis_dir, atol=1e-3):
                cls._active_drag_key = f"{cls.OVERLAY_KEY_PREFIX}_axis_{name}"
                break

    @classmethod
    def begin_plane_drag(
        cls,
        entity_pos: np.ndarray,
        d1: np.ndarray,
        d2: np.ndarray,
        ray_o: np.ndarray,
        ray_d: np.ndarray,
    ) -> None:
        """开始平面内拖拽。

        Args:
            entity_pos: 实体世界位置 (3,)
            d1, d2:     平面张成的两个 GL 方向 — 来自 PLANE_DEFS['gl_dirs']
            ray_o:      当前鼠标射线起点
            ray_d:      当前鼠标射线方向
        """
        d1 = np.asarray(d1, dtype=np.float32)
        d2 = np.asarray(d2, dtype=np.float32)
        d1 = d1 / max(np.linalg.norm(d1), 1e-8)
        d2 = d2 / max(np.linalg.norm(d2), 1e-8)
        entity_pos = np.asarray(entity_pos, dtype=np.float32)

        plane_normal = np.cross(d1, d2)
        plane_normal = plane_normal / max(np.linalg.norm(plane_normal), 1e-8)

        hit = cls.ray_plane_intersection(ray_o, ray_d, entity_pos, plane_normal)
        mouse_start = hit if hit is not None else entity_pos.copy()

        cls._drag_state = {
            'mode': 'plane',
            'plane_normal': plane_normal,
            'plane_point': entity_pos.copy(),
            'start_pos': entity_pos.copy(),
            'mouse_start': mouse_start,
        }

        # ── 查找 overlay key 用于亮度高亮 ──
        for name, pd in cls.PLANE_DEFS.items():
            if (np.allclose(pd['gl_dirs'][0], d1, atol=1e-3)
                    and np.allclose(pd['gl_dirs'][1], d2, atol=1e-3)):
                cls._active_drag_key = f"{cls.OVERLAY_KEY_PREFIX}_plane_{name}"
                break

    @classmethod
    def is_dragging(cls) -> bool:
        """是否正在拖拽中。"""
        return cls._drag_state is not None

    @classmethod
    def update_drag(
        cls,
        ray_o: np.ndarray,
        ray_d: np.ndarray,
    ) -> np.ndarray | None:
        """更新拖拽 — 返回新的实体世界位置。"""
        if cls._drag_state is None:
            return None

        ds = cls._drag_state
        hit = cls.ray_plane_intersection(
            ray_o, ray_d, ds['plane_point'], ds['plane_normal'])
        if hit is None:
            if cls._VERBOSE:
                print(f"  [DBG-GIZMO] update_drag: no hit (mode={ds['mode']})")
            return None

        if ds['mode'] == 'axis':
            current = cls.closest_point_on_axis(hit, ds['start_pos'], ds['axis_dir'])
            delta = current - ds['mouse_start']
        else:  # plane
            delta = hit - ds['mouse_start']

        new_pos = ds['start_pos'] + delta
        if cls._VERBOSE:
            print(f"  [DBG-GIZMO] update_drag: mode={ds['mode']} delta=({delta[0]:.3f},{delta[1]:.3f},{delta[2]:.3f}) new=({new_pos[0]:.2f},{new_pos[1]:.2f},{new_pos[2]:.2f})")
        return new_pos

    @classmethod
    def end_drag(cls) -> None:
        """结束拖拽 — 清理内部状态。"""
        cls._drag_state = None
        cls._active_drag_key = None
