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
        """设置默认轨道参数 (仅首次创建时调用)。"""
        # ── 轨道参数 ──
        self.yaw: float = math.pi       # 初始面朝 -Z 方向 (看向实体群)
        self.pitch: float = 0.0
        self.orbit_target: np.ndarray = np.array([0.0, 0.0, -50.0], dtype=np.float32)
        self.orbit_distance: float = 47.0

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
    # CameraBase 接口: 矩阵
    # ════════════════════════════════════════════════════════════

    def get_view_matrix(self) -> np.ndarray:
        """生成视图矩阵 — look_at(camera_pos, orbit_target, world_up)。

        Returns:
            4x4 float32 列主序视图矩阵
        """
        pos = Vector3(self.position.tolist())
        target = Vector3(self.orbit_target.tolist())
        up = Vector3([0.0, 1.0, 0.0])
        return matrix44.create_look_at(pos, target, up).astype(np.float32)

    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """生成透视投影矩阵。

        Args:
            aspect_ratio: 视口宽高比 (width / height)

        Returns:
            4x4 float32 列主序投影矩阵
        """
        return matrix44.create_perspective_projection(
            self.fov, aspect_ratio, self.near_plane, self.far_plane
        ).astype(np.float32)

    # ════════════════════════════════════════════════════════════
    # 内部: 轨道操作
    # ════════════════════════════════════════════════════════════

    def _orbit(self, offset_x: float, offset_y: float) -> None:
        """绕轨道原点旋转摄像机。

        Args:
            offset_x: 水平位移 → 修改 yaw
            offset_y: 垂直位移 → 修改 pitch
        """
        self.yaw += offset_x * self.orbit_speed
        self.pitch += offset_y * self.orbit_speed

        # 限制俯仰角，防止翻转 (≈ ±89°)
        limit = math.pi / 2 - 0.01
        self.pitch = max(-limit, min(limit, self.pitch))

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

        self.orbit_target[0] += rx * (-offset_x * self.pan_speed) + ux * (offset_y * self.pan_speed)
        self.orbit_target[1] += uy * (offset_y * self.pan_speed)
        self.orbit_target[2] += rz * (-offset_x * self.pan_speed) + uz * (offset_y * self.pan_speed)

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
