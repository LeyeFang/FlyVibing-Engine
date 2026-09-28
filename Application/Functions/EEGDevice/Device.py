"""
EEGDevice.Device — g.tec EEG 设备集成核心（后端无关，不依赖 pygds）。

职责分离:
  Device.py       配置模型 / 环形缓冲 / 会话 / 注册表 / 落盘     ← 本文件（后端无关）
  Gtec.py         真实后端 — pygds 驱动 g.HIamp（懒导入，无 pygds 时抛出清晰错误）
  GtecStub.py     空跑后端 — 确定性合成数据（MCP 干跑验证、无硬件环境）
  eCon.py         （预留）eConEXG 后端

关键约定（与节点编辑器 / MCP 干跑验证对齐）:
  - 缓冲数组形状 (channels, capacity) float32、单位 µV；快照按时间顺序返回，
    尚未填充的区域为 0（有效样本数 valid 单独给出）
  - 会话以 name 注册到模块级注册表；Start/Stop/Kill/Get 节点按 name 绑定
  - 引擎以自由线程模式运行 (-Xgil=0)，跨线程访问一律加锁
  - 空跑后端绝不触硬件、绝不落盘：保存只计算目标路径并标记 written=False
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

# 模板选项 → 通道数（g.HIamp 144 通道版本: 2×64 + 16）
TEMPLATE_CHOICES: dict[str, int] = {
    "64ch": 64,
    "128ch": 128,
    "144ch": 144,
}

# 设备族选项（当前仅 g.HIamp；后续可加 "NAUTILUS" 等）
DEVICE_CHOICES: tuple[str, ...] = ("HIAMP",)

# g.HIamp 支持的采样率（与设备 GetSupportedSamplingRates 一致）
SUPPORTED_RATES: tuple[int, ...] = (256, 512, 600, 1200, 2400, 4800, 9600, 19200, 38400)

# 缓冲长度保护: 每通道最大样本数（秒 × 采样率超限时截断并告警）
MAX_BUFFER_SAMPLES: int = 4_000_000

# 全量录制内存保护: 超过后仅保留窗口缓冲（防止长时间运行 OOM）
MAX_RECORD_BYTES: int = 2 * 1024 ** 3

# 导出格式
EXPORT_FORMATS: tuple[str, ...] = ("npz", "csv")

# g.tec extended 10-20 64 通道电极名（A1/A2 在 63/64，无 TP9/TP10）
# 来源: GtecAPI/scripts/montages.py（g.Recorder 电极模板 gHIamp_64ch.xml）
TEMPLATE_64: tuple[str, ...] = (
    "Fp1", "Fpz", "Fp2",
    "AF7", "AF3", "AF4", "AF8",
    "F7", "F5", "F3", "F1", "Fz", "F2", "F4", "F6", "F8",
    "FT7", "FC5", "FC3", "FC1", "FCz", "FC2", "FC4", "FC6", "FT8",
    "T7", "C5", "C3", "C1", "Cz", "C2", "C4", "C6", "T8",
    "TP7", "CP5", "CP3", "CP1", "CPz", "CP2", "CP4", "CP6", "TP8",
    "P7", "P5", "P3", "P1", "Pz", "P2", "P4", "P6", "P8",
    "PO7", "PO3", "POz", "PO4", "PO8",
    "O1", "Oz", "O2",
    "F9", "F10", "A1", "A2",
)


def channel_names_for(n_channels: int) -> list[str]:
    """按 g.tec 模板生成通道名；超过 64 的部分用 ch65.. 占位（与 GtecAPI 脚本一致）。"""
    names = list(TEMPLATE_64[: min(n_channels, len(TEMPLATE_64))])
    names += [f"ch{i + 1}" for i in range(len(TEMPLATE_64), n_channels)]
    return names


# ═══════════════════════════════════════════════════════════════
# 配置模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class GtecConfig:
    """InitGtecDevice 节点配置（props → 结构化）。

    滤波器语义（与 UI 提示一致）:
      - filter_type 决定哪些截止频率生效:
          highpass → 只用 low_cut;  lowpass → 只用 high_cut;  bandpass → 两者
      - 截止频率 ≤ 0 视为"未填"→ 不生效
      - 设备仅有预设滤波器对（GetBandpassFilters），匹配失败由后端跳过并告警
    """

    device: str = "HIAMP"          # 设备族（当前仅 HIAMP，可扩展）
    device_name: str = ""          # 会话名（空 = gtec#<node_id>）
    serial: str = ""               # 序列号（空 = 自动选择首个空闲设备）
    template: str = "64ch"         # 64ch / 128ch / 144ch
    sampling_rate: int = 512       # 见 SUPPORTED_RATES
    notch: str = "off"             # off / 50 / 60
    filter_type: str = "none"      # none / highpass / lowpass / bandpass
    low_cut: float = 0.0           # 高通/带通低截止 (Hz)，≤0 = 未填
    high_cut: float = 0.0          # 低通/带通高截止 (Hz)，≤0 = 未填
    export_format: str = "npz"     # npz / csv
    save_dir: str = "."            # 保存目录（默认当前目录）
    buffer_seconds: float = 10.0   # 窗口缓冲秒数 → (channels, 秒×采样率)

    # ── 构造 ────────────────────────────────────────────────

    @classmethod
    def from_props(cls, props: dict) -> "GtecConfig":
        """从节点 props 构造（容错解析，非法值回退默认）。"""

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

        template = str(props.get("template", "64ch"))
        if template not in TEMPLATE_CHOICES:
            template = "64ch"
        rate = _i("sampling_rate", 512)
        if rate not in SUPPORTED_RATES:
            rate = 512
        notch = str(props.get("notch", "off"))
        if notch not in ("off", "50", "60"):
            notch = "off"
        ftype = str(props.get("filter_type", "none"))
        if ftype not in ("none", "highpass", "lowpass", "bandpass"):
            ftype = "none"
        fmt = str(props.get("export_format", "npz"))
        if fmt not in EXPORT_FORMATS:
            fmt = "npz"
        device = str(props.get("device", "HIAMP"))
        if device not in DEVICE_CHOICES:
            device = "HIAMP"

        return cls(
            device=device,
            device_name=str(props.get("device_name", "")).strip(),
            serial=str(props.get("serial", "")).strip(),
            template=template,
            sampling_rate=rate,
            notch=notch,
            filter_type=ftype,
            low_cut=_f("low_cut", 0.0),
            high_cut=_f("high_cut", 0.0),
            export_format=fmt,
            save_dir=str(props.get("save_dir", "")).strip() or ".",
            buffer_seconds=max(0.1, min(600.0, _f("buffer_seconds", 10.0))),
        )

    # ── 派生属性 ────────────────────────────────────────────

    @property
    def channels(self) -> int:
        return TEMPLATE_CHOICES.get(self.template, 64)

    def buffer_capacity(self) -> int:
        """窗口缓冲每通道样本数（上限 MAX_BUFFER_SAMPLES 截断）。"""
        cap = int(round(self.buffer_seconds * self.sampling_rate))
        return max(1, min(cap, MAX_BUFFER_SAMPLES))

    def effective_filters(self) -> dict:
        """解析滤波器请求 → {notch_hz, low, high, note}。

        note 描述因"未填/类型不适用"而被忽略的字段（供日志与文档）。
        """
        low = self.low_cut if self.low_cut > 0 else None
        high = self.high_cut if self.high_cut > 0 else None
        note_parts: list[str] = []

        if self.filter_type == "none":
            if low is not None or high is not None:
                note_parts.append("filter_type=none → 截止频率忽略")
            low = high = None
        elif self.filter_type == "highpass":
            if high is not None:
                note_parts.append("highpass → high_cut 忽略")
            high = None
            if low is None:
                note_parts.append("highpass 未填 low_cut → 不启用")
        elif self.filter_type == "lowpass":
            if low is not None:
                note_parts.append("lowpass → low_cut 忽略")
            low = None
            if high is None:
                note_parts.append("lowpass 未填 high_cut → 不启用")
        elif self.filter_type == "bandpass":
            if low is None and high is None:
                note_parts.append("bandpass 未填截止频率 → 不启用")

        return {
            "notch_hz": None if self.notch == "off" else int(self.notch),
            "low": low,
            "high": high,
            "note": "; ".join(note_parts),
        }

    def summary(self) -> str:
        """单行摘要（日志用）。"""
        f = self.effective_filters()
        notch = f"notch={f['notch_hz']}Hz" if f["notch_hz"] else "notch=off"
        if f["low"] is None and f["high"] is None:
            bp = "bandpass=none"
        else:
            bp = "bandpass={}-{}Hz".format(f["low"] or 0, f["high"] or 0)
        return (
            f"device={self.device} serial={self.serial or 'auto'} "
            f"template={self.template}({self.channels}ch) fs={self.sampling_rate}Hz "
            f"{notch} {bp} buffer={self.buffer_seconds}s({self.buffer_capacity()}) "
            f"export={self.export_format} dir={self.save_dir or '.'}"
        )


# ═══════════════════════════════════════════════════════════════
# 环形缓冲 — 固定形状 (channels, capacity), 时间序快照
# ═══════════════════════════════════════════════════════════════

class RingBuffer:
    """固定容量滑动窗口。

    写入块布局 (samples, channels)（与 pygds GetData 一致）；
    快照布局 (channels, capacity)（与节点 GetGtecData 的数据引脚约定一致）。
    写指针回绕，旧数据被新数据覆盖；所有操作线程安全。
    """

    def __init__(self, channels: int, capacity: int) -> None:
        self.channels = int(channels)
        self.capacity = int(capacity)
        self._buf = np.zeros((self.channels, self.capacity), dtype=np.float32)
        self._lock = threading.Lock()
        self._cursor = 0    # 下一个写入列
        self._written = 0   # 累计写入样本数

    @property
    def valid(self) -> int:
        """当前有效样本数（≤ capacity）。"""
        with self._lock:
            return min(self._written, self.capacity)

    def clear(self) -> None:
        with self._lock:
            self._buf.fill(0.0)
            self._cursor = 0
            self._written = 0

    def push(self, block) -> None:
        """写入一个数据块 (samples, channels)。"""
        b = np.asarray(block, dtype=np.float32)
        if b.ndim == 1:
            b = b.reshape(-1, self.channels)
        if b.shape[1] != self.channels or b.shape[0] == 0:
            return

        with self._lock:
            if b.shape[0] >= self.capacity:
                self._buf[:] = b[-self.capacity:].T
                self._cursor = 0
                self._written += b.shape[0]
                return
            n = b.shape[0]
            first = min(n, self.capacity - self._cursor)
            self._buf[:, self._cursor:self._cursor + first] = b[:first].T
            if n > first:
                self._buf[:, : n - first] = b[first:].T
                self._cursor = n - first
            else:
                self._cursor = (self._cursor + n) % self.capacity
            self._written += n

    def snapshot(self) -> np.ndarray:
        """非销毁快照 — 时间序 (channels, capacity) 副本，未填区为 0。"""
        with self._lock:
            out = np.zeros((self.channels, self.capacity), dtype=np.float32)
            if self._written == 0:
                return out
            if self._written < self.capacity:
                out[:, : self._written] = self._buf[:, : self._written]
                return out
            # 已回绕: cursor 是最老数据列
            c = self._cursor
            if c == 0:
                out[:] = self._buf
            else:
                out[:, : self.capacity - c] = self._buf[:, c:]
                out[:, self.capacity - c:] = self._buf[:, :c]
            return out


# ═══════════════════════════════════════════════════════════════
# 后端接口（真实 / 空跑实现共同遵守）
# ═══════════════════════════════════════════════════════════════

class DeviceBackend:
    """设备后端协议。

    真实后端 (GtecHiampBackend): connect/configure → start 拉起采集线程 →
    stop 结束采集 → close 释放设备。
    空跑后端 (GtecStubBackend): 不触硬件；pump() 按时间合成确定性数据，
    start/stop 只切换状态。
    """

    is_stub: bool = False

    def configure(self, cfg: GtecConfig) -> None:
        raise NotImplementedError

    def start(self, on_block: Callable[[np.ndarray], None], user_block_ms: float = 100.0) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def pump(self, elapsed_s: float, on_block: Callable[[np.ndarray], None]) -> None:
        """空跑后端：按仿真时间补齐数据并回调；真实后端为空操作（数据由采集线程推送）。"""
        return None

    def info(self) -> dict:
        """设备/后端信息（写入导出元数据）。"""
        return {"backend": type(self).__name__, "stub": self.is_stub}


# ═══════════════════════════════════════════════════════════════
# 会 话
# ═══════════════════════════════════════════════════════════════

@dataclass
class SaveResult:
    """保存结果 — paths: 格式/元数据文件路径; written: 是否真正落盘（空跑=False）。"""
    paths: list[str] = field(default_factory=list)
    written: bool = False
    samples: int = 0
    duration_s: float = 0.0


class RecordingSession:
    """单个设备会话 — 配置 / 采集 / 缓冲 / 保存 / 关闭。

    state: configured → recording ⇄ stopped → closed
    """

    def __init__(self, name: str, cfg: GtecConfig, backend: DeviceBackend) -> None:
        self.name = name
        self.cfg = cfg
        self.backend = backend
        self.ring = RingBuffer(cfg.channels, cfg.buffer_capacity())
        self.state = "configured"
        self.started_iso: Optional[str] = None
        self.stopped_iso: Optional[str] = None
        self.backend_info: dict = {}

        self._lock = threading.Lock()
        self._blocks: list[np.ndarray] = []
        self._record_bytes = 0
        self._record_full = False  # 内存保护触发标记

    # ── 采集回调（后端线程调用） ────────────────────────────

    def _on_block(self, block: np.ndarray) -> None:
        self.ring.push(block)
        with self._lock:
            if self.state != "recording":
                return
            if self._record_full:
                return
            nbytes = int(block.size) * 4
            if self._record_bytes + nbytes > MAX_RECORD_BYTES:
                self._record_full = True
                print(f"[Gtec] WARNING: session '{self.name}' full-recording memory cap "
                      f"({MAX_RECORD_BYTES / 1024**3:.1f} GiB) reached — only window buffer updates")
                return
            self._blocks.append(np.array(block, dtype=np.float32, copy=True))
            self._record_bytes += nbytes

    # ── 生命周期 ────────────────────────────────────────────

    def start(self, elapsed_s: float = 0.0) -> None:
        self.state = "recording"
        self.started_iso = _iso_now()
        with self._lock:
            self._blocks.clear()
            self._record_bytes = 0
            self._record_full = False
        self.backend.start(self._on_block)
        # 空跑后端: 在 start 后锚定仿真起点 (真实后端 pump 为 no-op)
        self.backend.pump(elapsed_s, self._on_block)

    def stop(self, save_scope: str = "session", elapsed_s: float = 0.0) -> SaveResult:
        self.backend.pump(elapsed_s, self._on_block)
        self.backend.stop()
        self.state = "stopped"
        self.stopped_iso = _iso_now()
        return self.save(save_scope)

    def kill(self) -> None:
        """强制停止 + 释放设备（不保存）。"""
        try:
            self.backend.stop()
        finally:
            self.backend.close()
        self.state = "closed"

    # ── 数据读取 ────────────────────────────────────────────

    def get_data(self, elapsed_s: float = 0.0) -> dict:
        """非销毁快照 + 元信息。"""
        if self.state == "recording":
            self.backend.pump(elapsed_s, self._on_block)
        data = self.ring.snapshot()
        return {
            "data": data,
            "channels": self.cfg.channels,
            "samples": int(self.ring.valid),
            "capacity": self.ring.capacity,
            "fs": self.cfg.sampling_rate,
            "stub": self.backend.is_stub,
            "state": self.state,
        }

    # ── 保存 ────────────────────────────────────────────────

    def save(self, scope: str = "session") -> SaveResult:
        """按 scope 保存（session = 本次开始以来的全部数据; buffer = 当前窗口）。"""
        scope = scope if scope in ("session", "buffer") else "session"
        if scope == "buffer":
            data = self.ring.snapshot().T  # → (samples, channels)
        else:
            with self._lock:
                blocks = list(self._blocks)
            if blocks:
                data = np.concatenate(blocks, axis=0).astype(np.float32, copy=False)
            else:
                data = np.zeros((0, self.cfg.channels), dtype=np.float32)

        n_samples = int(data.shape[0])
        duration = n_samples / max(1, self.cfg.sampling_rate)
        base = _plan_base_path(self.cfg.save_dir, self.name)

        result = SaveResult(samples=n_samples, duration_s=duration)
        if self.backend.is_stub:
            # 空跑: 只计算目标路径，绝不落盘
            result.paths = [f"{base}.{self.cfg.export_format}", f"{base}.json"]
            return result

        paths = _write_recording(self, data, base, scope)
        result.paths = paths
        result.written = True
        return result

    def meta(self, save_scope: str, n_samples: int, duration_s: float, paths: list[str]) -> dict:
        """导出元数据（与 GtecAPI 脚本的 JSON 风格对齐）。"""
        f = self.cfg.effective_filters()
        info = self.backend.info()
        return {
            "source": "MyGameEngine.NodeEditor",
            "device": self.cfg.device,
            "device_name": self.name,
            "serial": info.get("serial", self.cfg.serial),
            "device_type": info.get("device_type", self.cfg.device),
            "device_information": info.get("device_information", ""),
            "sampling_rate_hz": self.cfg.sampling_rate,
            "channels_acquired": self.cfg.channels,
            "template": self.cfg.template,
            "channel_names": channel_names_for(self.cfg.channels),
            "notch_hz": f["notch_hz"],
            "notch_filter_index": info.get("notch_filter_index"),
            "bandpass_hz": [f["low"], f["high"]],
            "bandpass_filter_index": info.get("bandpass_filter_index"),
            "filter_note": f["note"],
            "trigger": "enabled (16 lines combined into one extra channel)",
            "buffer_seconds": self.cfg.buffer_seconds,
            "buffer_capacity_samples": self.ring.capacity,
            "save_scope": save_scope,
            "samples_saved": n_samples,
            "duration_s": duration_s,
            "started_iso": self.started_iso,
            "stopped_iso": self.stopped_iso,
            "mode": "stub (dry-run)" if self.backend.is_stub else "device",
            "files": paths,
            "units": "uV (float32, as delivered by GDS)",
        }


# ═══════════════════════════════════════════════════════════════
# 会话注册表（模块级）
# ═══════════════════════════════════════════════════════════════

_REGISTRY: dict[str, RecordingSession] = {}
_REG_LOCK = threading.Lock()


def register_session(session: RecordingSession) -> None:
    with _REG_LOCK:
        _REGISTRY[session.name] = session


def unregister_session(name: str) -> None:
    with _REG_LOCK:
        _REGISTRY.pop(name, None)


def get_session(name: str) -> Optional[RecordingSession]:
    with _REG_LOCK:
        return _REGISTRY.get(name)


def resolve_session(name: str) -> tuple[Optional[RecordingSession], str]:
    """按名称解析会话；空名称且仅有一个会话时自动绑定。

    Returns: (session | None, 失败原因)
    """
    name = (name or "").strip()
    with _REG_LOCK:
        if name:
            s = _REGISTRY.get(name)
            if s is None:
                known = ", ".join(_REGISTRY) or "(none)"
                return None, f"device '{name}' not registered (known: {known})"
            return s, ""
        if len(_REGISTRY) == 1:
            return next(iter(_REGISTRY.values())), ""
        if not _REGISTRY:
            return None, "no Gtec device registered — add/execute an InitGtecDevice node first"
        known = ", ".join(_REGISTRY)
        return None, f"multiple Gtec devices registered ({known}) — set device_name to select one"


def list_sessions() -> list[str]:
    with _REG_LOCK:
        return sorted(_REGISTRY)


def close_all() -> int:
    """关闭所有会话（不保存）— Runtime 停止/异常保护用。返回关闭数量。"""
    with _REG_LOCK:
        sessions = list(_REGISTRY.values())
        _REGISTRY.clear()
    for s in sessions:
        try:
            s.kill()
        except Exception as e:  # pragma: no cover - 保护性
            print(f"[Gtec] close_all: kill '{s.name}' failed: {e}")
    return len(sessions)


# ═══════════════════════════════════════════════════════════════
# 落盘辅助
# ═══════════════════════════════════════════════════════════════

_NAME_SAFE = re.compile(r"[^0-9A-Za-z_.-]+")


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _plan_base_path(save_dir: str, device_name: str) -> str:
    """生成 <dir>/<safe_name>_<stamp> 基础路径（不含扩展名）。"""
    d = (save_dir or ".").strip() or "."
    safe = _NAME_SAFE.sub("_", device_name) or "gtec"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(d, f"{safe}_{stamp}")


def _write_recording(session: RecordingSession, data: np.ndarray, base: str, scope: str) -> list[str]:
    """写出数据文件 + JSON 元数据。返回实际写入的文件路径列表。"""
    paths: list[str] = []
    try:
        os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)

        fmt = session.cfg.export_format
        if fmt == "csv":
            data_path = f"{base}.csv"
            names = channel_names_for(session.cfg.channels)
            header = ",".join(["sample"] + names)
            with open(data_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(header + "\n")
                for i in range(data.shape[0]):
                    row = data[i]
                    fh.write(str(i) + "," + ",".join(f"{v:.6g}" for v in row) + "\n")
        else:
            data_path = f"{base}.npz"
            np.savez_compressed(
                data_path,
                data=data,
                fs=session.cfg.sampling_rate,
                channel_names=np.asarray(channel_names_for(session.cfg.channels)),
                serial=session.backend_info.get("serial", session.cfg.serial),
                duration_s=data.shape[0] / max(1, session.cfg.sampling_rate),
            )
        paths.append(data_path)

        meta = session.meta(scope, int(data.shape[0]),
                            data.shape[0] / max(1, session.cfg.sampling_rate), [data_path])
        json_path = f"{base}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, ensure_ascii=False)
        paths.append(json_path)

        print(f"[Gtec] saved {data.shape[0]} samples x {data.shape[1]} ch "
              f"({data.shape[0] / max(1, session.cfg.sampling_rate):.2f}s) → {data_path}")
    except OSError as e:
        print(f"[Gtec] ERROR: save failed: {e}")
    return paths
