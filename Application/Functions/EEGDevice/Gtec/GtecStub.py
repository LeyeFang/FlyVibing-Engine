"""
EEGDevice.GtecStub — 空跑后端: 不触硬件、不落盘的确定性数据源。

用途:
  - MCP 干跑验证 (Utils/User/NodeEditor 的 validate_graph → dry_run_simulation,
    ctx.dry_run=True 时节点求值器选用此后端)
  - 无设备环境下跑通完整 Gtec 节点链路 (Init → Start → Get → Stop → Kill)

行为约定:
  - 数据按仿真时间 (ctx.elapsed_time) 合成: 每通道 = 正弦 (频率随通道号) +
    常量偏置 + 慢斜坡 — 幅度/格式与真实 µV float32 数据同形, 完全确定性
    (同一时间轴 → 同一数组, 干跑可复现)
  - 合成总量封顶为环形缓冲容量 (干跑只关心窗口数据, 避免长时间仿真占内存)
  - pump() 由会话在 start/stop/get_data 时调用, 逐块通过 on_block 推入 — 与真实
    后端共用同一条数据通路 (环形缓冲 / 全量录制逻辑被真实验证)
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..Device import DeviceBackend, GtecConfig

# 合成块大小 (samples) — 限制单次生成内存
_SYNTH_CHUNK = 4096


class GtecStubBackend(DeviceBackend):
    """确定性空跑后端 (HIAMP 形状)。"""

    is_stub = True

    def __init__(self) -> None:
        self._cfg: Optional[GtecConfig] = None
        self._recording = False
        self._t0: Optional[float] = None      # 仿真开始时刻 (s)
        self._emitted = 0                     # 已合成样本数
        self._max_samples = 0

    # ── 生命周期 ────────────────────────────────────────────

    def configure(self, cfg: GtecConfig) -> None:
        self._cfg = cfg
        self._max_samples = cfg.buffer_capacity()  # 干跑只合成一个窗口的量

    def start(self, on_block: Callable[[np.ndarray], None], user_block_ms: float = 100.0) -> None:
        self._recording = True
        self._t0 = None       # 首次 pump 时锚定
        self._emitted = 0

    def stop(self) -> None:
        self._recording = False

    def close(self) -> None:
        self._recording = False

    # ── 合成 ────────────────────────────────────────────────

    def pump(self, elapsed_s: float, on_block: Callable[[np.ndarray], None]) -> None:
        """按仿真时间补齐数据并逐块回调。"""
        if not self._recording or self._cfg is None:
            return
        if self._t0 is None:
            self._t0 = float(elapsed_s)
            return
        want = int((float(elapsed_s) - self._t0) * self._cfg.sampling_rate)
        want = max(0, min(want, self._max_samples))
        while self._emitted < want:
            n = min(_SYNTH_CHUNK, want - self._emitted)
            on_block(self._synth(self._emitted, n))
            self._emitted += n

    def _synth(self, start: int, count: int) -> np.ndarray:
        """确定性合成 (count, channels): 正弦 + 通道偏置 + 慢斜坡。"""
        cfg = self._cfg
        assert cfg is not None
        n = (start + np.arange(count, dtype=np.float64))
        t = n / cfg.sampling_rate
        ch_idx = np.arange(cfg.channels, dtype=np.float64)
        freq = 10.0 + np.mod(ch_idx, 10.0) * 2.0                 # 10..28 Hz 每通道
        bias = ch_idx * 3.0                                       # 通道偏置(µV)
        wave = 50.0 * np.sin(2.0 * np.pi * np.outer(t, freq))     # (samples, ch)
        ramp = np.mod(n, 100.0)[:, None] * 0.05
        return (wave + bias[None, :] + ramp).astype(np.float32)

    # ── 阻抗 ────────────────────────────────────────────────

    def get_impedance(self, electrode_type: str = "passive", tms_box: bool = False) -> list:
        """确定性合成阻抗（kΩ 演示分布, 单位 Ω）— 无硬件演示/测试。"""
        from ..Device import synthetic_impedance_ohm

        channels = self._cfg.channels if self._cfg is not None else 64
        return synthetic_impedance_ohm(channels, electrode_type)

    # ── 信息 ────────────────────────────────────────────────

    def info(self) -> dict:
        cfg = self._cfg
        return {
            "backend": type(self).__name__,
            "stub": True,
            "serial": (cfg.serial if cfg else "") or "STUB",
            "device_type": f"{cfg.device if cfg else 'HIAMP'} (stub)",
            "device_information": "dry-run stub — no hardware involved",
        }
