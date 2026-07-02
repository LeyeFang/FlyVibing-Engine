"""
轨道摄像机基类 — 纯球坐标轨道模型，不含任何输入映射逻辑。

职责:
  - 持有轨道参数 (yaw / pitch / target / distance)
  - 提供纯操作接口: orbit(Δyaw, Δpitch) / pan(Δright, Δup) / dolly(factor)
  - 生成 view / proj 矩阵

不包含:
  - 鼠标/滚轮输入映射 (像素 → 角度/世界单位, 由 EditorCamera/Controller 负责)
  - 编辑器单例模式 (由 EditorCamera 提供)
  - 2D/3D 正交切换 (由 EditorCamera 提供)
  - ViewGizmo 预设视角 (由 EditorCamera 提供)

使用场景:
  - EditorCamera 继承本类，附加输入映射 + 编辑器特化功能
  - PreviewRuntime 直接使用本类作为预览自由摄像机
  - 任何需要轨道交互的运行时场景

球坐标约定:
  - yaw   : 水平环绕角, 0 = 面朝 GL -Z
  - pitch : 垂直俯仰角, 0 = 水平, ±π/2 = 顶/底

摄像机位置 = orbit_target + orbit_distance * direction(yaw, pitch)
direction = (sin(yaw)*cos(pitch),  sin(pitch),  -cos(yaw)*cos(pitch))

MATRIX CONVENTION:
  相机矩阵采用 pyrr-style (row-vector convention)。
  For OpenGL upload: use glUniformMatrix4fv(..., GL_FALSE, ...).
  See Application/Core/Math/__init__.py for full convention documentation.
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44, Vector3

from Application.Core.Camera.CameraBase import CameraBase


class OrbitCamera(CameraBase):
    """轨道摄像机 — 纯球坐标模型，仅提供角度/世界单位操作接口。

    实例属性:
        yaw            : 水平环绕角 (弧度)
        pitch          : 垂直俯仰角 (弧度)
        orbit_target   : 轨道注视点 (世界坐标)
        orbit_distance : 摄像机到注视点的距离
        fov            : 透视视场角 (角度制)
        near_plane     : 近裁剪面距离
        far_plane      : 远裁剪面距离
        position       : 摄像机世界位置 (派生自球坐标)

    注意: 本类不包含任何灵敏度参数 (orbit_speed/pan_speed/zoom_speed)，
    输入映射由调用方 (EditorCamera / Controller) 负责。
    """

    _POLE_THRESHOLD: float = math.pi / 2 - 0.05  # ≈ 87°

    # ════════════════════════════════════════════════════════════
    # 初始化
    # ════════════════════════════════════════════════════════════

    def __init__(self) -> None:
        super().__init__()
        self._init_orbit_defaults()

    def _init_orbit_defaults(self) -> None:
        """设置默认轨道参数。

        初始视角: GL 第一卦限 (X>0, Y>0, Z>0), 注视世界坐标原点。
        """
        self.yaw: float = math.pi * 0.75       # 3π/4
        self.pitch: float = math.pi / 6.0      # 30° 俯角
        self.orbit_target: np.ndarray = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.orbit_distance: float = 15.0
        # ── 投影参数 ──
        self.fov: float = 45.0
        self.near_plane: float = 0.1
        self.far_plane: float = 1000.0
        # ── 派生: 摄像机世界位置 ──
        self.position: np.ndarray = np.zeros(3, dtype=np.float32)
        self._update_position()

    # ════════════════════════════════════════════════════════════
    # 公共操作接口 (纯角度/世界单位, 不含输入映射)
    # ════════════════════════════════════════════════════════════

    def orbit(self, delta_yaw: float, delta_pitch: float) -> None:
        """旋转摄像机 — 按给定的 yaw/pitch 增量 (弧度)。

        使用 Rodrigues 旋转 + 极点退化保护，无万向锁。

        Args:
            delta_yaw:   水平旋转增量 (弧度, 正=右旋)
            delta_pitch: 垂直旋转增量 (弧度, 正=上仰)

        调用方示例:
            cam.orbit(mouse_dx * orbit_speed, mouse_dy * orbit_speed)
        """
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
        f = self._rotate_vector(f, right, delta_pitch)
        # 水平旋转 + yaw/pitch 提取
        if near_pole:
            self.yaw = old_yaw + delta_yaw
            self.pitch = math.asin(max(-1.0, min(1.0, float(f[1]))))
        else:
            f = self._rotate_vector(f, world_up, -delta_yaw)
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

    def pan(self, delta_right: float, delta_up: float) -> None:
        """平移注视点 — 沿摄像机局部坐标系的 right/up 轴 (世界单位)。
        Args:
            delta_right: 沿摄像机 right 轴位移 (世界单位, 正=右移)
            delta_up:    沿摄像机 up 轴位移 (世界单位, 正=上移)

        调用方示例:
            cam.pan(-mouse_dx * pan_speed, mouse_dy * pan_speed)
        """
        rx = math.cos(self.yaw)
        rz = math.sin(self.yaw)
        ux = -math.sin(self.pitch) * math.sin(self.yaw)
        uy = math.cos(self.pitch)
        uz = math.sin(self.pitch) * math.cos(self.yaw)
        self.orbit_target[0] += rx * delta_right + ux * delta_up
        self.orbit_target[1] += uy * delta_up
        self.orbit_target[2] += rz * delta_right + uz * delta_up
        self._update_position()

    def dolly(self, factor: float) -> None:
        """缩放距离 — 按比例调整 orbit_distance。

        Args:
            factor: 距离缩放因子 (>1 = 远离, <1 = 靠近, 1 = 不变)

        调用方示例:
            cam.dolly(1.0 - scroll_dy * zoom_speed)
        """
        self.orbit_distance *= factor
        self.orbit_distance = max(self.orbit_distance, 0.01)
        self._update_position()

    def set_orbit(self, yaw: float, pitch: float) -> None:
        """直接设置轨道角度 (保留 distance 和 target 不变)。

        Args:
            yaw:   水平环绕角 (弧度)
            pitch: 垂直俯仰角 (弧度)
        """
        self.yaw = yaw
        self.pitch = pitch
        self._update_position()

    def focus_on(
        self,
        target: tuple[float, float, float],
        distance: float | None = None
    ) -> None:
        """将轨道原点移动到指定位置，可选调整距离。

        Args:
            target:   世界坐标目标点 (x, y, z)
            distance: 新距离 (None 表示保持不变)
        """
        self.orbit_target = np.array(target, dtype=np.float32)
        if distance is not None:
            self.orbit_distance = max(distance, 0.1)
        self._update_position()

    # ════════════════════════════════════════════════════════════
    # CameraBase 接口: 矩阵
    # ════════════════════════════════════════════════════════════
    def get_view_matrix(self) -> np.ndarray:
        """Generate view matrix — look_at(camera_pos, orbit_target, world_up).

        当摄像机近垂直俯视 (|pitch| ≈ π/2) 时使用 yaw 相关的 up 向量:
          - up = (-sin(yaw), 0, cos(yaw)) — 在 GL XZ 平面内随 yaw 旋转
          - 解决极点退化: cos(pitch)=0 时 position 与 yaw 无关,
            但 up 随 yaw 旋转使视图仍可水平旋转

        Returns:
            4x4 float32 view matrix (pyrr-style, row-vector convention).
        """
        pos = Vector3(self.position.tolist())
        target = Vector3(self.orbit_target.tolist())
        if abs(self.pitch) > math.pi * 0.49:
            up = Vector3([-math.sin(self.yaw), 0.0, math.cos(self.yaw)])
        else:
            up = Vector3([0.0, 1.0, 0.0])
        return matrix44.create_look_at(pos, target, up).astype(np.float32)

    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """Generate perspective projection matrix.

        子类 EditorCamera 覆写此方法以支持正交投影切换。

        Args:
            aspect_ratio: Viewport aspect ratio (width / height)

        Returns:
            4x4 float32 projection matrix (pyrr-style, row-vector convention).
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
