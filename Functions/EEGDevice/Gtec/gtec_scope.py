"""Gtec 监视面板 — 示波器绘制（imgui; 仅渲染帧内调用）。

职责: 把 `gtec_display.ScopeFrame`（min/max 抽取列 + 统计）画成经典多通道
术中式波形视图：
  - 网格 + 时间轴标签 + 每行零线（堆叠布局 — 每通道一行）
  - min/max 包络折线（保留尖峰; 每行独立裁剪, 不串行）
  - 左侧通道名标签（通道色）、悬停十字线 + 数值读数
  - 交互: 滚轮缩放时间窗（由调用方应用）、双击复位
绘制缓存: 按 (版本号, 视口尺寸, 标尺, 行集合) 缓存 ImVec2 点列 —
数据未刷新（冻结/暂停）或窗口未变化时不重建, 渲染帧零 Python 分配。

文本安全: 本文件所有 imgui 文本为 ASCII/安全标点（dev protocol §7 / ui_protocol §12）。
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui

from gtec_display import ScopeFrame  # noqa: F401 — 类型说明用（同目录模块, 由扩展加载器置于 sys.path）

# ── 几何常量（px） ─────────────────────────────────────────
_GUTTER_L = 54.0          # 左侧通道名
_AXIS_H = 16.0            # 底部时间轴
_TOP_PAD = 4.0
_RIGHT_PAD = 6.0

# ── 颜色 ───────────────────────────────────────────────────
_CLR_BG = (0.085, 0.092, 0.110, 1.0)
_CLR_GRID = (0.22, 0.24, 0.28, 1.0)
_CLR_GRID_MAJOR = (0.32, 0.35, 0.40, 1.0)
_CLR_BASELINE = (0.30, 0.34, 0.40, 1.0)
_CLR_DIM = imgui.ImVec4(0.60, 0.60, 0.60, 1.0)
_CLR_READ = imgui.ImVec4(0.95, 0.95, 0.85, 1.0)

_TRACE_PALETTE = (
    (0.40, 0.72, 1.00), (0.47, 0.85, 0.55), (0.95, 0.72, 0.32), (0.88, 0.48, 0.80),
    (0.45, 0.85, 0.90), (0.95, 0.55, 0.45), (0.72, 0.72, 0.95), (0.78, 0.85, 0.45),
    (0.60, 0.82, 0.70), (0.92, 0.62, 0.62), (0.55, 0.68, 0.92), (0.86, 0.86, 0.62),
)

_TICK_CANDIDATES = (0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)

# 点列缓存（单槽 — 单面板视图; key 变化即整体重建）
_cache_key = None
_cache_rows: list = []


def trace_color(index: int) -> imgui.ImVec4:
    """通道色（循环调色板）。"""
    r, g, b = _TRACE_PALETTE[index % len(_TRACE_PALETTE)]
    return imgui.ImVec4(r, g, b, 0.96)


def _col32(rgba) -> int:
    return imgui.get_color_u32(imgui.ImVec4(rgba[0], rgba[1], rgba[2], rgba[3]))


def _text_at(x: float, y: float, text: str, col=None) -> None:
    """在窗口绝对坐标绘制文本（不碰 draw_list 文本路径 — 字型正确）。"""
    imgui.set_cursor_screen_pos(imgui.ImVec2(float(x), float(y)))
    if col is not None:
        imgui.text_colored(col, text)
    else:
        imgui.text(text)


def _pick_xtick(window_s: float) -> float:
    """使 ~6 格的时间刻度（秒）。"""
    want = max(window_s / 6.0, 0.05)
    for t in _TICK_CANDIDATES:
        if t >= want:
            return t
    return _TICK_CANDIDATES[-1]


def draw_scope(frame, plot_key: str = "##gtec_scope", height: float = 0.0) -> dict:
    """绘制波形视口。返回交互结果:

        {"wheel": float, "double_click": bool} — 调用方据此缩放/复位时间窗。

    任务布局: 调用前后光标位置被恢复（占满 (w, h) 的不可见按钮）。
    """
    avail = imgui.get_content_region_avail()
    w = float(avail.x)
    h = float(height if height > 0 else avail.y)
    h = max(60.0, h)
    origin = imgui.get_cursor_screen_pos()

    hovered = imgui.invisible_button(plot_key, imgui.ImVec2(w, h))
    hovered = bool(hovered) and imgui.is_item_hovered()
    dl = imgui.get_window_draw_list()

    left = origin.x + _GUTTER_L
    top = origin.y + _TOP_PAD
    right = origin.x + w - _RIGHT_PAD
    bottom = origin.y + h - _AXIS_H
    plot_w = max(10.0, right - left)
    plot_h = max(10.0, bottom - top)

    dl.add_rect_filled(imgui.ImVec2(origin.x, origin.y), imgui.ImVec2(origin.x + w, origin.y + h),
                       _col32(_CLR_BG))

    result = {"wheel": 0.0, "double_click": False}

    if frame is None or frame.n_view <= 0 or not frame.rows:
        msg = "no waveform yet - open a device and press Start"
        tw = imgui.calc_text_size(msg).x
        _text_at(origin.x + (w - tw) * 0.5, origin.y + h * 0.5 - 8.0, msg, _CLR_DIM)
        imgui.set_cursor_screen_pos(imgui.ImVec2(origin.x, origin.y + h))
        return result

    k = len(frame.rows)
    c = int(frame.mins.shape[1])
    row_h = plot_h / k
    window = frame.window_s

    # ── 网格 + 时间轴 ──────────────────────────────────────
    tick = _pick_xtick(window)
    t = 0.0
    while t <= window + 1e-9:
        x = right - (t / window) * plot_w if window > 0 else right
        major = abs(t / (tick * 5.0) - round(t / (tick * 5.0))) < 1e-6
        dl.add_line(imgui.ImVec2(x, top), imgui.ImVec2(x, bottom),
                    _col32(_CLR_GRID_MAJOR if major else _CLR_GRID), 1.0)
        label = f"-{t:g}s" if t > 0 else "now"
        _text_at(x - 10.0, bottom + 2.0, label, _CLR_DIM)
        t += tick
    for i in range(k + 1):
        y = top + i * row_h
        dl.add_line(imgui.ImVec2(left, y), imgui.ImVec2(right, y), _col32(_CLR_GRID), 1.0)
    # now 游标
    dl.add_line(imgui.ImVec2(right, top), imgui.ImVec2(right, bottom),
                _col32(_CLR_GRID_MAJOR), 1.5)

    # ── 点列缓存（版本/视口/标尺/行集变化才重建） ──────────
    global _cache_key, _cache_rows
    key = (frame.version, round(plot_w, 1), round(plot_h, 1),
           round(frame.scale_uv, 6), tuple(frame.rows))
    if key != _cache_key:
        xs = left + np.linspace(0.0, plot_w, c)
        xs2 = np.repeat(xs, 2).astype(np.float64)
        rows_pts: list = []
        for i, r in enumerate(frame.rows):
            row_center = top + (i + 0.5) * row_h
            k_px = max(0.5, (row_h * 0.5 - 3.0)) / max(1e-9, frame.scale_uv)
            lo = np.asarray(frame.mins[i], dtype=np.float64)
            hi = np.asarray(frame.maxs[i], dtype=np.float64)
            ys = np.empty(2 * c, dtype=np.float64)
            ys[0::2] = row_center - hi * k_px
            ys[1::2] = row_center - lo * k_px
            rows_pts.append([imgui.ImVec2(x, y) for x, y in zip(xs2, ys)])
        _cache_key = key
        _cache_rows = rows_pts

    # ── 逐行: 零线 + 包络折线（行内裁剪, 越界不串行） ─────
    for i, r in enumerate(frame.rows):
        row_top = top + i * row_h
        row_center = row_top + row_h * 0.5
        dl.add_line(imgui.ImVec2(left, row_center), imgui.ImVec2(right, row_center),
                    _col32(_CLR_BASELINE), 1.0)
        dl.push_clip_rect(imgui.ImVec2(left, row_top), imgui.ImVec2(right, row_top + row_h), True)
        dl.add_polyline(_cache_rows[i], imgui.get_color_u32(trace_color(i)), 0, 1.4)
        dl.pop_clip_rect()
        if row_h >= 11.0:
            name = frame.names[r] if r < len(frame.names) else f"ch{r + 1}"
            _text_at(left - _GUTTER_L + 4.0, row_center - 7.0, name, trace_color(i))

    # ── 交互: 滚轮 / 双击 ──────────────────────────────────
    if hovered:
        io = imgui.get_io()
        result["wheel"] = float(io.mouse_wheel)
        if imgui.is_mouse_double_clicked(0):
            result["double_click"] = True

        mx, my = imgui.get_mouse_pos()
        if left <= mx <= right and top <= my <= bottom and c > 1:
            col = int(round((mx - left) / plot_w * (c - 1)))
            col = max(0, min(c - 1, col))
            row_i = max(0, min(k - 1, int((my - top) / row_h)))
            value = 0.5 * (float(frame.mins[row_i, col]) + float(frame.maxs[row_i, col]))
            t_rel = -window + (col / (c - 1)) * window
            dl.add_line(imgui.ImVec2(mx, top), imgui.ImVec2(mx, bottom),
                        _col32((0.85, 0.85, 0.60, 0.55)), 1.0)
            name = frame.names[frame.rows[row_i]] if frame.rows[row_i] < len(frame.names) \
                else f"ch{frame.rows[row_i] + 1}"
            _text_at(mx + 10.0, my - 8.0, f"{name}  {value:+.1f} uV   t {t_rel:+.2f} s", _CLR_READ)

    imgui.set_cursor_screen_pos(imgui.ImVec2(origin.x, origin.y + h))
    return result


def draw_quality_table(frame, table_key: str = "gtec_quality", height: float = 168.0) -> None:
    """通道信号质量表（RMS / 峰峰值 / 相对活跃度条）— 显示行 = 视口行。

    配对纪律: BeginChild/EndChild 无条件配对（全裁剪时 BeginChild 返回 False
    也需 EndChild）; BeginTable 仅在返回 True 时 End。
    """
    child_visible = imgui.begin_child(f"##{table_key}", imgui.ImVec2(0, height), True)
    try:
        if child_visible and (frame is None or not frame.rows):
            imgui.text_disabled("(no data)")
        elif child_visible:
            rows = frame.rows
            rms = frame.stats["rms"]
            ptp = frame.stats["ptp"]
            rms_max = float(np.max(rms)) if len(rms) else 0.0
            flags = imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_inner_h
            table_open = imgui.begin_table(f"##{table_key}_t", 4, flags, imgui.ImVec2(0, 0))
            try:
                if table_open:
                    imgui.table_setup_column("Ch")
                    imgui.table_setup_column("RMS uV")
                    imgui.table_setup_column("P2P uV")
                    imgui.table_setup_column("activity")
                    imgui.table_headers_row()
                    for i, r in enumerate(rows):
                        name = frame.names[r] if r < len(frame.names) else f"ch{r + 1}"
                        frac = float(rms[r]) / rms_max if rms_max > 0 else 0.0
                        imgui.table_next_row()
                        imgui.table_next_column()
                        imgui.text_colored(trace_color(i), name)
                        imgui.table_next_column()
                        imgui.text(f"{float(rms[r]):.1f}")
                        imgui.table_next_column()
                        imgui.text(f"{float(ptp[r]):.1f}")
                        imgui.table_next_column()
                        imgui.progress_bar(max(0.0, min(1.0, frac)), imgui.ImVec2(110, 0), "")
            finally:
                if table_open:
                    imgui.end_table()
    finally:
        imgui.end_child()
