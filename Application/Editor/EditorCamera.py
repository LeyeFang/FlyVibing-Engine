"""
编辑器轨道摄像机 — 独立单例，继承 OrbitCamera 获得轨道交互能力。

职责:
  - 编辑器视角的轨道参数 (继承自 OrbitCamera)
  - 2D/3D 投影模式切换
  - ViewGizmo 预设视角
  - 单例模式 (编辑器全局唯一)

OrbitCamera 提供:
  - yaw / pitch / target / distance 轨道参数
  - orbit(Δyaw, Δpitch) / pan(Δright, Δup) / dolly(factor) 纯操作接口
  - get_view_matrix / get_projection_matrix (perspective)

EditorCamera 负责:
  - 输入映射 (像素 → 角度/世界单位, 灵敏度参数)
  - 2D/3D 输入分派

使用方式:
  cam = EditorCamera.get_instance()
  cam.focus_on((0, 0, -50), distance=47)
  cam.on_mouse_drag(MouseButtonCode.Middle, dx, dy, shift_held=False)
  cam.on_scroll(dy)
  view = cam.get_view_matrix()
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44

from Application.Core.Camera.OrbitCamera import OrbitCamera
from Application.Core.Events.Enum.InputEnum import MouseButtonCode


class EditorCamera(OrbitCamera):
    """编辑器轨道摄像机 — OrbitCamera + 单例 + 2D/3D 切换 + 预设视角。

    继承 OrbitCamera 的全部球坐标轨道能力，增加:
      - 单例模式 (全局唯一, 供 Renderer 注入)
      - 正交/透视投影切换 (2D 俯视 ↔ 3D 自由视角)
      - ViewGizmo 预设六面朝向
    """

    # ════════════════════════════════════════════════════════════
    # 单例
    # ════════════════════════════════════════════════════════════

    _instance: EditorCamera | None = None

    def __new__(cls) -> EditorCamera:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
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

    def __init__(self) -> None:
        """防止单例重复初始化 — 仅首次构造时执行 OrbitCamera 初始化 + 编辑器扩展。"""
        if getattr(self, '_initialized', False):
            return
        super().__init__()  # OrbitCamera.__init__ → _init_orbit_defaults()
        self._init_editor_defaults()
        self._initialized = True

    def _init_editor_defaults(self) -> None:
        """编辑器特化参数 (输入灵敏度 / 正交投影 / 2D-3D 切换)。"""
        # ── 输入灵敏度 (像素 → 角度/世界单位 映射) ──
        self.orbit_speed: float = 0.005
        self.pan_speed: float = 0.01
        self.zoom_speed: float = 0.1
        # ── 正交投影切换 ──
        self._orthographic: bool = False
        self._ortho_size: float = 10.0
        self._saved_perspective: dict | None = None

    # ════════════════════════════════════════════════════════════
    # 输入映射: 鼠标/滚轮 → 摄像机操作 (EditorCamera 独有)
    # ════════════════════════════════════════════════════════════

    def on_mouse_drag(
        self,
        button: int,
        offset_x: float,
        offset_y: float,
        shift_held: bool = False,
    ) -> None:
        """处理鼠标拖动 — 根据当前 2D/3D 模式分派。

        Args:
            button:     MouseButtonCode
            offset_x:   水平位移 (像素)
            offset_y:   垂直位移 (像素)
            shift_held: Shift 修饰键是否按下
        """
        if self._orthographic:
            self._on_mouse_drag_2d(button, offset_x, offset_y, shift_held)
        else:
            self._on_mouse_drag_3d(button, offset_x, offset_y, shift_held)

    def _on_mouse_drag_3d(
        self,
        button: int,
        offset_x: float,
        offset_y: float,
        shift_held: bool,
    ) -> None:
        """3D 透视模式: 像素位移 → OrbitCamera.orbit() / pan()。"""
        if button == MouseButtonCode.Left:
            return
        elif button == MouseButtonCode.Middle:
            if shift_held:
                # 屏幕 X 反向映射到摄像机 right 轴
                self.pan(offset_x * self.pan_speed, offset_y * self.pan_speed)
            else:
                self.orbit(offset_x * self.orbit_speed, offset_y * self.orbit_speed)

    def _on_mouse_drag_2d(
        self,
        button: int,
        offset_x: float,
        offset_y: float,
        shift_held: bool,
    ) -> None:
        """2D 正交模式: 纯旋转屏蔽, 仅允许平移。"""
        if button == MouseButtonCode.Left:
            return
        elif button == MouseButtonCode.Middle:
            if shift_held:
                self.pan(-offset_x * self.pan_speed, offset_y * self.pan_speed)

    def on_scroll(self, y_offset: float) -> None:
        """滚轮映射 — 2D 调 ortho_size, 3D 调 orbit_distance。

        Args:
            y_offset: 滚轮垂直偏移量 (正值=靠近, 负值=远离)
        """
        if self._orthographic:
            self._on_scroll_2d(y_offset)
        else:
            self._on_scroll_3d(y_offset)

    def _on_scroll_3d(self, y_offset: float) -> None:
        """3D 透视模式: 滚轮 → OrbitCamera.dolly()。"""
        factor = 1.0 - y_offset * self.zoom_speed
        self.dolly(factor)

    def _on_scroll_2d(self, y_offset: float) -> None:
        """2D 正交模式滚轮缩放 — 调整 ortho_size (正交半高)。"""
        self._ortho_size *= (1.0 - y_offset * self.zoom_speed)
        self._ortho_size = max(self._ortho_size, 0.01)

    # ════════════════════════════════════════════════════════════
    # 公共 API: 预设视角 (ViewGizmo 面点击)
    # ════════════════════════════════════════════════════════════

    def look_from_preset(self, yaw: float, pitch: float) -> None:
        """直接设置轨道角度（保留 distance 和 target 不变）。"""
        self.set_orbit(yaw, pitch)

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
    # CameraBase 接口: 投影矩阵 (覆写 OrbitCamera, 增加正交投影)
    # ════════════════════════════════════════════════════════════

    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """Generate projection matrix — perspective or orthographic.

        正交模式下覆写父类透视矩阵，返回正交投影矩阵。
        view 矩阵由 OrbitCamera.get_view_matrix() 提供 (含极点处理)。

        Args:
            aspect_ratio: Viewport aspect ratio (width / height)

        Returns:
            4x4 float32 projection matrix (pyrr-style, row-vector convention).
        """
        if self._orthographic:
            half_h = self._ortho_size * aspect_ratio
            half_v = self._ortho_size
            return matrix44.create_orthogonal_projection(
                -half_h, half_h, -half_v, half_v,
                self.near_plane, self.far_plane,
            ).astype(np.float32)
        return super().get_projection_matrix(aspect_ratio)

    # ════════════════════════════════════════════════════════════
    # 2D / 3D 模式切换
    # ════════════════════════════════════════════════════════════

    @property
    def is_orthographic(self) -> bool:
        """当前是否为正交投影模式（2D 俯视）。"""
        return self._orthographic

    @property
    def ortho_size(self) -> float:
        """正交投影半高（世界单位）。"""
        return self._ortho_size

    @ortho_size.setter
    def ortho_size(self, value: float) -> None:
        self._ortho_size = max(value, 0.01)

    def set_2d_top_down_view(self) -> None:
        """切换到 2D 正交俯视模式。

        摄像机从 GL +Y 方向俯视 GL XZ 平面 (编辑器 XY 平面):
          - GL forward (tgt→cam): (0, +1, 0)
          - 投影: 正交 (orthographic)

        首次进入 2D 时保存当前 3D 透视状态，重复调用不覆盖。
        """
        if self._saved_perspective is None:
            self._saved_perspective = {
                'yaw': self.yaw,
                'pitch': self.pitch,
                'distance': self.orbit_distance,
                'fov': self.fov,
                'target': self.orbit_target.copy(),
            }
        self.look_from_direction(np.array([0.0, 1.0, 0.0], dtype=np.float32))
        if self._ortho_size <= 0.0:
            self._ortho_size = self.orbit_distance * 0.5
        self._orthographic = True

    def set_3d_perspective_view(self) -> None:
        """切回 3D 透视模式，恢复之前保存的视角状态。"""
        if self._saved_perspective is not None:
            sp = self._saved_perspective
            self.yaw = sp['yaw']
            self.pitch = sp['pitch']
            self.orbit_distance = sp['distance']
            self.fov = sp['fov']
            self.orbit_target = sp['target'].copy()
        self._saved_perspective = None
        self._orthographic = False
        self._update_position()

    def toggle_2d_3d(self) -> str:
        """一键切换 2D 正交俯视 ↔ 3D 透视。

        Returns:
            '2d' 或 '3d' — 切换后的模式标识。
        """
        if self._orthographic:
            self.set_3d_perspective_view()
            return '3d'
        else:
            self.set_2d_top_down_view()
            return '2d'
