"""Gtec 监视面板 — 显示管线（纯 DSP + 数据模型; headless 可测）。

本模块不触碰 imgui、不触碰设备/服务 —— 输入 = 会话环形缓冲快照
`(channels, capacity)` float32 µV，输出 = 可直接绘制的 `ScopeFrame`
（min/max 抽取列 + 通道统计 + 标尺），供 `gtec_scope`（绘制）与
`extension`（ops / 面板）使用。

滤波策略（经典信号工具做法 — 滑窗 + 预热余量, 无跨帧状态）:
  每次刷新取「显示窗口 + 预热余量」的最新样本，整段做因果 IIR 滤波（notch → band），
  丢弃预热区后得到显示序列。UI 卡顿/跳帧后无需重建状态（余量重新收敛），
  开销 = O(通道 × (窗口 + 余量))，单次刷新毫秒级。

滤波选项（2026-10-12 升级）: 陷波支持谐波组合（50+100 / 60+120）; 频带提供标准
  EEG 频段预设（delta/theta/alpha/beta/gamma + broadband/hp/lp）; IIR 阶数 2/4 可选。

抽取策略: min/max 列抽取（每列取最小值/最大值 — 示波器标准做法, 保留尖峰），
  列数固定 `DECIMATE_COLUMNS`，绘制时逐列形成包络折线。

确定性: 同一输入窗口 + 同一滤波规格 → 同一输出（无随机、无时间依赖），
  便于无头测试与 e2e 数值断言。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy import signal as _sp

# 抽取列数（与示波器视口像素宽同量级; 增大 = 更细腻 + 绘制开销线性增长）
DECIMATE_COLUMNS = 512

# 显示滤波频段预设（面板下拉）与限幅
BAND_TYPES = ("none", "highpass", "lowpass", "bandpass")
NOTCH_CHOICES = ("off", "50", "60", "50+100", "60+120")
# 频带预设（面板下拉; value = (band_type, low, high) — None = 该侧不适用; "custom" 除外）
BAND_PRESETS: dict = {
    "custom": None,
    "broadband 0.5-45": ("bandpass", 0.5, 45.0),
    "broadband 0.5-100": ("bandpass", 0.5, 100.0),
    "delta 0.5-4": ("bandpass", 0.5, 4.0),
    "theta 4-8": ("bandpass", 4.0, 8.0),
    "alpha 8-13": ("bandpass", 8.0, 13.0),
    "beta 13-30": ("bandpass", 13.0, 30.0),
    "gamma 30-80": ("bandpass", 30.0, 80.0),
    "highpass 0.5": ("highpass", 0.5, None),
    "lowpass 45": ("lowpass", None, 45.0),
    "lowpass 100": ("lowpass", None, 100.0),
}

_ORDER = 4                # Butterworth 默认阶数（显示滤波 — 兼顾滚降与瞬态）
_ORDERS = (2, 4)          # 可选阶数（面板/ops）
ORDERS = _ORDERS          # 公开别名（UI/ops 枚举）
_NOTCH_Q = 30.0           # 陷波 Q
_MARGIN_CAP_S = 6.0       # 预热余量上限 (s)


def match_band_preset(band_type, low, high) -> str:
    """当前 (band_type, low, high) 对应的预设名; 无匹配 → "custom"。"""
    for name, spec in BAND_PRESETS.items():
        if spec is None:
            continue
        bt, lo, hi = spec
        if str(band_type) != bt:
            continue
        if (abs(float(low or 0.0) - float(lo or 0.0)) < 1e-6
                and abs(float(high or 0.0) - float(hi or 0.0)) < 1e-6):
            return name
    return "custom"


# ═══════════════════════════════════════════════════════════════
# 显示滤波链（notch → bandpass）
# ═══════════════════════════════════════════════════════════════

class FilterChain:
    """不可变显示滤波链 — `apply` 为纯函数（滑动窗口 + 预热余量语义）。

    `margin` = 预热样本数: apply 的输入应比显示窗口多出 `margin` 个样本，
    调用方丢弃结果尾部之外的预热区（见 `SignalView.refresh`）。
    """

    __slots__ = ("_stages", "margin", "labels", "notes")

    def __init__(self, stages: list, margin: int, labels: list, notes: list) -> None:
        self._stages = list(stages)
        self.margin = int(margin)
        self.labels = list(labels)      # 生效阶段的人类可读标签
        self.notes = list(notes)        # 因无效被跳过的阶段说明

    @property
    def active(self) -> bool:
        return bool(self._stages)

    def apply(self, raw: np.ndarray) -> np.ndarray:
        """逐级 sosfilt（沿时间轴）; 无阶段时原样返回。"""
        if not self._stages:
            return raw
        out = np.asarray(raw, dtype=np.float64)
        for sos in self._stages:
            out = _sp.sosfilt(sos, out, axis=-1)
        return out.astype(np.float32, copy=False)


def sanitize_spec(spec: dict, fs: float) -> dict:
    """容错解析显示滤波规格（非法值回退/跳过, 不抛异常）。

    Returns: {enabled, notch, band_type, low, high, order} — low/high ≤ 0 → None。
    """
    spec = spec or {}
    notch = str(spec.get("notch", "off"))
    if notch not in NOTCH_CHOICES:
        notch = "off"
    band = str(spec.get("band_type", "none"))
    if band not in BAND_TYPES:
        band = "none"
    try:
        order = int(spec.get("order", _ORDER) or _ORDER)
    except (TypeError, ValueError):
        order = _ORDER
    if order not in _ORDERS:
        order = _ORDER

    def _f(key):
        try:
            value = float(spec.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0.0:
            return None
        return value

    return {
        "enabled": bool(spec.get("enabled", False)),
        "notch": notch,
        "band_type": band,
        "low": _f("low") if band in ("highpass", "bandpass") else None,
        "high": _f("high") if band in ("lowpass", "bandpass") else None,
        "order": order,
    }


_build_cache: dict = {}


def build_filter_chain(spec: dict, fs: float) -> FilterChain:
    """按规格构造（带缓存）显示滤波链。

    无效阶段（截止频率缺失/越界/顺序错误, notch ≥ Nyquist）被跳过并记入 notes；
    spec.enabled=False → 空链（apply = 原样透传）。
    设计失败（极端参数）同样跳过该阶段 — 绝不抛异常（面板/干跑安全）。
    """
    spec = sanitize_spec(spec, fs)
    key = (int(fs), spec["enabled"], spec["notch"], spec["band_type"],
           round(spec["low"], 6) if spec["low"] else 0.0,
           round(spec["high"], 6) if spec["high"] else 0.0, spec["order"])
    hit = _build_cache.get(key)
    if hit is not None:
        return hit

    stages: list = []
    labels: list = []
    notes: list = []
    taus: list = []
    order = int(spec["order"])
    nyq = fs / 2.0 * 0.98

    if spec["enabled"] and fs > 0:
        # ── 陷波（支持谐波组合: "50+100"） ──
        if spec["notch"] != "off":
            for f0 in [float(x) for x in str(spec["notch"]).split("+")]:
                if f0 < nyq:
                    try:
                        b, a = _sp.iirnotch(f0, _NOTCH_Q, fs=fs)
                        stages.append(_sp.tf2sos(b, a))
                        labels.append("notch {:g} Hz".format(f0))
                        taus.append(_NOTCH_Q / (math.pi * f0))
                    except Exception as e:  # noqa: BLE001 — 显示滤波绝不阻塞
                        notes.append("notch {:g} Hz skipped: {!r}".format(f0, e))
                else:
                    notes.append("notch {:g} Hz >= Nyquist".format(f0))

        # ── 频带（高通/低通/带通） ──
        band = spec["band_type"]
        low, high = spec["low"], spec["high"]
        if band == "highpass" and low is not None and low < nyq:
            try:
                stages.append(_sp.butter(order, low, btype="highpass", fs=fs, output="sos"))
                labels.append("hp {:g} Hz".format(low))
                taus.append(1.0 / (2.0 * math.pi * low))
            except Exception as e:  # noqa: BLE001
                notes.append("highpass skipped: {!r}".format(e))
        elif band == "lowpass" and high is not None and high < nyq:
            try:
                stages.append(_sp.butter(order, high, btype="lowpass", fs=fs, output="sos"))
                labels.append("lp {:g} Hz".format(high))
                taus.append(1.0 / (2.0 * math.pi * high))
            except Exception as e:  # noqa: BLE001
                notes.append("lowpass skipped: {!r}".format(e))
        elif band == "bandpass":
            if low is None or high is None:
                notes.append("bandpass needs both cutoffs")
            elif not (0 < low < high < nyq):
                notes.append("bandpass cutoffs invalid ({:g}-{:g} Hz)".format(
                    low or 0.0, high or 0.0))
            else:
                try:
                    stages.append(_sp.butter(order, (low, high), btype="bandpass",
                                             fs=fs, output="sos"))
                    labels.append("bp {:g}-{:g} Hz".format(low, high))
                    taus.append(1.0 / (2.0 * math.pi * low))
                except Exception as e:  # noqa: BLE001
                    notes.append("bandpass skipped: {!r}".format(e))
        elif band == "highpass" and low is None:
            notes.append("highpass needs low cutoff")
        elif band == "lowpass" and high is None:
            notes.append("lowpass needs high cutoff")

    margin_s = min(_MARGIN_CAP_S, 3.0 * max(taus)) if taus else 0.0
    margin = int(round(margin_s * fs)) if fs > 0 else 0
    chain = FilterChain(stages, margin, labels, notes)
    _build_cache[key] = chain
    return chain


def clear_cache() -> None:
    """清空滤波链缓存（测试用）。"""
    _build_cache.clear()


# ═══════════════════════════════════════════════════════════════
# 抽取 / 统计 / 标尺
# ═══════════════════════════════════════════════════════════════

def decimate_minmax(trace: np.ndarray, columns: int) -> tuple:
    """(k, n) → (mins, maxs)，形状 (k, c)；每列覆盖连续样本段（保留全部样本）。

    c = min(columns, n)；n == 0 时返回空数组（调用方保证 n ≥ 1）。
    """
    tr = np.asarray(trace)
    k, n = tr.shape
    if n <= 0:
        return (np.zeros((k, 0), dtype=np.float32), np.zeros((k, 0), dtype=np.float32))
    c = int(max(1, min(int(columns), n)))
    if c == n:
        return (tr, tr)
    edges = np.linspace(0, n, c + 1).astype(np.int64)
    idx = edges[:-1]
    mins = np.minimum.reduceat(tr, idx, axis=1)
    maxs = np.maximum.reduceat(tr, idx, axis=1)
    return mins, maxs


def channel_stats(window: np.ndarray) -> dict:
    """(ch, n) → {"mean","rms","ptp"}（float64 数组; 单位 µV）。"""
    w = np.asarray(window, dtype=np.float64)
    if w.ndim != 2 or w.shape[1] == 0:
        z = np.zeros(w.shape[0] if w.ndim == 2 else 0, dtype=np.float64)
        return {"mean": z, "rms": z.copy(), "ptp": z.copy()}
    return {
        "mean": w.mean(axis=1),
        "rms": np.sqrt(np.mean(w * w, axis=1)),
        "ptp": w.max(axis=1) - w.min(axis=1),
    }


def nice_scale(value: float) -> float:
    """向上取 1/1.2/1.5/2/2.5/3/4/5/6/8 × 10^k 的“整齐”标尺值（自动幅度用）。"""
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = value / (10.0 ** exp)
    for m in (1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        if base <= m + 1e-9:
            return float(m * (10.0 ** exp))
    return float(10.0 ** (exp + 1))


# ═══════════════════════════════════════════════════════════════
# ScopeFrame — 一次刷新的可绘制结果
# ═══════════════════════════════════════════════════════════════

class ScopeFrame:
    """单帧可绘制波形（immutable after construction）。"""

    __slots__ = ("version", "fs", "n_view", "rows", "names", "mins", "maxs",
                 "stats", "scale_uv", "auto", "filtered", "filter_labels",
                 "valid", "view")

    def __init__(self, version: int, fs: float, n_view: int, rows: list, names: list,
                 mins, maxs, stats: dict, scale_uv: float, auto: bool,
                 filtered: bool, filter_labels: list, valid: int, view: np.ndarray) -> None:
        self.version = version
        self.fs = fs
        self.n_view = n_view
        self.rows = list(rows)          # 显示行对应的通道号
        self.names = list(names)        # 全通道名
        self.mins = mins                # (k, c) µV — 列最小值
        self.maxs = maxs                # (k, c) µV — 列最大值
        self.stats = stats              # 全通道统计（numpy 数组）
        self.scale_uv = scale_uv        # 每行满量程 ±scale（µV）
        self.auto = auto
        self.filtered = filtered
        self.filter_labels = list(filter_labels)
        self.valid = valid
        self.view = view                # (ch, n_view) 滤波后显示序列（原始分辨率）

    @property
    def window_s(self) -> float:
        return self.n_view / self.fs if self.fs > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
# SignalView — 面板显示状态 + 最近一帧
# ═══════════════════════════════════════════════════════════════

class SignalView:
    """监视面板显示状态（窗口/标尺/通道选择/显示滤波/冻结）+ 最近一帧。

    用法（扩展侧）:
        view.apply_settings(settings_dict)      # 每帧同步面板设置（廉价）
        view.refresh(data, valid, fs, names)    # 录音中定期调用（~20-30 Hz）
        frame = view.frame                      # 绘制/统计
    设置变更（滤波/通道选择）会在下一次 refresh 生效；版本号只在 refresh 时递增，
    绘制缓存据此判断重建。
    """

    def __init__(self) -> None:
        self.window_s = 4.0
        self.amplitude_uv = 0.0        # 0 = 自动
        self.channel_start = 0
        self.channel_count = 8
        self.freeze = False
        self.filter_enabled = False
        self.notch = "off"
        self.band_type = "none"
        self.low = 0.0
        self.high = 0.0
        self.order = 4
        self._frame: Optional[ScopeFrame] = None
        self._version = 0
        self._names: list = []
        self._chain: Optional[FilterChain] = None
        self._chain_key = None

    # ── 状态 ────────────────────────────────────────────────

    @property
    def frame(self) -> Optional[ScopeFrame]:
        return self._frame

    @property
    def version(self) -> int:
        return self._version

    def clear(self) -> None:
        self._frame = None
        self._version = 0
        self._names = []
        self._chain = None
        self._chain_key = None

    def apply_settings(self, disp: dict) -> None:
        """从面板设置字典同步字段（廉价; 滤波链在 refresh 时按 key 重建）。"""
        if not disp:
            return
        self.window_s = float(disp.get("window_s", self.window_s) or self.window_s)
        self.amplitude_uv = float(disp.get("amplitude_uv", self.amplitude_uv) or 0.0)
        self.channel_start = int(disp.get("channel_start", self.channel_start) or 0)
        self.channel_count = int(disp.get("channel_count", self.channel_count) or 1)
        self.freeze = bool(disp.get("freeze", self.freeze))
        self.filter_enabled = bool(disp.get("filter_enabled", self.filter_enabled))
        self.notch = str(disp.get("notch", self.notch) or "off")
        self.band_type = str(disp.get("band_type", self.band_type) or "none")
        self.low = float(disp.get("low", self.low) or 0.0)
        self.high = float(disp.get("high", self.high) or 0.0)
        try:
            order = int(disp.get("order", self.order) or _ORDER)
        except (TypeError, ValueError):
            order = _ORDER
        self.order = order if order in _ORDERS else _ORDER

    def filter_spec(self) -> dict:
        return {
            "enabled": self.filter_enabled,
            "notch": self.notch,
            "band_type": self.band_type,
            "low": self.low,
            "high": self.high,
            "order": self.order,
        }

    def filter_labels(self) -> list:
        chain = self._chain
        return chain.labels if chain is not None else []

    def filter_notes(self) -> list:
        chain = self._chain
        return chain.notes if chain is not None else []

    # ── 刷新（音频/EEG 数据 → 帧） ──────────────────────────

    def refresh(self, data, valid: int, fs: float, names: list) -> Optional[ScopeFrame]:
        """从窗口快照构建显示帧（不修改输入数组）。

        Args:
            data: (channels, capacity) 时间序快照（未填区为 0）。
            valid: 有效样本数（≤ capacity）。
            fs: 采样率 (Hz)。
            names: 通道名（可为 None → 用 ch1..chN 占位）。
        """
        if data is None or fs <= 0 or valid <= 0:
            return self._frame
        arr = np.asarray(data)
        if arr.ndim != 2 or arr.shape[1] == 0:
            return self._frame
        ch = int(arr.shape[0])
        valid = int(min(valid, arr.shape[1]))
        names = list(names) if names else [f"ch{i + 1}" for i in range(ch)]
        self._names = names

        start = max(0, min(int(self.channel_start), ch - 1))
        count = max(1, min(int(self.channel_count), ch - start))
        rows = list(range(start, start + count))

        n_view = int(max(16, min(valid, round(float(self.window_s) * fs))))
        chain = self._ensure_chain(fs)
        margin = chain.margin if chain.active else 0
        n_take = int(min(valid, n_view + margin))
        raw = np.asarray(arr[:, valid - n_take: valid], dtype=np.float32)
        proc = chain.apply(raw) if chain.active else raw
        view = np.ascontiguousarray(proc[:, -n_view:])

        mins, maxs = decimate_minmax(view[rows], DECIMATE_COLUMNS)
        stats = channel_stats(view)

        if self.amplitude_uv > 0:
            scale_uv, auto = float(self.amplitude_uv), False
        else:
            peak = float(np.max(stats["ptp"])) / 2.0 if len(rows) else 1.0
            scale_uv, auto = nice_scale(max(0.5, peak * 1.1)), True

        self._version += 1
        self._frame = ScopeFrame(
            version=self._version, fs=float(fs), n_view=n_view, rows=rows,
            names=names, mins=mins, maxs=maxs, stats=stats, scale_uv=scale_uv,
            auto=auto, filtered=bool(chain.active), filter_labels=list(chain.labels),
            valid=valid, view=view)
        return self._frame

    def _ensure_chain(self, fs: float) -> FilterChain:
        spec = self.filter_spec()
        key = (int(fs), spec["enabled"], spec["notch"], spec["band_type"],
               round(spec["low"] or 0.0, 6), round(spec["high"] or 0.0, 6),
               int(spec["order"]))
        if self._chain is None or self._chain_key != key:
            self._chain = build_filter_chain(spec, fs)
            self._chain_key = key
        return self._chain


# ═══════════════════════════════════════════════════════════════
# agent 通道辅助 — 数值预览（供 ext.gtec.snapshot）
# ═══════════════════════════════════════════════════════════════

def preview_series(frame: Optional[ScopeFrame], max_channels: int = 3,
                   points: int = 128) -> dict:
    """帧 → JSON 友好预览 {t: [...], series: {name: [...]}}（等间隔抽取, 相对秒）。

    时间轴: 最旧 = -window_s, 最新 = 0。无帧 → {"t": [], "series": {}}。
    """
    if frame is None or frame.n_view <= 0 or not frame.rows:
        return {"t": [], "series": {}}
    rows = frame.rows[: max(1, int(max_channels))]
    m = max(2, min(int(points), frame.n_view))
    idx = np.linspace(0, frame.n_view - 1, m).astype(np.int64)
    t = (idx - (frame.n_view - 1)) / frame.fs
    series = {}
    for i, r in enumerate(rows):
        name = frame.names[r] if r < len(frame.names) else f"ch{r + 1}"
        series[name] = [round(float(v), 3) for v in frame.view[r, idx]]
    return {"t": [round(float(v), 4) for v in t], "series": series}
