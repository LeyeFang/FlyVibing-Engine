"""
TestEditorCamera — 与主线 EditorCamera 行为完全一致的测试用轨道摄像机。

使用方式:
    cam = TestEditorCamera()
    cam.orbit(dx, dy)           # 拖拽旋转
    cam.zoom(dy)                # 滚轮缩放
    view = cam.get_view_matrix()
    proj = cam.get_projection_matrix(aspect)

    # ★ 2D/3D 切换 (v8+)
    cam.set_2d_top_down_view()   # 切到 2D 正交俯视
    cam.set_3d_perspective_view()# 切回 3D 透视
    cam.toggle_2d_3d()          # 一键切换

与主线 EditorCamera 的对齐:
    - 同样的初始参数 (yaw=3π/4, pitch=π/6, distance=15)
    - 同样的 orbit 方向 (yaw += dx*speed, pitch += dy*speed)
    - 同样的 position 计算 (sin/cos 公式)
    - 同样的灵敏度 (orbit_speed=0.005)

2D 正交俯视约定 (v8):
    - GL 视线方向: (0, -1, 0) — 摄像机位于 GL +Y 看向原点
    - 对应编辑器视线: (0, 0, -1) — 编辑器 +Z 看向原点
    - 视图平面: GL XZ 平面 = 编辑器 XY 平面
    - 投影: 正交 (orthographic), up=(0, 0, -1) 使 GL +X→右, GL -Z→上
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44, Vector3


class TestEditorCamera:
    """测试专用轨道摄像机 — 参数和行为与主线 EditorCamera 完全对齐。"""

    def __init__(self):
        # ── 轨道参数 (与 EditorCamera._init_defaults 一致) ──
        self.yaw: float = math.pi * 0.75    # 3π/4
        self.pitch: float = math.pi / 6.0   # 30° 俯角
        self.target: np.ndarray = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.distance: float = 15.0

        # ── 投影参数 ──
        self.fov: float = 45.0
        self.near: float = 0.1
        self.far: float = 1000.0

        # ── 正交投影参数 (v8) ──
        self._orthographic: bool = False        # True=正交, False=透视
        self._ortho_size: float = 10.0          # 正交半高 (世界单位)
        self._saved_perspective: dict | None = None  # 保存 3D 状态以便切回

        # ── 灵敏度 ──
        self.orbit_speed: float = 0.005
        self.pan_speed: float = 0.01      # 与 EditorCamera 一致

    # ════════════════════════════════════════════════════════════
    # 公开属性别名 (与 OrbitCamera/EditorCamera 接口对齐)
    # ════════════════════════════════════════════════════════════

    @property
    def is_orthographic(self) -> bool:
        return self._orthographic

    @is_orthographic.setter
    def is_orthographic(self, value: bool) -> None:
        self._orthographic = value

    @property
    def ortho_size(self) -> float:
        return self._ortho_size

    @ortho_size.setter
    def ortho_size(self, value: float) -> None:
        self._ortho_size = value

    @property
    def position(self) -> np.ndarray:
        """摄像机世界位置 — 由轨道参数计算 (与 OrbitCamera 一致)。"""
        return self.target + self.distance * self._forward

    @property
    def _forward(self) -> np.ndarray:
        """当前向前方向 (GL 空间, target → camera, 单位向量)。

        forward = (sin(y)*cos(p),  sin(p),  -cos(y)*cos(p))
        """
        cp = math.cos(self.pitch)
        return np.array([
            math.sin(self.yaw) * cp,
            math.sin(self.pitch),
            -math.cos(self.yaw) * cp,
        ], dtype=np.float32)

    @staticmethod
    def _rotate_vector(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
        """Rodrigues 旋转公式 — 将向量 v 绕单位轴 axis 旋转 angle 弧度。

        v_rot = v*cosθ + (k×v)*sinθ + k*(k·v)*(1-cosθ)
        """
        c = math.cos(angle)
        s = math.sin(angle)
        k_dot_v = float(np.dot(axis, v))
        cross = np.cross(axis, v)
        return v * c + cross * s + axis * (k_dot_v * (1.0 - c))

    # ── 极点阈值: |pitch| 超过此值时切换为 yaw-直控模式 ──
    _POLE_THRESHOLD: float = math.pi / 2 - 0.05  # ≈ 87°, cos ≈ 0.05

    # ════════════════════════════════════════════════════════════
    # 轨道操作 (混合方案: 极点 yaw-直控, 非极点 Rodrigues 全向量)
    # ════════════════════════════════════════════════════════════

    def orbit(self, dx: float, dy: float) -> None:
        """绕轨道原点旋转摄像机 (混合方案, 无万向锁, 无抖动)。

        非极点 (|pitch| < ~87°):
          全 Rodrigues 向量旋转 → 增量提取 yaw/pitch → 稳定连续

        极点 (|pitch| ≥ ~87°):
          垂直: Rodrigues (yaw-对齐右轴) → 提取 pitch
          水平: 直接修改 yaw → 从 (yaw, pitch) 重建 forward
          避免从近乎退化的 XZ 投影提取 yaw 导致的数值抖动

        Args:
            dx: 水平鼠标位移 (像素)
            dy: 垂直鼠标位移 (像素)
        """
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        old_yaw = self.yaw
        old_pitch = self.pitch
        near_pole = abs(old_pitch) >= self._POLE_THRESHOLD

        f = self._forward

        # ══════════════════════════════════════════════════════
        # 1. 垂直旋转 (Rodrigues — 两极均稳定)
        # ══════════════════════════════════════════════════════
        right = np.cross(f, world_up)
        right_norm = float(np.linalg.norm(right))
        if right_norm < 1e-6:          # 极点: forward ∥ world_up
            right = np.array([-math.cos(old_yaw), 0.0, math.sin(old_yaw)], dtype=np.float32)
            rn = float(np.linalg.norm(right))
            if rn < 1e-6:
                right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            else:
                right /= rn
        else:
            right /= right_norm
        f = self._rotate_vector(f, right, dy * self.orbit_speed)

        # ══════════════════════════════════════════════════════
        # 2. 水平旋转 + yaw/pitch 提取
        # ══════════════════════════════════════════════════════
        if near_pole:
            # ── 极点路径: yaw 直控, 从 (yaw,pitch) 重建 forward ──
            self.yaw = old_yaw + dx * self.orbit_speed
            self.pitch = math.asin(max(-1.0, min(1.0, float(f[1]))))
            cp = math.cos(self.pitch)
            f = np.array([
                math.sin(self.yaw) * cp,
                math.sin(self.pitch),
                -math.cos(self.yaw) * cp,
            ], dtype=np.float32)
        else:
            # ── 非极点路径: Rodrigues + 增量提取 ──
            f = self._rotate_vector(f, world_up, -dx * self.orbit_speed)
            f_norm = float(np.linalg.norm(f))
            if f_norm < 1e-8:
                return
            f /= f_norm
            self.pitch = math.asin(max(-1.0, min(1.0, float(f[1]))))
            # yaw 增量: 新旧 forward 在 XZ 平面的投影夹角 (远离极点, 数值稳定)
            old_cp = math.cos(old_pitch)
            ox = math.sin(old_yaw) * old_cp
            oz = -math.cos(old_yaw) * old_cp
            nx, nz = float(f[0]), float(f[2])
            cross_xz = ox * nz - oz * nx
            dot_xz = ox * nx + oz * nz
            self.yaw = old_yaw + math.atan2(cross_xz, dot_xz)

    def zoom(self, delta: float) -> None:
        """缩放 — 3D: 调整距离; 2D: 调整 ortho_size。"""
        if self._orthographic:
            self._ortho_size *= (1.0 - delta * 0.1)
            self._ortho_size = max(self._ortho_size, 0.01)
        else:
            self.distance *= (1.0 - delta * 0.1)
            self.distance = max(self.distance, 0.01)

    def on_scroll(self, y_offset: float) -> None:
        """滚轮缩放 — 与 EditorCamera.on_scroll 签名兼容。"""
        self.zoom(y_offset)

    def on_mouse_drag(
        self,
        button: int,
        offset_x: float,
        offset_y: float,
        shift_held: bool = False,
    ) -> None:
        """处理鼠标拖动 — 与 EditorCamera.on_mouse_drag 签名和行为一致。

        主线约定 (EditorCamera._on_mouse_drag_3d):
          - 左键 → 无操作 (预留给 Gizmo/Pick)
          - 中键 → orbit(offset_x * orbit_speed, offset_y * orbit_speed)
          - 中键+Shift → pan(offset_x * pan_speed, offset_y * pan_speed)

        Args:
            button:     GLFW 鼠标按钮码
            offset_x:   水平像素位移
            offset_y:   垂直像素位移
            shift_held: Shift 是否按下
        """
        from Application.Core.Events.Enum.InputEnum import MouseButtonCode
        if button == MouseButtonCode.Left:
            return
        elif button == MouseButtonCode.Middle:
            if shift_held:
                self.pan(offset_x * self.pan_speed, offset_y * self.pan_speed)
            else:
                self.orbit(offset_x, offset_y)

    def pan(self, delta_right: float, delta_up: float) -> None:
        """平移注视点 — 沿摄像机局部坐标系 (与 OrbitCamera.pan 一致)。

        Args:
            delta_right: 沿摄像机 right 轴位移 (世界单位)
            delta_up:    沿摄像机 up 轴位移 (世界单位)
        """
        rx = math.cos(self.yaw)
        rz = math.sin(self.yaw)
        ux = -math.sin(self.pitch) * math.sin(self.yaw)
        uy = math.cos(self.pitch)
        uz = math.sin(self.pitch) * math.cos(self.yaw)
        self.target[0] += rx * delta_right + ux * delta_up
        self.target[1] += uy * delta_up
        self.target[2] += rz * delta_right + uz * delta_up

    # ════════════════════════════════════════════════════════════
    # 位置计算 (与 EditorCamera._update_position 一致)
    # ════════════════════════════════════════════════════════════

    @property
    def position(self) -> np.ndarray:
        dx = math.sin(self.yaw) * math.cos(self.pitch)
        dy = math.sin(self.pitch)
        dz = -math.cos(self.yaw) * math.cos(self.pitch)
        return np.array([
            self.target[0] + dx * self.distance,
            self.target[1] + dy * self.distance,
            self.target[2] + dz * self.distance,
        ], dtype=np.float32)

    # ════════════════════════════════════════════════════════════
    # 预设视角 (ViewGizmo 面点击 → 方向向量 → yaw/pitch)
    # ════════════════════════════════════════════════════════════

    def look_from_preset(self, yaw: float, pitch: float) -> None:
        """直接设置轨道角度（保留 distance 和 target 不变）。

        供 ViewGizmo 面点击等预设视角切换使用。
        调用方负责提供正确的 (yaw, pitch)，本方法不做任何三角运算。

        Args:
            yaw:   水平环绕角 (弧度)
            pitch: 垂直俯仰角 (弧度)
        """
        self.yaw = yaw
        self.pitch = pitch

    def look_from_direction(self, forward: np.ndarray) -> None:
        """从 GL 空间方向向量设置摄像机朝向 — 无万向锁, 允许精确 ±Y。

        摄像机位置 = target + distance * normalize(forward),
        视线始终指向 target。

        yaw/pitch 从 forward 反算, 精确值包括 ±π/2 (正顶/正底)。
        orbit() 使用向量旋转, 从任意方向拖拽均可平滑过渡, 无万向锁。

        Args:
            forward: GL 空间中从 target 指向摄像机的方向 (shape (3,), 自动归一化)

        Formula:
            forward = (sin(y)*cos(p),  sin(p),  -cos(y)*cos(p))
            pitch   = asin(forward.y)
            yaw     = atan2(forward.x, -forward.z)
        """
        d = np.asarray(forward, dtype=np.float32)
        norm = float(np.linalg.norm(d))
        if norm < 1e-8:
            return
        d = d / norm
        self.pitch = math.asin(max(-1.0, min(1.0, float(d[1]))))
        # 避免 IEEE 754: atan2(0, -0) 返回 π 而非 0
        nz = float(-d[2])
        self.yaw = math.atan2(float(d[0]), 0.0 if nz == 0.0 else nz)
        # 正顶/正底: yaw 额外转 180° 使 ViewGizmo 字母正向
        if abs(d[1]) > 0.9999:
            self.yaw += math.pi

    # ════════════════════════════════════════════════════════════
    # 矩阵
    # ════════════════════════════════════════════════════════════

    def get_view_matrix(self) -> np.ndarray:
        """生成视图矩阵。

        当摄像机近垂直俯视 (|pitch| ≈ π/2) 时使用 yaw 相关的 up 向量:
          - up = (-sin(yaw), 0, cos(yaw)) — 在 GL XZ 平面内随 yaw 旋转
          - 解决极点退化: cos(pitch)=0 时 position 与 yaw 无关,
            但 up 随 yaw 旋转使视图仍可水平旋转
          - GL +X → 右, GL -Z (编辑器 +Y) → 上 (当 yaw=π 时)
          - 其他: up=(0,1,0)
        """
        pos = Vector3(self.position.tolist())
        tgt = Vector3(self.target.tolist())
        # 当 |pitch| 接近 90° 时, forward 与 (0,1,0) 近平行, 切换 up
        if abs(self.pitch) > math.pi * 0.49:
            # ★ yaw 相关 up: 解决极点 yaw 旋转失效问题
            #    up 在 GL XZ 平面内旋转, yaw 变化 → 视图绕 Y 轴旋转
            up = Vector3([-math.sin(self.yaw), 0.0, math.cos(self.yaw)])
        else:
            up = Vector3([0.0, 1.0, 0.0])
        return matrix44.create_look_at(pos, tgt, up).astype(np.float32)

    def get_projection_matrix(self, aspect: float) -> np.ndarray:
        """生成投影矩阵 — 根据当前模式返回透视或正交投影。"""
        if self._orthographic:
            half_h = self._ortho_size * aspect
            half_v = self._ortho_size
            return matrix44.create_orthogonal_projection(
                -half_h, half_h, -half_v, half_v,
                self.near, self.far,
            ).astype(np.float32)
        else:
            return matrix44.create_perspective_projection(
                self.fov, aspect, self.near, self.far,
            ).astype(np.float32)

    # ════════════════════════════════════════════════════════════
    # 2D / 3D 模式切换 (v8)
    # ════════════════════════════════════════════════════════════

    @property
    def is_orthographic(self) -> bool:
        """当前是否为正交投影模式。"""
        return self._orthographic

    def set_2d_top_down_view(self) -> None:
        """切换到 2D 正交俯视模式。

        摄像机从 GL +Y 方向俯视 GL XZ 平面 (编辑器 XY 平面):
          - GL forward (tgt→cam): (0, +1, 0)
          - GL look (cam→tgt):    (0, -1, 0) 对应编辑器 (0, 0, -1)
          - 投影: 正交 (orthographic)
          - up: (0, 0, -1) → GL +X 右, GL -Z (编辑器 +Y) 上

        首次进入 2D 时保存当前 3D 透视状态 (yaw/pitch/distance/fov),
        重复调用不会覆盖已保存的状态, 确保 toggle 切回的是最初 3D 视角。
        ortho_size 根据当前 distance 估算, 保持视野范围大致一致。
        """
        # ── 保存 3D 透视状态 (仅首次, 不覆盖已有备份) ──
        if self._saved_perspective is None:
            self._saved_perspective = {
                'yaw': self.yaw,
                'pitch': self.pitch,
                'distance': self.distance,
                'fov': self.fov,
                'target': self.target.copy(),
            }
        # ── 视线: forward=(0,+1,0) — 摄像机在 GL +Y 俯视原点 ──
        #     forward 约定: target→camera 方向
        #     look 方向 (cam→tgt) = (0,-1,0), 对应编辑器 (0,0,-1)
        self.look_from_direction(np.array([0.0, 1.0, 0.0], dtype=np.float32))
        # ── 正交大小: 根据当前 distance 估算匹配的视野 ──
        if self._ortho_size <= 0.0:
            self._ortho_size = self.distance * 0.5
        # ── 切换投影模式 ──
        self._orthographic = True

    def set_3d_perspective_view(self) -> None:
        """切回 3D 透视模式, 恢复之前保存的视角状态。

        恢复后清除 _saved_perspective, 以便下次进入 2D 时重新保存。
        """
        if self._saved_perspective is not None:
            sp = self._saved_perspective
            self.yaw = sp['yaw']
            self.pitch = sp['pitch']
            self.distance = sp['distance']
            self.fov = sp['fov']
            self.target = sp['target'].copy()
        self._saved_perspective = None   # ★ 清除, 下次进 2D 重新保存
        self._orthographic = False

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
