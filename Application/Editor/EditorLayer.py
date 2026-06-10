# ── 标准库 ──
import ctypes
import os

# ── 第三方库 ──
from imgui_bundle import imgui

# ── 应用层: 核心 ──
from Application.Application import GetEditorWindow, GetEditorRenderer
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.Enum.InputEnum import (
    MouseButtonCode, MouseActionCode, KeyButtonCode, KeyActionCode,
)
from Application.Core.Layers.Layer import Layer

# ── 应用层: 编辑器 ──
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.EditorEvent import (
    SelecteEntityEvent, DeselectEntityEvent, ClearSelectionEvent,
)
from Application.Editor.Rendering.Grid import Grid
from Application.Editor.Rendering.Outliner import Outliner
from Application.Editor.Rendering.ViewGizmo import ViewGizmo
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel

# ── 模块引用 (访问 InputState 中的可变全局状态 press/release 坐标) ──
import Application.Core.Input.InputState as _input_state


class EditorLayer(Layer):

    # ── 字体配置 ────────────────────────────────────────────────
    FONT_SIZE: float = 15.0
    # 优先级从高到低: Inter (Blender 同款) → Segoe UI → Arial → 默认
    FONT_CANDIDATES: list[str] = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    # ── 选中状态 (编辑器侧, 不 import GL) ─────────────────────────
    current_selected_entity: int = None
    _selected_ids: set = set()       # 当前选中的实体 ID 集合
    _outline_xray: bool = True       # 轮廓 X-Ray 模式
    _click_threshold: float = 4.0    # 点击判定最大位移 (像素)
    _outliner: Outliner = None       # 轮廓渲染模块 (自包含 GPU 资源)

    # ── 跨线程拾取 (main thread → render thread) ─────────────
    _pending_pick_coords: tuple = None   # (sx, sy) 待处理的拾取请求

    # ════════════════════════════════════════════════════════════
    # 生命周期 (Layer 接口)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        """编辑器层初始化 — 创建 ImGui 上下文、注册 3D 渲染资源和 UI 面板。"""
        imgui.create_context()
        imgui.style_colors_dark()

        # ── 配置文件路径: 生成到 Application/Editor/config/ ──
        cls._config_dir = os.path.join(os.path.dirname(__file__), "config")
        os.makedirs(cls._config_dir, exist_ok=True)
        io = imgui.get_io()
        io.set_ini_filename(os.path.join(cls._config_dir, "imgui.ini"))

        # ── 加载字体 (必须在 backend init 之前，否则纹理不会包含新字体) ──
        cls._load_fonts()

        editor_window = GetEditorWindow()
        cls.editor_renderer = GetEditorRenderer()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        # OpenGL 后端: GLFW + OpenGL3
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 150")
        io = imgui.get_io()
        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))
        cls._init_ui_panels()

        # ── 编辑器 3D 渲染资源: Grid 注册到 Renderer ──
        Grid.register_to(cls.editor_renderer)

        # ── 视图立方体: 右上角摄像机方向指示器 ──
        ViewGizmo.register_to(cls.editor_renderer)

        # ── 轮廓高亮: 创建 Outliner 并注册到 Renderer ──
        w, h = editor_window.GetSize()
        cls._outliner = Outliner()
        cls._outliner.init(cls.editor_renderer, w, h)
        cls.editor_renderer.register_outliner(cls._outliner)
        cls._sync_outline_to_renderer()

    @classmethod
    def OnDetach(cls):
        """编辑器层销毁 — 注销渲染资源、销毁 ImGui 上下文。"""
        Grid.unregister_from(cls.editor_renderer)
        ViewGizmo.unregister_from(cls.editor_renderer)
        if cls._outliner is not None:
            cls.editor_renderer.unregister_outliner()
            cls._outliner = None
        imgui.destroy_context()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        """事件分发 — 键盘快捷键全局处理；鼠标事件仅在视口内转发。"""
        # ── 键盘快捷键 (全局, 不受 ImGui 面板遮挡影响) ──
        if event is KeyboardButtonEvent:
            cls._handle_keyboard_event(event)
            return

        # ── 以下事件仅在鼠标不在 ImGui 面板内时处理 ──
        if cls._mouse_in_any_panel():
            return
        cam = EditorCamera.get_instance()

        if event is ScrollerEvent:
            _, y_offset = ScrollerEvent.UnPack()
            cam.on_scroll(y_offset)
            SceneCameraUpdateEvent.Pack()

        elif event is MouseGragEvent:
            bt, offset_x, offset_y = MouseGragEvent.UnPack()
            cam.on_mouse_drag(bt, offset_x, offset_y)
            SceneCameraUpdateEvent.Pack()

        # ── 实体拾取 (左键单击, 非拖拽) ──
        elif event is MouseButtonEvent:
            cls._handle_mouse_button_event(event)

    @classmethod
    def OnUpdate(cls):
        """每帧逻辑更新 (当前无操作)。"""
        pass

    @classmethod
    def OnRender(cls):
        """每帧渲染 — 执行待处理拾取 + ImGui 绘制。"""
        # ── 处理待处理的拾取请求 (render thread, GL 上下文有效) ──
        cls._execute_pending_pick()

        # ── ImGui 渲染 ──
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())

    # ════════════════════════════════════════════════════════════
    # 初始化辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _load_fonts(cls) -> None:
        """加载 UI 字体 — 优先 Inter (Blender 同款)，否则用系统字体。

        调用时机: create_context() 之后、opengl3_init() 之前。
        """
        io = imgui.get_io()
        font_loaded = False

        for font_path in cls.FONT_CANDIDATES:
            if os.path.isfile(font_path):
                io.fonts.add_font_from_file_ttf(font_path, cls.FONT_SIZE)
                print(f"[Font] Loaded: {font_path} ({cls.FONT_SIZE}px)")
                font_loaded = True
                break

        if not font_loaded:
            print(
                "[Font] No custom font found. Using ImGui default.\n"
                "       To get Blender-style font, download Inter:\n"
                "       https://rsms.me/inter/ → Resource/Fonts/Inter-Regular.ttf"
            )

    @classmethod
    def _init_ui_panels(cls):
        """注册编辑器 UI 面板 (幂等, 仅首次调用生效)。"""
        if not hasattr(cls, '_panels_registered'):
            UIManager.register(ScenePanel())
            UIManager.register(NodeEditorPanel())
            cls._panels_registered = True

    # ════════════════════════════════════════════════════════════
    # 输入事件处理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _handle_keyboard_event(
        cls,
        event: KeyboardButtonEvent
    ) -> None:
        """处理键盘快捷键。

        Escape : 清除选中
        X      : 切换轮廓 X-Ray 模式
        """
        if event.action != KeyActionCode.Press:
            return

        if event.key == KeyButtonCode.Escape:
            if cls._selected_ids:
                old = set(cls._selected_ids)
                cls._selected_ids.clear()
                cls.current_selected_entity = None
                ClearSelectionEvent.Pack()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                cls._sync_outline_to_renderer()

        elif event.key == KeyButtonCode.X:
            cls._outline_xray = not cls._outline_xray
            cls._sync_outline_to_renderer()
            print(f"[EditorLayer] X-Ray={'ON' if cls._outline_xray else 'OFF'}")

    @classmethod
    def _handle_mouse_button_event(
        cls,
        event: MouseButtonEvent
    ) -> None:
        """处理鼠标按键事件 — 区分点击与拖拽。

        单击 (位移 < _click_threshold) → FBO 拾取实体。
        拖拽已由 MouseGragEvent 处理, 此处忽略。
        """
        if event.button != MouseButtonCode.Left:
            return
        if event.action != MouseActionCode.Release:
            return

        # 计算拖拽距离
        dx = _input_state.button_release_pos_x - _input_state.button_press_pos_x
        dy = _input_state.button_release_pos_y - _input_state.button_press_pos_y
        dist = (dx * dx + dy * dy) ** 0.5

        if dist >= cls._click_threshold:
            return  # 拖拽, 已由 MouseGragEvent 处理

        # ── 单击 → 延迟到渲染线程执行 FBO 拾取 ──
        # PickAt() 需要 GL 上下文 (render thread), 此处仅记录坐标
        cls._pending_pick_coords = (
            _input_state.button_release_pos_x,
            _input_state.button_release_pos_y,
        )

    # ════════════════════════════════════════════════════════════
    # 实体拾取 & 选中管线
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _execute_pending_pick(cls) -> None:
        """在渲染线程执行待处理的 FBO 拾取。"""
        if cls._pending_pick_coords is None:
            return
        if cls._outliner is None:
            cls._pending_pick_coords = None
            return
        sx, sy = cls._pending_pick_coords
        cls._pending_pick_coords = None

        entity_id = cls._outliner.pick_at(cls.editor_renderer, sx, sy)

        if entity_id >= 0:
            # 选中实体
            cls._selected_ids = {entity_id}
            cls.current_selected_entity = entity_id
            SelecteEntityEvent.Pack(entity_id)
        else:
            # 点击空白 → 清除选中
            if cls._selected_ids:
                old = set(cls._selected_ids)
                cls._selected_ids.clear()
                cls.current_selected_entity = None
                for eid in old:
                    DeselectEntityEvent.Pack(eid)

        cls._sync_outline_to_renderer()

    @classmethod
    def _sync_outline_to_renderer(cls) -> None:
        """编辑器 → 渲染器: 同步选中状态和轮廓配置。

        对齐 Grid.register_to 的解耦模式:
          编辑器只传数据 (selected_ids, xray), 不碰 GL。
          Outliner 根据数据在渲染时执行 stencil 轮廓绘制。
        """
        if cls._outliner is not None:
            cls._outliner.set_config(
                selected_ids=cls._selected_ids,
                xray=cls._outline_xray,
            )

    # ════════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _mouse_in_any_panel(cls) -> bool:
        """检查鼠标是否悬停在任意 ImGui 面板区域内。"""
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False
