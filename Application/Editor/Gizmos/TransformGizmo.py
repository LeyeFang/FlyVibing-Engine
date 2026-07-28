
"""
TransformGizmo — Gizmo Facade
===============================
G/R/S keys switch mode, delegating to PositionGizmo / RotationGizmo / ScaleGizmo.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from enum import Enum

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
uniform float uAlpha;
out vec4 fragColor;
void main() {
    fragColor = vec4(vColor * uBrightness, uAlpha);
}
"""


class GizmoMode(Enum):
    GRAB = "grab"
    ROTATE = "rotate"
    SCALE = "scale"


class TransformGizmo:
    """Transform Gizmo facade — mode switching + shared state + math utils."""

    OVERLAY_KEY_PREFIX: str = "editor_transform_gizmo"

    AXIS_DEFS: dict[str, dict] = {
        'x': {'gl_dir': np.array([1.0, 0.0, 0.0], dtype=np.float32),
              'color': (1.0, 0.15, 0.10), 'pick_id': 1},
        'y': {'gl_dir': np.array([0.0, 0.0, -1.0], dtype=np.float32),
              'color': (0.15, 1.0, 0.15), 'pick_id': 2},
        'z': {'gl_dir': np.array([0.0, 1.0, 0.0], dtype=np.float32),
              'color': (0.15, 0.25, 1.0), 'pick_id': 3},
    }

    PLANE_DEFS: dict[str, dict] = {
        'xy': {'gl_dirs': (np.array([1.0, 0.0, 0.0], dtype=np.float32),
                           np.array([0.0, 0.0, -1.0], dtype=np.float32)),
               'color': (1.0, 1.0, 0.0), 'pick_id': 4},
        'xz': {'gl_dirs': (np.array([1.0, 0.0, 0.0], dtype=np.float32),
                           np.array([0.0, 1.0, 0.0], dtype=np.float32)),
               'color': (1.0, 0.0, 1.0), 'pick_id': 5},
        'yz': {'gl_dirs': (np.array([0.0, 0.0, -1.0], dtype=np.float32),
                           np.array([0.0, 1.0, 0.0], dtype=np.float32)),
               'color': (0.0, 1.0, 1.0), 'pick_id': 6},
    }

    GIZMO_SCREEN_FRACTION: float = 0.30
    BRIGHTNESS_DIM: float = 0.35
    BRIGHTNESS_ACTIVE: float = 1.0

    _target_pos: np.ndarray = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    _target_entity_id: int | None = None
    _visible: bool = False
    _renderer: any = None
    _mode: GizmoMode = GizmoMode.GRAB
    _pos_gizmo: any = None
    _rot_gizmo: any = None
    _scl_gizmo: any = None

    @classmethod
    def set_mode(cls, mode: GizmoMode) -> None:
        if cls._mode == mode:
            return
        old = cls._renderer
        if old is not None:
            cls._unregister_current(old)
        cls._mode = mode
        if old is not None:
            cls._register_current(old)

    @classmethod
    def get_mode(cls) -> GizmoMode:
        return cls._mode

    @classmethod
    def _ensure_gizmos(cls) -> None:
        if cls._pos_gizmo is None:
            from Application.Editor.Gizmos.PositionGizmo import PositionGizmo
            cls._pos_gizmo = PositionGizmo()
        if cls._rot_gizmo is None:
            from Application.Editor.Gizmos.RotationGizmo import RotationGizmo
            cls._rot_gizmo = RotationGizmo()
        if cls._scl_gizmo is None:
            from Application.Editor.Gizmos.ScaleGizmo import ScaleGizmo
            cls._scl_gizmo = ScaleGizmo()

    @classmethod
    def _active_gizmo(cls):
        cls._ensure_gizmos()
        if cls._mode == GizmoMode.GRAB:
            return cls._pos_gizmo
        elif cls._mode == GizmoMode.ROTATE:
            return cls._rot_gizmo
        else:
            return cls._scl_gizmo

    @classmethod
    def _register_current(cls, renderer: 'Renderer') -> None:
        cls._ensure_gizmos()
        cls._active_gizmo().register_to(renderer)

    @classmethod
    def _unregister_current(cls, renderer: 'Renderer') -> None:
        for gz in (cls._pos_gizmo, cls._rot_gizmo, cls._scl_gizmo):
            if gz is not None:
                gz.unregister_from(renderer)

    @classmethod
    def register_to(cls, renderer: 'Renderer') -> None:
        cls._register_current(renderer)

    @classmethod
    def unregister_from(cls, renderer: 'Renderer') -> None:
        cls._unregister_current(renderer)
        cls._renderer = None
        OverlayUnregisteredEvent.Pack('TransformGizmo', engine=EditorHost)

    @classmethod
    def show(cls, renderer: 'Renderer', entity_id: int) -> None:
        if cls._renderer is None:
            cls._register_current(renderer)
            cls._renderer = renderer
        cls._visible = True
        cls._target_entity_id = entity_id
        try:
            t = EditorHost.scene.GetEntityTransform(entity_id)
            cls.set_target_position((t.position_x, t.position_y, t.position_z))
        except Exception:
            pass

    @classmethod
    def hide(cls) -> None:
        cls._visible = False
        if cls._renderer is not None:
            cls._unregister_current(cls._renderer)
            cls._renderer = None

    @classmethod
    def set_target_position(cls, pos) -> None:
        cls._target_pos = np.array(pos, dtype=np.float32)

    @classmethod
    def get_target_position(cls) -> np.ndarray:
        return cls._target_pos.copy()

    @classmethod
    def parse_pick_key(cls, pick_value: str) -> dict | None:
        cls._ensure_gizmos()
        for gz in (cls._pos_gizmo, cls._rot_gizmo, cls._scl_gizmo):
            if gz is not None:
                r = gz.parse_pick_key(pick_value)
                if r is not None:
                    return r
        return None

    @classmethod
    def begin_axis_drag(cls, entity_pos, axis_dir, cam_pos, ray_o, ray_d) -> None:
        cls._ensure_gizmos()
        cls._pos_gizmo.begin_axis_drag(entity_pos, axis_dir, cam_pos, ray_o, ray_d)

    @classmethod
    def begin_plane_drag(cls, entity_pos, d1, d2, ray_o, ray_d) -> None:
        cls._ensure_gizmos()
        cls._pos_gizmo.begin_plane_drag(entity_pos, d1, d2, ray_o, ray_d)

    @classmethod
    def begin_ring_drag(cls, entity_pos, ring_axis, cam_pos, ray_o, ray_d) -> None:
        cls._ensure_gizmos()
        cls._rot_gizmo.begin_ring_drag(entity_pos, ring_axis, cam_pos, ray_o, ray_d)

    @classmethod
    def begin_scale_drag(cls, entity_pos, gl_dir, ray_o, ray_d,
                         current_scale: tuple = (1.0, 1.0, 1.0)) -> None:
        cls._ensure_gizmos()
        cls._scl_gizmo.begin_scale_drag(entity_pos, gl_dir, ray_o, ray_d, current_scale)

    @classmethod
    def is_dragging(cls) -> bool:
        cls._ensure_gizmos()
        gz = cls._active_gizmo()
        if hasattr(gz, 'is_dragging'):
            return gz.is_dragging()
        return False

    @classmethod
    def update_drag(cls, ray_o: np.ndarray, ray_d: np.ndarray):
        cls._ensure_gizmos()
        gz = cls._active_gizmo()
        if cls._mode == GizmoMode.GRAB:
            return gz.update_drag(ray_o, ray_d)
        elif cls._mode == GizmoMode.ROTATE:
            return gz.update_rotation_drag(ray_o, ray_d)
        elif cls._mode == GizmoMode.SCALE:
            return gz.update_scale_drag(ray_o, ray_d)
        return None

    @classmethod
    def end_drag(cls) -> None:
        cls._ensure_gizmos()
        for gz in (cls._pos_gizmo, cls._rot_gizmo, cls._scl_gizmo):
            if gz is not None:
                gz.end_drag()

    @classmethod
    def _compute_mvp_cb(cls, vp_w: int, vp_h: int) -> np.ndarray:
        if not cls._visible:
            return np.zeros((4, 4), dtype=np.float32)
        if cls._target_entity_id is not None:
            try:
                if not EditorHost.scene.IsEditorVisible(cls._target_entity_id):
                    return np.zeros((4, 4), dtype=np.float32)
            except Exception:
                pass
        from Application.Editor.EditorCamera import EditorCamera
        cam = EditorCamera.get_instance()
        pos = cls._target_pos
        aspect = vp_w / max(vp_h, 1)
        V = np.array(cam.get_view_matrix(), dtype=np.float32).T
        P = np.array(cam.get_projection_matrix(aspect), dtype=np.float32).T
        if cam.is_orthographic:
            scale = cls.GIZMO_SCREEN_FRACTION * cam.ortho_size
        else:
            cp = np.asarray(cam.position, dtype=np.float32)
            dist = float(np.linalg.norm(cp - pos))
            dist = max(dist, 0.01)
            fov_half = math.radians(cam.fov / 2.0)
            scale = cls.GIZMO_SCREEN_FRACTION * dist * math.tan(fov_half)
        M = np.identity(4, dtype=np.float32)
        M[0, 0] = scale; M[1, 1] = scale; M[2, 2] = scale
        M[0, 3] = pos[0]; M[1, 3] = pos[1]; M[2, 3] = pos[2]
        return (P @ V @ M).astype(np.float32)

    @staticmethod
    def _make_billboard_mvp_cb(local_offset):
        """返回 billboard MVP 回调。local_offset 可以是固定 ndarray 或 callable()→ndarray。"""
        if callable(local_offset):
            getter = local_offset
        else:
            off_fixed = np.asarray(local_offset, dtype=np.float32)
            def getter():
                return off_fixed
        def cb(vp_w: int, vp_h: int) -> np.ndarray:
            off = np.asarray(getter(), dtype=np.float32)
            if not TransformGizmo._visible:
                return np.zeros((4, 4), dtype=np.float32)
            if TransformGizmo._target_entity_id is not None:
                try:
                    if not EditorHost.scene.IsEditorVisible(TransformGizmo._target_entity_id):
                        return np.zeros((4, 4), dtype=np.float32)
                except Exception:
                    pass
            from Application.Editor.EditorCamera import EditorCamera
            cam = EditorCamera.get_instance()
            pos = TransformGizmo._target_pos
            aspect = vp_w / max(vp_h, 1)
            V = np.array(cam.get_view_matrix(), dtype=np.float32).T
            P = np.array(cam.get_projection_matrix(aspect), dtype=np.float32).T
            if cam.is_orthographic:
                scale = TransformGizmo.GIZMO_SCREEN_FRACTION * cam.ortho_size
            else:
                cp = np.asarray(cam.position, dtype=np.float32)
                dist = float(np.linalg.norm(cp - pos))
                dist = max(dist, 0.01)
                fov_half = math.radians(cam.fov / 2.0)
                scale = TransformGizmo.GIZMO_SCREEN_FRACTION * dist * math.tan(fov_half)
            cp = np.asarray(cam.position, dtype=np.float32)
            view_dir = pos - cp
            view_dir = view_dir / max(np.linalg.norm(view_dir), 1e-8)
            forward = view_dir
            world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            right = np.cross(world_up, forward)
            if np.linalg.norm(right) < 1e-6:
                right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            right = right / max(np.linalg.norm(right), 1e-8)
            up_v = np.cross(forward, right)
            R = np.identity(4, dtype=np.float32)
            R[0, 0] = right[0]; R[1, 0] = right[1]; R[2, 0] = right[2]
            R[0, 1] = up_v[0];  R[1, 1] = up_v[1];  R[2, 1] = up_v[2]
            R[0, 2] = forward[0]; R[1, 2] = forward[1]; R[2, 2] = forward[2]
            M = np.identity(4, dtype=np.float32)
            M[0, 3] = pos[0] + off[0] * scale
            M[1, 3] = pos[1] + off[1] * scale
            M[2, 3] = pos[2] + off[2] * scale
            M = M @ np.diag(np.array([scale, scale, scale, 1.0], dtype=np.float32)) @ R
            return (P @ V @ M).astype(np.float32)
        return cb

    @staticmethod
    def screen_to_world_ray(mx: float, my: float, vp_w: int, vp_h: int,
                            view_mat: np.ndarray, proj_mat: np.ndarray
                            ) -> tuple[np.ndarray, np.ndarray]:
        ndc_x = (2.0 * mx / vp_w) - 1.0
        ndc_y = 1.0 - (2.0 * my / vp_h)
        near = np.array([ndc_x, ndc_y, -1.0, 1.0], dtype=np.float32)
        far = np.array([ndc_x, ndc_y, 1.0, 1.0], dtype=np.float32)
        V = np.array(view_mat, dtype=np.float32).T
        P = np.array(proj_mat, dtype=np.float32).T
        inv = np.linalg.inv(P @ V)
        nw = inv @ near; nw /= nw[3]
        fw = inv @ far; fw /= fw[3]
        origin = nw[:3].copy()
        d = fw[:3] - nw[:3]
        return origin, d / np.linalg.norm(d)

    @staticmethod
    def ray_plane_intersection(ray_o: np.ndarray, ray_d: np.ndarray,
                                plane_p: np.ndarray, plane_n: np.ndarray
                                ) -> np.ndarray | None:
        denom = np.dot(ray_d, plane_n)
        if abs(denom) < 1e-8:
            return None
        t = np.dot(plane_p - ray_o, plane_n) / denom
        if t < 0:
            return None
        return ray_o + ray_d * t

    @staticmethod
    def closest_point_on_axis(point: np.ndarray, axis_origin: np.ndarray,
                               axis_dir: np.ndarray) -> np.ndarray:
        v = point - axis_origin
        t = np.dot(v, axis_dir)
        return axis_origin + axis_dir * t
