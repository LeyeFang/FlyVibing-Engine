"""UI 编译 — `UIElement` 列表 → 绘制指令（`UIQuad`）+ 命中矩形。

纯数据 / 纯数学：**不 import esper、imgui、GL**（可离线单测）。
文本光栅化通过 `text_fn` 注入（默认走 `Core/Text/TextSystem`），
这样单测可以塞假实现，运行期也能换成图集版本而不动这里。

编译规则（协议：`Doc/Dev/product_todo.md` §10.1–§10.5）:
  - 每个元素的位置相对**最近的带 `UIRect` 的祖先**；没有祖先 → 画布内容框。
  - 画布自带 `scale_mode`（参考分辨率 → 视口），多画布按 `sort_order` 排序。
  - 可见性沿父链传递；`visible_overrides` 允许运行期临时显隐（不改场景数据）。
  - 绘制顺序 = (画布 sort_order, 深度, order, eid)；父先于子。
  - **只有按钮产生命中矩形**；`modal` 面板吃掉整屏输入（见 `hit_test/captures`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from Application.Core.UI.controls import (
    draw_select_segmented,
    draw_select_stepper,
    draw_slider,
    draw_toggle,
    format_value,
    row_areas,
    select_index,
    select_label,
    select_options,
    slider_range,
    slider_value,
    toggle_value,
)
from Application.Core.UI.layout import (
    REFERENCE_H,
    REFERENCE_W,
    UIQuad,
    content_box,
    rect_hit,
    resolve_rect,
)
from Application.Core.UI.theme import (
    DEFAULT_TOKENS,
    button_colors,
    parse_color,
    with_alpha,
)

# ════════════════════════════════════════════════════════════════
# 输入 / 输出模型
# ════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UIElement:
    """一个 UI 实体在编译期的只读快照（组件对象按鸭子类型读取）。

    组件字段全部可选：`canvas/rect/panel/label/button/...` 为 None 表示该实体没有这个组件。
    """

    eid: int
    parent_id: int | None = None
    canvas: object | None = None
    rect: object | None = None
    panel: object | None = None
    label: object | None = None
    button: object | None = None
    toggle: object | None = None
    slider: object | None = None
    select: object | None = None
    name: str = ""


@dataclass(frozen=True)
class UIHitRect:
    """可交互元素的命中矩形（屏幕像素，左上原点）。"""

    eid: int
    rect: tuple
    action: str = ""
    enabled: bool = True
    panel_eid: int = 0        # 所属面板（`close` 动作用）；0 = 无
    in_modal: bool = False    # 属于模态面板子树（模态时只有它能被点）
    kind: str = "button"      # button | toggle | slider | select | step | dropdown
    index: int = 0            # select 选项下标 / step 的 -1、+1
    track: tuple = ()         # slider 轨道 (x0, x1)（像素）— 命中转数值用


@dataclass(frozen=True)
class UIBuildResult:
    quads: tuple = ()
    hits: tuple = ()
    modal: bool = False
    modal_eid: int = 0
    # eid → 屏幕矩形（调试/编辑器预览用）
    rects: dict = field(default_factory=dict, compare=False, repr=False)

    def hit_at(self, x: float, y: float) -> UIHitRect | None:
        """光标 → 最上层可交互元素（模态时只认模态子树）。"""
        for hit in reversed(self.hits):
            if not hit.enabled:
                continue
            if self.modal and not hit.in_modal:
                continue
            if rect_hit(hit.rect, x, y):
                return hit
        return None


EMPTY_RESULT = UIBuildResult()


# ════════════════════════════════════════════════════════════════
# 文本（默认实现 — 运行期可替换）
# ════════════════════════════════════════════════════════════════

_TEXT_CACHE: dict = {}


@dataclass
class _TextSpec:
    """`TextSystem.rasterize` 需要的字段子集（鸭子类型）。"""

    text: str = ""
    font: str = ""
    size: int = 28
    bold: bool = False
    italic: bool = False
    color: tuple = (1.0, 1.0, 1.0, 1.0)
    bg_color: tuple = (0.0, 0.0, 0.0, 0.0)
    align: str = "center"
    line_spacing: float = 1.15
    padding: int = 0
    wrap_width: int = 0


def default_text_image(text: str, size: int, color: tuple,
                       bold: bool = False) -> tuple:
    """文本 → (w, h, RGBA uint8 数组, 缓存 key)。按内容缓存。"""
    key = f"{text}|{int(size)}|{tuple(round(float(c), 3) for c in color)}|{1 if bold else 0}"
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        return cached
    from Application.Core.Text import TextSystem
    from Application.Core.UI.layout import resolve_font

    spec = _TextSpec(text=str(text), font=resolve_font(text), size=int(max(1, size)),
                     bold=bool(bold), color=tuple(color),
                     bg_color=(0.0, 0.0, 0.0, 0.0), align="center", padding=0)
    arr = TextSystem.rasterize(spec)
    h, w = int(arr.shape[0]), int(arr.shape[1])
    entry = (w, h, arr, key)
    if len(_TEXT_CACHE) > 256:      # 简易上限，防止无限增长
        _TEXT_CACHE.clear()
    _TEXT_CACHE[key] = entry
    return entry


def clear_text_cache() -> None:
    _TEXT_CACHE.clear()


# ════════════════════════════════════════════════════════════════
# 字段读取（组件缺失 → 默认值）
# ════════════════════════════════════════════════════════════════

def _g(obj, name, default):
    if obj is None:
        return default
    return getattr(obj, name, default)


def _canvas_settings(canvas) -> tuple:
    return (
        str(_g(canvas, "scale_mode", "fit_height") or "fit_height"),
        int(_g(canvas, "reference_w", REFERENCE_W) or REFERENCE_W),
        int(_g(canvas, "reference_h", REFERENCE_H) or REFERENCE_H),
        int(_g(canvas, "sort_order", 0) or 0),
        bool(_g(canvas, "visible", True)),
    )


# ════════════════════════════════════════════════════════════════
# 编译
# ════════════════════════════════════════════════════════════════

def build_ui(elements, viewport_w: int, viewport_h: int, *,
             hover_eid: int = 0, pressed_eid: int = 0,
             visible_overrides: dict | None = None,
             values: dict | None = None,
             texts: dict | None = None,
             expanded_eid: int = 0,
             hover_index: int = -1,
             text_fn=None,
             tokens: dict | None = None) -> UIBuildResult:
    """编译 UI 元素 → 绘制指令 + 命中矩形。

    Args:
        elements: `UIElement` 序列（顺序无所谓 — 内部按父子关系排序）
        viewport_w/h: 视口像素尺寸（framebuffer）
        hover_eid / pressed_eid: 交互状态（按钮底色派生）
        visible_overrides: {eid: bool} 临时显隐（运行期动作，不改场景数据）
        values: {eid: value} 控件运行期值（开关 bool / 滑条 float / 选择 int）
        texts: {eid: str} 标签运行期文本覆盖（`SetUIText` 节点写入）
        expanded_eid: 展开中的下拉选择 eid（0 = 无）
        hover_index: 光标悬停的子区域下标（segmented 分段）
        text_fn: (text, size_px, rgba, bold) → (w, h, image, key)
        tokens: 主题 token 表（默认 `DEFAULT_TOKENS`）

    Returns:
        `UIBuildResult`（quads 按绘制顺序；hits 按绘制顺序 → 取最上层要反向遍历）
    """
    els = [e for e in (elements or ()) if e is not None]
    vw, vh = int(viewport_w), int(viewport_h)
    if not els or vw <= 0 or vh <= 0:
        return EMPTY_RESULT

    overrides = visible_overrides or {}
    vals = values or {}
    label_texts = texts or {}
    table = DEFAULT_TOKENS if tokens is None else tokens
    raster = text_fn or default_text_image

    by_eid: dict[int, UIElement] = {int(e.eid): e for e in els}

    def _depth(eid: int) -> int:
        n, cur, guard = 0, by_eid.get(eid), 0
        while cur is not None and cur.parent_id is not None and guard < 64:
            cur = by_eid.get(int(cur.parent_id))
            n += 1
            guard += 1
        return n

    depth = {eid: _depth(eid) for eid in by_eid}
    order_key = {
        eid: (
            _canvas_settings(e.canvas)[3],      # 画布 sort_order
            depth[eid],
            int(_g(e.rect, "order", 0) or 0),
            eid,
        )
        for eid, e in by_eid.items()
    }
    ordered = sorted(els, key=lambda e: order_key[int(e.eid)])

    # ── 可见性（父链 + 画布 + 运行期覆盖）──
    vis_cache: dict[int, bool] = {}

    def _visible(eid: int) -> bool:
        if eid in vis_cache:
            return vis_cache[eid]
        el = by_eid.get(eid)
        if el is None:
            vis_cache[eid] = True      # 非 UI 祖先不影响可见性
            return True
        own = bool(_g(el.rect, "visible", True))
        if eid in overrides:
            own = bool(overrides[eid])
        canvas_visible = bool(_g(el.canvas, "visible", True))
        parent = el.parent_id
        ok = own and canvas_visible and (_visible(int(parent)) if parent is not None else True)
        vis_cache[eid] = ok
        return ok

    # ── 布局：每个元素的屏幕矩形 ──
    rects: dict[int, tuple] = {}
    scales: dict[int, tuple] = {}
    panel_of: dict[int, int] = {}
    canvas_boxes: dict = {}
    canvas_scales: dict = {}

    def _canvas_box(canvas):
        key = int(getattr(canvas, "sort_order", 0) or 0), id(canvas)
        if key not in canvas_boxes:
            mode, rw, rh, _so, _vis = _canvas_settings(canvas)
            canvas_boxes[key], canvas_scales[key] = content_box(
                vw, vh, mode, (rw, rh))
        return canvas_boxes[key], canvas_scales[key]

    for el in ordered:
        eid = int(el.eid)
        parent = int(el.parent_id) if el.parent_id is not None else None
        box, scale = _canvas_box(el.canvas)
        # 父矩形：向上找最近的已布局 UI 祖先（纯容器也会被布局）
        while parent is not None and parent not in rects:
            p_el = by_eid.get(parent)
            parent = int(p_el.parent_id) if (p_el is not None and p_el.parent_id is not None) else None
        if parent is not None:
            pbox = rects[parent]
            box = pbox
            # 子元素的缩放跟随自己的画布（同画布 → 一致）
        anchor = str(_g(el.rect, "anchor", "center") or "center")
        pivot = str(_g(el.rect, "pivot", anchor) or anchor)
        want_w = float(_g(el.rect, "width", 0.0) or 0.0)
        want_h = float(_g(el.rect, "height", 0.0) or 0.0)
        # width/height = 0 → 撑满父矩形（换算回参考单位）
        sx = scale[0] if scale[0] else 1.0
        sy = scale[1] if scale[1] else 1.0
        if want_w <= 0.0:
            want_w = box[2] / sx
        if want_h <= 0.0:
            want_h = box[3] / sy
        rects[eid] = resolve_rect(
            (float(_g(el.rect, "pos_x", 0.0) or 0.0),
             float(_g(el.rect, "pos_y", 0.0) or 0.0)),
            (want_w, want_h), box, scale, anchor, pivot)
        scales[eid] = scale

        if el.panel is not None:
            panel_of[eid] = eid
        elif parent is not None and parent in panel_of:
            panel_of[eid] = panel_of[parent]

    # ── 模态：最上层（画得最晚）的模态面板 ──
    modal_eid = 0
    for el in ordered:
        eid = int(el.eid)
        if not _visible(eid):
            continue
        if el.panel is not None and bool(_g(el.panel, "modal", False)):
            modal_eid = eid
    modal = modal_eid != 0

    # ── 绘制 ──
    quads: list[UIQuad] = []
    hits: list[UIHitRect] = []
    dropdown_box: dict = {}      # eid → 下拉控件区域（弹层用，不含左侧标签）

    def _is_descendant_of(eid: int, ancestor: int) -> bool:
        cur = by_eid.get(eid)
        guard = 0
        while cur is not None and guard < 64:
            if int(cur.eid) == ancestor:
                return True
            cur = by_eid.get(int(cur.parent_id)) if cur.parent_id is not None else None
            guard += 1
        return False

    for el in ordered:
        eid = int(el.eid)
        if not _visible(eid):
            continue
        x, y, w, h = rects[eid]
        if w <= 0.0 or h <= 0.0:
            continue
        in_modal = (not modal) or _is_descendant_of(eid, modal_eid)
        sx = scales[eid][0] if scales[eid][0] else 1.0

        # ── 面板 ──
        if el.panel is not None:
            scrim = _g(el.panel, "scrim_color", "")
            if scrim:
                quads.append(UIQuad(0.0, 0.0, float(vw), float(vh),
                                    parse_color(scrim, table)))
            bg = parse_color(_g(el.panel, "bg_color", ""), table,
                             default=(0.0, 0.0, 0.0, 0.0))
            if bg[3] > 0.0:
                quads.append(UIQuad(x, y, w, h, bg))
            bw = float(_g(el.panel, "border_width", 0.0) or 0.0)
            if bw > 0.0:
                border = parse_color(_g(el.panel, "border_color", ""), table,
                                     default=(0.0, 0.0, 0.0, 0.0))
                if border[3] > 0.0:
                    quads.extend(_border_quads(x, y, w, h, bw, border))

        # ── 按钮 ──
        if el.button is not None:
            enabled = bool(_g(el.button, "enabled", True))
            hovered = enabled and eid == int(hover_eid)
            pressed = hovered and eid == int(pressed_eid)
            bg, fg = button_colors(_g(el.button, "variant", "secondary"),
                                   hover=hovered or pressed, enabled=enabled,
                                   tokens=table)
            if bg[3] > 0.0:
                quads.append(UIQuad(x, y, w, h, bg))
            size = float(_g(el.button, "size", 0.0) or 0.0)
            size_px = int(round((size or float(table.get("font.size.button", 30))) * sx))
            quads.append(_label_quad(raster, str(_g(el.button, "text", "")), size_px,
                                     fg, x, y, w, h, "center"))
            hits.append(UIHitRect(
                eid=eid, rect=(x, y, w, h),
                action=str(_g(el.button, "action", "") or ""),
                enabled=enabled,
                panel_eid=int(panel_of.get(eid, 0)),
                in_modal=in_modal,
            ))
            continue

        # ── 设置控件（开关 / 滑条 / 选择）──
        ctrl = el.toggle or el.slider or el.select
        if ctrl is not None:
            hovered = eid == int(hover_eid)
            pressed = hovered and eid == int(pressed_eid)
            action = str(_g(ctrl, "action", "") or "")
            label_text = str(_g(ctrl, "label", "") or "")
            lbl_rect, (cx, cy, cw, ch) = row_areas(x, y, w, h, bool(label_text), sx)
            if label_text:
                size_px = int(round(
                    (float(_g(ctrl, "size", 0.0) or 0.0)
                     or float(table.get("font.size.body", 28)) * 0.86) * sx))
                quads.append(_label_quad(
                    raster, label_text, size_px,
                    parse_color("@color.text.muted", table),
                    lbl_rect[0], lbl_rect[1], lbl_rect[2], lbl_rect[3], "left"))
            base = dict(eid=eid, action=action, panel_eid=int(panel_of.get(eid, 0)),
                        in_modal=in_modal)

            if el.toggle is not None:
                on = toggle_value(vals, eid, el.toggle)
                quads.extend(draw_toggle(cx, cy, cw, ch, sx, on,
                                         hovered or pressed, table))
                hits.append(UIHitRect(rect=(x, y, w, h), kind="toggle", **base))
                continue

            if el.slider is not None:
                lo, hi, step = slider_range(el.slider)
                val = slider_value(vals, eid, el.slider)
                show_value = bool(_g(el.slider, "show_value", True))
                s_quads, track, value_w = draw_slider(
                    cx, cy, cw, ch, sx, lo, hi, val, show_value,
                    hovered or pressed, table)
                quads.extend(s_quads)
                if show_value and value_w > 0.0:
                    size_px = int(round(
                        (float(_g(el.slider, "size", 0.0) or 0.0)
                         or float(table.get("font.size.body", 28)) * 0.8) * sx))
                    quads.append(_label_quad(
                        raster, format_value(val, step), size_px,
                        parse_color("@color.text", table),
                        cx + cw - value_w, cy - ch / 2.0, value_w, ch, "right"))
                hits.append(UIHitRect(rect=(x, y, w, h), kind="slider",
                                      track=tuple(track), **base))
                continue

            if el.select is not None:
                opts = select_options(el.select)
                idx = select_index(vals, eid, el.select)
                skin = str(_g(el.select, "skin", "segmented") or "segmented").lower()
                size_px = int(round(
                    (float(_g(el.select, "size", 0.0) or 0.0)
                     or float(table.get("font.size.button", 30))) * sx))
                fg = parse_color("@color.text", table)
                if skin == "stepper":
                    s_quads, specs = draw_select_stepper(
                        cx, cy, cw, ch, sx, opts, idx, hovered or pressed, table)
                    quads.extend(s_quads)
                    for (rx, ry, rw, rh), delta in specs:
                        quads.append(_label_quad(
                            raster, "-" if delta < 0 else "+", size_px, fg,
                            rx, ry, rw, rh, "center"))
                    quads.append(_label_quad(raster, select_label(opts, idx),
                                             size_px, fg, cx, cy, cw, ch, "center"))
                    for (rx, ry, rw, rh), delta in specs:
                        hits.append(UIHitRect(rect=(rx, ry, rw, rh), kind="step",
                                              index=int(delta), **base))
                elif skin == "dropdown":
                    dropdown_box[eid] = (cx, cy, cw, ch)
                    box_bg = parse_color(
                        "@color.button.hover" if (hovered or pressed) else "@color.button",
                        table)
                    quads.append(UIQuad(cx, cy, cw, ch, box_bg))
                    arrow_w = min(ch, 34.0 * sx)
                    quads.append(_label_quad(
                        raster, "v", size_px, fg,
                        cx + cw - arrow_w, cy, arrow_w, ch, "center"))
                    quads.append(_label_quad(
                        raster, select_label(opts, idx), size_px, fg,
                        cx, cy, cw - arrow_w, ch, "left"))
                    hits.append(UIHitRect(rect=(x, y, w, h), kind="dropdown", **base))
                else:      # segmented
                    s_quads, specs = draw_select_segmented(
                        cx, cy, cw, ch, sx, opts, idx,
                        int(hover_index), hovered or pressed, table)
                    quads.extend(s_quads)
                    for (rx, ry, rw, rh), i in specs:
                        quads.append(_label_quad(
                            raster, opts[i] if i < len(opts) else str(i),
                            size_px, fg, rx, ry, rw, rh, "center"))
                        hits.append(UIHitRect(rect=(rx, ry, rw, rh), kind="select",
                                              index=int(i), **base))
                continue

        # ── 文字 ──
        if el.label is not None:
            size = float(_g(el.label, "size", 0.0) or 0.0)
            size_px = int(round((size or float(table.get("font.size.body", 28))) * sx))
            color = parse_color(_g(el.label, "color", "@color.text"), table)
            text = label_texts.get(eid, _g(el.label, "text", ""))
            quads.append(_label_quad(
                raster, str(text), size_px, color,
                x, y, w, h, str(_g(el.label, "align", "center") or "center"),
                bold=bool(_g(el.label, "bold", False))))

    # ── 下拉展开列表（画在所有元素之上；命中排最后 = 最上层）──
    if expanded_eid and int(expanded_eid) in rects:
        eid = int(expanded_eid)
        el = by_eid.get(eid)
        if (el is not None and el.select is not None and _visible(eid)):
            x, y, w, h = dropdown_box.get(eid, rects[eid])
            sx = scales[eid][0] if scales[eid][0] else 1.0
            opts = select_options(el.select)
            in_modal = (not modal) or _is_descendant_of(eid, modal_eid)
            row_h = max(16.0, min(h, 40.0 * sx))
            size_px = int(round(
                (float(_g(el.select, "size", 0.0) or 0.0)
                 or float(table.get("font.size.button", 30))) * sx))
            # 弹层必须不透明（否则下层文字透出来）
            bg = with_alpha(parse_color("@color.surface", table), 1.0)
            fg = parse_color("@color.text", table)
            border = parse_color("@color.border", table)
            thick = max(0.5, 1.0 * sx)
            popup_h = len(opts) * row_h
            # 下方空间不够 → 向上展开（避免超出视口被裁掉）
            popup_y = y + h
            if popup_y + popup_h > vh:
                popup_y = max(0.0, y - popup_h)
            for i, opt in enumerate(opts):
                ry = popup_y + i * row_h
                quads.append(UIQuad(x, ry, w, row_h, bg))
                quads.append(UIQuad(x, ry + row_h - thick, w, thick, border))
                quads.append(_label_quad(raster, opt, size_px, fg,
                                         x + 12.0 * sx, ry, w - 24.0 * sx, row_h,
                                         "left"))
                hits.append(UIHitRect(
                    eid=eid, rect=(x, ry, w, row_h), kind="select", index=i,
                    action=str(_g(el.select, "action", "") or ""),
                    panel_eid=int(panel_of.get(eid, 0)), in_modal=in_modal))

    return UIBuildResult(
        quads=tuple(quads), hits=tuple(hits), modal=modal,
        modal_eid=modal_eid, rects=rects,
    )


# ════════════════════════════════════════════════════════════════
# 绘制小工具
# ════════════════════════════════════════════════════════════════

def _border_quads(x: float, y: float, w: float, h: float,
                  t: float, color: tuple) -> list[UIQuad]:
    """四边描边（M0 直角；圆角留给 SDF 版本）。"""
    t = max(0.5, float(t))
    return [
        UIQuad(x, y, w, t, color),
        UIQuad(x, y + h - t, w, t, color),
        UIQuad(x, y, t, h, color),
        UIQuad(x + w - t, y, t, h, color),
    ]


def _label_quad(raster, text: str, size_px: int, color: tuple,
                x: float, y: float, w: float, h: float,
                align: str = "center", bold: bool = False) -> UIQuad:
    """把文字画进 (x,y,w,h) —— 水平按 align，垂直居中。"""
    size_px = max(1, int(size_px))
    tw, th, arr, key = raster(str(text), size_px, color, bold)
    if align == "left":
        tx = x
    elif align == "right":
        tx = x + w - tw
    else:
        tx = x + (w - tw) / 2.0
    ty = y + (h - th) / 2.0
    return UIQuad(x=float(tx), y=float(ty), w=float(tw), h=float(th),
                  color=(1.0, 1.0, 1.0, 1.0), image=arr, key=key)


# ════════════════════════════════════════════════════════════════
# 查询辅助
# ════════════════════════════════════════════════════════════════

def captures(result: UIBuildResult, x: float, y: float) -> bool:
    """光标处是否应被 UI 捕获（模态整屏 / 可点按钮上）。"""
    if result is None:
        return False
    if result.modal:
        return True
    return result.hit_at(x, y) is not None


__all__ = [
    "UIElement", "UIHitRect", "UIBuildResult", "EMPTY_RESULT",
    "build_ui", "captures", "default_text_image", "clear_text_cache",
]
