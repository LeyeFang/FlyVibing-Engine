"""
节点编辑器 — UI 样式常量与辅助函数。

供 NodeEditorPanel 使用，不依赖 imgui_bundle 之外的模块。
"""

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Editor.UI.PanelStyle import (
    TEXT_DISABLED,
)


# ═══════════════════════════════════════════════════════════════
# 渲染辅助
# ═══════════════════════════════════════════════════════════════

def _col(c: tuple, a: float = 1.0) -> imgui.ImVec4:
    return imgui.ImVec4(c[0], c[1], c[2], a)


def _apply_ne_style(accent: tuple):
    """设置当前节点的 node-editor 样式色（边框、选中、悬停、pin）"""
    s = node_ed.get_style()
    bg_near_black = (0.110, 0.110, 0.110)
    s.set_color_(node_ed.StyleColor.node_bg,           _col(bg_near_black, 0.95))
    s.set_color_(node_ed.StyleColor.node_border,       _col(accent, 0.50))
    s.set_color_(node_ed.StyleColor.sel_node_border,   _col(accent, 1.00))
    s.set_color_(node_ed.StyleColor.hov_node_border,   _col(accent, 0.75))
    s.set_color_(node_ed.StyleColor.pin_rect,          _col(accent, 0.20))
    s.set_color_(node_ed.StyleColor.pin_rect_border,   _col(accent, 0.40))
    s.set_color_(node_ed.StyleColor.flow,              _col(accent, 0.70))
    s.set_color_(node_ed.StyleColor.flow_marker,       _col(accent, 1.00))


_HDR_COLOR = imgui.ImVec4(0.600, 0.600, 0.600, 0.70)

# ═══════════════════════════════════════════════════════════════
# Add 菜单分类数据
# ═══════════════════════════════════════════════════════════════

# 每个分类: (标题, [子项 ...])
#   子项 = ("标签", "类型名")           ← 叶子 → 直接创建节点
#   子项 = ("标签", [子项 ...])         ← 子菜单 → 展开更深层级
MENU_SECTIONS: list[tuple[str, list]] = [
    ("Math", [
        ("Variable", [
            ("Constant", "Constant"),
            ("Set Variable", "VarSet"),
            ("Get Variable", "VarGet"),
            ("Make Vec3", "MakeVec3"),
            ("Break Vec3", "BreakVec3"),
        ]),
        ("Calculate", [
            ("Scalar Math", "ScalarMath"),
            ("Compare", "Compare"),
            ("Random", "Random"),
            ("Vec Math", "VecMath"),
        ]),
    ]),
    ("Time", [
        ("Get Time", "TimeGetElapsed"),
        ("Get Delta Time", "TimeGetDelta"),
        ("Delay", "TimeDelay"),
        ("Time Trigger", "TimeTrigger"),
    ]),
    ("Flow", [
        ("Sequence", "Sequence"),
        ("Branch", "Branch"),
    ]),
    ("Scene", [
        ("Entity", [
            ("Spawn Entity", "EntitySpawn"),
            ("Destroy Entity", "EntityDestroy"),
        ]),
        ("Game", [
            ("Set Main Camera", "CameraSetMain"),
            ("Exit Game", "ExitGame"),
        ]),
        ("Component", [
            ("Add Component", "ComponentAdd"),
            ("Set Component", "SetComponent"),
            ("Get Component", "GetComponent"),
            ("Remove Component", "ComponentRemove"),
        ]),
    ]),
    ("Debug", [
        ("Print", "Print"),
        ("Print String", "PrintString"),
    ]),
]
