"""
EEGDevice.Gtec — 真实后端: 通过 pygds (g.NEEDaccess Python Client API) 驱动 g.HIamp。

要点:
  - pygds 只在 configure() 内懒导入 — 模块导入本身零重依赖
    (pygds 依赖 cffi / pywin32 / matplotlib; 运行于 Gtec 自有环境的服务进程内,
     引擎侧不安装 — 见 Gtec/README.md + ServiceHost/ServiceClient)
  - 依赖 Windows 服务 GDS 运行 + 设备空闲 (未被 g.Recorder / g.SCOPE 占用)
  - pygds 1.24.0 已知 bug: GDS(DEVICE_TYPE_*) 会 UnboundLocalError → 必须传序列号字符串
  - Trigger 固定启用 (16 条数字线合并为 1 个附加通道 — "combine trigger")
  - 设备滤波器是离散预设对 (GetBandpassFilters / GetNotchFilters)；
    用户填写的截止频率匹配不到预设时跳过并告警 (不阻塞采集)

数据流: 采集线程 (worker) 调 d.GetData(user_block, more)，more 回调逐块
推送给会话 (_on_block) → 环形缓冲 + 全量录制。stop() 使 more 返回 False,
GetData 内部随即将 StopStreaming / StopAcquisition 收尾。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

from ..Device import DeviceBackend, GtecConfig


class GtecUnavailable(RuntimeError):
    """设备不可用（pygds 缺失 / GDS 服务未运行 / 无空闲设备 / 配置被拒）。"""


# ═══════════════════════════════════════════════════════════════
# pygds 懒加载与设备发现
# ═══════════════════════════════════════════════════════════════

def _load_pygds():
    """懒导入 pygds；失败时抛出带指引的清晰错误。"""
    try:
        import pygds  # noqa: F401
        return pygds
    except Exception as e:  # ImportError / DLL 加载失败等
        raise GtecUnavailable(
            "pygds 不可用（{}）。真实采集需在 Gtec 自有环境中运行本模块的服务进程"
            "（见 Gtec/README.md 的启动命令），并确保 Windows 服务 GDS 正在运行。".format(e)
        )


def probe_environment() -> dict:
    """环境自检 — 供日志/UI 使用（不抛异常）。"""
    info: dict = {"pygds": False, "gds_service": None, "devices": []}
    try:
        import win32serviceutil  # type: ignore

        info["gds_service"] = bool(win32serviceutil.QueryServiceStatus("GDS")[1] == 4)
    except Exception:
        info["gds_service"] = None
    try:
        import pygds

        info["pygds"] = True
        try:
            info["devices"] = [name for name, _t, inuse in pygds.ConnectedDevices() if not inuse]
        except Exception:
            pass
    except Exception:
        pass
    return info


def _find_free_hiamp(pygds) -> Optional[str]:
    """返回一个已连接且空闲的 g.HIamp 序列号；无则 None。"""
    hiamp_type = getattr(pygds, "DEVICE_TYPE_GHIAMP", 2)
    for name, dev_type, inuse in pygds.ConnectedDevices():
        if not inuse and dev_type == hiamp_type:
            return name
    return None


# ═══════════════════════════════════════════════════════════════
# 滤波器查找（离散预设匹配；找不到返回 None + 原因）
# ═══════════════════════════════════════════════════════════════

def _find_notch_index(d, rate: int, mains: int, tol: float = 2.0):
    """返回 (index | None, 说明)。mains 为 50/60。"""
    try:
        cands = [f for f in d.GetNotchFilters()[0] if f.get("SamplingRate") == rate]
    except Exception as e:
        return None, f"GetNotchFilters failed: {e}"
    for f in cands:
        center = 0.5 * (f.get("LowerCutoffFrequency", 0.0) + f.get("UpperCutoffFrequency", 0.0))
        if abs(center - mains) <= tol:
            return f["NotchFilterIndex"], f"notch {mains}Hz @ {rate}Hz → #{f['NotchFilterIndex']}"
    return None, f"no {mains}Hz notch preset at {rate}Hz (skipped)"


def _find_bandpass_index(d, rate: int, low: Optional[float], high: Optional[float], tol: float = 0.005):
    """返回 (index | None, 说明)。low/high 为 None 表示该侧未启用（匹配 0 截止）。"""
    want_low = 0.0 if low is None else float(low)
    want_high = 0.0 if high is None else float(high)
    try:
        cands = [f for f in d.GetBandpassFilters()[0] if f.get("SamplingRate") == rate]
    except Exception as e:
        return None, f"GetBandpassFilters failed: {e}"
    for f in cands:
        if (abs(f.get("LowerCutoffFrequency", -1.0) - want_low) <= tol
                and abs(f.get("UpperCutoffFrequency", -1.0) - want_high) <= tol):
            return f["BandpassFilterIndex"], f"bandpass {want_low}-{want_high}Hz @ {rate}Hz → #{f['BandpassFilterIndex']}"
    return None, f"no bandpass preset {want_low}-{want_high}Hz at {rate}Hz (skipped)"


# ═══════════════════════════════════════════════════════════════
# 真实后端
# ═══════════════════════════════════════════════════════════════

class GtecHiampBackend(DeviceBackend):
    """g.HIamp 真实后端 — pygds 连接 + 配置下发 + 采集线程。"""

    is_stub = False

    def __init__(self) -> None:
        self._d = None
        self._cfg: Optional[GtecConfig] = None
        self._serial: str = ""
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._user_block: int = 256
        self._filter_info: dict = {}

    # ── 连接 + 配置 ─────────────────────────────────────────

    def configure(self, cfg: GtecConfig) -> None:
        pygds = _load_pygds()
        self._cfg = cfg

        serial = cfg.serial or _find_free_hiamp(pygds)
        if serial is None:
            raise GtecUnavailable(
                "未找到空闲的 g.HIamp — 请确认设备开机且未被其他程序占用 "
                "(g.Recorder / g.SCOPE / 其他会话)"
            )
        # pygds 1.24 bug: 必须传序列号字符串（传 DEVICE_TYPE_* 整型会 UnboundLocalError）
        self._d = pygds.GDS(serial)
        self._serial = serial
        d = self._d

        # ── 采样率 + 设备块大小 ──
        rates = d.GetSupportedSamplingRates()[0]  # {rate: 推荐 NumberOfScans}
        if cfg.sampling_rate not in rates:
            raise GtecUnavailable(
                f"采样率 {cfg.sampling_rate}Hz 不受支持；可选: {sorted(rates)}"
            )
        d.SamplingRate = cfg.sampling_rate
        d.NumberOfScans = rates[cfg.sampling_rate]

        # ── 触发 (固定启用 + combine) / 计数器 / Hold ──
        d.Counter = 0
        d.Trigger = 1        # g.HIamp: TriggerLinesEnabled — 16 线合并为 1 附加通道
        d.HoldEnabled = 0

        # ── 在线滤波（离散预设匹配） ──
        f = cfg.effective_filters()
        notch_index = -1
        if f["notch_hz"]:
            idx, msg = _find_notch_index(d, cfg.sampling_rate, f["notch_hz"])
            print(f"[Gtec] {msg}")
            if idx is not None:
                notch_index = idx
        bp_index = -1
        if f["low"] is not None or f["high"] is not None:
            idx, msg = _find_bandpass_index(d, cfg.sampling_rate, f["low"], f["high"])
            print(f"[Gtec] {msg}")
            if idx is not None:
                bp_index = idx
        if f["note"]:
            print(f"[Gtec] filter note: {f['note']}")

        # ── 通道: 前 N 开启 + 滤波索引 + GND 参考 ──
        for i, ch in enumerate(d.Channels):
            ch.Acquire = 1 if i < cfg.channels else 0
            ch.BandpassFilterIndex = bp_index
            ch.NotchFilterIndex = notch_index
            ch.BipolarChannel = 0  # 0 = GND 参考

        # ── 可用性核对（combine=False = 硬件真实可用性） ──
        try:
            available = list(d.GetAvailableChannels(combine=False)[0])
            missing = [i + 1 for i in range(cfg.channels)
                       if i < len(available) and not available[i]]
            if missing:
                print(f"[Gtec] WARNING: channels not available on hardware: {missing}")
        except Exception as e:
            print(f"[Gtec] WARNING: GetAvailableChannels failed: {e}")

        d.SetConfiguration()
        self._filter_info = {
            "notch_filter_index": notch_index if notch_index >= 0 else None,
            "bandpass_filter_index": bp_index if bp_index >= 0 else None,
        }
        self._user_block = self._calc_user_block(d, cfg.sampling_rate)
        print(f"[Gtec] configured '{cfg.device_name or 'HIAMP'}' serial={serial} "
              f"{cfg.summary()} user_block={self._user_block}")

    @staticmethod
    def _calc_user_block(d, rate: int, block_ms: float = 100.0) -> int:
        """用户块大小 = 整数个设备块，约 block_ms 毫秒（推荐 ~30–100ms）。"""
        try:
            device_block = max(1, int(d.NumberOfScans))
        except Exception:
            device_block = 1
        blocks = max(1, int(round(block_ms / 1000.0 * rate / device_block)))
        return blocks * device_block

    # ── 采集线程 ────────────────────────────────────────────

    def start(self, on_block: Callable[[np.ndarray], None], user_block_ms: float = 100.0) -> None:
        if self._d is None:
            raise GtecUnavailable("start() before configure()")
        if self._worker is not None and self._worker.is_alive():
            return  # 已在采集

        self._stop.clear()
        d = self._d
        block = self._user_block

        def _more(samples: np.ndarray) -> bool:
            if self._stop.is_set():
                return False
            on_block(np.array(samples, copy=True))
            return True

        def _run() -> None:
            try:
                # 官方建议: 每个采集会话只调用一次 GetData，more 返回 False 即结束
                d.GetData(block, _more)
            except Exception as e:  # 含超时 RuntimeError / 服务断开
                print(f"[Gtec] acquisition stopped: {e}")
            finally:
                print("[Gtec] acquisition worker exited")

        self._worker = threading.Thread(target=_run, name="gtec-acq", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        w = self._worker
        if w is not None and w.is_alive():
            w.join(timeout=3.0)
        self._worker = None

    def close(self) -> None:
        try:
            if self._d is not None:
                self._d.Close()
        except Exception as e:
            print(f"[Gtec] Close failed: {e}")
        finally:
            self._d = None
            time.sleep(0.05)  # 给 GDS 服务释放会话的余量

    def info(self) -> dict:
        info = {
            "backend": type(self).__name__,
            "stub": False,
            "serial": self._serial,
            "device_type": "g.HIamp",
        }
        try:
            if self._d is not None:
                info["device_information"] = (
                    self._d.GetDeviceInformation()[0].replace("\r\n", " | ").strip(" |")
                )
        except Exception:
            pass
        info.update(self._filter_info)
        return info
