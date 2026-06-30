"""Blender 风格深色主题 — 工业感 · 极简 · 橙色调"""

from imgui_bundle import imgui


# ============================================================
# Blender 调色板
# ============================================================
# 背景:      #1C1C1C  (0.110, 0.110, 0.110)  近黑
# 控件底:    #2D2D2D  (0.176, 0.176, 0.176)  炭灰
# 控件悬停:  #3A3A3A  (0.227, 0.227, 0.227)
# 控件激活:  #4A4A4A  (0.290, 0.290, 0.290)
# 强调橙:    #E06A27  (0.878, 0.416, 0.153)  Blender 标志色
# 文字:      #C0C0C0  (0.753, 0.753, 0.753)  暖灰白
# 文字禁用:  #666666  (0.400, 0.400, 0.400)
# 边框:      #3D3D3D  (0.239, 0.239, 0.239)
# ============================================================


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
# Blender 橙
# ============================================================

BLENDER_ORANGE      = (0.878, 0.416, 0.153)   # #E06A27
BLENDER_ORANGE_DIM  = (0.702, 0.333, 0.122)   # 80% 亮度，用于按下态
BLENDER_ORANGE_LOW  = (0.878, 0.416, 0.153)   # 保持同色，靠 alpha 控制透明度

# ── 语义色 ─────────────────────────────────────────────────
SUCCESS_GREEN   = (0.471, 0.714, 0.471)   # 运行/成功 按钮文字
WARNING_AMBER   = (0.788, 0.722, 0.471)   # 暂停/警告 按钮文字
ERROR_RED       = (0.788, 0.471, 0.471)   # 停止/错误 按钮文字

# ── 通用色调别名 ──────────────────────────────────────────────
TEXT_DISABLED   = (0.400, 0.400, 0.400)   # #666666

# ── Node Editor 节点配色 ──────────────────────────────────────
COLOR_EVENT     = (0.420, 0.650, 0.920)   # 淡蓝 — 事件节点
COLOR_FLOW      = (0.600, 0.600, 0.600)   # 灰色 — 流程节点
COLOR_EXEC_PIN  = (0.950, 0.950, 0.950)   # 白色 — 执行引脚
COLOR_DATA_PIN  = (0.600, 0.800, 1.000)   # 淡蓝 — 数据引脚

# ============================================================
# 主入口
# ============================================================

def apply_custom_style(
) -> None:
    """覆盖 imgui 默认样式，应用 Blender 风格深色主题"""
    style = imgui.get_style()

    # ── 基本颜色基调 ────────────────────────────────────────────
    _set_col(style, imgui.Col_.window_bg,        0.110, 0.110, 0.110, 1.00)   # #1C1C1C
    _set_col(style, imgui.Col_.child_bg,         0.110, 0.110, 0.110, 1.00)
    _set_col(style, imgui.Col_.popup_bg,         0.137, 0.137, 0.137, 1.00)   # #232323
    _set_col(style, imgui.Col_.frame_bg,         0.176, 0.176, 0.176, 1.00)   # #2D2D2D
    _set_col(style, imgui.Col_.frame_bg_hovered, 0.227, 0.227, 0.227, 1.00)   # #3A3A3A
    _set_col(style, imgui.Col_.frame_bg_active,  0.290, 0.290, 0.290, 1.00)   # #4A4A4A

    # 标题栏 — Blender 用深色标题，激活时橙色下划线式高亮
    _set_col(style, imgui.Col_.title_bg,              0.094, 0.094, 0.094, 1.00)   # #181818
    _set_col(style, imgui.Col_.title_bg_active,       0.137, 0.137, 0.137, 1.00)   # #232323
    _set_col(style, imgui.Col_.title_bg_collapsed,    0.094, 0.094, 0.094, 1.00)

    # 菜单栏 — 略亮于窗口背景
    _set_col(style, imgui.Col_.menu_bar_bg, 0.137, 0.137, 0.137, 1.00)

    # 选中 / 高亮 — Blender 橙
    _set_col(style, imgui.Col_.header,          0.878, 0.416, 0.153, 0.55)
    _set_col(style, imgui.Col_.header_hovered,  0.878, 0.416, 0.153, 0.70)
    _set_col(style, imgui.Col_.header_active,   0.878, 0.416, 0.153, 0.85)

    # 按钮 — 扁平炭灰，不抢眼
    _set_col(style, imgui.Col_.button,          0.176, 0.176, 0.176, 0.80)
    _set_col(style, imgui.Col_.button_hovered,  0.227, 0.227, 0.227, 1.00)
    _set_col(style, imgui.Col_.button_active,   0.290, 0.290, 0.290, 1.00)

    # 边框 / 分割线 — 细且低调
    _set_col(style, imgui.Col_.border,              0.239, 0.239, 0.239, 1.00)
    _set_col(style, imgui.Col_.border_shadow,       0.000, 0.000, 0.000, 0.00)
    _set_col(style, imgui.Col_.separator,           0.239, 0.239, 0.239, 1.00)
    _set_col(style, imgui.Col_.separator_hovered,   0.878, 0.416, 0.153, 0.55)
    _set_col(style, imgui.Col_.separator_active,    0.878, 0.416, 0.153, 0.80)

    # 文字 — 暖灰白，接近 Blender 默认文字色
    _set_col(style, imgui.Col_.text,             0.753, 0.753, 0.753, 1.00)   # #C0C0C0
    _set_col(style, imgui.Col_.text_disabled,    0.400, 0.400, 0.400, 1.00)   # #666666
    _set_col(style, imgui.Col_.text_selected_bg, 0.878, 0.416, 0.153, 0.30)

    # 滚动条 — 细窄，深色底 + 中灰滑块
    _set_col(style, imgui.Col_.scrollbar_bg,            0.094, 0.094, 0.094, 0.60)
    _set_col(style, imgui.Col_.scrollbar_grab,          0.290, 0.290, 0.290, 1.00)
    _set_col(style, imgui.Col_.scrollbar_grab_hovered,  0.388, 0.388, 0.388, 1.00)
    _set_col(style, imgui.Col_.scrollbar_grab_active,   0.486, 0.486, 0.486, 1.00)

    # 选项卡 — 无圆角扁平风格
    _set_col(style, imgui.Col_.tab,          0.110, 0.110, 0.110, 1.00)
    _set_col(style, imgui.Col_.tab_hovered,  0.176, 0.176, 0.176, 1.00)
    # 以下枚举在较旧版本 imgui_bundle 中可能不存在，静默跳过
    for _col, _val in [
        ("tab_active",          (0.878, 0.416, 0.153, 0.35)),
        ("tab_unfocused",       (0.110, 0.110, 0.110, 1.00)),
        ("tab_unfocused_active",(0.878, 0.416, 0.153, 0.20)),
    ]:
        try:
            _set_col(style, getattr(imgui.Col_, _col), *_val)
        except AttributeError:
            pass

    # 停靠 / Docking — 橙色预览
    _set_col(style, imgui.Col_.docking_preview,  0.878, 0.416, 0.153, 0.50)
    _set_col(style, imgui.Col_.docking_empty_bg, 0.000, 0.000, 0.000, 0.00)

    # 尺寸调整手柄 / 滑条 / 勾选框（旧版 imgui_bundle 可能没有这些枚举）
    for _col, _val in [
        ("resize_grip",         (0.176, 0.176, 0.176, 0.00)),
        ("resize_grip_hovered", (0.878, 0.416, 0.153, 0.55)),
        ("resize_grip_active",  (0.878, 0.416, 0.153, 0.80)),
        ("slider_grab",         (0.878, 0.416, 0.153, 0.80)),
        ("slider_grab_active",  (0.878, 0.416, 0.153, 1.00)),
        ("check_mark",          (0.878, 0.416, 0.153, 1.00)),
    ]:
        try:
            _set_col(style, getattr(imgui.Col_, _col), *_val)
        except AttributeError:
            pass

    # ── 尺寸 / 圆角 — Blender 极简，几乎无圆角 ──────────────────
    style.frame_rounding     = 2.0
    style.child_rounding     = 2.0
    style.window_rounding    = 2.0
    style.popup_rounding     = 2.0
    style.scrollbar_rounding = 2.0
    style.grab_rounding      = 2.0
    style.tab_rounding       = 2.0

    # ── 间距 / 内边距 — 紧凑工业风 ──────────────────────────────
    style.frame_padding      = (6.0, 3.0)
    style.window_padding     = (6.0, 6.0)
    style.item_spacing       = (6.0, 4.0)
    style.item_inner_spacing = (4.0, 4.0)
    style.indent_spacing     = 16.0

    # ── 边框粗细 — Blender 几乎无可见边框 ────────────────────────
    style.window_border_size = 0.0
    style.child_border_size  = 0.0
    style.popup_border_size  = 1.0
    style.frame_border_size  = 0.0
    style.tab_border_size    = 0.0

    # ── 其他 ───────────────────────────────────────────────────
    style.scrollbar_size     = 10.0
    style.grab_min_size      = 6.0
