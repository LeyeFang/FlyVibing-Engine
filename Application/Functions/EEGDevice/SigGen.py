"""
EEGDevice.SigGen — 虚拟信号发生器 (纯软件正弦波信号源)。

用途:
  - 设备体系端到端验证: 创建 → 采集 → 保存 → 销毁, 不依赖任何硬件;
  - 后续算法节点的开发基座 (确定性信号 → 可复现的算法测试)。

设计 (与 Gtec/GtecStub 同族的单一后端):
  - VirtualSigGenBackend 一份代码两种模式:
      dry_run=True  → 干跑: 确定性合成、不落盘、不起线程 (is_stub 动态为 True);
      dry_run=False → 真实: 合成 + 走 RecordingSession 完整落盘通路 (is_stub=False)。
  - 数据 (samples, channels) float32 µV: 通道 i = amplitude × sin(2π (f0 + i·Δf) t)
    (可选高斯噪声; seed 固定 → 同时间轴同参数 → 同一数组, 完全确定性)。
  - pump() 由会话在 start/stop/get_data 时按仿真时间补齐 — 与真实后端共用数据通路
    (环形缓冲 / 全量录制 / npz/csv 导出一并被验证)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .Device import DeviceBackend, MAX_BUFFER_SAMPLES

# 合成块大小 (samples) — 限制单次生成内存
_SYNTH_CHUNK = 4096

_CHANNEL_MAX = 256     # 通道数上限
_RATE_MAX = 38400      # 采样率上限 (Hz)


@dataclass
class SigGenConfig:
    """InitSigGenDevice 节点配置 (props → 结构化)。

    钳位规则 (from_props):
      - channels: 1..256 (默认 8);  sampling_rate: 1..38400 (默认 512)
      - frequency: >0 且 ≤ Nyquist, ≤0 视为"未填"→ 默认 10Hz
      - freq_step: ≥0 (通道 i 的频率 = f0 + i·step; 0 = 全通道同频)
      - amplitude_uv / noise_uv: ≥0 (noise=0 → 纯正弦)
    """

    device: str = "VIRTUAL"
    device_name: str = ""
    channels: int = 8
    sampling_rate: int = 512
    frequency: float = 10.0        # 基频 (Hz)
    freq_step: float = 2.0         # 通道间频率步进 (Hz)
    amplitude_uv: float = 50.0     # 正弦幅度 (µV)
    noise_uv: float = 0.0          # 高斯噪声 RMS (µV); 0 = 纯净正弦
    seed: int = 0                  # 噪声种子 (确定性)
    export_format: str = "npz"     # npz / csv
    save_dir: str = "."            # 保存目录 (默认当前目录)
    buffer_seconds: float = 10.0   # 窗口缓冲秒数
    serial: str = "VIRTUAL"        # 元数据占位 (无真实串口)

    # ── 构造 ────────────────────────────────────────────────

    @classmethod
    def from_props(cls, props: dict) -> "SigGenConfig":
        """从节点 props 构造 (容错解析, 非法值回退默认/钳位)。"""

        def _f(key: str, default: float) -> float:
            try:
                return float(props.get(key, default))
            except (TypeError, ValueError):
                return default

        def _i(key: str, default: int) -> int:
            try:
                return int(float(props.get(key, default)))
            except (TypeError, ValueError):
                return default

        channels = max(1, min(_CHANNEL_MAX, _i("channels", 8)))
        rate = max(1, min(_RATE_MAX, _i("sampling_rate", 512)))
        freq = _f("frequency", 10.0)
        if freq <= 0.0:
            freq = 10.0
        freq = min(freq, rate / 2.0)
        step = max(0.0, min(_f("freq_step", 2.0), rate / 2.0))
        amp = max(0.0, _f("amplitude_uv", 50.0))
        noise = max(0.0, _f("noise_uv", 0.0))
        fmt = str(props.get("export_format", "npz"))
        if fmt not in ("npz", "csv"):
            fmt = "npz"

        return cls(
            device_name=str(props.get("device_name", "")).strip(),
            channels=channels,
            sampling_rate=rate,
            frequency=freq,
            freq_step=step,
            amplitude_uv=amp,
            noise_uv=noise,
            seed=_i("seed", 0),
            export_format=fmt,
            save_dir=str(props.get("save_dir", "")).strip() or ".",
            buffer_seconds=max(0.1, min(600.0, _f("buffer_seconds", 10.0))),
        )

    # ── 派生属性 ────────────────────────────────────────────

    @property
    def template(self) -> str:
        """兼容 RecordingSession.meta 的模板字段。"""
        return f"{self.channels}ch"

    def buffer_capacity(self) -> int:
        """窗口缓冲每通道样本数（上限 MAX_BUFFER_SAMPLES 截断）。"""
        cap = int(round(self.buffer_seconds * self.sampling_rate))
        return max(1, min(cap, MAX_BUFFER_SAMPLES))

    def effective_filters(self) -> dict:
        """兼容 meta 导出 — 虚拟设备无硬件滤波器。"""
        return {"notch_hz": None, "low": None, "high": None,
                "note": "virtual signal generator — no hardware filters"}

    def summary(self) -> str:
        """单行摘要（日志用）。"""
        return (
            f"device=VIRTUAL name={self.device_name or 'auto'} "
            f"channels={self.channels} fs={self.sampling_rate}Hz "
            f"f0={self.frequency}Hz dF={self.freq_step}Hz amp={self.amplitude_uv}uV "
            f"noise={self.noise_uv}uV seed={self.seed} "
            f"buffer={self.buffer_seconds}s({self.buffer_capacity()}) "
            f"export={self.export_format} dir={self.save_dir or '.'}"
        )


class VirtualSigGenBackend(DeviceBackend):
    """虚拟信号发生器后端 — 纯软件正弦源。

    dry_run=False (真实): 无限合成 (受会话层 2GiB 录制保护), 保存时真正落盘;
    dry_run=True  (干跑): 合成总量封顶为窗口容量, 不落盘 (is_stub 动态为 True)。
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry = bool(dry_run)
        self._cfg: Optional[SigGenConfig] = None
        self._recording = False
        self._t0: Optional[float] = None
        self._emitted = 0
        self._max_samples = 0            # 0 = 不限 (真实模式)
        self._rng: Optional[np.random.Generator] = None

    @property
    def is_stub(self) -> bool:  # type: ignore[override] — 干跑时参与"不落盘"判定
        return self._dry

    # ── 生命周期 ────────────────────────────────────────────

    def configure(self, cfg: SigGenConfig) -> None:
        self._cfg = cfg
        self._max_samples = cfg.buffer_capacity() if self._dry else 0

    def start(self, on_block: Callable[[np.ndarray], None], user_block_ms: float = 100.0) -> None:
        self._recording = True
        self._t0 = None                  # 首次 pump 时锚定 (device_io_protocol §4 时序)
        self._emitted = 0
        seed = int(self._cfg.seed) if self._cfg is not None else 0
        self._rng = np.random.default_rng(seed)

    def stop(self) -> None:
        self._recording = False

    def close(self) -> None:
        self._recording = False

    # ── 合成 ────────────────────────────────────────────────

    def pump(self, elapsed_s: float, on_block: Callable[[np.ndarray], None]) -> None:
        """按仿真时间补齐数据并逐块回调。"""
        if not self._recording or self._cfg is None:
            return
        elapsed = float(elapsed_s)
        if self._t0 is None:
            self._t0 = elapsed
            return
        want = int((elapsed - self._t0) * self._cfg.sampling_rate)
        want = max(0, want)
        if self._max_samples > 0:
            want = min(want, self._max_samples)
        while self._emitted < want:
            n = min(_SYNTH_CHUNK, want - self._emitted)
            on_block(self._synth(self._emitted, n))
            self._emitted += n

    def _synth(self, start: int, count: int) -> np.ndarray:
        """确定性合成 (count, channels): 正弦 + 可选高斯噪声。"""
        cfg = self._cfg
        assert cfg is not None
        idx = start + np.arange(count, dtype=np.float64)
        t = idx / float(cfg.sampling_rate)
        ch_idx = np.arange(cfg.channels, dtype=np.float64)
        freqs = cfg.frequency + ch_idx * cfg.freq_step          # 通道 i: f0 + i·Δf
        wave = cfg.amplitude_uv * np.sin(2.0 * np.pi * np.outer(t, freqs))
        if cfg.noise_uv > 0.0 and self._rng is not None:
            wave = wave + self._rng.normal(0.0, cfg.noise_uv,
                                           size=(count, cfg.channels))
        return wave.astype(np.float32)

    # ── 信息 ────────────────────────────────────────────────

    def info(self) -> dict:
        cfg = self._cfg
        if cfg is None:
            return {"backend": type(self).__name__, "stub": self._dry}
        return {
            "backend": type(self).__name__,
            "stub": self._dry,
            "serial": cfg.serial,
            "device_type": "VirtualSigGen" + (" (dry-run)" if self._dry else ""),
            "device_information": (
                f"virtual signal generator: {cfg.channels}ch @ {cfg.sampling_rate}Hz, "
                f"f0={cfg.frequency}Hz +{cfg.freq_step}Hz/ch, "
                f"amp={cfg.amplitude_uv}uV, noise={cfg.noise_uv}uV, seed={cfg.seed}"
            ),
        }
