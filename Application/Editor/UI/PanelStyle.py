"""现代化深色主题 — 灵感来自 Unity / Unreal Editor"""

from imgui_bundle import imgui


# ============================================================
# 辅助函数
# ============================================================

def _set_col(
    style,
    col_enum,
    r: float,
    g: float,
    b: float,
    a: float
) -> None:
    """用 ImVec4 设置单个颜色"""
    style.set_color_(col_enum, imgui.ImVec4(r, g, b, a))


# ============================================================
# 主入口
# ============================================================

def apply_custom_style(
) -> None:
    """覆盖 imgui 默认样式，应用自定义深色主题"""
    style = imgui.get_style()

    # ── 基本颜色基调 ────────────────────────────────────────────
    _set_col(style, imgui.Col_.window_bg,        0.094, 0.102, 0.114, 1.00)
    _set_col(style, imgui.Col_.child_bg,         0.094, 0.102, 0.114, 1.00)
    _set_col(style, imgui.Col_.popup_bg,         0.122, 0.133, 0.153, 1.00)
    _set_col(style, imgui.Col_.frame_bg,         0.157, 0.169, 0.188, 1.00)
    _set_col(style, imgui.Col_.frame_bg_hovered, 0.216, 0.227, 0.247, 1.00)
    _set_col(style, imgui.Col_.frame_bg_active,  0.290, 0.302, 0.322, 1.00)

    # 标题栏
    _set_col(style, imgui.Col_.title_bg,              0.067, 0.075, 0.086, 1.00)
    _set_col(style, imgui.Col_.title_bg_active,       0.129, 0.451, 0.741, 1.00)
    _set_col(style, imgui.Col_.title_bg_collapsed,    0.067, 0.075, 0.086, 1.00)

    # 菜单栏
    _set_col(style, imgui.Col_.menu_bar_bg, 0.118, 0.129, 0.149, 1.00)

    # 选中 / 高亮
    _set_col(style, imgui.Col_.header,          0.192, 0.404, 0.643, 0.70)
    _set_col(style, imgui.Col_.header_hovered,  0.192, 0.404, 0.643, 0.85)
    _set_col(style, imgui.Col_.header_active,   0.192, 0.404, 0.643, 1.00)

    # 按钮
    _set_col(style, imgui.Col_.button,          0.192, 0.404, 0.643, 0.60)
    _set_col(style, imgui.Col_.button_hovered,  0.192, 0.404, 0.643, 0.85)
    _set_col(style, imgui.Col_.button_active,   0.129, 0.322, 0.541, 1.00)

    # 边框 / 分割线
    _set_col(style, imgui.Col_.border,              0.157, 0.169, 0.188, 1.00)
    _set_col(style, imgui.Col_.border_shadow,       0.000, 0.000, 0.000, 0.00)
    _set_col(style, imgui.Col_.separator,           0.157, 0.169, 0.188, 1.00)
    _set_col(style, imgui.Col_.separator_hovered,   0.192, 0.404, 0.643, 0.78)
    _set_col(style, imgui.Col_.separator_active,    0.192, 0.404, 0.643, 1.00)

    # 文字
    _set_col(style, imgui.Col_.text,             0.839, 0.855, 0.875, 1.00)
    _set_col(style, imgui.Col_.text_disabled,    0.447, 0.463, 0.490, 1.00)
    _set_col(style, imgui.Col_.text_selected_bg, 0.192, 0.404, 0.643, 0.35)

    # 滚动条
    _set_col(style, imgui.Col_.scrollbar_bg,            0.067, 0.075, 0.086, 1.00)
    _set_col(style, imgui.Col_.scrollbar_grab,          0.290, 0.302, 0.322, 1.00)
    _set_col(style, imgui.Col_.scrollbar_grab_hovered,  0.388, 0.400, 0.420, 1.00)
    _set_col(style, imgui.Col_.scrollbar_grab_active,   0.486, 0.498, 0.518, 1.00)

    # 选项卡 / Tab（部分枚举在当前 imgui_bundle 版本中不存在，已注释保留）
    _set_col(style, imgui.Col_.tab,          0.122, 0.133, 0.153, 1.00)
    _set_col(style, imgui.Col_.tab_hovered,  0.192, 0.404, 0.643, 0.80)

    # 停靠 / Docking
    _set_col(style, imgui.Col_.docking_preview,  0.192, 0.404, 0.643, 0.70)
    _set_col(style, imgui.Col_.docking_empty_bg, 0.067, 0.075, 0.086, 1.00)

    # ── 尺寸 / 圆角 ────────────────────────────────────────────
    style.frame_rounding     = 4.0
    style.child_rounding     = 4.0
    style.window_rounding    = 6.0
    style.popup_rounding     = 4.0
    style.scrollbar_rounding = 4.0
    style.grab_rounding      = 3.0
    style.tab_rounding       = 3.0

    # ── 间距 / 内边距 ──────────────────────────────────────────
    style.frame_padding      = (6.0, 3.0)
    style.window_padding     = (8.0, 8.0)
    style.item_spacing       = (6.0, 4.0)
    style.item_inner_spacing = (4.0, 4.0)
    style.indent_spacing     = 18.0

    # ── 边框粗细 ──────────────────────────────────────────────
    style.window_border_size = 1.0
    style.child_border_size  = 1.0
    style.popup_border_size  = 1.0
    style.frame_border_size  = 0.0
    style.tab_border_size    = 1.0

    # ── 其他 ───────────────────────────────────────────────────
    style.scrollbar_size     = 12.0
    style.grab_min_size      = 8.0
