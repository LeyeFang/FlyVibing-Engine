"""
RotationGizmo — 旋转手柄 (R 键)
===============================

三色旋转环 (line_strip) + θ=0 处圆点 (filled, billboard)。
环用于视觉参考，圆点用于点击拖拽。
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


class RotationGizmo:
    """三轴旋转环 + θ=0 圆点。"""

    OVERLAY_KEY_PREFIX: str = "editor_rotation_gizmo"
    PICK_TYPE: int = 3
    RING_RADIUS: float = 0.75
    RING_SEGMENTS: int = 64
    DOT_RADIUS: float = 0.07
    DOT_SEGMENTS: int = 16

    RING_DEFS: dict[str, dict] = {
        'x': {'gl_dir': np.array([1.0, 0.0, 0.0], dtype=np.float32),
              'theta_zero': np.array([0.0, 0.0, -1.0], dtype=np.float32),
              'color': (1.0, 0.15, 0.10), 'pick_id': 7},
        'y': {'gl_dir': np.array([0.0, 0.0, -1.0], dtype=np.float32),
              'theta_zero': np.array([0.0, 1.0, 0.0], dtype=np.float32),
              'color': (0.15, 1.0, 0.15), 'pick_id': 8},
        'z': {'gl_dir': np.array([0.0, 1.0, 0.0], dtype=np.float32),
              'theta_zero': np.array([1.0, 0.0, 0.0], dtype=np.float32),
              'color': (0.15, 0.25, 1.0), 'pick_id': 9},
    }

    def __init__(self) -> None:
        self._active_drag_key: str | None = None
        self._drag_state: dict | None = None
        # ★ 每轴累计旋转角 (弧度), 供 dot 动态偏移
        self._total_rot: dict[str, float] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        # ★ 每轴圆点当前偏移 (mutable, 供 billboard callback 读取)
        self._dot_offsets: dict[str, np.ndarray] = {}
        for name, rd in self.RING_DEFS.items():
            tz = rd['theta_zero'] / max(np.linalg.norm(rd['theta_zero']), 1e-8)
            self._dot_offsets[name] = (tz * self.RING_RADIUS).copy()

    def _axis_from_key(self, key: str) -> str:
        """从 ring_X 或 dot_X 键提取轴名 X。"""
        for p in ('_ring_', '_dot_'):
            if p in key:
                return key.split(p)[-1]
        return ''

    def get_handle_brightness(self, key: str) -> float:
        if self._active_drag_key is None:
            return TransformGizmo.BRIGHTNESS_DIM
        return (TransformGizmo.BRIGHTNESS_ACTIVE
                if self._axis_from_key(key) == self._axis_from_key(self._active_drag_key)
                else TransformGizmo.BRIGHTNESS_DIM)

    # ════════════════════════════════════════════════════════════
    # 几何
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _build_ring_geometry(axis_dir: np.ndarray, color: tuple,
                             radius: float = 0.75, segments: int = 64
                             ) -> tuple[np.ndarray, np.ndarray]:
        fwd = axis_dir.astype(np.float32)
        fwd = fwd / max(np.linalg.norm(fwd), 1e-8)
        ref = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        if abs(np.dot(fwd, ref)) > 0.99:
            ref = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        right = np.cross(fwd, ref)
        right = right / max(np.linalg.norm(right), 1e-8)
        up_v = np.cross(right, fwd)
        verts = []
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            rdir = right * math.cos(angle) + up_v * math.sin(angle)
            pos = rdir * radius
            verts.extend([pos[0], pos[1], pos[2], color[0], color[1], color[2]])
        vertices = np.array(verts, dtype=np.float32).reshape(-1, 6)
        indices = np.arange(segments, dtype=np.uint32)
        return vertices, indices

    @staticmethod
    def _build_dot_geometry(color: tuple, radius: float, segments: int
                            ) -> tuple[np.ndarray, np.ndarray]:
        """原点在 (0,0,0) 的填充圆, XY 平面, 供 billboard MVP 使用。"""
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
        radius = self.RING_RADIUS
        for axis_name, rd in self.RING_DEFS.items():
            # ── 旋转环 (line_strip, 沿用标准 MVP) ──
            r_verts, r_indices = self._build_ring_geometry(
                rd['gl_dir'], rd['color'], radius, self.RING_SEGMENTS)
            ring_key = f"{self.OVERLAY_KEY_PREFIX}_ring_{axis_name}"
            overlay = RRM.overlay_drawable_struct(
                key=ring_key, vertices=r_verts, indices=r_indices,
                vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='lines',
                depth_test=True, blend=False, cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=TransformGizmo._compute_mvp_cb,
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=0, pick_id=0,  # ★ 环不可拾取, 仅视觉参考
                render_layer=1, model_is_ndc=True,
                uniforms={'uBrightness': (lambda k=ring_key, s=self: np.array(
                    [s.get_handle_brightness(k)], 'f4')),
                    'uAlpha': np.array([1.0], 'f4')},
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay))
            # ── θ=0 圆点 (billboard, 动态偏移随旋转角移动) ──
            dot_verts, dot_indices = self._build_dot_geometry(
                rd['color'], self.DOT_RADIUS, self.DOT_SEGMENTS)
            dot_key = f"{self.OVERLAY_KEY_PREFIX}_dot_{axis_name}"
            # ★ 动态 offset: 每帧从 _dot_offsets 读取最新旋转后的位置
            overlay_dot = RRM.overlay_drawable_struct(
                key=dot_key, vertices=dot_verts, indices=dot_indices,
                vs_src=_GIZMO_VS, fs_src=_GIZMO_FS, draw_mode='triangles',
                depth_test=True, blend=False, cull_face=False,
                ignore_scene_matrices=True,
                model_matrix_cb=TransformGizmo._make_billboard_mvp_cb(
                    lambda name=axis_name: self._dot_offsets[name]),
                layout=STD_LAYOUT.TRANSFORM_GIZMO,
                pick_type=self.PICK_TYPE, pick_id=rd['pick_id'],
                render_layer=1, model_is_ndc=True,
                uniforms={'uBrightness': (lambda k=dot_key, s=self: np.array(
                    [s.get_handle_brightness(k)], 'f4')),
                    'uAlpha': np.array([1.0], 'f4')},
            )
            renderer.enqueue(OverlayRegistrationCommand(overlay_dot))
        OverlayRegisteredEvent.Pack('RotationGizmo', engine=EditorHost)

    def unregister_from(self, renderer: 'Renderer') -> None:
        for axis_name in self.RING_DEFS:
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{self.OVERLAY_KEY_PREFIX}_ring_{axis_name}"))
            renderer.enqueue(OverlayUnregistrationCommand(
                f"{self.OVERLAY_KEY_PREFIX}_dot_{axis_name}"))
        OverlayUnregisteredEvent.Pack('RotationGizmo', engine=EditorHost)

    # ════════════════════════════════════════════════════════════
    # Pick
    # ════════════════════════════════════════════════════════════

    def parse_pick_key(self, pick_value: str) -> dict | None:
        prefix = self.OVERLAY_KEY_PREFIX
        if not pick_value.startswith(prefix):
            return None
        rest = pick_value[len(prefix) + 1:]
        if rest.startswith('dot_'):
            name = rest[4:]
            rd = self.RING_DEFS.get(name)
            if rd:
                return {'kind': 'ring', 'name': name, 'pick_id': rd['pick_id'],
                        'gl_dir': rd['gl_dir'].copy(), 'color': rd['color']}
        return None

    # ════════════════════════════════════════════════════════════
    # 拖拽
    # ════════════════════════════════════════════════════════════

    def begin_ring_drag(self, entity_pos: np.ndarray, ring_axis: np.ndarray,
                        cam_pos: np.ndarray, ray_o: np.ndarray, ray_d: np.ndarray) -> None:
        ring_axis = ring_axis / max(np.linalg.norm(ring_axis), 1e-8)
        entity_pos = np.asarray(entity_pos, dtype=np.float32)
        hit = TransformGizmo.ray_plane_intersection(ray_o, ray_d, entity_pos, ring_axis)
        mouse_start = hit if hit is not None else entity_pos.copy()
        self._drag_state = {
            'mode': 'ring', 'ring_axis': ring_axis,
            'plane_normal': ring_axis, 'plane_point': entity_pos.copy(),
            'start_pos': entity_pos.copy(), 'mouse_start': mouse_start,
        }
        for name, rd in self.RING_DEFS.items():
            if np.allclose(rd['gl_dir'], ring_axis, atol=1e-3):
                self._active_drag_key = f"{self.OVERLAY_KEY_PREFIX}_dot_{name}"
                self._drag_state['axis_name'] = name  # ★ 记录轴名用于更新 dot offset
                break

    def update_rotation_drag(self, ray_o: np.ndarray, ray_d: np.ndarray
                             ) -> np.ndarray | None:
        """返回单帧 delta 欧拉角 (rx, ry, rz), 调用方累加到实体旋转。"""
        if self._drag_state is None or self._drag_state.get('mode') != 'ring':
            return None
        ds = self._drag_state
        hit = TransformGizmo.ray_plane_intersection(
            ray_o, ray_d, ds['plane_point'], ds['plane_normal'])
        if hit is None:
            return None
        v0 = ds['mouse_start'] - ds['plane_point']
        v1 = hit - ds['plane_point']
        len0 = float(np.linalg.norm(v0))
        len1 = float(np.linalg.norm(v1))
        if len0 < 1e-6 or len1 < 1e-6:
            return None
        v0u = v0 / len0
        v1u = v1 / len1
        axis = ds['ring_axis']
        ref = np.cross(axis, np.array([0.0, 1.0, 0.0], dtype=np.float32))
        if np.linalg.norm(ref) < 1e-6:
            ref = np.cross(axis, np.array([1.0, 0.0, 0.0], dtype=np.float32))
        ref = ref / max(np.linalg.norm(ref), 1e-8)
        up_v = np.cross(ref, axis)
        a0 = math.atan2(float(np.dot(v0u, up_v)), float(np.dot(v0u, ref)))
        a1 = math.atan2(float(np.dot(v1u, up_v)), float(np.dot(v1u, ref)))
        delta_angle = a1 - a0  # entity 旋转方向 (还原)
        delta_angle = (delta_angle + math.pi) % (2.0 * math.pi) - math.pi
        ds['mouse_start'] = hit
        # ★ 更新 dot 视觉偏移: 绕 ring_axis 旋转 theta_zero 方向
        name = ds.get('axis_name')
        if name:
            self._total_rot[name] += delta_angle
            rd = self.RING_DEFS[name]
            k = rd['gl_dir'] / max(np.linalg.norm(rd['gl_dir']), 1e-8)
            tz0 = rd['theta_zero'] / max(np.linalg.norm(rd['theta_zero']), 1e-8)
            angle = -self._total_rot[name]  # ★ dot 视觉取反: atan2 CW/CCW 与 ring 平面投影相反
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            # Rodrigues: v_rot = v*cos + (k×v)*sin + k*(k·v)*(1-cos)
            kxv = np.cross(k, tz0)
            kdv = np.dot(k, tz0)
            rotated = tz0 * cos_a + kxv * sin_a + k * (kdv * (1.0 - cos_a))
            self._dot_offsets[name][:] = rotated * self.RING_RADIUS
        return (axis * delta_angle).astype(np.float32)

    def end_drag(self) -> None:
        self._drag_state = None
        self._active_drag_key = None

    def is_dragging(self) -> bool:
        return self._drag_state is not None
