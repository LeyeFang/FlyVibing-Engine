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
# 连线颜色 — 按 pin data_type 着色
# ═══════════════════════════════════════════════════════════════

LINK_COLORS: dict[str, tuple[float, float, float]] = {
    "exec":       (0.95, 0.95, 0.95),  # 纯白 — 执行流
    "float":      (0.31, 0.78, 0.47),  # 翠绿 — 连续数值
    "int":        (0.31, 0.65, 0.92),  # 钢蓝 — 离散数值
    "bool":       (0.88, 0.42, 0.42),  # 珊瑚红 — 二元信号
    "vec3":       (0.65, 0.42, 0.92),  # 淡紫 — 向量/结构体
    "string":     (0.88, 0.62, 0.31),  # 暖橙 — 文本
    "entity_ref": (0.88, 0.75, 0.31),  # 琥珀 — 对象引用
    "variant":    (0.65, 0.65, 0.65),  # 浅灰 — 动态类型
}

# 未识别类型的 fallback（半透明白）
_LINK_COLOR_FALLBACK: tuple[float, float, float] = (0.55, 0.55, 0.55)

# ═══════════════════════════════════════════════════════════════
# Add 菜单分类数据
# ═══════════════════════════════════════════════════════════════
#
# 组织约定:
#   - 顶级页按建图顺序排列: 事件 → 流控 → 值 → 计算 → 时间 → 场景 → 调试 → IO
#   - 页内条目 ≤ 3 直接平铺; 更多则按语义分组 (组头仅作视觉分区, 不可点击)
#   - 菜单项标签与节点卡片标题一致 (NodeTypeDef.label), 点选后所见即所得
#   - 所有可创建节点都应在此可达; 仅"兼容保留"的旧节点不出现:
#     MathAdd / MathSubtract / MathMultiply / MathDivide /
#     MathRandomUniform / MathRandomGaussian (旧版数学, 由 ScalarMath / Random 覆盖)
#     EntityAddMesh / EntityAddCamera (由 Component 节点覆盖)
#
# 每个分类: (标题, [子项 ...])
#   子项 = ("标签", "类型名")           ← 叶子 → 直接创建节点
#   子项 = ("标签", [子项 ...])         ← 分组 → 组内继续展开
MENU_SECTIONS: list[tuple[str, list]] = [
    # ── 图入口 (exec 链起点) ────────────────────────────────
    ("Event", [
        ("On Game Start", "OnGameStart"),
        ("On Frame Update", "OnFrameUpdate"),
        ("On Game Stop", "OnGameStop"),
    ]),

    # ── 执行流控制 ──────────────────────────────────────────
    ("Flow", [
        ("Sequence", "Sequence"),
        ("Branch", "Branch"),
    ]),

    # ── 基础值 (纯数据常量, 无 exec 引脚) ───────────────────
    ("Basic", [
        ("Number", "Constant"),
        ("String Constant", "StringConst"),
    ]),

    # ── 变量读写 ────────────────────────────────────────────
    ("Variable", [
        ("Set Variable", "VarSet"),
        ("Get Variable", "VarGet"),
    ]),

    # ── 数学计算 ────────────────────────────────────────────
    ("Math", [
        ("Calculate", [
            ("Scalar Math", "ScalarMath"),
            ("Compare", "Compare"),
        ]),
        ("Vector", [
            ("Make Vec3", "MakeVec3"),
            ("Break Vec3", "BreakVec3"),
            ("Vec Math", "VecMath"),
        ]),
        ("Random", [
            ("Random", "Random"),
            ("Set Seed", "RandomSetSeed"),
        ]),
    ]),

    # ── 时间 / 定时 ─────────────────────────────────────────
    ("Time", [
        ("Query", [
            ("Get Time", "TimeGetElapsed"),
            ("Get Delta Time", "TimeGetDelta"),
            ("Get Date", "TimeGetDate"),
        ]),
        ("Control", [
            ("Delay", "TimeDelay"),
            ("Time Trigger", "TimeTrigger"),
        ]),
        ("Timer", [
            ("New Timer", "NewTimer"),
            ("Set Timer", "SetTimer"),
        ]),
    ]),

    # ── 场景 / 实体 / 组件 ──────────────────────────────────
    ("Scene", [
        ("Entity", [
            ("Spawn Entity", "EntitySpawn"),
            ("Get Entity", "EntityGet"),
            ("Destroy Entity", "EntityDestroy"),
            ("Set Render Visible", "EntitySetRenderVisible"),
        ]),
        ("Component", [
            ("Add Component", "ComponentAdd"),
            ("Set Component", "SetComponent"),
            ("Get Component", "GetComponent"),
            ("Remove Component", "ComponentRemove"),
        ]),
        ("Game", [
            ("Set Main Camera", "CameraSetMain"),
            ("Exit Game", "ExitGame"),
        ]),
    ]),

    # ── 调试输出 ────────────────────────────────────────────
    ("Debug", [
        ("Print", "Print"),
        ("Print String", "PrintString"),
    ]),

    # ── 设备 / 文件输出 ─────────────────────────────────────
    ("IO", [
        ("Serial", [
            ("Serial Send", "SerialSend"),
            ("Parallel Send", "ParallelSend"),
        ]),
        ("File", [
            ("Path", "PathVar"),
            ("Write Text File", "TextFileWrite"),
        ]),
        ("Gtec", [
            ("Init Gtec Device", "InitGtecDevice"),
            ("Start Gtec Record", "StartGtecRecord"),
            ("Stop Gtec Record", "StopGtecRecord"),
            ("Kill Gtec Device", "KillGtecDevice"),
            ("Get Gtec Data", "GetGtecData"),
        ]),
        ("SigGen", [
            ("Init SigGen Device", "InitSigGenDevice"),
            ("Start SigGen Record", "StartSigGenRecord"),
            ("Stop SigGen Record", "StopSigGenRecord"),
            ("Kill SigGen Device", "KillSigGenDevice"),
            ("Get SigGen Data", "GetSigGenData"),
        ]),
    ]),
]
