"""视口控制器 — 管理 2D/3D 投影模式切换，桥接 UI 与 EditorCamera"""

from Application.Editor.EditorCamera import EditorCamera
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent


class ViewportController:
    """2D/3D 视口模式控制器 — 纯数据层，不 import imgui

    职责:
      - 持有当前场景的 2D/3D 模式状态
      - 通过 EditorCamera 开放接口切换正交/透视投影
      - 供 ScenePanel 等 UI 面板调用
    """

    # ── 模式状态 (默认 3D) ──
    _mode_2d: bool = False

    # ── 模式查询 ────────────────────────────────────────────

    @classmethod
    def is_2d(cls) -> bool:
        """当前是否为 2D 模式。"""
        return cls._mode_2d

    @classmethod
    def is_3d(cls) -> bool:
        """当前是否为 3D 模式。"""
        return not cls._mode_2d

    @classmethod
    def get_mode_label(cls) -> str:
        """返回当前模式标签，如 '2D (Ortho)' 或 '3D (Persp)'。"""
        return "2D (Ortho)" if cls._mode_2d else "3D (Persp)"

    # ── 模式切换 ────────────────────────────────────────────

    @classmethod
    def switch_to_2d(cls) -> None:
        """切换到 2D 正交俯视模式。

        通过 EditorCamera.set_2d_top_down_view() 执行摄像机切换，
        并 Pack SceneCameraUpdateEvent 通知渲染器刷新矩阵缓存。
        """
        if cls._mode_2d:
            return
        cam = EditorCamera.get_instance()
        cam.set_2d_top_down_view()
        cls._mode_2d = True
        SceneCameraUpdateEvent.Pack()

    @classmethod
    def switch_to_3d(cls) -> None:
        """切换到 3D 透视模式。"""
        if not cls._mode_2d:
            return
        cam = EditorCamera.get_instance()
        cam.set_3d_perspective_view()
        cls._mode_2d = False
        SceneCameraUpdateEvent.Pack()

    @classmethod
    def switch_to_overlay(cls) -> None:
        """切换到 Overlay 模式。

        Overlay 是运行时模式，编辑器视口不变，但触发 SceneCameraUpdateEvent
        强制渲染器刷新（消除按钮点击后的感知延迟）。
        """
        SceneCameraUpdateEvent.Pack()

    @classmethod
    def toggle(cls) -> str:
        """一键切换 2D ↔ 3D。

        Returns:
            '2d' 或 '3d' — 切换后的模式标识。
        """
        if cls._mode_2d:
            cls.switch_to_3d()
            return '3d'
        else:
            cls.switch_to_2d()
            return '2d'

    # ── 同步: 从 EditorCamera 回读实际模式 ──────────────────

    @classmethod
    def sync_from_camera(cls) -> None:
        """从 EditorCamera 同步实际投影模式（用于外部切换后保持一致）。"""
        cam = EditorCamera.get_instance()
        cls._mode_2d = cam.is_orthographic


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_VIEWPORT
register(NAME_VIEWPORT, ViewportController)
