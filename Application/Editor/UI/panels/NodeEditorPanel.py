from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Editor.UI.BasePanel import BasePanel


class NodeEditorPanel(BasePanel):
    """节点编辑器画布 — 目前为空白画布 + 右键菜单占位"""

    name = "Node Editor"
    flags = imgui.WindowFlags_.none

    def __init__(
        self
    ) -> None:
        super().__init__()
        self.visible = True
        # imgui_node_editor 上下文
        self._editor_context: node_ed.EditorContext | None = None
        # 是否已完成初始化
        self._editor_initialized: bool = False

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(
        self
    ) -> None:
        """面板注册时创建节点编辑器上下文"""
        if not self._editor_initialized:
            try:
                self._editor_context = node_ed.create_editor()
                self._editor_initialized = True
            except Exception:
                self._editor_context = None

    def on_detach(
        self
    ) -> None:
        """面板移除时销毁节点编辑器上下文"""
        if self._editor_context is not None:
            try:
                node_ed.destroy_editor(self._editor_context)
            except Exception:
                pass
            self._editor_context = None
            self._editor_initialized = False

    # ============================================================
    # 绘制
    # ============================================================

    def draw(
        self
    ) -> None:
        """绘制节点编辑画布及右键菜单"""
        # 节点编辑器不可用时的降级提示
        if self._editor_context is None:
            imgui.text_colored(
                imgui.ImVec4(1.0, 0.3, 0.3, 1.0),
                "Node Editor not available"
            )
            imgui.text_disabled(
                "Ensure imgui_bundle is compiled with node editor support."
            )
            return

        canvas_size = imgui.get_content_region_avail()

        # 激活当前编辑器上下文并开始绘制
        node_ed.set_current_editor(self._editor_context)
        node_ed.begin("NodeEditor", canvas_size)

        # ── 右键菜单检测（node editor 函数，需在 suspend 外调用） ──
        node_ed.suspend()
        if node_ed.show_background_context_menu():
            imgui.open_popup("Create Node")
        node_ed.resume()

        # ── 空画布提示 & 右键菜单绘制（必须在 suspend 内进行普通 imgui 绘制） ──
        node_ed.suspend()
        canvas_pos = imgui.get_cursor_screen_pos()
        imgui.set_cursor_screen_pos((
            canvas_pos.x + canvas_size.x / 2 - 80,
            canvas_pos.y + canvas_size.y / 2 - 10
        ))
        imgui.text_colored(
            imgui.ImVec4(0.400, 0.400, 0.400, 1.00),
            "Right-click canvas to add nodes"
        )

        if imgui.begin_popup("Create Node"):
            imgui.text_disabled("Add Node...")
            imgui.separator()
            # 未来：这些菜单项将创建真实节点
            if imgui.menu_item("SSVEP Stimulus", "", False)[0]:
                pass
            if imgui.menu_item("Image Stimulus", "", False)[0]:
                pass
            if imgui.menu_item("EEG Device", "", False)[0]:
                pass
            if imgui.menu_item("PyTorch Inference", "", False)[0]:
                pass
            imgui.end_popup()
        node_ed.resume()

        node_ed.end()
