"""运行时 UI 控件绘制（开关 / 滑条 / 离散选择三皮肤）。

纯数据 + 纯数学：输入组件对象与屏幕矩形，输出 `UIQuad` 列表 + 命中描述，
**不 import esper / imgui / GL**。由 `Core/UI/tree.py` 在元素树编译时调用。

几何约定（参考 `Doc/Dev/runtime_ui_protocol.md` §2.5）:
  - 组件 `label` 非空 → 左侧 `LABEL_RATIO` 宽度画说明文字，右侧剩余区域是控件本体
  - 控件本体在行内**垂直居中**
  - 所有尺寸乘画布缩放 `sx`（参考分辨率 → 视口）
"""

from __future__ import annotations

from Application.Core.UI.layout import UIQuad
from Application.Core.UI.theme import parse_color

LABEL_RATIO = 0.38
_MIN_CTRL = 96.0        # 控件本体最小宽度（参考像素）


def _g(obj, name, default):
    if obj is None:
        return default
    return getattr(obj, name, default)


# ════════════════════════════════════════════════════════════════
# 行布局
# ════════════════════════════════════════════════════════════════

def row_areas(x: float, y: float, w: float, h: float,
              has_label: bool, sx: float) -> tuple:
    """→ ((label_x, label_y, label_w, label_h), (ctrl_x, ctrl_y, ctrl_w, ctrl_h))。"""
    if not has_label:
        return ((x, y, 0.0, h), (x, y, w, h))
    ratio = LABEL_RATIO
    if w * ratio > w - _MIN_CTRL * sx:      # 控件本体保底宽度
        ratio = max(0.0, (w - _MIN_CTRL * sx) / max(w, 1.0))
    lw = w * ratio
    return ((x, y, lw, h), (x + lw, y, w - lw, h))


# ════════════════════════════════════════════════════════════════
# 值（运行期覆盖优先）
# ════════════════════════════════════════════════════════════════

def toggle_value(values: dict, eid: int, comp) -> bool:
    if values and int(eid) in values:
        return bool(values[int(eid)])
    return bool(_g(comp, "value", False))


def slider_range(comp) -> tuple:
    lo = _g(comp, "min_value", 0.0)
    hi = _g(comp, "max_value", 1.0)
    # ★ 不能用 `x or default`：0.0 是合法取值（会被当成缺省吞掉）
    lo = 0.0 if lo is None else float(lo)
    hi = 1.0 if hi is None else float(hi)
    if hi < lo:
        lo, hi = hi, lo
    step = _g(comp, "step", 0.0)
    step = max(0.0, float(step) if step is not None else 0.0)
    return lo, hi, step


def slider_value(values: dict, eid: int, comp) -> float:
    lo, hi, step = slider_range(comp)
    raw = values.get(int(eid)) if values and int(eid) in values else _g(comp, "value", lo)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = lo
    return clamp_value(val, lo, hi, step)


def select_options(comp) -> list:
    opts = _g(comp, "options", ()) or ()
    if isinstance(opts, str):
        return [p.strip() for p in opts.split(",") if p.strip()]
    return [str(o) for o in opts]


def select_index(values: dict, eid: int, comp) -> int:
    opts = select_options(comp)
    raw = values.get(int(eid)) if values and int(eid) in values else _g(comp, "index", 0)
    try:
        idx = int(raw)
    except (TypeError, ValueError):
        idx = 0
    if not opts:
        return 0
    return max(0, min(len(opts) - 1, idx))


def clamp_value(value: float, lo: float, hi: float, step: float = 0.0) -> float:
    val = max(lo, min(hi, float(value)))
    if step > 0.0:
        steps = round((val - lo) / step)
        val = lo + steps * step
        val = max(lo, min(hi, val))
    return float(val)


# ════════════════════════════════════════════════════════════════
# 开关
# ════════════════════════════════════════════════════════════════

def draw_toggle(x: float, y: float, w: float, h: float, sx: float,
                on: bool, hovered: bool, table: dict) -> list[UIQuad]:
    """开关：右侧一条轨道 + 方块旋钮（M1 无圆角，用方块代替圆）。"""
    sw_h = max(12.0, min(h * 0.62, 30.0 * sx))
    sw_w = sw_h * 2.0
    tx = x + w - sw_w
    ty = y + (h - sw_h) / 2.0
    track = parse_color("@color.button.primary" if on else "@color.button", table)
    if hovered and not on:
        track = parse_color("@color.button.hover", table)
    quads = [UIQuad(tx, ty, sw_w, sw_h, track)]
    pad = max(2.0, sw_h * 0.14)
    knob = sw_h - 2 * pad
    kx = tx + (sw_w - pad - knob if on else pad)
    quads.append(UIQuad(kx, ty + pad, knob, knob,
                        parse_color("@color.text", table)))
    return quads


# ════════════════════════════════════════════════════════════════
# 滑条
# ════════════════════════════════════════════════════════════════

def slider_layout(x: float, y: float, w: float, h: float, sx: float,
                  show_value: bool) -> tuple:
    """→ (track_x0, track_x1, center_y, value_area_width)。"""
    value_w = 96.0 * sx if show_value else 0.0
    knob = 18.0 * sx
    x0 = x + knob / 2.0
    x1 = x + w - value_w - knob / 2.0
    if x1 <= x0:
        x1 = x0 + 1.0
    return (x0, x1, y + h / 2.0, value_w)


def value_at_track(track: tuple, cx: float, lo: float, hi: float,
                   step: float = 0.0) -> float:
    """光标 x → 数值（轨道两端 = 取值范围两端）。"""
    x0, x1 = float(track[0]), float(track[1])
    t = 0.0 if x1 <= x0 else (float(cx) - x0) / (x1 - x0)
    t = max(0.0, min(1.0, t))
    return clamp_value(lo + t * (hi - lo), lo, hi, step)


def draw_slider(x: float, y: float, w: float, h: float, sx: float,
                lo: float, hi: float, value: float, show_value: bool,
                hovered: bool, table: dict) -> tuple:
    """→ (quads, track)。"""
    x0, x1, cy, value_w = slider_layout(x, y, w, h, sx, show_value)
    t = 0.0 if hi <= lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    track_h = max(3.0, 6.0 * sx)
    knob = max(8.0, 18.0 * sx)
    quads = [UIQuad(x0, cy - track_h / 2.0, x1 - x0, track_h,
                    parse_color("@color.border", table))]
    fill_w = (x1 - x0) * t
    if fill_w > 0.0:
        quads.append(UIQuad(x0, cy - track_h / 2.0, fill_w, track_h,
                            parse_color("@color.button.primary", table)))
    knob_color = "@color.button.primary.hover" if hovered else "@color.text"
    quads.append(UIQuad(x0 + (x1 - x0) * t - knob / 2.0, cy - knob / 2.0,
                        knob, knob, parse_color(knob_color, table)))
    return quads, (x0, x1), value_w


def format_value(value: float, step: float) -> str:
    """数值文本：step ≥ 1 → 整数；否则两位小数（去尾零）。"""
    if step >= 1.0:
        return str(int(round(value)))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


# ════════════════════════════════════════════════════════════════
# 离散选择（三皮肤）
# ════════════════════════════════════════════════════════════════

def draw_select_segmented(x: float, y: float, w: float, h: float, sx: float,
                          options: list, index: int, hovered_index: int,
                          hovered: bool, table: dict) -> tuple:
    """并排分段（2-4 项）。

    → (quads, hit_specs)；hit_specs = [(rect, index), ...]（供 tree 造命中）。
    """
    n = max(1, len(options))
    seg_w = w / n
    quads: list[UIQuad] = []
    specs: list[tuple] = []
    radius = max(1.0, 1.0 * sx)
    for i in range(n):
        sxv = x + i * seg_w
        selected = (i == index)
        if selected:
            color = parse_color("@color.button.primary", table)
        elif hovered and i == hovered_index:
            color = parse_color("@color.button.hover", table)
        else:
            color = parse_color("@color.button", table)
        quads.append(UIQuad(sxv, y, seg_w, h, color))
        thick = max(0.5, 1.0 * sx)
        quads.append(UIQuad(sxv, y, thick, h, parse_color("@color.border", table)))
        specs.append(((sxv, y, seg_w, h), i))
    quads.append(UIQuad(x + w - max(0.5, 1.0 * sx), y, max(0.5, 1.0 * sx), h,
                        parse_color("@color.border", table)))
    _ = radius
    return quads, specs


def draw_select_stepper(x: float, y: float, w: float, h: float, sx: float,
                        options: list, index: int, hovered: bool,
                        table: dict) -> tuple:
    """`−` 值 `+`（多项列表 / 数值步进都用它）。"""
    btn = max(16.0, min(h, 44.0 * sx))
    bg = parse_color("@color.button.hover" if hovered else "@color.button", table)
    quads = [
        UIQuad(x, y, btn, h, bg),
        UIQuad(x + w - btn, y, btn, h, bg),
    ]
    border = parse_color("@color.border", table)
    thick = max(0.5, 1.0 * sx)
    quads.append(UIQuad(x, y + h - thick, w, thick, border))
    quads.append(UIQuad(x, y, thick, h, border))
    quads.append(UIQuad(x + w - thick, y, thick, h, border))
    specs = [((x, y, btn, h), -1), ((x + w - btn, y, btn, h), +1)]
    return quads, specs


def select_label(options: list, index: int) -> str:
    if options:
        return options[max(0, min(len(options) - 1, index))]
    return ""


__all__ = [
    "LABEL_RATIO", "row_areas",
    "toggle_value", "slider_range", "slider_value", "select_options",
    "select_index", "clamp_value",
    "draw_toggle", "slider_layout", "value_at_track", "draw_slider", "format_value",
    "draw_select_segmented", "draw_select_stepper", "select_label",
]
