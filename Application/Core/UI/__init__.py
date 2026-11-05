"""运行时 UI 基础原语（Core 侧）：布局/命中/主题 + `UIQuad` 绘制指令。

分层（协议：`Doc/Dev/product_todo.md` §10）:
  - `layout`  — 坐标数学（参考分辨率 → 视口，9 宫格锚点，矩形命中）
  - `theme`   — token（颜色/字号/间距）+ 按钮变体
  - `tree`    — 元素 → 绘制指令 + 命中矩形（纯数据，可离线单测）
  - `scene`   — esper 场景 → 元素快照（只在逻辑线程调用）
"""

from Application.Core.UI.layout import (
    REFERENCE_H,
    REFERENCE_W,
    UIQuad,
    content_box,
    rect_hit,
    resolve_font,
    resolve_rect,
)
from Application.Core.UI.theme import (
    DEFAULT_TOKENS,
    button_colors,
    parse_color,
    resolve,
)

__all__ = [
    "REFERENCE_W",
    "REFERENCE_H",
    "UIQuad",
    "content_box",
    "resolve_rect",
    "rect_hit",
    "resolve_font",
    "DEFAULT_TOKENS",
    "button_colors",
    "parse_color",
    "resolve",
]
