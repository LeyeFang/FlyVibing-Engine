"""virtual_scope — 示波器绘制（imgui draw_list; 无状态, 只读视图缓存）。

设计语言（沿用社区监视面板, 代码为干净重写）:
  - 堆叠通道行: 每通道一条基线 + 名称;
  - min/max 包络: 每列一根竖线（保尖峰）; 点列由 virtual_display 预抽取;
  - 网格 + 悬停十字读数（t / ch / 极值）;
  - 统计表: Ch / RMS / P2P / Mean（µV 原始口径）。

UI 文本全程 ASCII（字形图集约束 — ui_protocol §12）。
"""

from __future__ import annotations

from imgui_bundle import imgui

GRID_COL = imgui.ImVec4(0.30, 0.30, 0.34, 0.60)
BASE_COL = imgui.ImVec4(0.42, 0.42, 0.48, 0.85)
TRACE_COL = imgui.ImVec4(0.30, 0.85, 0.95, 1.00)
BG_COL = imgui.ImVec4(0.09, 0.09, 0.11, 1.00)
TEXT_DIM = imgui.ImVec4(0.60, 0.60, 0.64, 1.00)
HOVER_COL = imgui.ImVec4(0.95, 0.85, 0.40, 1.00)
_MAX_ROWS_SHOWN = 8


def _c32(col: imgui.ImVec4) -> int:
    """ImVec4 -> packed u32（draw_list 颜色参数格式）。"""
    return imgui.get_color_u32(col)


def auto_amplitude(view) -> float:
    """自动幅度档: 最大峰峰值的一半 → 1-2-5 阶梯。"""
    if not view.stats:
        return 50.0
    ptp_max = max((s[1] for s in view.stats), default=0.0)
    return max(1.0, ptp_max / 2.0)


def draw_scope(view, window_s: float, amplitude_uv: float,
               channel_start: int, height: float = 240.0) -> None:
    """绘制波形视口（调用方负责在窗口帧内; 只读 view 的缓存列）。"""
    dl = imgui.get_window_draw_list()
    x0, y0 = imgui.get_cursor_screen_pos()
    w = max(120.0, float(imgui.get_content_region_avail()[0]))
    h = float(height)
    imgui.dummy(imgui.ImVec2(w, h))
    dl.add_rect_filled(imgui.ImVec2(x0, y0), imgui.ImVec2(x0 + w, y0 + h), _c32(BG_COL))

    # 网格（4 等分竖线 + 上下边框）
    for i in range(1, 4):
        x = x0 + w * i / 4.0
        dl.add_line(imgui.ImVec2(x, y0), imgui.ImVec2(x, y0 + h), _c32(GRID_COL))
    dl.add_rect(imgui.ImVec2(x0, y0), imgui.ImVec2(x0 + w, y0 + h), _c32(GRID_COL))

    ch_total = int(view.mins.shape[0])
    if ch_total == 0 or view.cols == 0:
        dl.add_text(imgui.ImVec2(x0 + 8, y0 + 8), _c32(TEXT_DIM),
                    "no data - open a session, then Watch or Record")
        return

    start = max(0, min(int(channel_start), ch_total - 1))
    shown = max(1, min(_MAX_ROWS_SHOWN, ch_total - start))
    amp = float(amplitude_uv) if float(amplitude_uv) > 0.0 else auto_amplitude(view)
    row_h = h / shown
    scale = (row_h * 0.45) / max(1e-6, amp)

    for r in range(shown):
        c = start + r
        base_y = y0 + row_h * (r + 0.5)
        dl.add_line(imgui.ImVec2(x0, base_y), imgui.ImVec2(x0 + w, base_y), _c32(BASE_COL))
        dl.add_text(imgui.ImVec2(x0 + 4, y0 + row_h * r + 2), _c32(TEXT_DIM), f"ch{c + 1}")
        if c < view.maxs.shape[0]:
            hi_row = view.maxs[c]
            lo_row = view.mins[c]
            for i in range(view.cols):
                x = x0 + w * (i + 0.5) / view.cols
                y_hi = base_y - float(hi_row[i]) * scale
                y_lo = base_y - float(lo_row[i]) * scale
                dl.add_line(imgui.ImVec2(x, y_hi), imgui.ImVec2(x, y_lo), _c32(TRACE_COL))

    # 悬停读数（t / ch / 极值）—— hover 判定基于 dummy 占位区
    if imgui.is_item_hovered():
        mx, my = imgui.get_mouse_pos()
        if x0 <= mx <= x0 + w and y0 <= my <= y0 + h:
            i = min(view.cols - 1, max(0, int((mx - x0) / w * view.cols)))
            r = min(shown - 1, max(0, int((my - y0) / row_h)))
            c = start + r
            t = (i + 0.5) / view.cols * float(window_s)
            lo = float(view.mins[c, i])
            hi = float(view.maxs[c, i])
            dl.add_text(imgui.ImVec2(x0 + 8, y0 + 4), _c32(HOVER_COL),
                        f"t=+{t:0.2f}s ch{c + 1}  {lo:0.0f} .. {hi:0.0f} uV")
            dl.add_line(imgui.ImVec2(mx, y0), imgui.ImVec2(mx, y0 + h), _c32(HOVER_COL))


def draw_stats_table(stats, max_rows: int = 16) -> None:
    """通道统计表（Ch / RMS / P2P / Mean; µV）。"""
    if not imgui.begin_table("##vstats", 4,
                             imgui.TableFlags_.borders | imgui.TableFlags_.row_bg):
        return
    try:
        for name in ("Ch", "RMS uV", "P2P uV", "Mean uV"):
            imgui.table_setup_column(name)
        imgui.table_headers_row()
        for c, (rms, ptp, mean) in enumerate(stats[:max_rows]):
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.text(f"ch{c + 1}")
            imgui.table_next_column()
            imgui.text(f"{rms:0.1f}")
            imgui.table_next_column()
            imgui.text(f"{ptp:0.1f}")
            imgui.table_next_column()
            imgui.text(f"{mean:0.1f}")
    finally:
        imgui.end_table()
