"""
编辑器轨道摄像机 — 独立单例，不进入 ECS 系统。

职责:
  - 持有编辑器视角的轨道参数 (yaw / pitch / target / distance)
  - 处理鼠标输入 (左键旋转 / 中键平移 / 滚轮缩放)
  - 生成 view/proj 矩阵供 Renderer 使用

使用方式:
  cam = EditorCamera.get_instance()
  cam.focus_on((0, 0, -50), distance=47)
  cam.on_mouse_drag(MouseButtonCode.Left, dx, dy)
  cam.on_scroll(dy)
  view = cam.get_view_matrix()
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44, Vector3

from Application.Core.Camera.CameraBase import CameraBase
from Application.Core.Events.Enum.InputEnum import MouseButtonCode


class EditorCamera(CameraBase):
    """编辑器轨道摄像机 — 绕轨道原点旋转、平移、缩放。

    球坐标约定:
      - yaw   (rotation_y): 水平环绕角, 0 = 面朝 -Z
      - pitch (rotation_x): 垂直俯仰角, 0 = 水平, ±π/2 = 顶/底

    摄像机位置 = orbit_target + orbit_distance * direction(yaw, pitch)
    direction = (sin(yaw)*cos(pitch),  sin(pitch),  -cos(yaw)*cos(pitch))
    """

    # ════════════════════════════════════════════════════════════
    # 单例
    # ════════════════════════════════════════════════════════════

    _instance: EditorCamera | None = None

    def __new__(cls) -> EditorCamera:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_defaults()
        return cls._instance

    @classmethod
    def get_instance(cls) -> EditorCamera:
        """获取全局唯一的编辑器摄像机实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ════════════════════════════════════════════════════════════
    # 初始化
    # ════════════════════════════════════════════════════════════

    def _init_defaults(self) -> None:
        """设置默认轨道参数 (仅首次创建时调用)。

        初始视角: 编辑器 XY 第四象限 (X>0, Y<0) 平面上方 (Z>0),
        注视世界坐标原点。
        对应 GL 坐标中摄像机位于 (+, +, +) 看向原点。
        """
        # ── 轨道参数 ──
        self.yaw: float = math.pi * 0.75    # 3π/4, 摄像机在 GL 第一卦限
        self.pitch: float = math.pi / 6.0   # 30° 俯角
        self.orbit_target: np.ndarray = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.orbit_distance: float = 15
        # ── 投影参数 ──
        self.fov: float = 45.0
        self.near_plane: float = 0.1
        self.far_plane: float = 1000.0
        # ── 派生: 摄像机世界位置 ──
        self.position: np.ndarray = np.zeros(3, dtype=np.float32)
        self._update_position()
        # ── 灵敏度 ──
        self.orbit_speed: float = 0.005
        self.pan_speed: float = 0.01
        self.zoom_speed: float = 0.1

    # ════════════════════════════════════════════════════════════
    # 公共 API: 聚焦
    # ════════════════════════════════════════════════════════════

    def focus_on(
        self,
        target: tuple[float, float, float],
        distance: float | None = None
    ) -> None:
        """将轨道原点移动到指定位置，可选调整距离。

        使用场景: 双击实体 → 摄像机聚焦到该实体。

        Args:
            target:   世界坐标目标点 (x, y, z)
            distance: 新距离 (None 表示保持不变)
        """
        self.orbit_target = np.array(target, dtype=np.float32)
        if distance is not None:
            self.orbit_distance = max(distance, 0.1)
        self._update_position()

    # ════════════════════════════════════════════════════════════
    # 公共 API: 鼠标输入
    # ════════════════════════════════════════════════════════════

    def on_mouse_drag(
        self,
        button: int,
        offset_x: float,
        offset_y: float
    ) -> None:
        """处理鼠标拖动事件。

        Args:
            button:   MouseButtonCode.Left / .Middle / .Right
            offset_x: 鼠标水平位移 (像素)
            offset_y: 鼠标垂直位移 (像素)
        """
        if button == MouseButtonCode.Left:
            self._orbit(offset_x, offset_y)
        elif button == MouseButtonCode.Middle:
            self._pan(-offset_x, offset_y)

    def on_scroll(self, y_offset: float) -> None:
        """处理滚轮缩放。

        Args:
            y_offset: 滚轮垂直偏移量 (正值=放大/靠近, 负值=缩小/远离)
        """
        # 指数缩放，手感更自然
        self.orbit_distance *= (1.0 - y_offset * self.zoom_speed)
        self.orbit_distance = max(self.orbit_distance, 0.01)
        self._update_position()

    # ════════════════════════════════════════════════════════════
    # 公共 API: 预设视角 (ViewGizmo 面点击)
    # ════════════════════════════════════════════════════════════

    def look_from_preset(self, yaw: float, pitch: float) -> None:
        """直接设置轨道角度（保留 distance 和 target 不变）。"""
        self.yaw = yaw
        self.pitch = pitch
        self._update_position()

    def look_from_direction(self, forward: np.ndarray) -> None:
        """从 GL 方向向量设置朝向 — 无万向锁, 允许精确 ±Y。"""
        d = np.asarray(forward, dtype=np.float32)
        norm = float(np.linalg.norm(d))
        if norm < 1e-8:
            return
        d = d / norm
        self.pitch = math.asin(max(-1.0, min(1.0, float(d[1]))))
        nz = float(-d[2])
        self.yaw = math.atan2(float(d[0]), 0.0 if nz == 0.0 else nz)
        # 正顶/正底: yaw 额外转 180° 使 ViewGizmo 字母正向
        if abs(d[1]) > 0.9999:
            self.yaw += math.pi
        self._update_position()

    # ════════════════════════════════════════════════════════════
    # CameraBase 接口: 矩阵
    # ════════════════════════════════════════════════════════════

    def get_view_matrix(self) -> np.ndarray:
        """Generate view matrix — look_at(camera_pos, orbit_target, world_up).
        Returns:
            4x4 float32 view matrix (pyrr-style, row-vector convention).
            For OpenGL upload: use glUniformMatrix4fv(..., GL_FALSE, ...).

        See Application/Core/Math/__init__.py for full convention documentation.
        """
        pos = Vector3(self.position.tolist())
        target = Vector3(self.orbit_target.tolist())
        up = Vector3([0.0, 1.0, 0.0])
        return matrix44.create_look_at(pos, target, up).astype(np.float32)

    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """Generate perspective projection matrix.

        Args:
            aspect_ratio: Viewport aspect ratio (width / height)

        Returns:
            4x4 float32 projection matrix (pyrr-style, row-vector convention).
            For OpenGL upload: use glUniformMatrix4fv(..., GL_FALSE, ...).

        See Application/Core/Math/__init__.py for full convention documentation.
        """
        return matrix44.create_perspective_projection(
            self.fov, aspect_ratio, self.near_plane, self.far_plane
        ).astype(np.float32)

    # ════════════════════════════════════════════════════════════
    # 内部: 方向向量 + 向量旋转
    # ════════════════════════════════════════════════════════════

    @property
    def _forward(self) -> np.ndarray:
        """当前向前方向 (GL 空间, orbit_target → camera, 单位向量)。"""
        cp = math.cos(self.pitch)
        return np.array([
            math.sin(self.yaw) * cp,
            math.sin(self.pitch),
            -math.cos(self.yaw) * cp,
        ], dtype=np.float32)

    @staticmethod
    def _rotate_vector(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
        """Rodrigues 旋转公式 — v 绕单位轴 axis 旋转 angle 弧度。"""
        c = math.cos(angle)
        s = math.sin(angle)
        k_dot_v = float(np.dot(axis, v))
        cross = np.cross(axis, v)
        return v * c + cross * s + axis * (k_dot_v * (1.0 - c))

    _POLE_THRESHOLD: float = math.pi / 2 - 0.05  # ≈ 87°

    # ════════════════════════════════════════════════════════════
    # 内部: 轨道操作 (混合方案: 极点 yaw-直控, 非极点 Rodrigues)
    # ════════════════════════════════════════════════════════════

    def _orbit(self, offset_x: float, offset_y: float) -> None:
        """绕轨道原点旋转摄像机 (混合方案, 无万向锁, 无抖动)。"""
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        old_yaw = self.yaw
        old_pitch = self.pitch
        near_pole = abs(old_pitch) >= self._POLE_THRESHOLD
        f = self._forward

        # 垂直旋转
        right = np.cross(f, world_up)
        right_norm = float(np.linalg.norm(right))
        if right_norm < 1e-6:
            right = np.array([-math.cos(old_yaw), 0.0, math.sin(old_yaw)], dtype=np.float32)
            rn = float(np.linalg.norm(right))
            right = right / rn if rn > 1e-6 else np.array([1.0, 0.0, 0.0], dtype=np.float32)
        else:
            right /= right_norm
        f = self._rotate_vector(f, right, offset_y * self.orbit_speed)

        # 水平旋转 + yaw/pitch 提取
        if near_pole:
            self.yaw = old_yaw + offset_x * self.orbit_speed
            self.pitch = math.asin(max(-1.0, min(1.0, float(f[1]))))
        else:
            f = self._rotate_vector(f, world_up, -offset_x * self.orbit_speed)
            f_norm = float(np.linalg.norm(f))
            if f_norm < 1e-8:
                self._update_position()
                return
            f /= f_norm
            self.pitch = math.asin(max(-1.0, min(1.0, float(f[1]))))
            old_cp = math.cos(old_pitch)
            ox = math.sin(old_yaw) * old_cp
            oz = -math.cos(old_yaw) * old_cp
            nx, nz = float(f[0]), float(f[2])
            cross_xz = ox * nz - oz * nx
            dot_xz = ox * nx + oz * nz
            self.yaw = old_yaw + math.atan2(cross_xz, dot_xz)

        self._update_position()

    def _pan(self, offset_x: float, offset_y: float) -> None:
        """在屏幕平面内平移轨道原点。
        Args:
            offset_x: 水平位移
            offset_y: 垂直位移
        """
        # 计算摄像机空间中的 right 和 up 向量
        rx = math.cos(self.yaw)
        rz = math.sin(self.yaw)
        ux = -math.sin(self.pitch) * math.sin(self.yaw)
        uy = math.cos(self.pitch)
        uz = math.sin(self.pitch) * math.cos(self.yaw)
        self.orbit_target[0] += \
            rx * (-offset_x * self.pan_speed) \
            + ux * (offset_y * self.pan_speed)
        self.orbit_target[1] += \
            uy * (offset_y * self.pan_speed)
        self.orbit_target[2] += \
            rz * (-offset_x * self.pan_speed) \
            + uz * (offset_y * self.pan_speed)
        self._update_position()

    def _update_position(self) -> None:
        """根据球坐标 (yaw, pitch, distance) 更新摄像机世界位置。
        direction = (sin(yaw)*cos(pitch),  sin(pitch),  -cos(yaw)*cos(pitch))
        position  = orbit_target + orbit_distance * direction
        """
        dx = math.sin(self.yaw) * math.cos(self.pitch)
        dy = math.sin(self.pitch)
        dz = -math.cos(self.yaw) * math.cos(self.pitch)
        self.position[0] = self.orbit_target[0] + dx * self.orbit_distance
        self.position[1] = self.orbit_target[1] + dy * self.orbit_distance
        self.position[2] = self.orbit_target[2] + dz * self.orbit_distance
