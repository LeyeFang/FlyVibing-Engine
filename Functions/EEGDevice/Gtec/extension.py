"""Gtec 监视面板扩展 — 实时信号观察 / 软件实时滤波 / 采集落盘（M1 参考实现）。

规范对照（Doc/ExtDev/extension_dev_protocol.md）:
  §2  三文件形态: extension.json + extension.py（+ 同目录私有模块 gtec_display / gtec_scope）
  §5  生命周期: on_load 装配（窗口 + ops + 设置）; on_enable 幂等重装（_install）;
      disable / 卸载 = 停采集（录音中先落盘）→ 关闭会话 → 宿主保险丝清 ops / 窗口
  §6  ctx 能力: log / ops.register / ui.register_window / data_dir
  §7  UI 纪律: draw_fn 仅渲染线程帧内调用 — 刷新节流 + 只读会话环形缓冲拷贝, 零阻塞;
      close_policy="disable": 窗口 X = 停用扩展（Extensions 菜单勾选同步消失）,
      on_ui_event("closed") 即时收尾（停采集/落盘/释放设备）
  §9  agent 通道: ext.gtec.{status, open, close, watch, record, start(=record 别名),
      stop, filters, display, impedance, service, snapshot}
      （参数/返回全 JSON 友好; 无 UI 环境同样可调）
  §11 设置: ctx.data_dir/settings.json 持久化（重开面板保持上次配置）

模式（mode）:
  sim      进程内 Gtec 空跑后端（确定性合成、不落盘 — 演示与无头验证; 窗口满后合成停止）
  device   真实 g.HIamp — 连接外部品牌服务进程（自有环境启动; MGE_GTEC_SERVICE, 默认 127.0.0.1:47810）
  virtual  虚拟信号发生器（VIRTUAL 服务 — 引擎自动拉起; 连续合成 + Stop 真正落盘）
  （真实模式绝不静默回退 stub — 连接失败即显式报错并在面板展示启动指引）

数据通路（与节点图/服务架构同源, 面板绝不直接触碰设备 API）:
  Watch  → facade start_record(record=False)（只观察 — 流式 + 环形缓冲, 不累积文件）
  Record → facade start_record(record=True)（采集 + 落盘; 可在监视中升级, 从此刻起录）
  刷新(~25 Hz) → session.get_data(elapsed)（环形缓冲时间序拷贝）→ SignalView.refresh
  （显示滤波链 notch→band + min/max 抽取 + 通道统计）→ gtec_scope 绘制
  Stop → session.stop(save=auto)（recording → 引擎侧落盘 npz/csv + json 元数据;
         监视 → 不落盘; save=false 可显式弃录）
  阻抗 → facade measure_impedance（设备空闲操作; sim/virtual = 确定性合成, device = pygds 真值）

显示滤波 vs 设备滤波:
  显示滤波 = 本面板实时软件滤波（notch/band, 滑动窗口 + 预热余量, 随时可改）;
  设备滤波 = g.HIamp 硬件预设（notch / bandpass — 在 Open 时下发, 属硬件配置, 改后需重开会话）。
"""

from __future__ import annotations

import json
import os
import time

from imgui_bundle import imgui

from Application.Core.Extension.ExtensionBase import UIExtensionBase

# 同目录私有模块（ExtensionManager 加载入口时已把扩展目录置于 sys.path）
import gtec_display
import gtec_scope
from gtec_display import SignalView, build_filter_chain, preview_series

# 引擎设备门面（应用层领域模块 — 扩展白名单内, 见审查器 C6）
from Application.Functions.EEGDevice import (
    EXPORT_FORMATS,
    IMPEDANCE_ELECTRODE_TYPES,
    IMPEDANCE_THRESHOLDS_KOHM,
    SUPPORTED_RATES,
    TEMPLATE_CHOICES,
    GtecConfig,
    SigGenConfig,
    channel_names_for,
    classify_impedance,
    get_session,
    init_session,
    kill_device,
    measure_impedance,
    probe_gtec_service,
    start_record,
)

try:  # FontAwesome 图标（UI 文本只用图集内字符 — dev protocol §7 / ui_protocol §12）
    from imgui_bundle import icons_fontawesome_6 as _fa6
except Exception:  # noqa: BLE001
    _fa6 = None


def _icon(name: str) -> str:
    return getattr(_fa6, name, "") if _fa6 is not None else ""


def _as_bool(v, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _as_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


_CLR_OK = imgui.ImVec4(0.45, 0.85, 0.55, 1.0)
_CLR_WARN = imgui.ImVec4(0.95, 0.75, 0.35, 1.0)
_CLR_ERR = imgui.ImVec4(0.90, 0.40, 0.35, 1.0)
_CLR_DIM = imgui.ImVec4(0.60, 0.60, 0.60, 1.0)

_MODES = ("sim", "device", "virtual")
_MODE_LABELS = {
    "sim": "Simulated (in-process stub)",
    "device": "Device (g.HIamp service)",
    "virtual": "Simulator (VIRTUAL service)",
}
_WINDOW_CHOICES = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
_AMP_CHOICES = (0.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0)
_SCOPE_CHOICES = ("session", "buffer")

_REFRESH_PERIOD_S = 1.0 / 25.0     # 面板数据拉取上限频率
_ERROR_SHOW_S = 20.0               # 面板错误行展示时长


class GtecMonitorExtension(UIExtensionBase):
    """Gtec 监视面板 — 实时观察 / 实时滤波 / 采集落盘 + ext.gtec.* ops。"""

    id = "gtec"
    name = "Gtec Device"
    version = "0.3.1"

    _WINDOW_NAME = "Gtec Monitor"

    def __init__(self) -> None:
        self._ctx = None
        self._settings = {
            # 会话
            "mode": "sim",
            "session_name": "gtec-monitor",
            "template": "64ch",
            "sampling_rate": 512,
            "buffer_seconds": 15.0,
            "serial": "",
            "svc_python": "",            # Gtec 服务自动拉起用 python（空 = 仅连接外部服务）
            "save_dir": "",              # 空 = ctx.data_dir/recordings
            "export_format": "npz",
            # 设备滤波（Open 时下发 — g.HIamp 硬件预设）
            "notch": "off",
            "filter_type": "none",
            "low_cut": 0.0,
            "high_cut": 0.0,
            # 虚拟信号源（mode=virtual）
            "sim_channels": 8,
            "sim_f0": 10.0,
            "sim_step": 2.0,
            "sim_amp": 50.0,
            # 显示（gtec_display.SignalView 同步源）
            "disp_window_s": 4.0,
            "disp_amplitude": 0.0,       # 0 = 自动
            "disp_ch_start": 0,
            "disp_ch_count": 8,
            "disp_freeze": False,
            "disp_filter": False,        # 显示滤波（软件实时）
            "disp_notch": "off",
            "disp_band": "none",
            "disp_low": 0.0,
            "disp_high": 0.0,
            "disp_order": 4,             # 显示滤波 IIR 阶数 (2/4)
            # 阻抗（设备空闲操作）
            "imp_electrode": "passive",
            "imp_tms": False,
            # 视图页
            "view_tab": "waveform",
            # 录制
            "save_scope": "session",
        }
        self._view = SignalView()
        self._session_name = ""
        self._session_mode = ""
        self._backend_info: dict = {}
        self._run_anchor = None          # monotonic — 流式采集起点 (watch/record)
        self._record_anchor = None       # monotonic — 录制起点 (监视中升级时重置)
        self._impedance: dict = {}       # 最近一次阻抗测量结果
        self._elapsed_last = 0.0
        self._last_save: dict = {}
        self._last_pull = None           # (data, valid, fs, names) — 最近一次拉取（重建用）
        self._last_refresh = 0.0
        self._last_error = ""
        self._ui_error = ""
        self._ui_error_ts = 0.0
        self._settings_snapshot = ""    # 面板脏检查（变更才落盘）

    # ════════════════════════════════════════════════════════════
    # 生命周期（协议 §5）
    # ════════════════════════════════════════════════════════════

    def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._load_settings()
        self._install(ctx)
        ctx.log(f"monitor panel ready ('{self._WINDOW_NAME}'; mode={self._settings['mode']})")

    def on_enable(self) -> None:
        if self._ctx is not None:
            self._install(self._ctx)     # 幂等 — disable 后 enable 重走

    def on_unload(self) -> None:
        """卸载 = 停采集（录音中先落盘）→ 关闭会话（释放设备/服务进程）。"""
        try:
            ok, detail = self._close_session(save_recording=True)
            if self._ctx is not None:
                self._ctx.log(f"unload cleanup: {detail}")
        except Exception as e:  # noqa: BLE001 — 清理失败不得阻塞卸载
            if self._ctx is not None:
                self._ctx.log(f"unload cleanup failed: {e!r}")

    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件（UIExtensionBase 抽象方法实现）。

        "closed": 用户关闭面板 — 即时收尾: 停采集（录音中先落盘）+ 关闭会话;
        close_policy="disable" 下宿主另将请求停用本扩展（菜单勾选同步消失）。
        """
        if event != "closed":
            return
        try:
            ok, detail = self._close_session(save_recording=True)
            if self._ctx is not None:
                self._ctx.log(f"panel closed by user — {detail} ('{name}')")
        except Exception as e:  # noqa: BLE001 — 关闭事件不得抛出到渲染线程
            if self._ctx is not None:
                self._ctx.log(f"close cleanup failed: {e!r}")

    def _install(self, ctx) -> None:
        """注册 UI 窗口 + 扩展 ops（幂等; 重复注册同名窗口静默跳过）。"""
        try:
            ctx.ui.register_window(self._WINDOW_NAME, self._draw_panel,
                                   close_policy="disable")
        except ValueError:
            pass                        # 已注册（重复装载路径）
        except Exception as e:          # noqa: BLE001 — 无 UI 环境: 记日志降级
            ctx.log(f"window registration failed: {e!r}")
        try:
            self._register_ops(ctx)
        except Exception as e:          # noqa: BLE001
            ctx.log(f"op registration failed: {e!r}")

    def _register_ops(self, ctx) -> None:
        ops = ctx.ops
        ops.register("status", self._op_status,
                     summary="{} panel/session state (mode, recording, filters, last save)")
        ops.register("open", self._op_open,
                     summary="{mode?=sim|device|virtual, sampling_rate?, buffer_seconds?, "
                             "template?, serial?, service_python?, save_dir?, export_format?, "
                             "notch?, filter_type?, low_cut?, high_cut?, sim_*} open a session")
        ops.register("close", self._op_close,
                     summary="{save?=true} stop (save if recording) and close the session")
        ops.register("watch", self._op_watch,
                     summary="{} start watching (streaming + display, NO file recording)")
        ops.register("record", self._op_record,
                     summary="{} start recording (streaming + file, displayed live; "
                             "promotes a watching session from now)")
        ops.register("start", self._op_start, summary="{} alias of record (backward compat)")
        ops.register("stop", self._op_stop,
                     summary="{scope?=session|buffer, save?=true|false (default=auto)} "
                             "stop streaming (recording -> save; watching -> nothing saved)")
        ops.register("filters", self._op_filters,
                     summary="{enabled?, notch?=off|50|60, band_type?=none|highpass|lowpass|bandpass, "
                             "low?, high?} display filter chain (real-time, software)")
        ops.register("display", self._op_display,
                     summary="{view?=waveform|impedance, window_s?, amplitude_uv?, "
                             "channel_start?, channel_count?, freeze?} scope view settings")
        ops.register("impedance", self._op_impedance,
                     summary="{measure?=true, electrode_type?=passive|active, tms_box?=false} "
                             "electrode impedance (kOhm + good/medium/bad; device open & idle)")
        ops.register("service", self._op_service,
                     summary="{probe?=true} probe the Gtec brand service endpoint "
                             "(reachability + auto-launch config; no session needed)")
        ops.register("snapshot", self._op_snapshot,
                     summary="{preview?=true, preview_channels?=3, points?=128, max_channels?=16} "
                             "waveform stats + numeric preview")

    # ════════════════════════════════════════════════════════════
    # 会话控制（facade — 与节点图/服务架构同一条通路）
    # ════════════════════════════════════════════════════════════

    def _save_dir(self) -> str:
        v = str(self._settings.get("save_dir") or "").strip()
        if v:
            return os.path.abspath(os.path.expanduser(v))
        base = self._ctx.data_dir if self._ctx is not None else os.getcwd()
        return os.path.join(base, "recordings")

    def _open_session(self):
        """按当前设置创建会话。Returns: (ok, detail)。"""
        if self._session_name:
            self._close_session(save_recording=False)
        s = self._settings
        mode = str(s["mode"])
        name = str(s["session_name"] or "").strip() or "gtec-monitor"
        save_dir = self._save_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            detail = f"save_dir not writable: {save_dir!r} ({e})"
            self._set_error(detail)
            return False, detail

        if mode == "virtual":
            cfg = SigGenConfig(
                device="VIRTUAL", device_name=name,
                channels=int(s["sim_channels"]),
                sampling_rate=int(s["sampling_rate"]),
                frequency=float(s["sim_f0"]), freq_step=float(s["sim_step"]),
                amplitude_uv=float(s["sim_amp"]), noise_uv=0.0, seed=0,
                export_format=str(s["export_format"]), save_dir=save_dir,
                buffer_seconds=float(s["buffer_seconds"]))
            dry = False
        else:
            cfg = GtecConfig(
                device="HIAMP", device_name=name,
                serial=str(s["serial"] or "").strip(),
                template=str(s["template"]),
                sampling_rate=int(s["sampling_rate"]),
                notch=str(s["notch"]), filter_type=str(s["filter_type"]),
                low_cut=float(s["low_cut"]), high_cut=float(s["high_cut"]),
                export_format=str(s["export_format"]), save_dir=save_dir,
                buffer_seconds=float(s["buffer_seconds"]),
                service_python=str(s["svc_python"] or "").strip())
            dry = (mode == "sim")

        session, detail = init_session(name, cfg, dry_run=dry)
        if session is None:
            self._set_error(detail)
            return False, detail

        self._session_name = name
        self._session_mode = mode
        self._backend_info = dict(session.backend_info or {})
        self._view.clear()
        self._run_anchor = None
        self._record_anchor = None
        self._impedance = {}
        self._elapsed_last = 0.0
        self._last_save = {}
        self._last_pull = None
        if self._ctx is not None:
            self._ctx.log(f"session '{name}' open: mode={mode} "
                          f"{cfg.channels}ch @ {cfg.sampling_rate} Hz buffer={cfg.buffer_seconds:g}s "
                          f"save_dir={save_dir}")
        return True, detail

    def _close_session(self, save_recording: bool = True):
        """关闭会话（录音中先按 scope 落盘）。Returns: (ok, detail)。"""
        name = self._session_name
        if not name:
            return True, "no session"
        detail = "closed"
        session = get_session(name)
        if session is not None and session.state == "recording" and save_recording:
            ok, detail = self._stop_impl(str(self._settings["save_scope"]))
        elif session is not None and session.state == "recording":
            detail = "recording discarded"
        elif session is not None and session.state == "monitoring":
            detail = "watch stopped (nothing recorded)"
        if get_session(name) is not None:
            kill_device(name)           # 停采集/释放设备（幂等; 落盘失败也保证不泄漏）
        self._session_name = ""
        self._run_anchor = None
        self._record_anchor = None
        if self._ctx is not None:
            self._ctx.log(f"session '{name}' closed ({detail})")
        return True, detail

    def _start_impl(self, record: bool = True):
        """启动流式采集（record=False 仅观察; True = 录制，监视中调用则从此刻升级）。"""
        why = self._fault_unless()
        if why:
            self._set_error(why)
            return False, why
        session = get_session(self._session_name)
        streaming_before = session is not None and session.state in ("recording", "monitoring")
        was_recording = session is not None and session.state == "recording"
        ok, detail = start_record(self._session_name, record=record)
        if ok:
            now = time.monotonic()
            if not streaming_before:
                self._run_anchor = now
            session = get_session(self._session_name)
            if (not was_recording and session is not None
                    and session.state == "recording"):
                self._record_anchor = now     # 录制起点（含监视中升级）
            self._elapsed_last = 0.0
            self._last_save = {}
            self._refresh(force=True)
        else:
            self._set_error(detail)
        return ok, detail

    def _stop_impl(self, scope: str = "session", save=None):
        """停止流式采集（save=None → 自动: recording 落盘, 监视/未录不落盘）。"""
        name = self._session_name
        session = get_session(name) if name else None
        if session is None:
            return False, "no session open"
        if session.state not in ("recording", "monitoring"):
            return False, f"not streaming (state={session.state})"
        was_recording = session.state == "recording"
        do_save = was_recording if save is None else (bool(save) and was_recording)
        elapsed = time.monotonic() - (self._run_anchor or time.monotonic())
        self._refresh(force=True, elapsed=elapsed)      # 补齐最后一段并显示
        try:
            result = session.stop(save_scope=scope, elapsed_s=elapsed, save=do_save)
        except Exception as e:  # noqa: BLE001 — 受控错误
            detail = f"stop failed: {e!r}"
            self._set_error(detail)
            return False, detail
        self._elapsed_last = elapsed
        self._run_anchor = None
        self._record_anchor = None
        if was_recording and do_save:
            self._last_save = {
                "written": bool(result.written),
                "samples": int(result.samples),
                "duration_s": round(float(result.duration_s), 3),
                "scope": scope,
                "paths": [str(p) for p in result.paths],
            }
            if result.written:
                detail = (f"stopped; saved {result.samples} samples "
                          f"({result.duration_s:.2f}s, scope={scope}) -> "
                          f"{', '.join(result.paths)}")
            else:
                detail = (f"stopped [dry-run: not written]; would save {result.samples} samples "
                          f"({result.duration_s:.2f}s, scope={scope}) -> "
                          f"{', '.join(result.paths)}")
        elif was_recording:
            self._last_save = {
                "written": False, "discarded": True,
                "samples": int(result.samples),
                "duration_s": round(float(result.duration_s), 3),
                "scope": scope, "paths": [],
            }
            detail = (f"stopped; recording discarded "
                      f"({result.samples} samples, {result.duration_s:.2f}s)")
        else:
            self._last_save = {}
            detail = "watch stopped (nothing recorded)"
        if self._ctx is not None:
            self._ctx.log(detail)
        self._refresh(force=True, elapsed=elapsed)      # 显示最终帧
        return True, detail

    def _fault_unless(self, reason: str = "") -> str:
        """会话存在性检查（op/面板共用 — 返回空串 = 通过, 否则错误文本）。"""
        name = self._session_name
        if not name:
            return "no session open"
        if get_session(name) is None:
            return (f"session '{name}' not found — closed/reset "
                    f"(e.g. PIE start/stop resets devices; or service exited)")
        return ""

    # ════════════════════════════════════════════════════════════
    # 显示刷新（节流拉取 — 渲染线程帧内/ops 内调用, 零阻塞设计）
    # ════════════════════════════════════════════════════════════

    def _refresh(self, force: bool = False, elapsed: float = None) -> None:
        name = self._session_name
        if not name:
            return
        session = get_session(name)
        if session is None:
            return
        streaming = session.state in ("recording", "monitoring")
        if not streaming and self._view.frame is not None and not force:
            return                       # 停止后保留最终帧（冻结展示）
        if self._view.freeze and not force:
            return
        now = time.monotonic()
        if not force and (now - self._last_refresh) < _REFRESH_PERIOD_S:
            return
        self._last_refresh = now
        if elapsed is None:
            elapsed = (now - self._run_anchor) if (streaming and self._run_anchor) else 0.0
        try:
            data = session.get_data(elapsed_s=float(elapsed))
        except Exception as e:  # noqa: BLE001 — 读取失败只上报, 不拖垮帧
            self._set_error(f"read failed: {e!r}")
            return
        self._last_pull = (
            data.get("data"), int(data.get("samples", 0)), float(data.get("fs", 0.0)),
            channel_names_for(int(data.get("channels", 0) or 0)))
        self._view.apply_settings(self._display_source())
        self._view.refresh(*self._last_pull)

    def _rebuild_view(self) -> None:
        """用最近一次拉取的数据重建显示帧 — 设置变更（滤波/标尺/通道）即时生效,
        不拉新数据、不推进仿真、不破坏“冻结”语义（冻结中改设置 = 重渲染同一帧）。"""
        if self._last_pull is None:
            return
        self._view.apply_settings(self._display_source())
        self._view.refresh(*self._last_pull)

    # ════════════════════════════════════════════════════════════
    # 阻抗测量（设备空闲操作 — 面板/op 共用单点）
    # ════════════════════════════════════════════════════════════

    def _measure_impedance(self) -> bool:
        """执行一次阻抗测量（失败 → False + 面板错误行）。"""
        name = self._session_name
        if not name:
            self._set_error("no session open")
            return False
        result, why = measure_impedance(
            name, electrode_type=str(self._settings["imp_electrode"]),
            tms_box=bool(self._settings["imp_tms"]))
        if result is None:
            self._set_error(why)
            return False
        self._impedance = result
        return True

    def _impedance_dict(self) -> dict:
        """最近一次阻抗测量 → JSON 视图（每通道 kΩ + good/medium/bad 分类）。"""
        imp = self._impedance
        if not imp:
            return {"available": False}
        names = channel_names_for(int(imp.get("channels", 0) or 0))
        etype = str(imp.get("electrode_type", "passive"))
        counts = {"good": 0, "medium": 0, "bad": 0, "n/a": 0}
        channels = []
        for i, k in enumerate(imp.get("values_kohm") or []):
            status = classify_impedance(k, etype)
            counts[status] += 1
            channels.append({
                "index": i,
                "name": names[i] if i < len(names) else f"ch{i + 1}",
                "kohm": None if k is None else round(float(k), 3),
                "status": status,
            })
        return {
            "available": True,
            "ts": str(imp.get("ts", "")),
            "electrode_type": etype,
            "tms_box": bool(imp.get("tms_box")),
            "stub": bool(imp.get("stub")),
            "simulated": self._session_mode != "device",
            "thresholds_kohm": list(IMPEDANCE_THRESHOLDS_KOHM.get(
                etype, IMPEDANCE_THRESHOLDS_KOHM["passive"])),
            "counts": counts,
            "channels": channels,
        }

    def _impedance_summary(self):
        if not self._impedance:
            return None
        d = self._impedance_dict()
        return {"ts": d["ts"], "electrode_type": d["electrode_type"],
                "counts": dict(d["counts"]), "simulated": d["simulated"]}

    # ════════════════════════════════════════════════════════════
    # ops（agent 通道 — 协议 §9; 全部可在无 UI 环境调用）
    # ════════════════════════════════════════════════════════════

    def _op_status(self, args) -> dict:
        return self._status_dict()

    def _op_open(self, args) -> dict:
        self._apply_overrides(args or {})
        self._save_settings()
        ok, detail = self._open_session()
        if not ok:
            raise ValueError(detail)
        return self._status_dict()

    def _op_close(self, args) -> dict:
        save = _as_bool((args or {}).get("save"), True)
        ok, detail = self._close_session(save_recording=save)
        if not ok:
            raise ValueError(detail)
        return {"detail": detail, "status": self._status_dict()}

    def _op_watch(self, args) -> dict:
        return self._op_run(record=False)

    def _op_record(self, args) -> dict:
        return self._op_run(record=True)

    def _op_start(self, args) -> dict:
        return self._op_run(record=True)      # 兼容别名（旧调用方）

    def _op_run(self, record: bool) -> dict:
        ok, detail = self._start_impl(record=record)
        if not ok:
            raise ValueError(detail)
        return {"detail": detail, "status": self._status_dict()}

    def _op_stop(self, args) -> dict:
        args = args or {}
        scope = str(args.get("scope") or self._settings["save_scope"])
        if scope not in _SCOPE_CHOICES:
            raise ValueError(f"scope must be one of {_SCOPE_CHOICES}")
        self._settings["save_scope"] = scope
        save = None if "save" not in args else _as_bool(args.get("save"), True)
        ok, detail = self._stop_impl(scope, save=save)
        if not ok:
            raise ValueError(detail)
        return {"detail": detail, "saved": dict(self._last_save),
                "status": self._status_dict()}

    def _op_filters(self, args) -> dict:
        args = args or {}
        s = self._settings
        if "enabled" in args:
            s["disp_filter"] = _as_bool(args["enabled"], bool(s["disp_filter"]))
        if "preset" in args:
            name = str(args["preset"])
            if name not in gtec_display.BAND_PRESETS:
                raise ValueError(f"preset must be one of {tuple(gtec_display.BAND_PRESETS)}")
            self._apply_band_preset(name)
        if "order" in args:
            o = _as_int(args["order"], None)
            if o not in gtec_display.ORDERS:
                raise ValueError(f"order must be one of {gtec_display.ORDERS}")
            s["disp_order"] = int(o)
        if "notch" in args:
            notch = str(args["notch"])
            if notch not in gtec_display.NOTCH_CHOICES:
                raise ValueError(f"notch must be one of {gtec_display.NOTCH_CHOICES}")
            s["disp_notch"] = notch
        if "band_type" in args:
            band = str(args["band_type"])
            if band not in gtec_display.BAND_TYPES:
                raise ValueError(f"band_type must be one of {gtec_display.BAND_TYPES}")
            s["disp_band"] = band
        if "low" in args:
            s["disp_low"] = max(0.0, _as_float(args["low"], float(s["disp_low"])) or 0.0)
        if "high" in args:
            s["disp_high"] = max(0.0, _as_float(args["high"], float(s["disp_high"])) or 0.0)
        self._save_settings()
        self._view.apply_settings(self._display_source())
        self._rebuild_view()            # 即时生效（无需等下一次节流刷新）
        return self._filters_dict()

    def _op_display(self, args) -> dict:
        args = args or {}
        s = self._settings
        ch_total = self._channels_now()
        if "view" in args:
            v = str(args["view"]).strip().lower()
            if v not in ("waveform", "impedance"):
                raise ValueError("view must be waveform|impedance")
            s["view_tab"] = v
        if "window_s" in args:
            self._set_window_s(_as_float(args["window_s"], s["disp_window_s"]))
        if "amplitude_uv" in args:
            v = _as_float(args["amplitude_uv"], None)
            if v is None:
                raise ValueError("amplitude_uv must be a number (0 = auto)")
            s["disp_amplitude"] = 0.0 if v <= 0 else max(0.5, min(5000.0, v))
        if "channel_start" in args:
            s["disp_ch_start"] = max(0, min(int(ch_total) - 1,
                                            _as_int(args["channel_start"], 0) or 0))
        if "channel_count" in args:
            s["disp_ch_count"] = max(1, min(int(ch_total),
                                            _as_int(args["channel_count"], 8) or 8))
        if "freeze" in args:
            s["disp_freeze"] = _as_bool(args["freeze"], bool(s["disp_freeze"]))
        self._save_settings()
        self._view.apply_settings(self._display_source())
        self._rebuild_view()            # 即时生效（无需等下一次节流刷新）
        out = self._display_dict()
        frame = self._view.frame
        out["scale_uv"] = float(frame.scale_uv) if frame else None
        out["auto_scale"] = bool(frame.auto) if frame else None
        return out

    def _op_impedance(self, args) -> dict:
        args = args or {}
        s = self._settings
        if "electrode_type" in args:
            et = str(args["electrode_type"]).strip().lower()
            if et not in IMPEDANCE_ELECTRODE_TYPES:
                raise ValueError(f"electrode_type must be one of {IMPEDANCE_ELECTRODE_TYPES}")
            s["imp_electrode"] = et
        if "tms_box" in args:
            s["imp_tms"] = _as_bool(args["tms_box"], bool(s["imp_tms"]))
        self._save_settings()
        if _as_bool(args.get("measure"), True):
            if not self._measure_impedance():
                raise ValueError(self._last_error)
        return self._impedance_dict()

    def _op_service(self, args) -> dict:
        """Gtec 品牌服务连通性探针（不建会话 — 排障入口）。"""
        out = probe_gtec_service()
        out["panel_python"] = str(self._settings.get("svc_python") or "")
        if not out.get("reachable"):
            out["hint"] = ("service not running - set 'Svc python' (panel) or MGE_GTEC_PYTHON "
                           "to a python with pygds, then Open auto-launches it; or start it "
                           "manually: <python> -m Application.Functions.EEGDevice.Gtec.service "
                           "--port 47810")
        return out

    def _op_snapshot(self, args) -> dict:
        args = args or {}
        self._refresh()                 # 节流拉取（冻结时保持冻结帧 — 所见即所得）
        frame = self._view.frame
        session = get_session(self._session_name) if self._session_name else None
        out = {
            "available": frame is not None,
            "session_open": session is not None,
            "session": self._session_name,
            "mode": self._session_mode,
            "state": session.state if session is not None else "closed",
            "recording": bool(session is not None and session.state == "recording"),
            "streaming": bool(session is not None and session.state in ("recording", "monitoring")),
            "recording_s": round(float(self._status_dict()["recording_s"]), 3),
            "fs": float(frame.fs) if frame else None,
            "samples": int(frame.valid) if frame else 0,
            "window_s": round(float(frame.window_s), 4) if frame else None,
            "filtered": bool(frame.filtered) if frame else False,
            "filter_labels": list(frame.filter_labels) if frame else [],
            "frozen": bool(self._settings["disp_freeze"]),
            "last_save": dict(self._last_save),
            "last_error": self._last_error,
            "channels": [],
        }
        if frame is not None:
            max_ch = max(1, _as_int(args.get("max_channels"), 16) or 16)
            for i, r in enumerate(frame.rows[:max_ch]):
                name = frame.names[r] if r < len(frame.names) else f"ch{r + 1}"
                out["channels"].append({
                    "index": int(r), "name": name,
                    "mean": round(float(frame.stats["mean"][r]), 4),
                    "rms": round(float(frame.stats["rms"][r]), 4),
                    "ptp": round(float(frame.stats["ptp"][r]), 4),
                })
            if _as_bool(args.get("preview"), True):
                out["preview"] = preview_series(
                    frame,
                    max(1, _as_int(args.get("preview_channels"), 3) or 3),
                    max(4, _as_int(args.get("points"), 128) or 128))
        return out

    # ════════════════════════════════════════════════════════════
    # 设置 / 状态视图（ops 与面板共用）
    # ════════════════════════════════════════════════════════════

    def _channels_now(self) -> int:
        session = get_session(self._session_name) if self._session_name else None
        if session is not None:
            return int(session.cfg.channels)
        s = self._settings
        if s["mode"] == "virtual":
            return int(s["sim_channels"])
        return int(TEMPLATE_CHOICES.get(s["template"], 64))

    def _display_source(self) -> dict:
        s = self._settings
        return {
            "window_s": s["disp_window_s"], "amplitude_uv": s["disp_amplitude"],
            "channel_start": s["disp_ch_start"], "channel_count": s["disp_ch_count"],
            "freeze": s["disp_freeze"], "filter_enabled": s["disp_filter"],
            "notch": s["disp_notch"], "band_type": s["disp_band"],
            "low": s["disp_low"], "high": s["disp_high"],
            "order": int(s["disp_order"]),
        }

    def _display_dict(self) -> dict:
        s = self._settings
        return {
            "window_s": float(s["disp_window_s"]),
            "amplitude_uv": float(s["disp_amplitude"]),
            "channel_start": int(s["disp_ch_start"]),
            "channel_count": int(s["disp_ch_count"]),
            "freeze": bool(s["disp_freeze"]),
            "view_tab": str(s["view_tab"]),
            "channels_total": int(self._channels_now()),
        }

    def _filters_dict(self) -> dict:
        spec = self._view.filter_spec()
        fs = 0.0
        session = get_session(self._session_name) if self._session_name else None
        if session is not None:
            fs = float(session.cfg.sampling_rate)
        chain = build_filter_chain(spec, fs) if fs > 0 else None
        return {
            "enabled": bool(spec["enabled"]),
            "notch": str(spec["notch"]),
            "band_type": str(spec["band_type"]),
            "low": float(spec["low"] or 0.0), "high": float(spec["high"] or 0.0),
            "order": int(spec.get("order", 4)),
            "preset": gtec_display.match_band_preset(
                spec["band_type"], spec["low"], spec["high"]),
            "labels": list(chain.labels) if chain else [],
            "notes": list(chain.notes) if chain else [],
        }

    def _status_dict(self) -> dict:
        s = self._settings
        session = get_session(self._session_name) if self._session_name else None
        recording = bool(session is not None and session.state == "recording")
        streaming = bool(session is not None and session.state in ("recording", "monitoring"))
        now = time.monotonic()
        elapsed = (now - self._run_anchor) if (streaming and self._run_anchor) \
            else self._elapsed_last
        recording_s = (now - self._record_anchor) if (recording and self._record_anchor) else 0.0
        frame = self._view.frame
        return {
            "extension": self.id,
            "session_open": session is not None,
            "session": self._session_name,
            "mode": self._session_mode or str(s["mode"]),
            "state": session.state if session is not None else "closed",
            "recording": recording,
            "streaming": streaming,
            "recording_s": round(float(recording_s), 3),
            "elapsed_s": round(float(elapsed), 3),
            "samples": int(session.ring.valid) if session is not None else 0,
            "fs": int(session.cfg.sampling_rate) if session is not None else int(s["sampling_rate"]),
            "channels": int(session.cfg.channels) if session is not None else int(self._channels_now()),
            "buffer_seconds": float(session.cfg.buffer_seconds) if session is not None
            else float(s["buffer_seconds"]),
            "save_dir": self._save_dir(),
            "export_format": str(s["export_format"]),
            "device": {"name": str(s["session_name"]), "serial": str(s["serial"]),
                       "template": str(s["template"])},
            "display": self._display_dict(),
            "filters": self._filters_dict(),
            "impedance": self._impedance_summary(),
            "backend": dict(self._backend_info),
            "last_save": dict(self._last_save),
            "last_error": self._last_error,
            "frame_scale_uv": float(frame.scale_uv) if frame is not None else None,
        }

    # ── 参数覆盖（op open / 面板共用钳制规则） ─────────────────

    def _apply_overrides(self, args: dict) -> None:
        s = self._settings
        if "mode" in args:
            mode = str(args["mode"])
            if mode not in _MODES:
                raise ValueError(f"mode must be one of {_MODES}")
            s["mode"] = mode
        if "session_name" in args:
            s["session_name"] = str(args["session_name"] or "").strip()
        if "template" in args:
            t = str(args["template"])
            if t not in TEMPLATE_CHOICES:
                raise ValueError(f"template must be one of {tuple(TEMPLATE_CHOICES)}")
            s["template"] = t
        if "sampling_rate" in args:
            rate = _as_int(args["sampling_rate"], None)
            if rate not in SUPPORTED_RATES:
                raise ValueError(f"sampling_rate must be one of {SUPPORTED_RATES}")
            s["sampling_rate"] = rate
        if "buffer_seconds" in args:
            s["buffer_seconds"] = max(1.0, min(120.0,
                                               _as_float(args["buffer_seconds"], 15.0) or 15.0))
        if "serial" in args:
            s["serial"] = str(args["serial"] or "").strip()
        if "service_python" in args:
            s["svc_python"] = str(args["service_python"] or "").strip()
        if "save_dir" in args:
            s["save_dir"] = str(args["save_dir"] or "").strip()
        if "export_format" in args:
            fmt = str(args["export_format"])
            if fmt not in EXPORT_FORMATS:
                raise ValueError(f"export_format must be one of {EXPORT_FORMATS}")
            s["export_format"] = fmt
        if "notch" in args:
            v = str(args["notch"])
            if v not in gtec_display.NOTCH_CHOICES:
                raise ValueError(f"notch must be one of {gtec_display.NOTCH_CHOICES}")
            s["notch"] = v
        if "filter_type" in args:
            v = str(args["filter_type"])
            if v not in ("none", "highpass", "lowpass", "bandpass"):
                raise ValueError("filter_type must be none|highpass|lowpass|bandpass")
            s["filter_type"] = v
        if "low_cut" in args:
            s["low_cut"] = max(0.0, _as_float(args["low_cut"], 0.0) or 0.0)
        if "high_cut" in args:
            s["high_cut"] = max(0.0, _as_float(args["high_cut"], 0.0) or 0.0)
        if "sim_channels" in args:
            s["sim_channels"] = max(1, min(256, _as_int(args["sim_channels"], 8) or 8))
        if "sim_f0" in args:
            s["sim_f0"] = max(0.1, _as_float(args["sim_f0"], 10.0) or 10.0)
        if "sim_step" in args:
            s["sim_step"] = max(0.0, _as_float(args["sim_step"], 2.0) or 0.0)
        if "sim_amp" in args:
            s["sim_amp"] = max(0.0, _as_float(args["sim_amp"], 50.0) or 0.0)

    def _set_window_s(self, value) -> None:
        s = self._settings
        hi = min(30.0, float(s["buffer_seconds"]))
        s["disp_window_s"] = max(0.25, min(hi, _as_float(value, 4.0) or 4.0))

    def _apply_band_preset(self, name: str) -> None:
        """应用频带预设（custom → 保持现值不动）。"""
        spec = gtec_display.BAND_PRESETS.get(str(name))
        if spec is None:
            return
        band, low, high = spec
        s = self._settings
        s["disp_band"] = str(band)
        s["disp_low"] = float(low or 0.0)
        s["disp_high"] = float(high or 0.0)

    # ════════════════════════════════════════════════════════════
    # 设置持久化（协议 §11 — ctx.data_dir/settings.json）
    # ════════════════════════════════════════════════════════════

    def _settings_path(self) -> str:
        base = self._ctx.data_dir if self._ctx is not None else "."
        return os.path.join(base, "settings.json")

    def _load_settings(self) -> None:
        try:
            with open(self._settings_path(), encoding="utf-8") as fh:
                saved = json.load(fh)
            for key in self._settings:
                if key in saved:
                    self._settings[key] = saved[key]
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001 — 损坏设置不致命
            if self._ctx is not None:
                self._ctx.log(f"settings load failed: {e!r}")
        self._settings_snapshot = self._settings_json()

    def _settings_json(self) -> str:
        return json.dumps(self._settings, sort_keys=True, ensure_ascii=False)

    def _save_settings(self) -> None:
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as fh:
                json.dump(self._settings, fh, ensure_ascii=False, indent=2)
            self._settings_snapshot = self._settings_json()
        except Exception as e:  # noqa: BLE001
            if self._ctx is not None:
                self._ctx.log(f"settings save failed: {e!r}")

    def _set_error(self, msg: str) -> None:
        self._last_error = str(msg)
        self._ui_error = str(msg)
        self._ui_error_ts = time.perf_counter()
        if self._ctx is not None:
            self._ctx.log(f"error: {msg}")

    # ════════════════════════════════════════════════════════════
    # 面板绘制（渲染线程帧内 — 只读快照; 协议 §7）
    # ════════════════════════════════════════════════════════════

    def _draw_panel(self) -> None:
        try:
            imgui.set_window_size(imgui.ImVec2(1120.0, 730.0),
                                  imgui.Cond_.first_use_ever)
        except Exception:  # noqa: BLE001 — 尺寸设置失败不影响功能
            pass

        self._refresh()
        session = get_session(self._session_name) if self._session_name else None

        self._draw_transport(session)
        if self._ui_error and (time.perf_counter() - self._ui_error_ts) < _ERROR_SHOW_S:
            imgui.text_colored(_CLR_ERR, f"{_icon('ICON_FA_TRIANGLE_EXCLAMATION')} {self._ui_error}")

        avail = imgui.get_content_region_avail()
        left_w = 348.0
        body_h = max(220.0, avail.y - 6.0)
        # ★ BeginChild/EndChild 必须无条件配对（最小化 → 0x0 全裁剪时 BeginChild
        #   返回 False, 仍必须 EndChild — 否则窗口栈失衡、渲染循环断言崩溃）
        controls_visible = imgui.begin_child("##gtec_controls", imgui.ImVec2(left_w, body_h), True)
        try:
            if controls_visible:
                self._draw_controls(session)
        finally:
            imgui.end_child()
        imgui.same_line()
        right_w = max(240.0, avail.x - left_w - 14.0)
        view_visible = imgui.begin_child("##gtec_view", imgui.ImVec2(right_w, body_h), True)
        try:
            if view_visible:
                self._draw_view()
        finally:
            imgui.end_child()

    # ── 顶部运输条 ─────────────────────────────────────────────

    def _draw_transport(self, session) -> None:
        state = session.state if session is not None else "closed"
        streaming = state in ("recording", "monitoring")
        if not streaming:
            if imgui.button(f"{_icon('ICON_FA_PLAY')} Watch"):
                self._safe(lambda: self._start_impl(record=False))
            imgui.same_line()
            if imgui.button(f"{_icon('ICON_FA_CIRCLE')} Record"):
                self._safe(lambda: self._start_impl(record=True))
        elif state == "monitoring":
            if imgui.button(f"{_icon('ICON_FA_CIRCLE')} Record"):
                self._safe(lambda: self._start_impl(record=True))   # 监视中升级录制
            imgui.same_line()
            if imgui.button(f"{_icon('ICON_FA_STOP')} Stop watch"):
                self._safe(lambda: self._stop_impl(str(self._settings["save_scope"])))
        else:
            if imgui.button(f"{_icon('ICON_FA_STOP')} Stop & save"):
                self._safe(lambda: self._stop_impl(str(self._settings["save_scope"])))
        imgui.same_line()
        if imgui.button(f"{_icon('ICON_FA_XMARK')} Close device"):
            self._safe(lambda: self._close_session(save_recording=True))
        imgui.same_line()
        if session is None:
            imgui.text_colored(_CLR_DIM, "no session - press Open in Device panel")
        else:
            now = time.monotonic()
            if state == "recording":
                imgui.text_colored(_CLR_OK, f"{_icon('ICON_FA_CIRCLE')} recording")
                imgui.same_line()
                el = (now - self._record_anchor) if self._record_anchor else self._elapsed_last
            elif state == "monitoring":
                imgui.text_colored(_CLR_WARN, f"{_icon('ICON_FA_PLAY')} watching (no file)")
                imgui.same_line()
                el = (now - self._run_anchor) if self._run_anchor else self._elapsed_last
            else:
                imgui.text_colored(_CLR_WARN, f"{_icon('ICON_FA_PAUSE')} {state}")
                imgui.same_line()
                el = self._elapsed_last
            imgui.text_disabled(f"{el:6.1f} s   {session.ring.valid:6d} smp   "
                                f"{session.cfg.channels}ch @ {session.cfg.sampling_rate} Hz")

    # ── 左栏: 控制 ─────────────────────────────────────────────

    def _draw_controls(self, session) -> None:
        s = self._settings
        io_busy = session is not None

        if imgui.collapsing_header("Session", imgui.TreeNodeFlags_.default_open):
            self._combo("Mode", s["mode"], _MODES, "mode",
                        labels={m: _MODE_LABELS[m] for m in _MODES})
            imgui.set_next_item_width(180)
            changed, v = imgui.input_text("Name##gtec_name", str(s["session_name"]), 96)
            if changed:
                s["session_name"] = v
            imgui.set_next_item_width(150)
            changed, v = imgui.input_float("Buffer (s)##gtec_buf", float(s["buffer_seconds"]),
                                           0.5, 1.0, "%.1f")
            if changed:
                s["buffer_seconds"] = max(1.0, min(120.0, float(v)))

            if s["mode"] == "virtual":
                imgui.set_next_item_width(110)
                changed, v = imgui.input_int("Channels##gtec_simch", int(s["sim_channels"]))
                if changed:
                    s["sim_channels"] = max(1, min(256, int(v)))
                imgui.set_next_item_width(110)
                changed, v = imgui.input_float("f0 (Hz)##gtec_simf0", float(s["sim_f0"]), 0.5, 1.0)
                if changed:
                    s["sim_f0"] = max(0.1, float(v))
                imgui.set_next_item_width(110)
                changed, v = imgui.input_float("df (Hz)##gtec_simdf", float(s["sim_step"]), 0.5, 1.0)
                if changed:
                    s["sim_step"] = max(0.0, float(v))
                imgui.set_next_item_width(110)
                changed, v = imgui.input_float("amp (uV)##gtec_simamp", float(s["sim_amp"]), 5.0, 10.0)
                if changed:
                    s["sim_amp"] = max(0.0, float(v))
            else:
                self._combo("Template", s["template"], tuple(TEMPLATE_CHOICES), "template")
                imgui.set_next_item_width(180)
                changed, v = imgui.input_text("Serial##gtec_serial", str(s["serial"]), 64)
                if changed:
                    s["serial"] = v
                if s["mode"] == "device":
                    imgui.text_disabled("Svc python (auto-launch; blank = external service)")
                    imgui.set_next_item_width(-1)
                    changed, v = imgui.input_text("##gtec_svcpy", str(s["svc_python"]), 256)
                    if changed:
                        s["svc_python"] = v

            self._combo("Rate (Hz)", s["sampling_rate"],
                        tuple(SUPPORTED_RATES), "sampling_rate")
            if s["mode"] == "device":
                imgui.text_disabled("Device filters (applied at Open):")
                self._combo("  Notch", s["notch"], gtec_display.NOTCH_CHOICES, "notch")
                self._combo("  Band", s["filter_type"],
                            ("none", "highpass", "lowpass", "bandpass"), "filter_type")
                imgui.set_next_item_width(90)
                changed, v = imgui.input_float("  low (Hz)##gtec_low", float(s["low_cut"]), 1.0, 1.0)
                if changed:
                    s["low_cut"] = max(0.0, float(v))
                imgui.set_next_item_width(90)
                changed, v = imgui.input_float("  high (Hz)##gtec_high", float(s["high_cut"]), 1.0, 1.0)
                if changed:
                    s["high_cut"] = max(0.0, float(v))
            elif s["mode"] == "sim":
                imgui.text_disabled("(in-process stub - deterministic, no disk writes)")

            if not io_busy:
                if imgui.button(f"{_icon('ICON_FA_LINK')} Open##gtec_open"):
                    self._safe(self._open_session)
            else:
                if imgui.button(f"{_icon('ICON_FA_LINK_SLASH')} Close##gtec_closebtn"):
                    self._safe(lambda: self._close_session(save_recording=True))
            if session is not None:
                info = self._backend_info or {}
                line = str(info.get("serial") or info.get("backend") or "")
                if line:
                    imgui.text_disabled(f"backend: {line[:64]}")
                devinfo = str(info.get("device_information") or "")
                if devinfo:
                    imgui.text_disabled(devinfo[:64].replace(chr(10), " "))

        if imgui.collapsing_header("Recording", imgui.TreeNodeFlags_.default_open):
            imgui.text_disabled("Watch = live only; Record = watch + file")
            self._combo("Save scope", s["save_scope"], _SCOPE_CHOICES, "save_scope")
            self._combo("Format", s["export_format"], tuple(EXPORT_FORMATS), "export_format")
            imgui.set_next_item_width(280)
            changed, v = imgui.input_text("Dir##gtec_dir", str(s["save_dir"]), 256)
            if changed:
                s["save_dir"] = v
            imgui.text_disabled(f"-> {self._save_dir()[:56]}")
            if self._last_save:
                ls = self._last_save
                if ls.get("discarded"):
                    imgui.text_colored(_CLR_WARN, f"last stop: discarded "
                                                  f"{ls.get('samples', 0)} smp "
                                                  f"({ls.get('duration_s', 0):.1f}s)")
                else:
                    tag = "saved" if ls.get("written") else "planned (dry-run)"
                    imgui.text_disabled(f"last stop: {tag} {ls.get('samples', 0)} smp "
                                        f"({ls.get('duration_s', 0):.1f}s)")
                    for p in ls.get("paths", [])[:1]:
                        imgui.text_disabled(str(p))

        if imgui.collapsing_header("Display", imgui.TreeNodeFlags_.default_open):
            labels = {w: (f"{w:g} s" if w in _WINDOW_CHOICES else f"Custom ({w:g} s)")
                      for w in _WINDOW_CHOICES}
            cur = float(s["disp_window_s"])
            if cur not in _WINDOW_CHOICES:
                labels = dict(labels)
                labels[cur] = f"Custom ({cur:g} s)"
            self._combo("Window", cur, tuple(labels), "disp_window_s", labels=labels,
                        apply=lambda v: self._set_window_s(v))
            amp_labels = {a: ("Auto" if a == 0 else f"{a:g} uV") for a in _AMP_CHOICES}
            cur_amp = float(s["disp_amplitude"])
            if cur_amp not in _AMP_CHOICES:
                amp_labels = dict(amp_labels)
                amp_labels[cur_amp] = f"Custom ({cur_amp:g} uV)"
            self._combo("Amplitude", cur_amp, tuple(amp_labels), "disp_amplitude",
                        labels=amp_labels)
            ch_total = self._channels_now()
            imgui.set_next_item_width(90)
            changed, v = imgui.input_int("Ch from##gtec_ch0", int(s["disp_ch_start"]))
            if changed:
                s["disp_ch_start"] = max(0, min(int(ch_total) - 1, int(v)))
            imgui.set_next_item_width(90)
            changed, v = imgui.input_int("Ch count##gtec_chn", int(s["disp_ch_count"]))
            if changed:
                s["disp_ch_count"] = max(1, min(int(ch_total), int(v)))
            changed, v = imgui.checkbox("Freeze display##gtec_freeze", bool(s["disp_freeze"]))
            if changed:
                s["disp_freeze"] = bool(v)
            imgui.same_line()
            imgui.text_disabled("(acq continues)")

        if imgui.collapsing_header("Display filters (real-time)", imgui.TreeNodeFlags_.default_open):
            changed, v = imgui.checkbox("Enabled##gtec_flt", bool(s["disp_filter"]))
            if changed:
                s["disp_filter"] = bool(v)
            preset = gtec_display.match_band_preset(
                s["disp_band"], s["disp_low"], s["disp_high"])
            preset_labels = {p: p for p in gtec_display.BAND_PRESETS}
            if preset == "custom":
                if s["disp_band"] == "none":
                    preset_labels["custom"] = "custom (none)"
                else:
                    preset_labels["custom"] = (f"custom ({s['disp_band']} "
                                               f"{s['disp_low']:g}-{s['disp_high']:g} Hz)")
            self._combo("Preset", preset, tuple(preset_labels), "disp_preset",
                        labels=preset_labels, apply=self._apply_band_preset)
            self._combo("Band", s["disp_band"], gtec_display.BAND_TYPES, "disp_band")
            imgui.set_next_item_width(90)
            changed, v = imgui.input_float("low (Hz)##gtec_flo", float(s["disp_low"]), 0.5, 1.0)
            if changed:
                s["disp_low"] = max(0.0, float(v))
            imgui.same_line()
            imgui.set_next_item_width(90)
            changed, v = imgui.input_float("high (Hz)##gtec_fhi", float(s["disp_high"]), 0.5, 1.0)
            if changed:
                s["disp_high"] = max(0.0, float(v))
            self._combo("Order", int(s["disp_order"]), gtec_display.ORDERS, "disp_order",
                        labels={2: "2 (12 dB/oct)", 4: "4 (24 dB/oct)"})
            self._combo("Notch", s["disp_notch"], gtec_display.NOTCH_CHOICES, "disp_notch")
            f = self._filters_dict()
            if f["labels"]:
                imgui.text_colored(_CLR_OK, "active: " + ", ".join(f["labels"]))
            for note in f["notes"]:
                imgui.text_colored(_CLR_WARN, f"skip: {note}")
            imgui.text_disabled("software chain on display data (notch -> band); "
                                "notch combos: 50+100 / 60+120")

        # 面板脏检查 — 设置有变更才落盘 + 重建显示帧（不拉新数据）
        if self._settings_json() != self._settings_snapshot:
            self._save_settings()
            self._rebuild_view()

    # ── 右栏: 视图 ─────────────────────────────────────────────

    def _draw_view(self) -> None:
        s = self._settings
        if imgui.radio_button("Waveform##gtec_vt0", s["view_tab"] == "waveform"):
            s["view_tab"] = "waveform"
        imgui.same_line()
        if imgui.radio_button("Impedance##gtec_vt1", s["view_tab"] == "impedance"):
            s["view_tab"] = "impedance"
        imgui.separator()
        if s["view_tab"] == "impedance":
            self._draw_impedance_view()
            return
        frame = self._view.frame
        avail = imgui.get_content_region_avail()
        table_h = 160.0
        plot_h = max(120.0, avail.y - table_h - 34.0)

        res = gtec_scope.draw_scope(frame, "##gtec_scope", plot_h)
        if res.get("wheel"):
            factor = 0.85 if res["wheel"] > 0 else 1.0 / 0.85
            self._set_window_s(float(self._settings["disp_window_s"]) * factor)
        if res.get("double_click"):
            self._set_window_s(4.0)

        if frame is not None:
            line = (f"{frame.fs:g} Hz | {frame.n_view} smp | {frame.window_s:.2f} s | "
                    f"scale {frame.scale_uv:g} uV{' (auto)' if frame.auto else ''}")
            if frame.filter_labels:
                line += " | filter: " + ", ".join(frame.filter_labels)
            imgui.text_disabled(line)
            if self._settings["disp_freeze"]:
                imgui.same_line()
                imgui.text_colored(_CLR_WARN, "FROZEN")
        else:
            imgui.text_disabled("(waiting for data)")

        gtec_scope.draw_quality_table(frame, height=table_h)

    # ── 右栏: 阻抗视图（设备空闲测量 — 每通道表 + 分类着色） ─────

    def _draw_impedance_view(self) -> None:
        s = self._settings
        session = get_session(self._session_name) if self._session_name else None
        state = session.state if session is not None else "closed"
        can_measure = session is not None and state not in ("recording", "monitoring")
        if imgui.button(f"{_icon('ICON_FA_BOLT')} Measure"):
            self._safe(self._measure_impedance)
        imgui.same_line()
        self._combo("Electrodes", s["imp_electrode"], IMPEDANCE_ELECTRODE_TYPES,
                    "imp_electrode")
        imgui.same_line()
        changed, v = imgui.checkbox("TMS box##gtec_imptms", bool(s["imp_tms"]))
        if changed:
            s["imp_tms"] = bool(v)
        if not can_measure:
            imgui.text_colored(_CLR_WARN, "measure needs an open, idle device - "
                                          f"stop streaming first (state={state})")
        imgui.separator()
        d = self._impedance_dict()
        if not d.get("available"):
            imgui.text_disabled("no measurement yet - press Measure "
                                "(sim/virtual give deterministic demo values)")
            return
        counts = d["counts"]
        thr = d["thresholds_kohm"]
        imgui.text_colored(_CLR_OK, f"good {counts['good']}")
        imgui.same_line()
        imgui.text_colored(_CLR_WARN, f"medium {counts['medium']}")
        imgui.same_line()
        imgui.text_colored(_CLR_ERR, f"bad {counts['bad']}")
        imgui.same_line()
        imgui.text_disabled(f"n/a {counts['n/a']}   thresholds <{thr[0]:g} / "
                            f"{thr[0]:g}-{thr[1]:g} / >{thr[1]:g} kOhm ({d['electrode_type']})")
        imgui.same_line()
        ts = str(d.get("ts", ""))
        stamp = ts[11:19] if len(ts) >= 19 else ts
        imgui.text_disabled(f"at {stamp}" + ("  [simulated]" if d["simulated"] else ""))
        avail = imgui.get_content_region_avail()
        rows_visible = imgui.begin_child("##gtec_imp_table",
                                         imgui.ImVec2(0.0, max(120.0, avail.y - 4.0)), True)
        try:
            if rows_visible:
                for ch in d["channels"]:
                    val = ch["kohm"]
                    text = "--" if val is None else f"{val:7.1f} kOhm"
                    clr = {"good": _CLR_OK, "medium": _CLR_WARN,
                           "bad": _CLR_ERR}.get(ch["status"], _CLR_DIM)
                    imgui.text(f"{ch['index'] + 1:>3} {ch['name']:<6}")
                    imgui.same_line()
                    imgui.text_colored(clr, text)
                    imgui.same_line()
                    imgui.text_disabled(ch["status"])
        finally:
            imgui.end_child()

    # ── 小组件 ─────────────────────────────────────────────────

    def _combo(self, label: str, current, choices, key: str, labels: dict = None,
               apply=None) -> None:
        """通用下拉（受控枚举 — ui_protocol §11; 非法当前值须在 choices 内）。"""
        shown = (labels or {}).get(current, str(current))
        changed_value = None
        if imgui.begin_combo(f"{label}##gtec_cb_{key}", shown):
            for c in choices:
                text = (labels or {}).get(c, str(c))
                selected = (c == current)
                if imgui.selectable(f"{text}##{key}_{c}", selected)[0]:
                    changed_value = c
            imgui.end_combo()
        if changed_value is not None:
            if apply is not None:
                apply(changed_value)
            else:
                self._settings[key] = changed_value

    def _safe(self, fn) -> None:
        """面板按钮动作包裹 — 业务错误进面板错误行, 不炸渲染帧。"""
        try:
            result = fn()
            if isinstance(result, tuple) and len(result) == 2 and result[0] is False:
                if result[1]:
                    self._set_error(str(result[1]))
        except Exception as e:  # noqa: BLE001 — 受控展示
            self._set_error(f"{type(e).__name__}: {e}")


def create_extension() -> GtecMonitorExtension:
    """入口工厂（extension.json → entry: extension.py:create_extension）。"""
    return GtecMonitorExtension()
