"""生成 `dev/imgui_api.md` —— 编辑器面板控件目录（imgui-bundle，按用途归类）。

为什么要有这个生成器
--------------------
编辑器面板（含扩展贡献的面板）都直接写 `imgui.*`。以前唯一能查的是 ImGui 上游文档：
英文、按字母排、按 C++ 概念组织，而且不告诉我们自己的约定（`##` 作用域、返回 tuple、
`push_item_width` 配对）。结果是每写一个面板都要重新踩一遍同样的坑。

本生成器把「函数 → 用途」的策展写死在这张表里，把「函数 → 签名」交给运行时：
`imgui_bundle` 每个函数的 `__doc__` 首行就是完整 Python 签名（含类型与默认值），
所以升级依赖时差异会变成一次可审的 diff，而不是悄悄过时。

产物（唯一权威）::

    FlyVibing-User-And-Developer-Utils/
      packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/imgui_api.md

读取方式（CLI 按节取，省上下文）::

    engine-editor-cli doc outline dev/imgui_api
    engine-editor-cli doc show dev/imgui_api#表格
    engine-editor-cli doc search 表格

用法::

    python Utils/Dev/imgui_docgen.py            # 写文件
    python Utils/Dev/imgui_docgen.py --check    # 只比对（CI / 测试用）
    python Utils/Dev/imgui_docgen.py --stats    # 覆盖率统计

纪律（与 `print_inventory.md` / `test_nodes.md` 同一套）
  - 生成的 md **不要手改**；改这里的分组表，再重新生成；
  - `Test/Application/Editor/test_imgui_api_doc.py` 守卫三件事：
    产物新鲜、分组名真实存在、**引擎里用到的每个 imgui 函数都被归类**（否则报未归类）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

# ════════════════════════════════════════════════════════════════════
# 分组表（唯一的策展成本 —— 加函数就在这里加一行）
#   每个条目 = (函数名, 一句话用途/坑)。顺序即文档顺序。
# ════════════════════════════════════════════════════════════════════

GROUPS: list[dict] = [
    {
        "title": "文本、分隔与进度",
        "intro": "面板里出现最多的一类。全部按「当前行」往后排，需要并排时用 `same_line()`（见 §6）。",
        "items": [
            ("text", "静态文本。`fmt` 支持 printf 风格（`text(f\"{n} 项\")` 更直观）。"),
            ("text_wrapped", "自动折行的文本。面板说明文字用它，**不要自己算宽度**。"),
            ("text_colored", "带色文本。第一个参数是 `ImVec4`，主题色用 `get_style_color_vec4(Col_.text)`，不要手写字面量。"),
            ("text_disabled", "灰字/次要信息（快捷键提示、占位说明、引擎驱动值）。**不表示控件禁用**。"),
            ("bullet_text", "带项目符号的一行；适合列表说明。"),
            ("separator", "水平分隔线；分组之间用一条即可，不要连续两条。"),
            ("spacing", "竖直留白（等于一个 ItemSpacing）。比 `dummy` 语义更明确。"),
            ("new_line", "强制换行（`same_line` 的撤销）。"),
            ("align_text_to_frame_padding", "让文本基线与右侧输入框对齐；混排 label + 控件时少一行 `same_line`。"),
            ("calc_text_size", "量文本尺寸（`(w, h)`），用于自己算列宽或裁剪；结果受当前字体影响。"),
            ("progress_bar", "只读进度条；传 0.0–1.0。没有对应的「可拖」版本——要拖用 slider。"),
        ],
    },
    {
        "title": "按钮、勾选与选择",
        "intro": "所有「点一下」的入口。注意 **返回值的形状不统一**：`button` 返回 `bool`，"
                 "`checkbox`/`selectable` 返回 `(changed, value)`。",
        "items": [
            ("button", "普通按钮，返回是否按下。需要定宽时传 `size=(w, 0)`。"),
            ("small_button", "小号按钮，常用于行尾的 ✕ / ⚙ 图标。"),
            ("invisible_button", "不可见但可交互的区域；自绘图表命中检测用。"),
            ("checkbox", "复选框，返回 `(changed, v)`。**必须解包成两个变量**，否则永远为真。"),
            ("radio_button", "单选按钮，`(label, active)`；同组自己保证互斥（写 id 后缀或用 `push_id`）。"),
            ("selectable", "列表行/下拉项。返回 `(pressed, selected)` —— 仓库里几乎都写 `[0]`。"),
            ("combo", "一次性下拉（常数选项）。最短写法：`combo(label, idx, items)` 返回 `(changed, idx)`。"),
            ("begin_combo", "可定制下拉的开始（里面自己画 `selectable`）；必须 `end_combo()`。"),
            ("end_combo", "结束下拉。**必须在 `if begin_combo(...)` 外面调用**——否则没展开时栈就撕了。"),
            ("begin_list_box", "带边框的滚动列表容器（比 combo 更适合长列表/多选）。"),
            ("end_list_box", "结束列表容器。"),
        ],
    },
    {
        "title": "数值与文本输入",
        "intro": "全部返回 `(changed, value)`。**不要原地改传进去的值**——把返回值写回你自己的状态。",
        "items": [
            ("input_float", "精确输入框（可打字）。适合需要精确值的参数。"),
            ("input_int", "整数输入框。"),
            ("drag_float", "拖动滑杆。第 4/5 参数是 min/max：**传 0,0 表示不限制**（引擎里常这样用）。"),
            ("drag_float2", "二维拖动（xy）。"),
            ("drag_float3", "三维拖动（位置/缩放/颜色 RGB）。"),
            ("drag_float4", "四维拖动（颜色 RGBA 的兜底方案）。"),
            ("drag_int", "整数拖动；同样 `min=max=0` 表示不限制。"),
            ("input_text", "单行文本。`flags=InputTextFlags_.enter_returns_true` 可当「回车提交」。"),
            ("input_text_multiline", "多行文本；`size` 给宽高。"),
            ("input_text_with_hint", "带占位提示的文本框；空值时显示 hint。"),
            ("color_edit4", "颜色选择器，返回 `(changed, [r,g,b,a])`。想要 HSV 界面传 `ColorEditFlags_.display_hsv`。"),
        ],
    },
    {
        "title": "布局：宽度、间距与光标",
        "intro": "ImGui 是**立即模式 + 单行流**：控件默认占满可用宽度，并排全靠 `same_line`，"
                 "宽度全靠 `push_item_width` / `set_next_item_width`。",
        "items": [
            ("same_line", "把下一个控件接到当前行右侧（可给间距）。仓库里用得最多的布局函数。"),
            ("dummy", "占位盒（`dummy((w, h))`）。撑宽/撑高、占位对齐都靠它。"),
            ("push_item_width", "本段控件统一宽度。**必须和 `pop_item_width` 成对**。"),
            ("pop_item_width", "结束统一宽度。"),
            ("set_next_item_width", "只影响下一个控件宽度（比 push/pop 轻，适合单个例外）。"),
            ("get_content_region_avail", "当前可用区域 `(w, h)`；画满宽表格/子窗口前先问它。"),
            ("get_cursor_pos_x", "光标 x（窗口局部坐标）。"),
            ("get_cursor_pos_y", "光标 y（窗口局部坐标）。"),
            ("set_cursor_pos_x", "跳到指定 x（局部坐标）。"),
            ("set_cursor_pos_y", "跳到指定 y（局部坐标）——自己排版时用它换行。"),
            ("get_cursor_screen_pos", "光标屏幕坐标（绝对）；自绘/命中检测用。"),
            ("set_cursor_screen_pos", "跳到屏幕绝对坐标（画浮层时用）。"),
            ("get_item_rect_min", "上一个控件左上角屏幕坐标；画包围框/锚点用。"),
            ("get_item_rect_max", "上一个控件右下角屏幕坐标。"),
            ("get_text_line_height", "一行文本的高度（做垂直居中的常量）。"),
            ("get_frame_height", "一个输入框/按钮的标准高度。"),
        ],
    },
    {
        "title": "容器：子窗口 / 标签页 / 折叠树",
        "intro": "容器类全部是 `begin_*` + `end_*`。**规则：`end_*` 一定在 `if` 外面**，"
                 "并且不要在 begin 和 end 之间 `return`。",
        "items": [
            ("begin_child", "可滚动的子区域：日志、长列表、固定高度的波形槽。第一个参数是 id（可 `##`）。"),
            ("end_child", "结束子区域。"),
            ("begin_tab_bar", "标签栏开始；里面放 `begin_tab_item`。"),
            ("end_tab_bar", "结束标签栏。"),
            ("begin_tab_item", "单个标签页，返回 `(visible, p_open)`；**内容只在 visible 时画**。"),
            ("end_tab_item", "结束标签页（在 if 外面调）。"),
            ("collapsing_header", "可折叠分组标题（比 tree_node 更像「小节」）。"),
            ("tree_node", "树节点 / 折叠块，返回是否展开；`##` 控制 id。"),
            ("tree_node_ex", "带 flags 的树节点；常用 `default_open`、`open_on_arrow`、`leaf`、`span_avail_width`。"),
            ("tree_pop", "结束 tree/collapsing 层级（在 if 外面调）。"),
            ("set_next_item_open", "强制下一个树节点展开/收起（默认展开、搜索命中自动展开）。"),
            ("push_id", "压入 id 作用域：让内部同名控件互不冲突（循环里画同类控件时必备）。"),
            ("pop_id", "结束 id 作用域。"),
            ("get_id", "字符串 → id（自绘/手动匹配时用）。"),
        ],
    },
    {
        "title": "表格",
        "intro": "设备列表、参数矩阵、trial 表都用它。三步：`begin_table` → `table_setup_column` × N → "
                 "循环里 `table_next_row` / `table_next_column` → `end_table`。",
        "items": [
            ("begin_table", "开始表格，返回是否可见（不可见时也要走完 setup + end_table）。"),
            ("table_setup_column", "声明一列：`label` 是表头文本，`init_width_or_weight` 在 stretch 模式下是权重。"),
            ("table_headers_row", "画出表头行（调用一次，在 setup 之后）。"),
            ("table_next_row", "换行；表头之后第一次调用会跳过表头行。"),
            ("table_next_column", "换到下一列，返回是否还有列（超出会返回 False）。"),
            ("table_set_column_index", "直接跳到第 n 列（画不规则行时用）。"),
            ("table_setup_scroll_freeze", "冻结前 N 列 / 前 N 行（长表格固定表头）。"),
            ("end_table", "结束表格（无论如何都要调到）。"),
        ],
    },
    {
        "title": "弹窗、菜单与提示",
        "intro": "三类东西容易混：**popup**（点出来的浮层）、**modal**（挡住整个编辑器的对话框）、"
                 "**tooltip**（悬停提示）。它们的 begin/end 规则都一样：`end` 在 `if` 外面。",
        "items": [
            ("open_popup", "打开一个 popup（配合 `begin_popup` 使用）。"),
            ("begin_popup", "popup 开始，返回是否打开；必须 `end_popup()`。"),
            ("end_popup", "结束 popup。"),
            ("close_current_popup", "关闭当前 popup（选中一项后调）。"),
            ("begin_popup_modal", "模态对话框，返回 `(open, p_open)`；必须 `end_popup()`。"),
            ("begin_popup_context_item", "右键菜单（针对上一个控件）。"),
            ("begin_popup_context_window", "右键菜单（针对窗口空白处）。"),
            ("begin_menu", "下拉菜单项的开始（放在菜单栏里）；返回是否展开。"),
            ("end_menu", "结束菜单。"),
            ("menu_item", "菜单行，返回 `(pressed, selected)`；`shortcut` 只作展示，不会真的绑键。"),
            ("begin_main_menu_bar", "窗口顶部菜单栏（宿主已有一层，扩展一般不用自己开）。"),
            ("end_main_menu_bar", "结束菜单栏。"),
            ("set_tooltip", "悬停提示（在 `is_item_hovered()` 分支里调，不要每帧无脑调）。"),
            ("begin_tooltip", "自定义 tooltip 内容的开始。"),
            ("end_tooltip", "结束 tooltip。"),
            ("begin_item_tooltip", "给上一个控件挂 tooltip 的简写（里面画内容，`end_tooltip` 收尾）。"),
            ("set_item_tooltip", "给上一个控件设纯文本 tooltip（最省事）。"),
            ("set_next_window_focus", "让下一个窗口/弹窗获得焦点（弹出确认框时用）。"),
        ],
    },
    {
        "title": "交互状态（点击 / 悬停 / 焦点）",
        "intro": "都是查「上一个控件」的状态。**必须在画完控件之后、下一个控件之前**调用。",
        "items": [
            ("is_item_hovered", "上一个控件是否被悬停（tooltip、右键菜单的入口）。"),
            ("is_item_clicked", "上一个控件是否被点击（可指定鼠标键）。"),
            ("is_item_active", "上一个控件是否处于激活态（按住/正在编辑）。"),
            ("is_item_focused", "上一个控件是否有键盘焦点。"),
            ("is_item_deactivated_after_edit", "输入类控件「编辑完成」的瞬间——提交值的好时机。"),
            ("set_item_default_focus", "让下一个控件默认获得焦点（combo/输入框弹出的首选行）。"),
            ("set_keyboard_focus_here", "把键盘焦点给下一个控件（打开面板后直接可打字）。"),
        ],
    },
    {
        "title": "禁用态（包住任意控件）",
        "intro": "「现在不能点」的标准写法：把控件包在 `begin_disabled(True)` / `end_disabled()` 之间。"
                 "**`end_disabled()` 必须在 `if` 外面**；`begin_disabled(False)` 也会压栈，"
                 "所以不要用条件去跳过 begin。",
        "items": [
            ("begin_disabled", "开始禁用区（可传 False 作为「条件禁用」的写法，仍然要配对 end）。"),
            ("end_disabled", "结束禁用区。**无条件调用**，否则后续所有控件都会被连带禁用。"),
        ],
    },
    {
        "title": "拖放",
        "intro": "源 + 目标成对使用；载荷类型用字符串区分（`\"ENTITY\"` / `\"ASSET\"`）。",
        "items": [
            ("begin_drag_drop_source", "拖放源开始，返回是否在拖。"),
            ("end_drag_drop_source", "结束源（在 if 外面）。"),
            ("set_drag_drop_payload_py_id", "写入载荷（`py_id` 变体传整数 id，是 pybind 的安全版）。"),
            ("begin_drag_drop_target", "拖放目标开始，返回是否有东西悬在上面。"),
            ("end_drag_drop_target", "结束目标（在 if 外面）。"),
            ("accept_drag_drop_payload_py_id", "接受并取回载荷整数 id。"),
        ],
    },
    {
        "title": "样式与颜色（含自绘）",
        "intro": "颜色有两套表示：**`Col_` 索引 + u32**（`push_style_color` / `get_color_u32`）和 "
                 "**`ImVec4`**（`text_colored` / `get_style_color_vec4`）。传错类型是静默错色。",
        "items": [
            ("push_style_color", "临时改颜色（`push_style_color(Col_.button, get_color_u32(Col_.button_hovered))`）。"),
            ("pop_style_color", "恢复颜色；**参数是压入的层数**，默认 1。"),
            ("push_style_var", "临时改尺寸/间距（`StyleVar_.item_spacing` 等），值传 float。"),
            ("pop_style_var", "恢复；同样按层数弹。"),
            ("get_style", "拿全局 Style（读 `item_spacing`、`frame_padding` 等实际值）。"),
            ("get_color_u32", "`Col_` → u32 颜色（给 `push_style_color` 用，可带 alpha 乘子）。"),
            ("get_style_color_vec4", "`Col_` → `ImVec4`（给 `text_colored` 用）。"),
            ("get_window_draw_list", "当前窗口的 DrawList，自绘波形/连线/高亮的入口（不走控件布局）。"),
            ("push_text_wrap_pos", "临时设定折行宽度（配合 `text_wrapped`）。"),
            ("pop_text_wrap_pos", "恢复折行宽度。"),
        ],
    },
    {
        "title": "键盘鼠标原始输入",
        "intro": "面板里**优先用控件返回值**；只有在自绘/拖拽/快捷键时才直接查输入。",
        "items": [
            ("is_mouse_down", "鼠标键是否按住（0=左 1=右 2=中）。"),
            ("is_mouse_clicked", "本帧是否按下。"),
            ("is_mouse_double_clicked", "本帧是否双击。"),
            ("is_mouse_released", "本帧是否松开。"),
            ("is_key_down", "键是否按住（`imgui.Key.space` 等）。"),
            ("is_key_pressed", "本帧是否按下（可关掉 repeat）。"),
            ("get_mouse_pos", "鼠标位置（窗口坐标）。"),
            ("get_io", "IO 单例：`io.want_capture_mouse` / `want_text_input` 判「该不该响应」。"),
        ],
    },
    {
        "title": "窗口级接口（宿主负责，只在必要时用）",
        "intro": "扩展的 `draw_fn` 跑在宿主已经开好的窗口里，**不要再 `begin`/`end`**。"
                 "下面这些只在做弹窗、定位浮层时例外。",
        "items": [
            ("begin", "开窗口。**扩展禁用**：宿主 `BasePanel` 已经开好了。"),
            ("end", "关窗口。**扩展禁用**，理由同上。"),
            ("get_window_pos", "当前窗口左上角（屏幕坐标）。"),
            ("get_window_size", "当前窗口尺寸。"),
            ("set_next_window_pos", "设定下一个窗口/弹窗位置（`cond=ImGuiCond_.appearing` 只首次生效）。"),
            ("set_next_window_size", "设定下一个窗口/弹窗尺寸。"),
            ("set_window_size", "改当前窗口尺寸。"),
            ("get_main_viewport", "主视口（多显示器/DPI 时算绝对坐标）。"),
            ("set_mouse_cursor", "改鼠标指针形状（拖拽/缩放时反馈）。"),
            ("set_clipboard_text", "写系统剪贴板（「复制路径」这类操作）。"),
            ("push_font", "临时换字号：`push_font(font, size)`（1.92 起没有 `set_window_font_scale`）。"),
            ("pop_font", "恢复字号，与 `push_font` 成对。"),
        ],
    },
    {
        "title": "宿主侧 / 禁止调用",
        "intro": "这些是**引擎渲染管线**在用（`EditorImguiLayer` 等）。扩展或普通面板调用会破坏帧循环，"
                 "或者干脆崩。列在这里是为了「搜到也知道不能用」。",
        "items": [
            ("create_context", "建 ImGui 上下文。**禁止**：宿主已建；测试用 `flyvibing_extension_kit.imgui_headless`。"),
            ("destroy_context", "销毁上下文。**禁止**，同上。"),
            ("get_current_context", "取当前上下文。**禁止**，除非在写宿主层。"),
            ("new_frame", "开新帧。**禁止**：帧由 `EditorImguiLayer` 驱动。"),
            ("end_frame", "结束帧。**禁止**。"),
            ("render", "提交绘制数据。**禁止**。"),
            ("get_draw_data", "取绘制数据。**禁止**。"),
            ("dock_space", "建 DockSpace。**禁止**：停靠由宿主统一管理。"),
            ("set_next_window_dock_id", "指定停靠目标。**禁止**：同上。"),
        ],
    },
]

# ════════════════════════════════════════════════════════════════════
# flag 速查（成员名 → 值在生成时从运行时读取，不会和库版本漂移）
# ════════════════════════════════════════════════════════════════════

FLAGS: list[dict] = [
    {
        "enum": "TableFlags_",
        "intro": "表格的形态全靠它。**最常用的一行**："
                 "`row_bg | borders_inner_h | sizing_stretch_prop`。",
        "members": [
            ("row_bg", "隔行底色（长表格必开，扫行不串）"),
            ("borders_inner_h", "行间横线"),
            ("borders_outer_h", "外框横线"),
            ("resizable", "列宽可拖"),
            ("sizing_stretch_prop", "按 `init_width_or_weight` 比例分配宽度（自适应首选）"),
            ("no_saved_settings", "不把列宽写进 imgui.ini（临时表格用）"),
            ("scroll_y", "竖向滚动"),
            ("context_menu_in_body", "右键菜单覆盖整个表体"),
        ],
    },
    {
        "enum": "WindowFlags_",
        "intro": "主要影响**弹出的小窗口**；主面板窗口的 flag 由宿主决定。",
        "members": [
            ("no_title_bar", "无标题栏（自绘标题/浮层）"),
            ("no_resize", "禁止改大小（固定尺寸对话框）"),
            ("always_auto_resize", "尺寸随内容变化（小提示框）"),
            ("no_saved_settings", "不记忆位置尺寸"),
            ("no_collapse", "禁止折叠成标题条"),
            ("menu_bar", "窗口带菜单栏（要在里面 `begin_menu_bar`）"),
            ("horizontal_scrollbar", "允许横向滚动（宽表格）"),
        ],
    },
    {
        "enum": "InputTextFlags_",
        "intro": "文本框行为。回车提交、只读、数字字符集最常用。",
        "members": [
            ("enter_returns_true", "回车时返回 changed（「输入即提交」）"),
            ("auto_select_all", "获得焦点时全选（改名场景）"),
            ("chars_decimal", "只允许数字字符"),
            ("read_only", "只读但可选中复制"),
            ("allow_tab_input", "Tab 当输入而不是切焦点"),
        ],
    },
    {
        "enum": "TreeNodeFlags_",
        "intro": "树节点/折叠块的行为。",
        "members": [
            ("default_open", "默认展开"),
            ("open_on_arrow", "只有点箭头才展开（点文字做别的操作用）"),
            ("open_on_double_click", "双击展开"),
            ("span_avail_width", "占满可用宽度（点击区域更大，行选中的常见做法）"),
            ("leaf", "标记叶子节点（不画展开箭头）"),
            ("framed", "带背景框"),
        ],
    },
    {
        "enum": "SelectableFlags_",
        "intro": "列表行的行为。",
        "members": [
            ("allow_double_click", "允许双击"),
            ("span_all_columns", "跨满表格行（表格里做整行选中必备）"),
            ("allow_overlap", "允许与其它控件重叠"),
            ("disabled", "禁用态"),
        ],
    },
    {
        "enum": "ComboFlags_",
        "intro": "下拉框尺寸档位。",
        "members": [
            ("height_small", "小号（约 4 项高）"),
            ("height_regular", "标准"),
            ("height_large", "大号（长列表）"),
        ],
    },
    {
        "enum": "HoveredFlags_",
        "intro": "`is_item_hovered` 的补充条件。",
        "members": [
            ("allow_when_disabled", "禁用态也算悬停（做「为什么不能点」提示时用）"),
            ("delay_normal", "短暂延迟后才算悬停（防 tooltip 闪烁）"),
            ("child_windows", "连子窗口一起算"),
        ],
    },
    {
        "enum": "Col_",
        "intro": "主题色索引。**不要手写 ColorEdit 字面量**，从主题取（换主题才跟着变）。",
        "members": [
            ("text", "正文"),
            ("text_disabled", "次要/禁用文本"),
            ("button", "按钮底色"),
            ("button_hovered", "按钮悬停"),
            ("button_active", "按钮按下"),
            ("frame_bg", "输入框底色"),
            ("frame_bg_hovered", "输入框悬停底色"),
            ("popup_bg", "弹层底色"),
            ("child_bg", "子窗口底色"),
            ("table_header_bg", "表头底色"),
            ("check_mark", "勾选标记"),
            ("text_selected_bg", "选中文本底色"),
            ("separator", "分隔线"),
            ("border", "边框"),
        ],
    },
    {
        "enum": "StyleVar_",
        "intro": "间距/圆角等尺寸变量。传值给 `push_style_var` 时**标量 float**（不要 ImVec2）。",
        "members": [
            ("item_spacing", "控件间距（最常见的「太挤了」调整项）"),
            ("item_inner_spacing", "控件内部间距"),
            ("frame_padding", "输入框内边距"),
            ("window_padding", "窗口内边距"),
            ("cell_padding", "表格单元内边距（行高）"),
            ("indent_spacing", "缩进宽度"),
        ],
    },
]

# ════════════════════════════════════════════════════════════════════
# 渲染
# ════════════════════════════════════════════════════════════════════

_HEADER = """# imgui_api.md — 编辑器面板控件目录（imgui-bundle）

> 为写编辑器面板的人（引擎内部 + 扩展作者）准备：按「我要做什么」归类 imgui-bundle 的接口 ——
> 每个按钮/表格/弹窗该调哪个函数、返回什么、有哪些坑；附录给全量索引。
> **本页由 `Utils/Dev/imgui_docgen.py` 生成，勿手改**；签名来自已安装的 `imgui_bundle`，
> 所以升级依赖后重新生成即可看到真实差异。

读法（CLI 按节取，省上下文）：

```powershell
engine-editor-cli doc outline dev/imgui_api              # 章节索引
engine-editor-cli doc show dev/imgui_api#表格            # 单节正文
engine-editor-cli doc search 折叠                        # 跨主题检索
```

配套（扩展作者从这两篇入门，再回这里查控件）：

- `extdev/ui_development.md` —— 面板怎么挂到编辑器（`ctx.ui.register_window`、窗口契约、隔离）
- `extdev/ui_recipes.md` —— 常见面板配方（参数行 / 表格 / 日志 / 波形 / 确认框）
- `dev/ui_protocol.md` —— 引擎内部 UI 层协议（线程、绘制 pass、主题）

---

## 1. 动手前必须知道的约定

下面三条是绝大多数面板 bug 的来源；先记住它们，再去查具体控件。

| 规则 | 说明 |
|---|---|
| **`##` 是 id 作用域** | `"保存##save"` 只显示「保存」，`save` 参与唯一性。循环里画同名控件必须加 `##` 后缀或 `push_id`。 |
| **返回值形状不统一** | `button()` 返回 `bool`；`checkbox/selectable/input_*/drag_*/combo` 返回 `(changed, value)`。**必须解包**，否则 `if imgui.checkbox(...)` 恒为真。 |
| **`begin_*` / `end_*` 与 `push_*` / `pop_*` 必须配对** | 且 `end/pop` 写在 `if` 外面。begin 之后 early `return` 会撕裂栈，下一帧直接崩或整块 UI 错位。 |

其余高频约定：

1. **宽度**：`push_item_width(w)` + `pop_item_width()` 管一段，`set_next_item_width(w)` 只管下一个。
2. **并排**：`same_line()` 接右边的控件；换行用 `new_line()` / `spacing()`。
3. **颜色两套类型**：给 `text_colored` 传 `ImVec4`（用 `get_style_color_vec4`）；
   给 `push_style_color` 传 u32（用 `get_color_u32`）。传错不报错，只是颜色不对。
4. **不要在 `draw_fn` 里开窗口/建 context** —— 宿主已经开好了；见 §16。
5. **导入只有一种写法**：`from imgui_bundle import imgui`（枚举用 `imgui.TableFlags_.xxx`），
   `ImVec2/ImVec4` 从 `imgui_bundle` 顶层拿。
   **`from imgui_bundle.imgui import ImVec2 / TableFlags_` 会 `ImportError`** —— 那个模块不支持 from-import。
6. **异常会被隔离**：绘制抛异常 → 本帧跳过；连续多帧 → 窗口自动隐藏（`ExtensionPanel` 的保险丝）。

---
"""

_MAINTENANCE = """{heading}

| 事 | 怎么做 |
|---|---|
| 重新生成 | `python Utils/Dev/imgui_docgen.py`（写到工具仓 `docs_content/dev/imgui_api.md`，路径由已安装的 `engine_editor_mcp` 包定位） |
| 只校验 | `python Utils/Dev/imgui_docgen.py --check`（与磁盘比对，不写文件） |
| 看覆盖率 | `python Utils/Dev/imgui_docgen.py --stats`（分类数 / 未归类 / 引擎未使用） |
| 升级 imgui_bundle 后 | 重新生成 → 看 diff：新函数落进「附录」，确认值得收编就加进上面的分组表 |
| CI 守卫 | `Test/Application/Editor/test_imgui_api_doc.py` |

守的是三件事：

1. **产物新鲜** —— 磁盘内容 == 现渲染内容（依赖版本变了会红）。
2. **分组名真实** —— 分组表里写的函数必须在当前 `imgui_bundle` 里存在（拼错/被删会红）。
3. **引擎用到的都被归类** —— 仓库里任何地方调过 `imgui.<name>`，而 `<name>` 不在分组表里 → 报未归类。
   加新控件用法的人会被这条提醒「去补一行文档」，而不是默默多出一个没人知道的接口。
"""


def _imgui():
    from imgui_bundle import imgui  # 延迟导入：--help 也要能跑
    return imgui


def _short(text: str) -> str:
    """缩短 pybind 里冗长的类型路径，便于一行内阅读。"""
    for prefix in ("imgui_bundle._imgui_bundle.imgui.", "imgui_bundle.imgui.",
                   "collections.abc.", "imgui_bundle._imgui_bundle."):
        text = text.replace(prefix, "")
    return text


def _is_routine(obj) -> bool:
    """真正的函数/方法。**枚举类与结构体不算**。

    注意：imgui_bundle 1.92 底层是 **nanobind**（`nanobind.nb_func`），
    `inspect.isroutine()` / `isbuiltin()` 都返回 False —— 只能用「可调用且不是类型」判定。
    """
    return callable(obj) and not isinstance(obj, type)


def signature(name: str) -> str:
    """函数签名（取自运行时 `__doc__` 首行）；拿不到就退回 `name(...)`。

    pybind 的 `__doc__` 首行是签名；但枚举/类型对象的 `__doc__` 是散文
    （"Flags for ..."），所以要校验「`(` 之前只有名字」。
    """
    fn = getattr(_imgui(), name, None)
    if fn is None:
        return f"{name}(...)"
    doc = (getattr(fn, "__doc__", "") or "").strip().split("\n")[0].strip()
    head = doc.split("(", 1)[0].strip()
    if "(" not in doc or head != name:
        return f"{name}(...)"
    return _short(doc)


def grouped_names() -> dict[str, str]:
    """函数名 → 所属分组标题（用于覆盖率守卫与去重）。"""
    out: dict[str, str] = {}
    for group in GROUPS:
        for name, _note in group["items"]:
            out.setdefault(name, group["title"])
    return out


def duplicates() -> list[str]:
    """被多个分组重复收录的函数（渲染时只保留第一次出现）。"""
    seen: Counter = Counter()
    for group in GROUPS:
        for name, _note in group["items"]:
            seen[name] += 1
    return sorted(n for n, k in seen.items() if k > 1)


def unknown_group_names() -> list[str]:
    """分组表里写了、但当前 imgui_bundle 里不存在的函数。"""
    imgui = _imgui()
    return sorted(n for n in grouped_names() if not hasattr(imgui, n))


def usage_counts() -> Counter:
    """仓库内 `imgui.<name>` 调用频次（引擎 + 示例 + 扩展工具包）。

    扩展工具包按**包名**定位（`flyvibing_extension_kit`），不写开发链接目录的硬路径 ——
    `Test/Application/Editor/test_utils_layout.py` 禁止源码里出现那个路径字面量。
    """
    pat = re.compile(r"\bimgui\.([a-z][a-z0-9_]*)\b")
    root = _repo_root()
    roots = [os.path.join(root, "Application"), os.path.join(root, "Examples")]
    try:
        import flyvibing_extension_kit
        roots.append(os.path.dirname(os.path.abspath(flyvibing_extension_kit.__file__)))
    except Exception:
        pass                     # 工具仓不可用时只扫引擎仓
    counter: Counter = Counter()
    for start in roots:
        if not os.path.isdir(start):
            continue
        for dirpath, dirnames, files in os.walk(start):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "dist", "build")]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                try:
                    text = open(os.path.join(dirpath, fname), encoding="utf-8",
                                errors="ignore").read()
                except OSError:
                    continue
                counter.update(pat.findall(text))
    return counter


def unclassified_used() -> list[str]:
    """引擎里用过、但没进分组表的函数 —— 守卫 #3 的报告对象。

    只统计**真实函数**：`imgui.backends` / `imgui.internal` 这类模块属性、
    以及文档字符串里出现的 `imgui.xxx` 不算（它们无法被归类，也不该被归类）。
    """
    imgui = _imgui()
    grouped = grouped_names()
    return sorted(n for n in usage_counts()
                  if n not in grouped and callable(getattr(imgui, n, None)))


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = here
    while root and not os.path.exists(os.path.join(root, "startup.bat")):
        parent = os.path.dirname(root)
        if parent == root:
            return here
        root = parent
    return root or here


def default_out_path() -> str | None:
    """产物路径 —— 按**已安装的** `engine_editor_mcp` 包定位（工具仓不可用时返回 None）。

    不写开发链接目录的硬路径：包本身就在工具仓里（`engine-editor-cli` 依赖它），
    这样源码里也没有被 `test_utils_layout` 禁止的字面量。
    """
    try:
        import engine_editor_mcp
    except Exception:
        return None
    base = os.path.dirname(os.path.abspath(engine_editor_mcp.__file__))
    return os.path.join(base, "docs_content", "dev", "imgui_api.md")


def _render_groups() -> list[str]:
    """分组正文（H2 小节）。"""
    imgui = _imgui()
    out: list[str] = []
    seen: set[str] = set()
    for idx, group in enumerate(GROUPS, start=3):          # §1 规则 / §2 flag 速查在前
        title = group["title"]
        out.append(f"## {idx}. {title}")
        out.append("")
        intro = group.get("intro", "")
        if intro:
            out.append(intro)
            out.append("")
        for name, note in group["items"]:
            if name in seen:
                continue
            seen.add(name)
            sig = signature(name)
            missing = "" if hasattr(imgui, name) else "  ⚠️ 当前版本不存在"
            out.append(f"- `{sig}` — {note}{missing}")
        out.append("")
        out.append("---")
        out.append("")
    return out


def _render_flags(section_no: int) -> list[str]:
    imgui = _imgui()
    out = [f"## {section_no}. flag 速查", ""]
    out.append("值是运行时读出来的（`imgui.<Enum>.<成员>`），**用名字不要抄数字** —— "
               "升级库时数字会变。组合写法：`TableFlags_.row_bg | TableFlags_.borders_inner_h`。")
    out.append("")
    for spec in FLAGS:
        enum_name = spec["enum"]
        cls = getattr(imgui, enum_name, None)
        out.append(f"### {enum_name}")
        out.append("")
        if spec.get("intro"):
            out.append(spec["intro"])
            out.append("")
        out.append("| 成员 | 值 | 用途 |")
        out.append("|---|---|---|")
        for member, meaning in spec["members"]:
            value = getattr(cls, member, None) if cls is not None else None
            shown = "—" if value is None else f"`{int(value)}`"
            flag = "" if value is not None else " ⚠️ 不存在"
            out.append(f"| `{enum_name}.{member}` | {shown} | {meaning}{flag} |")
        out.append("")
    out.append("---")
    out.append("")
    return out


def _render_appendix(section_no: int) -> list[str]:
    imgui = _imgui()
    grouped = grouped_names()
    public = [n for n in dir(imgui) if not n.startswith("_")]

    loose_funcs = sorted(
        n for n in public
        if _is_routine(getattr(imgui, n)) and n not in grouped
    )
    enums, structs = [], []
    for name in sorted(public):
        obj = getattr(imgui, name)
        if _is_routine(obj):
            continue
        attrs = [a for a in dir(obj) if not a.startswith("_")]
        # 枚举成员是 int；int 自带的方法（bit_count 等）不是 —— 用它区分枚举与普通对象
        int_members = [a for a in attrs if isinstance(getattr(obj, a, None), int)]
        if int_members:
            enums.append((name, int_members))
        elif attrs:
            structs.append((name, len(attrs)))

    out = [f"## {section_no}. 附录：其余公开接口", ""]
    out.append(f"下面是当前 `imgui_bundle` 里**不在上面分组中**的接口"
               f"（函数 {len(loose_funcs)} 个 / 枚举 {len(enums)} 个 / 类型 {len(structs)} 个）。"
               "只列签名，不解释 —— 目的是「想到某个功能时能搜到名字」，"
               "真正要用之前先确认它不会破坏帧循环（§16）。")
    out.append("")
    out.append("> 本节很长：**不要整节读**。用 `engine-editor-cli doc search <关键词>` 定位，"
               "或 `doc show dev/imgui_api#附录` 后按字母扫。真正推荐的用法都在 §3–§16。")
    out.append("")
    out.append("### A. 函数（按字母）")
    out.append("")
    for name in loose_funcs:
        out.append(f"- `{signature(name)}`")
    out.append("")
    out.append("### B. 枚举（可用作 flag / 颜色 / 样式索引）")
    out.append("")
    out.append("| 枚举 | 成员数 | 例子 |")
    out.append("|---|---|---|")
    for name, members in enums:
        sample = ", ".join(f"`{m}`" for m in members[:4])
        out.append(f"| `imgui.{name}` | {len(members)} | {sample} |")
    out.append("")
    if structs:
        out.append("### C. 结构与对象")
        out.append("")
        out.append("| 类型 | 成员数 |")
        out.append("|---|---|")
        for name, count in structs:
            out.append(f"| `imgui.{name}` | {count} |")
        out.append("")
    out.append("---")
    out.append("")
    return out


def render() -> str:
    """渲染整篇文档（确定性输出 —— 同样输入必须逐字节一致）。"""
    imgui = _imgui()
    lines: list[str] = [_HEADER.rstrip(), ""]
    lines.extend(_render_flags(2))
    lines.extend(_render_groups())      # §3 起
    next_no = 3 + len(GROUPS)
    lines.extend(_render_appendix(next_no))
    lines.append(_MAINTENANCE.replace(
        "{heading}", f"## {next_no + 1}. 维护：生成器与守卫").rstrip())
    lines.append("")

    version = ""
    try:
        import imgui_bundle
        version = getattr(imgui_bundle, "__version__", "")
    except Exception:  # pragma: no cover
        pass
    footer = (f"\n<!-- generated by Utils/Dev/imgui_docgen.py | imgui_bundle {version} | "
              f"python {sys.version.split()[0]} -->\n")
    return "\n".join(lines).rstrip() + "\n" + footer


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 imgui-bundle 控件目录（按用途归类）")
    parser.add_argument("--out", default="", help="输出路径（默认工具仓 docs_content/dev/imgui_api.md）")
    parser.add_argument("--check", action="store_true", help="只比对，不写文件；不一致返回 1")
    parser.add_argument("--stats", action="store_true", help="打印覆盖率统计后退出")
    args = parser.parse_args(argv)

    imgui = _imgui()
    if args.stats:
        public = [n for n in dir(imgui) if not n.startswith("_")]
        grouped = grouped_names()
        used = Counter({n: k for n, k in usage_counts().items()
                        if callable(getattr(imgui, n, None))})
        unknown = unknown_group_names()
        dup = duplicates()
        loose = unclassified_used()
        print(f"public names     : {len(public)}")
        print(f"grouped          : {len(grouped)}  (在 {len(GROUPS)} 个分组里)")
        print(f"used in repo     : {len(used)} distinct / {sum(used.values())} 处调用")
        print(f"grouped & unused : {len(set(grouped) - set(used))}")
        print(f"used & ungrouped : {len(loose)}  {loose[:8]}{' ...' if len(loose) > 8 else ''}")
        print(f"grouped but absent in imgui : {len(unknown)}  {unknown[:8]}")
        print(f"duplicates       : {len(dup)}  {dup[:8]}")
        return 0 if not (unknown or dup or loose) else 1

    text = render()
    out_path = args.out or default_out_path()
    if not out_path:
        print("[imgui-doc] 找不到 engine_editor_mcp 包（工具仓不可用）；用 --out 指定路径")
        return 2
    if args.check:
        if not os.path.isfile(out_path):
            print(f"[imgui-doc] MISSING {out_path}")
            return 1
        current = open(out_path, encoding="utf-8").read()
        if current != text:
            print(f"[imgui-doc] STALE {out_path}  (run: python Utils/Dev/imgui_docgen.py)")
            return 1
        print(f"[imgui-doc] OK {out_path}")
        return 0

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"[imgui-doc] wrote {out_path}  ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
