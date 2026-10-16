"""virtual_display — 显示管线（纯 DSP，无 imgui — 可被无头测试直接导入）。

职责（与面板解耦, 对应 Gtec 监视面板设计语言中的 gtec_display 一职）:

  - 显示滤波链: 陷波（工频 off/50/60） + 频带（highpass / lowpass / bandpass,
    2/4 阶巴特沃斯; **因果 IIR、非零相位** — 实时工具语义, 离线分析请用离线工具链）;
  - min/max 抽取: (channels, N) → 每列一对极值（保尖峰, 绘制预算内）;
  - 通道统计: RMS / 峰峰值 / 均值（µV, 原始幅度口径）;
  - 标尺: 1-2-5 阶梯（自动幅度档）;
  - 数值预览: 等间隔抽取（agent 断言通道, JSON 友好）。

约束: 纯 numpy/scipy; 不 import 引擎; 不 import imgui。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfilt

NOTCH_CHOICES = ("off", "50", "60")
BAND_TYPES = ("none", "highpass", "lowpass", "bandpass")
ORDERS = (2, 4)
MAX_COLS = 480          # 抽取目标列数上限（绘制预算）
STATS_ROWS = 16         # 统计表展示行数上限


# ════════════════════════════════════════════════════════════════
# 滤波设置
# ════════════════════════════════════════════════════════════════

def _pos_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) and f > 0.0 else default


def sanitize_filters(d) -> dict:
    """显示滤波设置 → 合法值（非法回退默认; 纯数据, 供面板/ops 共用）。"""
    d = dict(d or {})
    notch = str(d.get("notch", "off"))
    if notch not in NOTCH_CHOICES:
        notch = "off"
    btype = str(d.get("filter_type", "none"))
    if btype not in BAND_TYPES:
        btype = "none"
    try:
        order = int(d.get("order", 4))
    except (TypeError, ValueError):
        order = 4
    if order not in ORDERS:
        order = 4
    return {
        "enabled": bool(d.get("enabled", False)),
        "notch": notch,
        "filter_type": btype,
        "low": _pos_float(d.get("low", 0.0)),
        "high": _pos_float(d.get("high", 0.0)),
        "order": order,
    }


def build_filter_chain(filters, fs: int):
    """(合法设置, 采样率) → (sos 级联列表, note)。未启用/无可生效滤波器 → ([], note)。"""
    f = sanitize_filters(filters)
    if not f["enabled"] or fs <= 0:
        return [], ""
    nyq = fs / 2.0
    stages: list = []
    notes: list = []

    if f["notch"] in ("50", "60"):
        f0 = float(f["notch"])
        if f0 + 2.0 < nyq:
            stages.append(butter(2, [f0 - 2.0, f0 + 2.0], btype="bandstop", fs=fs, output="sos"))
        else:
            notes.append(f"notch {f0}Hz skipped (Nyquist)")

    bt, low, high = f["filter_type"], f["low"], f["high"]
    if bt == "highpass" and low > 0.0:
        stages.append(butter(f["order"], min(low, nyq * 0.999),
                             btype="highpass", fs=fs, output="sos"))
    elif bt == "lowpass" and high > 0.0:
        stages.append(butter(f["order"], min(high, nyq * 0.999),
                             btype="lowpass", fs=fs, output="sos"))
    elif bt == "bandpass" and low > 0.0 and high > low:
        hi = min(high, nyq * 0.999)
        if hi > low:
            stages.append(butter(f["order"], [low, hi], btype="bandpass", fs=fs, output="sos"))
    elif bt != "none":
        notes.append(f"band '{bt}' incomplete (low={low}, high={high})")

    return stages, "; ".join(notes)


def apply_chain(data: np.ndarray, stages) -> np.ndarray:
    """逐级因果滤波 (channels, N); 无滤波器 = 拷贝返回。"""
    out = np.array(data, dtype=np.float32, copy=True)
    for sos in stages:
        out = np.asarray(sosfilt(sos, out, axis=1), dtype=np.float32)
    return out


# ════════════════════════════════════════════════════════════════
# 抽取 / 统计 / 标尺 / 预览
# ════════════════════════════════════════════════════════════════

def decimate_minmax(data: np.ndarray, target_cols: int = MAX_COLS):
    """(ch, N) → (mins, maxs, cols): 每列一对极值（保尖峰）。空数据 → (空, 空, 0)。"""
    ch, n = data.shape
    if n == 0:
        z = np.zeros((ch, 0), dtype=np.float32)
        return z, z, 0
    cols = max(1, min(int(target_cols), n))
    width = int(math.ceil(n / cols))
    pad = cols * width - n
    if pad:
        data = np.concatenate([data, np.zeros((ch, pad), dtype=np.float32)], axis=1)
    blocks = data.reshape(ch, cols, width)
    return (blocks.min(axis=2).astype(np.float32),
            blocks.max(axis=2).astype(np.float32), cols)


def channel_stats(data: np.ndarray) -> list:
    """[(rms, ptp, mean), ...] per channel（µV）; 无数据 → 全 0。"""
    ch = data.shape[0] if data is not None and data.ndim == 2 else 0
    if ch == 0 or data.shape[1] == 0:
        return [(0.0, 0.0, 0.0)] * ch
    d = np.asarray(data, dtype=np.float32)
    rms = np.sqrt(np.mean(d * d, axis=1))
    ptp = d.max(axis=1) - d.min(axis=1)
    mean = d.mean(axis=1)
    return [(round(float(r), 2), round(float(p), 2), round(float(m), 2))
            for r, p, m in zip(rms, ptp, mean)]


def nice_scale(value: float) -> float:
    """向上取 1-2-5 阶梯标尺（自动幅度档）。"""
    v = abs(float(value))
    if not math.isfinite(v) or v <= 0.0:
        return 1.0
    exp = math.floor(math.log10(v))
    base = v / (10.0 ** exp)
    step = 1.0 if base <= 1.0 else 2.0 if base <= 2.0 else 5.0 if base <= 5.0 else 10.0
    return step * (10.0 ** exp)


def preview_series(data: np.ndarray, samples: int, points: int = 128,
                   channels: int = 3) -> dict:
    """等间隔数值预览: {"ch1": [..], ...}（JSON 友好; agent 数值断言通道）。"""
    out: dict = {}
    if data is None or data.ndim != 2 or data.shape[0] == 0:
        return out
    n = max(0, min(int(samples), data.shape[1]))
    k = max(1, min(int(channels), data.shape[0]))
    for c in range(k):
        if n == 0:
            out[f"ch{c + 1}"] = []
            continue
        idx = np.linspace(0, n - 1, min(int(points), n)).astype(int)
        out[f"ch{c + 1}"] = [round(float(v), 2) for v in data[c, idx]]
    return out


# ════════════════════════════════════════════════════════════════
# 视图状态 — 原始快照 → 滤波 → 抽取/统计（缓存 + 版本号）
# ════════════════════════════════════════════════════════════════

class SignalView:
    """显示视图 — 面板只读这里的结果; 刷新节流与拉取在面板侧。"""

    def __init__(self, fs: int = 512) -> None:
        self.fs = int(fs or 512)
        self.version = 0
        self.samples = 0
        self.cols = 0
        self.mins: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self.maxs: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self.stats: list = []
        self.note = "no session - click Open"
        self._raw: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    # ── 生命周期 ────────────────────────────────────────────

    def reset(self, fs: int) -> None:
        self.__init__(fs)

    # ── 刷新 / 重建 ─────────────────────────────────────────

    def refresh(self, raw: np.ndarray, samples: int, filters) -> None:
        """拉取到新快照后调用: 保存原始窗口 + 走显示管线。"""
        if raw is None or raw.ndim != 2 or raw.shape[0] == 0:
            self.mins = self.maxs = np.zeros((0, 0), dtype=np.float32)
            self.cols = self.samples = 0
            self.stats = []
            self.note = "waiting for data..."
            self.version += 1
            return
        n = max(0, min(int(samples), raw.shape[1]))
        self._raw = np.array(raw[:, :n], dtype=np.float32, copy=True)
        self._rebuild(filters)

    def rebuild(self, filters) -> None:
        """冻结/设置变更时的即时重建（不拉新数据）。"""
        if self._raw.size == 0 and self._raw.shape[1] == 0:
            self.version += 1
            return
        self._rebuild(filters)

    def _rebuild(self, filters) -> None:
        if self._raw.shape[1] == 0:
            self.cols = self.samples = 0
            self.stats = channel_stats(self._raw)
            self.note = "waiting for data..."
            self.version += 1
            return
        stages, note = build_filter_chain(filters, self.fs)
        disp = apply_chain(self._raw, stages)
        self.mins, self.maxs, self.cols = decimate_minmax(disp)
        self.samples = int(self._raw.shape[1])
        self.stats = channel_stats(self._raw)   # 统计 = 原始幅度口径
        self.note = note
        self.version += 1
