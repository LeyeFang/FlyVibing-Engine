"""
PositionGizmo — 平移手柄 (G 键)
===============================

三轴箭头 + 三平面手柄，纯数据层，零 GL 调用。
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


class PositionGizmo:
    """三轴箭头 + 三平面平移手柄。"""

    OVERLAY_KEY_PREFIX: str = "editor_transform_gizmo"
    PICK_TYPE: int = 2

    AXIS_DEFS = TransformGizmo.AXIS_DEFS
    PLANE_DEFS = TransformGizmo.PLANE_DEFS

    # ── 尺寸常量 ──
    ARROW_SHAFT_LENGTH: float = 0.70
    ARROW_SHAFT_RADIUS: float = 0.025
    ARROW_TIP_LENGTH: float = 0.30
    ARROW_TIP_RADIUS: float = 0.07
    PLANE_HALF_SIZE: float = 0.12
    PLANE_OFFSET: float = 0.35

    def __init__(self) -> None:
        self._active_drag_key: str | None = None
        self._drag_state: dict | None = None

    # ════════════════════════════════════════════════════════════
    # Brightness
    # ════════════════════════════════════════════════════════════

    def get_handle_brightness(self, key: str) -> float:
        return TransformGizmo.BRIGHTNESS_ACTIVE if key == self._active_drag_key else TransformGizmo.BRIGHTNESS_DIM

    # ════════════════════════════════════════════════════════════
    # 几何生成
    # ════════════════════════════════════════════════════════════

    def _build_arrow_geometry(self, gl_dir: np.ndarray, color: tuple
                              ) -> tuple[np.ndarray, np.ndarray]:
        fwd = gl_dir.astype(np.float32)
        fwd = fwd / max(np.linalg.norm(fwd), 1e-8)
        ref = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        if abs(np.dot(fwd, ref)) > 0.99:
            ref = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        right = np.cross(fwd, ref)
        right = right / max(np.linalg.norm(right), 1e-8)
        up_v = np.cross(right, fwd)
        N_SEG = 10
        shaft_len = self.ARROW_SHAFT_LENGTH
        shaft_r = self.ARROW_SHAFT_RADIUS
        tip_len = self.ARROW_TIP_LENGTH
        tip_r = self.ARROW_TIP_RADIUS
        verts: list[float] = []
        indices: list[int] = []

        def _add_v(pos, col):
            verts.extend([pos[0], pos[1], pos[2], col[0], col[1], col[2]])

        for i in range(N_SEG):
            angle = 2.0 * math.pi * i / N_SEG
            rdir = right * math.cos(angle) + up_v * math.sin(angle)
            _add_v(rdir * shaft_r, color)
            _add_v(fwd * shaft_len + rdir * shaft_r, color)
        for i in range(N_SEG):
            i0, i1 = i * 2, i * 2 + 1
            j0, j1 = ((i + 1) % N_SEG) * 2, ((i + 1) % N_SEG) * 2 + 1
            indices.extend([i0, i1, j0, i1, j1, j0])
        vi = N_SEG * 2
        tip_base = fwd * shaft_len
        tip_apex = fwd * (shaft_len + tip_len)
        for i in range(N_SEG):
            angle = 2.0 * math.pi * i / N_SEG
            rdir = right * math.cos(angle) + up_v * math.sin(angle)
            pos = tip_base + rdir * tip_r
            cone_nrm = rdir * 0.7 + fwd * 0.3
            cone_nrm = cone_nrm / max(np.linalg.norm(cone_nrm), 1e-8)
            _add_v(pos, color)
        apex_idx = vi + N_SEG
        _add_v(tip_apex, color)
        for i in range(N_SEG):
            j = (i + 1) % N_SEG
            indices.extend([vi + i, vi + j, apex_idx])
        base_center_idx = apex_idx + 1
        _add_v(tip_base, color)
        for i in range(N_SEG):
            j = (i + 1) % N_SEG
            indices.extend([vi + j, vi + i, base_center_idx])
        vertices = np.array(verts, dtype=np.float32).reshape(-1, 6)
        idx_arr = np.array(indices, dtype=np.uint32)
        return vertices, idx_arr

    def _build_plane_geometry(self, dir1: np.ndarray, dir2: np.ndarray,
                               color: tuple) -> tuple[np.ndarray, np.ndarray]:
        d1 = dir1.astype(np.float32) / max(np.linalg.norm(dir1), 1e-8)
        d2 = dir2.astype(np.float32) / max(np.linalg.norm(dir2), 1e-8)
        half = self.PLANE_HALF_SIZE
        offset = self.PLANE_OFFSET
        center = (d1 + d2) * offset
        corners = [
            center - d1 * half - d2 * half,
            center + d1 * half - d2 * half,
            center + d1 * half + d2 * half,
            center - d1 * half + d2 * half,
        ]
        verts = []
        for pos in corners:
            verts.extend([pos[0], pos[1], pos[2], color[0], color[1], color[2]])
        vertices = np.array(verts, dtype=np.float32).reshape(4, 6)
        indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
        return vertices, indices

    # ════════════════════════════════════════════════════════════
    # 注册 / 注销
    # ════════════════════════════════════════════════════════════

    def register_to(self, renderer: 'Renderer') -> None:
        from Application.Core.Renderer.Renderer import RenderResourceManger as RRM
        from Application.Core.Renderer.VertexLayout import STD_LAYOUT
        for axis_name, ad in self.AXIS_DEFS.items():
            verts, indices = self._build_arrow_geometry(ad['gl_dir'], ad['color'])
            overlay_key = f"{self.OVERLAY_KEY_PREFIX}_axis_{axis_name}"
            overlay = RRM.overlay_drawable_struct(
                key=overlay_key, vertices=verts, indices=indices,
                vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='triangles',
                depth_test=True, blend=False, cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=TransformGizmo._compute_mvp_cb,
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=self.PICK_TYPE, pick_id=ad['pick_id'],
                render_layer=1, model_is_ndc=True,
                uniforms={'uBrightness': (lambda k=overlay_key, s=self: np.array(
                    [s.get_handle_brightness(k)], 'f4')),
                    'uAlpha': np.array([1.0], 'f4')},
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))
        for plane_name, pd in self.PLANE_DEFS.items():
            d1, d2 = pd['gl_dirs']
            verts, indices = self._build_plane_geometry(d1, d2, pd['color'])
            overlay_key = f"{self.OVERLAY_KEY_PREFIX}_plane_{plane_name}"
            overlay = RRM.overlay_drawable_struct(
                key=overlay_key, vertices=verts, indices=indices,
                vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='triangles',
                depth_test=True, blend=True, cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=TransformGizmo._compute_mvp_cb,
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=self.PICK_TYPE, pick_id=pd['pick_id'],
                render_layer=1, model_is_ndc=True,
                uniforms={'uBrightness': (lambda k=overlay_key, s=self: np.array(
                    [s.get_handle_brightness(k)], 'f4')),
                    'uAlpha': np.array([1.0], 'f4')},
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))
        OverlayRegisteredEvent.Pack('TransformGizmo', engine=EditorHost)

    def unregister_from(self, renderer: 'Renderer') -> None:
        for axis_name in self.AXIS_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{self.OVERLAY_KEY_PREFIX}_axis_{axis_name}"))
        for plane_name in self.PLANE_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{self.OVERLAY_KEY_PREFIX}_plane_{plane_name}"))
        OverlayUnregisteredEvent.Pack('TransformGizmo', engine=EditorHost)

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
                return {'kind': 'axis', 'name': name, 'pick_id': ad['pick_id'],
                        'gl_dir': ad['gl_dir'].copy(), 'color': ad['color']}
        elif rest.startswith('plane_'):
            name = rest[6:]
            pd = self.PLANE_DEFS.get(name)
            if pd:
                return {'kind': 'plane', 'name': name, 'pick_id': pd['pick_id'],
                        'gl_dirs': (pd['gl_dirs'][0].copy(), pd['gl_dirs'][1].copy()),
                        'color': pd['color']}
        return None

    # ════════════════════════════════════════════════════════════
    # 拖拽
    # ════════════════════════════════════════════════════════════

    def begin_axis_drag(self, entity_pos: np.ndarray, axis_dir: np.ndarray,
                        cam_pos: np.ndarray, ray_o: np.ndarray, ray_d: np.ndarray) -> None:
        axis_dir = axis_dir / max(np.linalg.norm(axis_dir), 1e-8)
        entity_pos = np.asarray(entity_pos, dtype=np.float32)
        cam_arr = np.asarray(cam_pos, dtype=np.float32)
        view_dir = entity_pos - cam_arr
        view_len = float(np.linalg.norm(view_dir))
        if view_len < 1e-4:
            view_dir = np.array([0.0, -1.0, 0.0], dtype=np.float32)
        else:
            view_dir = view_dir / view_len
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        camera_right = np.cross(view_dir, world_up)
        if np.linalg.norm(camera_right) < 1e-6:
            camera_right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        camera_right = camera_right / max(np.linalg.norm(camera_right), 1e-8)
        plane_normal = np.cross(axis_dir, camera_right)
        if np.linalg.norm(plane_normal) < 1e-6:
            plane_normal = np.cross(axis_dir, world_up)
        plane_normal = plane_normal / max(np.linalg.norm(plane_normal), 1e-8)
        hit = TransformGizmo.ray_plane_intersection(ray_o, ray_d, entity_pos, plane_normal)
        mouse_start = (TransformGizmo.closest_point_on_axis(hit, entity_pos, axis_dir)
                       if hit is not None else entity_pos.copy())
        self._drag_state = {
            'mode': 'axis', 'axis_dir': axis_dir,
            'plane_normal': plane_normal, 'plane_point': entity_pos.copy(),
            'start_pos': entity_pos.copy(), 'mouse_start': mouse_start,
        }
        for name, ad in self.AXIS_DEFS.items():
            if np.allclose(ad['gl_dir'], axis_dir, atol=1e-3):
                self._active_drag_key = f"{self.OVERLAY_KEY_PREFIX}_axis_{name}"
                break

    def begin_plane_drag(self, entity_pos: np.ndarray, d1: np.ndarray,
                         d2: np.ndarray, ray_o: np.ndarray, ray_d: np.ndarray) -> None:
        d1 = np.asarray(d1, dtype=np.float32) / max(np.linalg.norm(d1), 1e-8)
        d2 = np.asarray(d2, dtype=np.float32) / max(np.linalg.norm(d2), 1e-8)
        entity_pos = np.asarray(entity_pos, dtype=np.float32)
        plane_normal = np.cross(d1, d2)
        plane_normal = plane_normal / max(np.linalg.norm(plane_normal), 1e-8)
        hit = TransformGizmo.ray_plane_intersection(ray_o, ray_d, entity_pos, plane_normal)
        mouse_start = hit if hit is not None else entity_pos.copy()
        self._drag_state = {
            'mode': 'plane', 'plane_normal': plane_normal,
            'plane_point': entity_pos.copy(), 'start_pos': entity_pos.copy(),
            'mouse_start': mouse_start,
        }
        for name, pd in self.PLANE_DEFS.items():
            if (np.allclose(pd['gl_dirs'][0], d1, atol=1e-3)
                    and np.allclose(pd['gl_dirs'][1], d2, atol=1e-3)):
                self._active_drag_key = f"{self.OVERLAY_KEY_PREFIX}_plane_{name}"
                break

    def update_drag(self, ray_o: np.ndarray, ray_d: np.ndarray) -> np.ndarray | None:
        if self._drag_state is None:
            return None
        ds = self._drag_state
        hit = TransformGizmo.ray_plane_intersection(
            ray_o, ray_d, ds['plane_point'], ds['plane_normal'])
        if hit is None:
            return None
        if ds['mode'] == 'axis':
            current = TransformGizmo.closest_point_on_axis(
                hit, ds['start_pos'], ds['axis_dir'])
            delta = current - ds['mouse_start']
        else:
            delta = hit - ds['mouse_start']
        return ds['start_pos'] + delta

    def end_drag(self) -> None:
        self._drag_state = None
        self._active_drag_key = None

    def is_dragging(self) -> bool:
        return self._drag_state is not None
