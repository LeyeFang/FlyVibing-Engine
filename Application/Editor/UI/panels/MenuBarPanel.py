from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.UIManager import UIManager


def toggle_grid_visible() -> bool:
    """View ▸ Show Grid 的动作 — 与场景测试共用（返回切换后的状态）。

    业务实现唯一在 Grid.set_visible（菜单与 view.set_grid op 同路径）。
    """
    from Application.Editor.Gizmos.Grid import Grid
    return Grid.set_visible(not Grid.visible)


class MenuBarPanel(BasePanel):
    """主菜单栏：File / Edit / View / Help"""

    name = "##MainMenu"  # 隐藏窗口标题
    flags = (
        imgui.WindowFlags_.no_title_bar
        | imgui.WindowFlags_.no_collapse
        | imgui.WindowFlags_.no_resize
        | imgui.WindowFlags_.no_move
        | imgui.WindowFlags_.no_scrollbar
        | imgui.WindowFlags_.no_docking
        | imgui.WindowFlags_.always_auto_resize)

    def __init__(self):
        super().__init__()
        self.visible = True

    def draw(self):
        if imgui.begin_main_menu_bar():
            # ── File ────────────────────────────────────────
            if imgui.begin_menu("File", True):
                if imgui.menu_item("New Scene", "Ctrl+N", False, False)[0]:
                    pass
                if imgui.menu_item("Open Scene...", "Ctrl+O", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Save Scene", "Ctrl+S", False, False)[0]:
                    pass
                if imgui.menu_item("Save As...", "Ctrl+Shift+S", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Exit", "Alt+F4", False, False)[0]:
                    pass
                imgui.end_menu()

            # ── Edit ────────────────────────────────────────
            if imgui.begin_menu("Edit", True):
                if imgui.menu_item("Undo", "Ctrl+Z", False, False)[0]:
                    pass
                if imgui.menu_item("Redo", "Ctrl+Y", False, False)[0]:
                    pass
                imgui.separator()
                if imgui.menu_item("Preferences...", "", False, False)[0]:
                    pass
                imgui.end_menu()

            # ── View ────────────────────────────────────────
            if imgui.begin_menu("View", True):
                for target_name in ["Scene", "Node Editor", "Properties", "Console"]:
                    panel = UIManager.find(target_name)
                    if panel:
                        _, panel.visible = imgui.menu_item(
                            target_name, "", panel.visible, True)
                imgui.separator()
                # ── Show Grid — 视口网格开关 (动作单点: toggle_grid_visible) ──
                from Application.Editor.Gizmos.Grid import Grid
                clicked, _ = imgui.menu_item("Show Grid", "", Grid.visible, True)
                if clicked:
                    toggle_grid_visible()
                imgui.end_menu()

            # ── Extensions ──────────────────────────────────
            from Application.Editor.Extensions.ExtensionMenu import draw_extensions_menu
            draw_extensions_menu()

            # ── Help ────────────────────────────────────────
            if imgui.begin_menu("Help", True):
                if imgui.menu_item("About", "", False, True)[0]:
                    pass
                imgui.end_menu()

            imgui.end_main_menu_bar()
