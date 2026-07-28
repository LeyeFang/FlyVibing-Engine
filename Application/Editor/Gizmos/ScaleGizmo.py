"""
ScaleGizmo — 缩放手柄 (S 键)
============================

三轴缩放圆 (红/绿/蓝, alpha=0.3) + 均匀缩放圆 (灰白, alpha=0.3)。
所有圆均 billboard 始终面朝摄像机。按住高亮 alpha=0.8。
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
from Application.Editor.EditorHost import EditorHost
from Application.Editor.Gizmos.TransformGizmo import (
    _GIZMO_VS, _GIZMO_FS, TransformGizmo,
)


class ScaleGizmo:
    """三轴缩放圆 + 均匀缩放圆 (全部 billboard)。"""

    OVERLAY_KEY_PREFIX: str = "editor_scale_gizmo"
    PICK_TYPE: int = 4
    CIRCLE_RADIUS: float = 0.10
    CIRCLE_SEGMENTS: int = 32
    ALPHA_NORMAL: float = 0.3
    ALPHA_ACTIVE: float = 0.8

    AXIS_DEFS = TransformGizmo.AXIS_DEFS

    UNIFORM_OFFSET: np.ndarray = np.array([1.0, 1.0, 0.0], dtype=np.float32)
    UNIFORM_COLOR: tuple = (0.78, 0.78, 0.78)  # 200/255

    def __init__(self) -> None:
        self._active_drag_key: str | None = None
        self._drag_state: dict | None = None

    def _get_alpha(self, key: str) -> float:
        return self.ALPHA_ACTIVE if key == self._active_drag_key else self.ALPHA_NORMAL

    def get_handle_brightness(self, key: str) -> float:
        return 1.0  # Scale gizmo 用 uAlpha 控制透明度

    # ════════════════════════════════════════════════════════════
    # 几何 (原点 XY 平面, 颜色烘焙)
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _build_circle_geometry(color: tuple, radius: float, segments: int
                               ) -> tuple[np.ndarray, np.ndarray]:
        verts = [0.0, 0.0, 0.0, color[0], color[1], color[2]]
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            verts.extend([radius * math.cos(angle), radius * math.sin(angle),
                          0.0, color[0], color[1], color[2]])
        vertices = np.array(verts, dtype=np.float32).reshape(-1, 6)
        indices = []
        for i in range(1, segments):
            indices.extend([0, i, i + 1])
        indices.extend([0, segments, 1])
        return vertices, np.array(indices, dtype=np.uint32)

    # ════════════════════════════════════════════════════════════
    # 注册 / 注销
    # ════════════════════════════════════════════════════════════

    def register_to(self, renderer: 'Renderer') -> None:
        from Application.Core.Renderer.Renderer import RenderResourceManger as RRM
        from Application.Core.Renderer.VertexLayout import STD_LAYOUT
        # ── 3 轴圆 (各轴独立颜色 + billboard MVP) ──
        for i, (axis_name, ad) in enumerate(self.AXIS_DEFS.items()):
            verts, indices = self._build_circle_geometry(
                ad['color'], self.CIRCLE_RADIUS, self.CIRCLE_SEGMENTS)
            overlay_key = f"{self.OVERLAY_KEY_PREFIX}_axis_{axis_name}"
            overlay = RRM.overlay_drawable_struct(
                key=overlay_key, vertices=verts, indices=indices,
                vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='triangles',
                depth_test=True, blend=True, cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=TransformGizmo._make_billboard_mvp_cb(
                    ad['gl_dir'] * 1.0),
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=self.PICK_TYPE, pick_id=10 + i,
                render_layer=1, model_is_ndc=True,
                uniforms={'uBrightness': np.array([1.0], 'f4'),
                          'uAlpha': (lambda k=overlay_key, s=self: np.array(
                              [s._get_alpha(k)], 'f4'))},
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))
        # ── 均匀缩放圆 ──
        u_verts, u_indices = self._build_circle_geometry(
            self.UNIFORM_COLOR, self.CIRCLE_RADIUS, self.CIRCLE_SEGMENTS)
        u_key = f"{self.OVERLAY_KEY_PREFIX}_uniform"
        overlay_u = RRM.overlay_drawable_struct(
            key=u_key, vertices=u_verts, indices=u_indices,
            vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='triangles',
            depth_test=True, blend=True, cull_face=False,
            ignore_scene_matrices=True,
            model_matrix_cb=TransformGizmo._make_billboard_mvp_cb(
                self.UNIFORM_OFFSET),
            layout=STD_LAYOUT.TRANSFORM_GIZMO,
            pick_type=self.PICK_TYPE, pick_id=13,
            render_layer=1, model_is_ndc=True,
            uniforms={'uBrightness': np.array([1.0], 'f4'),
                      'uAlpha': (lambda k=u_key, s=self: np.array(
                          [s._get_alpha(k)], 'f4'))},
        )
        renderer.enqueue(OverlayRegistrationCommand(overlay_u))
        OverlayRegisteredEvent.Pack('ScaleGizmo', engine=EditorHost)

    def unregister_from(self, renderer: 'Renderer') -> None:
        for axis_name in self.AXIS_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{self.OVERLAY_KEY_PREFIX}_axis_{axis_name}"))
        renderer.enqueue(OverlayUnregistrationCommand(
            f"{self.OVERLAY_KEY_PREFIX}_uniform"))
        OverlayUnregisteredEvent.Pack('ScaleGizmo', engine=EditorHost)

    # ════════════════════════════════════════════════════════════
    # Pick
    # ════════════════════════════════════════════════════════════

    def parse_pick_key(self, pick_value: str) -> dict | None:
        prefix = self.OVERLAY_KEY_PREFIX
        if not pick_value.startswith(prefix):
            return None
        rest = pick_value[len(prefix) + 1:]
        if rest.startswith('axis_'):
            name = rest[5:]
            ad = self.AXIS_DEFS.get(name)
            if ad:
                return {'kind': 'scale_axis', 'name': name,
                        'pick_id': 10 + list(self.AXIS_DEFS.keys()).index(name),
                        'gl_dir': ad['gl_dir'].copy(), 'color': ad['color']}
        elif rest == 'uniform':
            return {'kind': 'scale_uniform', 'name': 'uniform', 'pick_id': 13,
                    'gl_dir': self.UNIFORM_OFFSET.copy(), 'color': self.UNIFORM_COLOR}
        return None

    # ════════════════════════════════════════════════════════════
    # 拖拽
    # ════════════════════════════════════════════════════════════

    def begin_scale_drag(self, entity_pos: np.ndarray, gl_dir: np.ndarray | None,
                         ray_o: np.ndarray, ray_d: np.ndarray,
                         current_scale: tuple = (1.0, 1.0, 1.0)) -> None:
        entity_pos = np.asarray(entity_pos, dtype=np.float32)
        cs = tuple(float(v) for v in current_scale)
        if gl_dir is not None:
            gl_dir = np.asarray(gl_dir, dtype=np.float32)
            gl_dir = gl_dir / max(np.linalg.norm(gl_dir), 1e-8)
            # ★ 拖拽平面法线: 用世界 up 叉乘轴方向, 保证射线求交不退化
            world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            plane_normal = np.cross(gl_dir, world_up)
            if np.linalg.norm(plane_normal) < 1e-6:
                plane_normal = np.cross(gl_dir, np.array([1.0, 0.0, 0.0], dtype=np.float32))
            plane_normal = plane_normal / max(np.linalg.norm(plane_normal), 1e-8)
            self._drag_state = {
                'mode': 'scale_axis', 'axis_dir': gl_dir,
                'plane_normal': plane_normal, 'plane_point': entity_pos.copy(),
                'start_pos': entity_pos.copy(), 'start_scale': list(cs),
                'mouse_start': None,
            }
            # 记录激活的 key
            for name, ad in self.AXIS_DEFS.items():
                if np.allclose(ad['gl_dir'], gl_dir, atol=1e-3):
                    self._active_drag_key = f"{self.OVERLAY_KEY_PREFIX}_axis_{name}"
                    break
        else:
            # 均匀缩放: 法线朝向摄像机
            from Application.Editor.EditorCamera import EditorCamera
            cam = EditorCamera.get_instance()
            cam_pos = np.asarray(cam.position, dtype=np.float32)
            to_cam = cam_pos - entity_pos
            to_cam = to_cam / max(np.linalg.norm(to_cam), 1e-8)
            self._drag_state = {
                'mode': 'scale_uniform', 'plane_point': entity_pos.copy(),
                'plane_normal': to_cam,
                'start_pos': entity_pos.copy(), 'start_scale': list(cs),
                'ref_dir': np.array([1.0, 1.0, 0.0], dtype=np.float32),
                'mouse_start': None,
            }
            self._active_drag_key = f"{self.OVERLAY_KEY_PREFIX}_uniform"
        pn = self._drag_state['plane_normal']
        hit = TransformGizmo.ray_plane_intersection(ray_o, ray_d, entity_pos, pn)
        self._drag_state['mouse_start'] = hit if hit is not None else entity_pos.copy()

    def update_scale_drag(self, ray_o: np.ndarray, ray_d: np.ndarray) -> tuple | None:
        if self._drag_state is None:
            return None
        ds = self._drag_state
        hit = TransformGizmo.ray_plane_intersection(
            ray_o, ray_d, ds['plane_point'], ds['plane_normal'])
        if hit is None:
            return None
        if ds['mode'] == 'scale_axis':
            axis = ds['axis_dir']
            delta = hit - ds['mouse_start']
            proj = float(np.dot(delta, axis))
            ss = ds['start_scale']  # [sx, sy, sz] baseline
            # 仅该轴缩放, 其他保持 baseline
            base_s = ss[0] if abs(float(axis[0])) > 0.5 else (ss[1] if abs(float(axis[1])) > 0.5 else ss[2])
            s = base_s + proj / 1.0
            s = max(s, 0.01)
            ax, ay, az = abs(float(axis[0])), abs(float(axis[1])), abs(float(axis[2]))
            return (s if ax > 0.5 else ss[0],
                    s if ay > 0.5 else ss[1],
                    s if az > 0.5 else ss[2])
        else:
            ref = ds['ref_dir']
            ref_len = float(np.linalg.norm(ref))
            if ref_len < 1e-8:
                return tuple(ds['start_scale'])
            ref_u = ref / ref_len
            delta = hit - ds['mouse_start']
            proj = float(np.dot(delta, ref_u))
            ss = ds['start_scale']
            base_s = ss[0]  # 均匀缩放取第一分量作为基准
            s = base_s + proj / ref_len
            s = max(s, 0.01)
            return (s, s, s)

    def end_drag(self) -> None:
        self._drag_state = None
        self._active_drag_key = None

    def is_dragging(self) -> bool:
        return self._drag_state is not None
