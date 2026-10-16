"""Virtual Device — 波形监视面板扩展（官方示例; 沿用社区设备监视面板的设计语言, 代码为干净重写）。

规范对照（Doc/ExtDev/extension_dev_protocol.md）:
  §2  文件形态: extension.json + extension.py（+ 同目录私有模块 virtual_display / virtual_scope）
  §5  生命周期: on_load 装配（窗口 + ops + 设置）; on_enable 幂等重装;
      disable / 卸载 = 停采集（录制中先落盘）→ 关闭会话（宿主保险丝清 ops / 窗口）
  §6  ctx 能力: log / ops.register / ui.register_window / data_dir
  §7  UI 纪律: draw_fn 仅渲染线程帧内调用 — 刷新节流（~25 Hz）+ 只读会话快照, 零阻塞;
      close_policy="disable": 窗口 X = 停用扩展（Extensions 菜单勾选同步消失）,
      on_ui_event("closed") 即时收尾（停流）
  §9  agent 通道: ext.virtual.{status, open, close, watch, record, stop, filters, display, snapshot}
  §11 设置: ctx.data_dir/settings.json 持久化（重开面板保持上次配置）

设计要点（取自社区设备监视面板设计语言）:
  - Watch（只观察波形, 不写文件） vs Record（显示 + 落盘; 监视中可随时升级）;
  - ~25 Hz 节流拉取会话环形缓冲快照（只读拷贝）→ 显示滤波 → min/max 抽取 → 绘制;
  - 显示滤波 + 设备滤波概念分离: 虚拟设备无硬件滤波; 显示滤波 = 面板软件链（随时可改）;
  - 面板绝不直接触碰设备 API —— 一律经设备门面 Application.Functions.VirtualDevice。

模式（mode）:
  sim      进程内虚拟后端（确定性合成、不落盘 — 演示与无头验证; 合成量封顶一个窗口）
  virtual  VIRTUAL 服务（引擎自动拉起; 连续合成, Stop 真正落盘至 save_dir）

UI 文本全程 ASCII / FontAwesome（字形图集约束 — ui_protocol §12）。
"""

from __future__ import annotations

import json
import math
import os
import time

from imgui_bundle import imgui

from Application.Core.Extension.ExtensionBase import UIExtensionBase

# 同目录私有模块（ExtensionManager 加载入口时已把扩展目录置于 sys.path）
import virtual_display as vd
import virtual_scope as vs

# 引擎设备门面（应用层领域模块 — 扩展白名单内, 见审查器 C6）
from Application.Functions.VirtualDevice import (
    SigGenConfig,
    get_data,
    get_session,
    init_session,
    kill_device,
    start_record,
    stop_record,
)

# ════════════════════════════════════════════════════════════════
# 常量 / 默认设置
# ════════════════════════════════════════════════════════════════

_MODES = ("sim", "virtual")
_MODE_LABELS = {
    "sim": "Simulated (in-process stub)",
    "virtual": "Virtual service (auto-spawn)",
}
_WINDOW_CHOICES = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
_AMP_CHOICES = (0.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0)
_PULL_INTERVAL_S = 1.0 / 25.0

_DEFAULT_SETTINGS = {
    # 会话（Open 时生效）
    "mode": "sim",
    "channels": 8,
    "sampling_rate": 512,
    "frequency": 10.0,
    "freq_step": 2.0,
    "amplitude_uv": 50.0,
    "noise_uv": 0.0,
    "seed": 0,
    "buffer_seconds": 4.0,
    "save_dir": ".",
    "export_format": "npz",
    # 显示（实时生效）
    "display_window_s": 4.0,
    "display_amp": 0.0,        # 0 = auto
    "channel_start": 0,
    "channel_count": 8,
    # 显示滤波（实时生效）
    "filt_enabled": False,
    "filt_notch": "off",
    "filt_type": "none",
    "filt_low": 0.5,
    "filt_high": 45.0,
    "filt_order": 4,
}

_CLR_OK = imgui.ImVec4(0.45, 0.85, 0.55, 1.0)
_CLR_WARN = imgui.ImVec4(0.95, 0.75, 0.35, 1.0)
_CLR_ERR = imgui.ImVec4(0.90, 0.40, 0.35, 1.0)
_CLR_DIM = imgui.ImVec4(0.60, 0.60, 0.60, 1.0)

try:  # FontAwesome 图标（UI 文本只用图集内字符 — dev protocol §7 / ui_protocol §12）
    from imgui_bundle import icons_fontawesome_6 as _fa6
except Exception:  # noqa: BLE001
    _fa6 = None


def _icon(name: str) -> str:
    return getattr(_fa6, name, "") if _fa6 is not None else ""


# ════════════════════════════════════════════════════════════════
# 小工具
# ════════════════════════════════════════════════════════════════

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


def _clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        i = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, i))


def _clamp_float(v, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, f))


def _sanitize(settings) -> dict:
    """设置全量钳位（非法回退默认; 纯数据）。"""
    s = dict(_DEFAULT_SETTINGS)
    src = settings or {}
    for k in _DEFAULT_SETTINGS:
        if k in src:
            s[k] = src[k]
    s["mode"] = s["mode"] if s["mode"] in _MODES else "sim"
    s["channels"] = _clamp_int(s["channels"], 1, 256, 8)
    s["sampling_rate"] = _clamp_int(s["sampling_rate"], 1, 38400, 512)
    s["frequency"] = _clamp_float(s["frequency"], 0.1, s["sampling_rate"] / 2.0, 10.0)
    s["freq_step"] = _clamp_float(s["freq_step"], 0.0, s["sampling_rate"] / 2.0, 2.0)
    s["amplitude_uv"] = _clamp_float(s["amplitude_uv"], 0.0, 1e6, 50.0)
    s["noise_uv"] = _clamp_float(s["noise_uv"], 0.0, 1e6, 0.0)
    s["seed"] = _clamp_int(s["seed"], -(2 ** 31), 2 ** 31 - 1, 0)
    s["buffer_seconds"] = _clamp_float(s["buffer_seconds"], 0.5, 60.0, 4.0)
    s["save_dir"] = str(s["save_dir"] or ".").strip() or "."
    s["export_format"] = s["export_format"] if s["export_format"] in ("npz", "csv") else "npz"
    s["display_window_s"] = _clamp_float(s["display_window_s"], 0.5, 30.0, 4.0)
    s["display_amp"] = _clamp_float(s["display_amp"], 0.0, 10000.0, 0.0)
    s["channel_start"] = _clamp_int(s["channel_start"], 0, 255, 0)
    s["channel_count"] = _clamp_int(s["channel_count"], 1, 32, 8)
    s["filt_enabled"] = bool(s["filt_enabled"])
    s["filt_notch"] = s["filt_notch"] if s["filt_notch"] in vd.NOTCH_CHOICES else "off"
    s["filt_type"] = s["filt_type"] if s["filt_type"] in vd.BAND_TYPES else "none"
    s["filt_low"] = _clamp_float(s["filt_low"], 0.0, 10000.0, 0.5)
    s["filt_high"] = _clamp_float(s["filt_high"], 0.0, 10000.0, 45.0)
    try:
        order = int(s["filt_order"])
    except (TypeError, ValueError):
        order = 4
    s["filt_order"] = order if order in vd.ORDERS else 4
    return s


def _combo_text(label: str, current, choices, fmt=str):
    """受控枚举 combo — 仅 begin 返回 True 时 end（C9）; 返回新值或 None。"""
    out = None
    if imgui.begin_combo(label, fmt(current)):
        for c in choices:
            if imgui.selectable(fmt(c), c == current)[0]:
                out = c
        imgui.end_combo()
    return out


# ════════════════════════════════════════════════════════════════
# 扩展
# ════════════════════════════════════════════════════════════════

class VirtualDeviceExtension(UIExtensionBase):
    """Virtual Device — 波形监视面板 + `ext.virtual.*` ops（官方示例）。

    窗口生命周期（dev protocol §7 完备性示范）:
      close_policy="disable" — 用户点击窗口 X = 停用扩展（菜单勾选同步消失）;
      on_ui_event("closed") 收尾 = 停止流式采集（录制中先落盘由 disable 链路完成）。
    """

    id = "virtual"
    name = "Virtual Device"
    version = "0.1.0"

    _WINDOW_NAME = "Virtual Device Monitor"
    _SESSION = "panel"

    def __init__(self) -> None:
        self._ctx = None
        self._settings: dict = dict(_DEFAULT_SETTINGS)
        self._view = vd.SignalView()
        self._t0 = None
        self._last_pull = 0.0
        self._force_pull = False
        self._freeze = False
        self._error = ""

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._load_settings()
        self._install(ctx)
        ctx.log(f"monitor panel ready ('{self._WINDOW_NAME}')")

    def on_enable(self) -> None:
        if self._ctx is not None:
            self._install(self._ctx)   # 幂等 — disable 后 enable 重走

    def on_disable(self) -> None:
        self._teardown(save=True)

    def on_unload(self) -> None:
        self._teardown(save=True)

    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件（UIExtensionBase 抽象方法实现）。

        "closed": 用户关闭了监视面板 —— 停流收尾（录制中先落盘）。
        close_policy="disable" 下, 宿主另将请求停用本扩展（菜单勾选随窗口关闭同步消失）。
        """
        if event == "closed":
            self._stop_streaming(save=True)
            if self._ctx is not None:
                self._ctx.log(f"panel closed by user — streaming stopped ('{name}')")

    # ════════════════════════════════════════════════════════════
    # 装配
    # ════════════════════════════════════════════════════════════

    def _install(self, ctx) -> None:
        """注册 UI 窗口 + 扩展 ops（幂等; 重复注册同名窗口静默跳过）。"""
        try:
            ctx.ui.register_window(self._WINDOW_NAME, self._draw_monitor,
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
                     summary="会话/流式/录制/滤波器/视图状态总览")
        ops.register("open", self._op_open,
                     summary="{mode?=sim|virtual, channels?.., save_dir?..} 创建会话")
        ops.register("close", self._op_close,
                     summary="{save?=true} 录制中先落盘再关会话（释放设备/服务）")
        ops.register("watch", self._op_watch,
                     summary="开始观察（流式 + 显示, 不写文件）")
        ops.register("record", self._op_record,
                     summary="开始录制（显示 + 落盘）; 监视中调用 = 从此刻升级")
        ops.register("stop", self._op_stop,
                     summary="{scope?=session|buffer, save?=true|false} 停止流式（录制→保存; 监视→无落盘）")
        ops.register("filters", self._op_filters,
                     summary="{enabled, notch?=off|50|60, filter_type?, low?, high?, order?=2|4} 显示滤波链")
        ops.register("display", self._op_display,
                     summary="{window_s?, amplitude_uv?(0=auto), channel_start?, channel_count?, freeze?} 视口设置")
        ops.register("snapshot", self._op_snapshot,
                     summary="{points?, preview_channels?, max_channels?} 波形统计 + 数值预览（agent 验证）")

    # ════════════════════════════════════════════════════════════
    # 内部 — 会话辅助
    # ════════════════════════════════════════════════════════════

    def _elapsed(self) -> float:
        return (time.monotonic() - self._t0) if self._t0 is not None else 0.0

    def _filters(self) -> dict:
        s = self._settings
        return {"enabled": s["filt_enabled"], "notch": s["filt_notch"],
                "filter_type": s["filt_type"], "low": s["filt_low"],
                "high": s["filt_high"], "order": s["filt_order"]}

    def _display(self) -> dict:
        s = self._settings
        return {"window_s": s["display_window_s"], "amplitude_uv": s["display_amp"],
                "channel_start": s["channel_start"], "channel_count": s["channel_count"],
                "freeze": self._freeze}

    def _apply(self, upd) -> None:
        """更新设置（钳位 + 持久化 + 触发视图重建）。"""
        upd = {k: v for k, v in (upd or {}).items() if k in _DEFAULT_SETTINGS}
        if not upd:
            return
        before = dict(self._settings)
        self._settings = _sanitize({**self._settings, **upd})
        self._force_pull = True
        if any(k.startswith("filt_") for k in upd):
            self._view.rebuild(self._filters())   # 滤波设置变更 → 即时重建帧
        if self._settings != before:
            self._save_settings()

    def _stop_streaming(self, save: bool = True) -> str:
        """停流（录制中按 save 落盘）; 返回 detail 文本。"""
        session = get_session(self._SESSION)
        if session is None:
            return ""
        if session.state in ("recording", "monitoring"):
            try:
                ok, detail = stop_record(self._SESSION, "session", self._elapsed(), save=save)
                return detail if ok else f"stop failed: {detail}"
            except Exception as e:  # noqa: BLE001 — 收尾路径不抛
                return f"stop failed: {e}"
        return ""

    def _teardown(self, save: bool = True) -> None:
        """停流 + 关闭会话（disable / unload 收尾; 幂等）。"""
        self._stop_streaming(save=save)
        try:
            kill_device(self._SESSION)
        except Exception:  # noqa: BLE001
            pass
        self._t0 = None

    # ════════════════════════════════════════════════════════════
    # 设置持久化（ctx.data_dir/settings.json）
    # ════════════════════════════════════════════════════════════

    def _settings_path(self) -> str:
        return os.path.join(self._ctx.data_dir, "settings.json") if self._ctx else ""

    def _load_settings(self) -> None:
        path = self._settings_path()
        data = None
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = None
        self._settings = _sanitize(data)

    def _save_settings(self) -> None:
        path = self._settings_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._settings, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            if self._ctx is not None:
                self._ctx.log(f"settings save failed: {e!r}")

    # ════════════════════════════════════════════════════════════
    # ops 实现（agent 通道 — 全部可在无 UI 环境调用）
    # ════════════════════════════════════════════════════════════

    def _op_status(self, args) -> dict:
        session = get_session(self._SESSION)
        state = session.state if session is not None else None
        return {
            "extension": self.id, "window": self._WINDOW_NAME,
            "session": self._SESSION, "state": state,
            "streaming": bool(session and state in ("recording", "monitoring")),
            "recording": bool(state == "recording"),
            "mode": self._settings["mode"],
            "settings": dict(self._settings),
            "filters": self._filters(),
            "display": self._display(),
            "view": {"samples": self._view.samples, "cols": self._view.cols,
                     "note": self._view.note},
            "backend": dict(getattr(session, "backend_info", {}) or {}) if session else None,
            "error": self._error,
        }

    def _op_open(self, args) -> dict:
        args = args or {}
        self._apply({k: args[k] for k in _DEFAULT_SETTINGS if k in args})
        s = self._settings
        props = {
            "device_name": self._SESSION,
            "channels": s["channels"], "sampling_rate": s["sampling_rate"],
            "frequency": s["frequency"], "freq_step": s["freq_step"],
            "amplitude_uv": s["amplitude_uv"], "noise_uv": s["noise_uv"],
            "seed": s["seed"], "buffer_seconds": s["buffer_seconds"],
            "save_dir": s["save_dir"], "export_format": s["export_format"],
        }
        cfg = SigGenConfig.from_props(props)
        dry = s["mode"] == "sim"
        session, detail = init_session(self._SESSION, cfg, dry_run=dry)
        if session is None:
            self._error = str(detail)
            raise ValueError(str(detail))
        self._t0 = time.monotonic()
        self._view.reset(int(cfg.sampling_rate))
        self._error = ""
        return {"opened": True, "mode": s["mode"], "dry_run": dry,
                "fs": int(cfg.sampling_rate), "channels": int(cfg.channels),
                "detail": detail}

    def _op_close(self, args) -> dict:
        args = args or {}
        save = _as_bool(args.get("save"), True)
        session = get_session(self._SESSION)
        if session is None:
            return {"closed": False, "detail": "no session"}
        saved = self._stop_streaming(save=save)
        kill_device(self._SESSION)
        self._t0 = None
        return {"closed": True, "stop_detail": saved}

    def _op_watch(self, args) -> dict:
        if get_session(self._SESSION) is None:
            raise ValueError("no session — call ext.virtual.open first")
        ok, detail = start_record(self._SESSION, self._elapsed(), record=False)
        if not ok:
            raise ValueError(detail)
        return {"streaming": True, "recording": False, "detail": detail}

    def _op_record(self, args) -> dict:
        if get_session(self._SESSION) is None:
            raise ValueError("no session — call ext.virtual.open first")
        ok, detail = start_record(self._SESSION, self._elapsed(), record=True)
        if not ok:
            raise ValueError(detail)
        return {"streaming": True, "recording": True, "detail": detail}

    def _op_stop(self, args) -> dict:
        args = args or {}
        scope = "buffer" if str(args.get("scope", "session")) == "buffer" else "session"
        save = _as_bool(args.get("save"), True)
        if get_session(self._SESSION) is None:
            raise ValueError("no session")
        ok, detail = stop_record(self._SESSION, scope, self._elapsed(), save=save)
        if not ok:
            raise ValueError(detail)
        return {"stopped": True, "scope": scope, "save": save, "detail": detail}

    def _op_filters(self, args) -> dict:
        args = args or {}
        upd = {}
        mapping = {"enabled": "filt_enabled", "notch": "filt_notch",
                   "filter_type": "filt_type", "low": "filt_low",
                   "high": "filt_high", "order": "filt_order"}
        for src, dst in mapping.items():
            if src in args:
                upd[dst] = args[src]
        self._apply(upd)
        return {"filters": self._filters()}

    def _op_display(self, args) -> dict:
        args = args or {}
        upd = {}
        mapping = {"window_s": "display_window_s", "amplitude_uv": "display_amp",
                   "channel_start": "channel_start", "channel_count": "channel_count"}
        for src, dst in mapping.items():
            if src in args:
                upd[dst] = args[src]
        self._apply(upd)
        if "freeze" in args:
            self._freeze = _as_bool(args.get("freeze"), self._freeze)
        return {"display": self._display()}

    def _op_snapshot(self, args) -> dict:
        args = args or {}
        session = get_session(self._SESSION)
        if session is None:
            raise ValueError("no session — call ext.virtual.open first")
        result, why = get_data(self._SESSION, self._elapsed())
        if result is None:
            raise ValueError(why)
        data, samples = result["data"], int(result["samples"])
        max_ch = max(1, int(args.get("max_channels", vd.STATS_ROWS)))
        points = max(1, int(args.get("points", 128)))
        prev_ch = max(1, int(args.get("preview_channels", 3)))
        valid = data[:, :samples]         # 只统计有效样本（未填充区为 0 会拉低 RMS）
        stats = [{"ch": i + 1, "rms": r, "ptp": p, "mean": m}
                 for i, (r, p, m) in enumerate(vd.channel_stats(valid)[:max_ch])]
        if session.state in ("recording", "monitoring"):
            self._view.refresh(result["data"], samples, self._filters())
        return {"state": result["state"], "samples": samples, "fs": int(result["fs"]),
                "channels": int(result["channels"]), "stub": bool(result["stub"]),
                "stats": stats,
                "preview": vd.preview_series(data, samples, points, prev_ch)}

    # ════════════════════════════════════════════════════════════
    # 面板
    # ════════════════════════════════════════════════════════════

    def _btn(self, label: str, fn, enabled: bool = True) -> None:
        imgui.begin_disabled(not enabled)
        clicked = imgui.button(label)
        imgui.end_disabled()
        if clicked:
            try:
                fn()
                self._error = ""
            except ValueError as e:
                self._error = str(e)
        imgui.same_line()

    def _draw_transport(self) -> None:
        s = self._settings
        session = get_session(self._SESSION)
        streaming = bool(session and session.state in ("recording", "monitoring"))
        recording = bool(session and session.state == "recording")

        imgui.begin_disabled(session is not None)
        if imgui.begin_combo("##vd_mode", _MODE_LABELS[s["mode"]]):
            for m in _MODES:
                if imgui.selectable(_MODE_LABELS[m], m == s["mode"])[0]:
                    self._apply({"mode": m})
            imgui.end_combo()
        imgui.end_disabled()
        imgui.same_line()
        imgui.text("Mode")
        imgui.same_line()

        self._btn(f"{_icon('ICON_FA_PLAY')} Open".strip(), lambda: self._op_open({}),
                  enabled=session is None)
        self._btn(f"{_icon('ICON_FA_EYE')} Watch".strip(), lambda: self._op_watch({}),
                  enabled=session is not None and not streaming)
        self._btn(f"{_icon('ICON_FA_CIRCLE')} Record".strip(), lambda: self._op_record({}),
                  enabled=session is not None and not streaming)
        self._btn(f"{_icon('ICON_FA_FLOPPY_DISK')} Stop & Save".strip(),
                  lambda: self._op_stop({}), enabled=streaming)
        self._btn(f"{_icon('ICON_FA_XMARK')} Close".strip(), lambda: self._op_close({}),
                  enabled=session is not None)

        state = session.state if session is not None else "closed"
        if recording:
            imgui.text_colored(_CLR_WARN, f"state: {state} (recording)")
        elif streaming:
            imgui.text_colored(_CLR_OK, f"state: {state} (watch)")
        else:
            imgui.text_colored(_CLR_DIM, f"state: {state}")

    def _draw_session_section(self) -> None:
        s = self._settings
        session_open = get_session(self._SESSION) is not None
        imgui.begin_disabled(session_open)
        imgui.push_item_width(130)
        changed, v = imgui.input_int("channels##vd_ch", int(s["channels"]))
        if changed:
            self._apply({"channels": v})
        changed, v = imgui.input_int("sampling_rate (Hz)##vd_fs", int(s["sampling_rate"]))
        if changed:
            self._apply({"sampling_rate": v})
        changed, v = imgui.input_float("f0 (Hz)##vd_f0", float(s["frequency"]), 0.5, 1.0)
        if changed:
            self._apply({"frequency": v})
        changed, v = imgui.input_float("freq_step (Hz)##vd_df", float(s["freq_step"]), 0.5, 1.0)
        if changed:
            self._apply({"freq_step": v})
        changed, v = imgui.input_float("amp (uV)##vd_amp", float(s["amplitude_uv"]), 5.0, 10.0)
        if changed:
            self._apply({"amplitude_uv": v})
        changed, v = imgui.input_float("noise (uV)##vd_noise", float(s["noise_uv"]), 1.0, 5.0)
        if changed:
            self._apply({"noise_uv": v})
        changed, v = imgui.input_int("seed##vd_seed", int(s["seed"]))
        if changed:
            self._apply({"seed": v})
        changed, v = imgui.input_float("buffer (s)##vd_buf", float(s["buffer_seconds"]), 0.5, 1.0)
        if changed:
            self._apply({"buffer_seconds": v})
        imgui.push_item_width(260)
        changed, v = imgui.input_text("save_dir##vd_dir", str(s["save_dir"]))
        if changed:
            self._apply({"save_dir": v})
        imgui.pop_item_width()
        fmt = _combo_text("format##vd_fmt", s["export_format"], ("npz", "csv"))
        if fmt:
            self._apply({"export_format": fmt})
        imgui.pop_item_width()
        imgui.end_disabled()
        if session_open:
            imgui.text_colored(_CLR_DIM, "(session settings apply on next Open)")

    def _draw_display_section(self) -> None:
        s = self._settings
        win = _combo_text("window (s)##vd_win", float(s["display_window_s"]),
                          _WINDOW_CHOICES, lambda v: f"{v:g}")
        if win is not None:
            self._apply({"display_window_s": win})
        amp = _combo_text("amp (uV)##vd_damp", float(s["display_amp"]),
                          _AMP_CHOICES, lambda v: "auto" if v <= 0 else f"{v:g}")
        if amp is not None:
            self._apply({"display_amp": amp})
        imgui.push_item_width(130)
        changed, v = imgui.input_int("ch from##vd_ch0", int(s["channel_start"]))
        if changed:
            self._apply({"channel_start": v})
        changed, v = imgui.input_int("ch count##vd_chn", int(s["channel_count"]))
        if changed:
            self._apply({"channel_count": v})
        imgui.pop_item_width()
        changed, v = imgui.checkbox("freeze display##vd_freeze", bool(self._freeze))
        if changed:
            self._freeze = bool(v)

    def _draw_filters_section(self) -> None:
        s = self._settings
        changed, v = imgui.checkbox("enabled##vd_fen", bool(s["filt_enabled"]))
        if changed:
            self._apply({"filt_enabled": v})
        notch = _combo_text("notch##vd_notch", s["filt_notch"], vd.NOTCH_CHOICES)
        if notch is not None:
            self._apply({"filt_notch": notch})
        band = _combo_text("band##vd_band", s["filt_type"], vd.BAND_TYPES)
        if band is not None:
            self._apply({"filt_type": band})
        imgui.push_item_width(130)
        changed, v = imgui.input_float("low (Hz)##vd_flo", float(s["filt_low"]), 0.5, 1.0)
        if changed:
            self._apply({"filt_low": v})
        changed, v = imgui.input_float("high (Hz)##vd_fhi", float(s["filt_high"]), 0.5, 1.0)
        if changed:
            self._apply({"filt_high": v})
        imgui.pop_item_width()
        order = _combo_text("order##vd_order", int(s["filt_order"]), vd.ORDERS, lambda v: str(v))
        if order is not None:
            self._apply({"filt_order": order})
        imgui.text_colored(_CLR_DIM, "display filter = causal IIR (real-time semantics)")

    def _maybe_pull(self) -> None:
        """节流拉取会话快照 → 视图刷新（~25 Hz; freeze 时停拉）。"""
        session = get_session(self._SESSION)
        if session is None:
            return
        now = time.monotonic()
        if not self._force_pull and (now - self._last_pull) < _PULL_INTERVAL_S:
            return
        self._last_pull = now
        self._force_pull = False
        if self._freeze:
            return
        if session.state in ("recording", "monitoring"):
            result, why = get_data(self._SESSION, self._elapsed())
        else:
            result, why = get_data(self._SESSION, 0.0)
        if result is None:
            self._error = why
            return
        self._view.refresh(result["data"], result["samples"], self._filters())

    def _draw_monitor(self) -> None:
        """面板绘制（渲染线程帧内; 只画内容 — 窗口由宿主管理）。"""
        s = self._settings
        self._draw_transport()
        if self._error:
            imgui.text_colored(_CLR_ERR, f"error: {self._error}")
        if imgui.collapsing_header("Session", imgui.TreeNodeFlags_.default_open):
            self._draw_session_section()
        if imgui.collapsing_header("Display", imgui.TreeNodeFlags_.default_open):
            self._draw_display_section()
        if imgui.collapsing_header("Display filters (real-time)"):
            self._draw_filters_section()
        imgui.separator()
        self._maybe_pull()
        vs.draw_scope(self._view, s["display_window_s"], s["display_amp"],
                      s["channel_start"], 240.0)
        if self._view.note:
            imgui.text_colored(vs.TEXT_DIM, f"note: {self._view.note}")
        imgui.separator()
        vs.draw_stats_table(self._view.stats, vd.STATS_ROWS)


def create_extension() -> VirtualDeviceExtension:
    return VirtualDeviceExtension()
