"""
EditorInputLayer — 编辑器输入事件路由层（从 EditorLayer 拆分）。

职责:
  - 处理所有输入事件（鼠标/键盘/滚轮/窗口resize）的路由
  - 相机导航（滚动缩放、拖拽旋转/平移）
  - 拾取更新（鼠标移动 → 更新 GPU pick 坐标）
  - Gizmo 交互分发（拖拽、点选）
  - ViewGizmo 方向切换
  - SPACE 摄像机预览切换

设计:
  - 零 ImGui 依赖 — 仅处理 3D 视口的输入，不涉及 UI 面板
  - EditorLayer 通过 cls._editor_layer 引用访问编辑器状态
  - EditorLayer.OnAttach 中推入并设置 renderer 引用
"""

from __future__ import annotations

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.WindowEvent import WindowResizeEvent
from Application.Core.Events.Enum.InputEnum import (
    MouseButtonCode,
    MouseActionCode,
    KeyButtonCode,
    KeyActionCode,
)
from Application.Core.Input.InputState import IsShiftPressed, IsKeyDown


class EditorInputLayer(Layer):
    """编辑器输入层 — 路由所有输入事件到对应的编辑器操作。

    依赖 EditorLayer 的静态方法:
      - _sync_camera_to_renderer()
      - _toggle_preview_camera()
      - invalidate_camera_gizmos()
      - _handle_left_press(mx, my, cam)
      - _handle_left_release(mx, my, cam)
      - _handle_gizmo_drag(mx, my)
    """

    renderer = None  # EditorLayer 在 OnAttach 中赋值
    _editor_layer = None  # EditorLayer 类引用 (延迟导入)

    @classmethod
    def OnAttach(cls):
        super().OnAttach()
        # 延迟导入 EditorLayer 避免循环依赖
        from Application.Editor.EditorLayer import EditorLayer
        cls._editor_layer = EditorLayer

    @classmethod
    def OnDetach(cls):
        cls.renderer = None
        cls._editor_layer = None

    @classmethod
    def OnUpdate(cls):
        pass

    # ════════════════════════════════════════════════════════════
    # 输入事件路由
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        """统一输入事件入口 — 按事件类型分发。"""
        from imgui_bundle import imgui

        # ── 防御: EditorInputLayer 在 OnAttach 之前就可能收到事件 ──
        if cls._editor_layer is None:
            return

        # ── 防御: 渲染线程已退出时 ImGui 上下文已被销毁 ──
        if imgui.get_current_context() is None:
            return

        # ── MouseMoveEvent: 始终更新拾取鼠标位置 (主线程安全, 零 GL 调用) ──
        if isinstance(event, MouseMoveEvent):
            if cls.renderer is not None:
                cls.renderer.update_pick_mouse(event.pos_x, event.pos_y)
            return

        # ── SceneCameraUpdateEvent: 始终处理 (ViewportController / DebugLayer 触发) ──
        if isinstance(event, SceneCameraUpdateEvent):
            cls._editor_layer._sync_camera_to_renderer()
            cls._editor_layer.invalidate_camera_gizmos()
            return

        # ── 窗口 resize 始终处理，不受面板鼠标拦截影响 ──
        if isinstance(event, WindowResizeEvent):
            w, h = event.unpack()
            io = imgui.get_io()
            io.display_size = (float(w), float(h))
            cls._editor_layer._sync_camera_to_renderer()
            return

        # ── 键盘事件: ImGui 捕获键盘时跳过 (如正在文本框输入) ──
        if isinstance(event, KeyboardButtonEvent):
            io = imgui.get_io()
            if not io.want_capture_keyboard:
                if (event.key == KeyButtonCode.Space
                        and event.action == KeyActionCode.Press):
                    cls._editor_layer._toggle_preview_camera()
            return

        # ── 鼠标在 ImGui 面板内 → 不处理 3D 视口输入 ──
        if cls._mouse_in_any_panel():
            return

        if cls.renderer is None:
            return

        from Application.Editor.EditorCamera import EditorCamera
        from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
        cam = EditorCamera.get_instance()

        if isinstance(event, ScrollerEvent):
            _, y_offset = event.unpack()
            cam.on_scroll(y_offset)
            cls._editor_layer._sync_camera_to_renderer()

        elif isinstance(event, MouseGragEvent):
            bt, offset_x, offset_y = event.unpack()
            if bt == MouseButtonCode.Left:
                if TransformGizmo.is_dragging():
                    cls._editor_layer._handle_gizmo_drag(event.pos_x, event.pos_y)
                    return
                return  # 非 gizmo 左键拖动不操作视图
            cam.on_mouse_drag(bt, offset_x, offset_y, IsShiftPressed())
            cls._editor_layer._sync_camera_to_renderer()

        elif isinstance(event, MouseButtonEvent):
            if event.button != MouseButtonCode.Left:
                return
            if event.action == MouseActionCode.Press:
                cls._editor_layer._handle_left_press(event.pos_x, event.pos_y, cam)
            else:
                cls._editor_layer._handle_left_release(event.pos_x, event.pos_y, cam)

    # ════════════════════════════════════════════════════════════
    # 辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _mouse_in_any_panel(cls) -> bool:
        """检查鼠标是否悬停在任意 ImGui 面板区域内。"""
        from imgui_bundle import imgui
        from Application.Editor.UI.UIManager import UIManager
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False
