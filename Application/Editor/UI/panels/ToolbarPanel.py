from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.controllers.SimulationController import (
    SimulationController,
)


class ToolbarPanel(BasePanel):
    """播放控制工具栏 — 共享 SimulationController"""

    name = "##Toolbar"
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
        # ── Run (绿色) ──
        imgui.push_style_color(imgui.Col_.button,        imgui.ImVec4(0.173, 0.545, 0.271, 0.60))
        imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.173, 0.545, 0.271, 0.85))
        imgui.push_style_color(imgui.Col_.button_active,  imgui.ImVec4(0.118, 0.420, 0.216, 1.00))
        if imgui.button("▶  Run"):
            SimulationController.play()
        imgui.pop_style_color(3)

        imgui.same_line()

        # ── Pause (黄色) ──
        imgui.push_style_color(imgui.Col_.button,        imgui.ImVec4(0.698, 0.588, 0.110, 0.40))
        imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.698, 0.588, 0.110, 0.70))
        if imgui.button("⏸  Pause"):
            SimulationController.pause()
        imgui.pop_style_color(2)

        imgui.same_line()

        # ── Stop (红色) ──
        imgui.push_style_color(imgui.Col_.button,        imgui.ImVec4(0.631, 0.173, 0.173, 0.40))
        imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.631, 0.173, 0.173, 0.70))
        if imgui.button("■  Stop"):
            SimulationController.stop()
        imgui.pop_style_color(2)

        # ── 右侧信息 ──
        imgui.same_line()
        imgui.text("  |  Scene: default")
        imgui.same_line()
        imgui.text_disabled(SimulationController.get_state_label())
