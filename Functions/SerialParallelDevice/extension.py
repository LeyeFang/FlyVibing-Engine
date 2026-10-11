"""Device (Serial/Parallel) 扩展 — **官方示例**（严格对照开发规范编写）。

规范对照（Doc/ExtDev/extension_dev_protocol.md）:
  §2  三文件形态: extension.json + extension.py（+ 复用引擎能力 SPD 模块）
  §5  生命周期: on_load 装配 / on_enable 幂等重装 /
      disable 后由宿主保险丝清理（ops + UI 窗口 — 见 ExtensionManager._purge_*）
  §6  ctx 能力: log / ops.register / ui.register_window / data_dir
  §7  UI 纪律: draw_fn 在渲染线程帧内调用, 只读线程安全快照（SPD.monitor_snapshot —
      模块锁保护）; 池发送经模块内部队列（spd-io 线程执行）— draw 内零阻塞;
      draw 异常由宿主 ExtensionPanel 遏制（本文件不吞错, 抛出即被隔离计数)
  §9  agent 通道: ops → `ext.device.status / list_ports / watch / send / monitor_snapshot /
      write_parallel`（增量扫描 + CLI/MCP 原样透传）
  §11 设置: ctx.data_dir/settings.json 持久化（重开面板保持）

自由度标注（Doc/Dev/ui_protocol.md §11 — 每控件对应级别）:
  L0 按钮/开关: Refresh / Start-Stop Watch / Send / hex 开关 / Write Parallel
  L1 受控枚举: 波特率集 / 换行策略 / 枚举端口拾取器 / 并口地址集 / 并口编码格式
  L2 开放输入: 端口名（域开放, 允许枚举不到的 COM）/ 发送文本 / 并口值
      — L2 约束: 端口空值拒绝; hex 解析失败拒绝; 并口驱动缺失拒绝（UI 层先检 + 业务层兜底）

面板内容:
  - Serial 页: 端口（枚举 + 手输）/ 波特率 / 监视启停 / 发送（文本·hex / 换行策略）
  - Parallel 页: 驱动状态 / 地址集 / 写值（5ms 自动复位由 SPD 模块保证）
  - 事件流: RX / TX / PX / SYS 环形缓冲快照 + 统计（tx/rx 计数、最后错误、线程状态）
"""

from __future__ import annotations

import json
import os
import time

from imgui_bundle import imgui

from Application.Core.Extension.ExtensionBase import UIExtensionBase

# ── 选择集（L1 受控枚举 — 与 ui_protocol §11 对齐; 仅收录已实现值） ──
_COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 921600]
_NEWLINE_CHOICES = [("(none)", b""), ("\\n", b"\n"), ("\\r\\n", b"\r\n")]
_PAR_FMTS = ["bytes", "string"]

_PORT_CACHE_TTL = 2.0     # 秒 — 串口枚举缓存
_STREAM_ROWS = 200        # 事件流显示上限

_CLR_OK = imgui.ImVec4(0.45, 0.85, 0.55, 1.0)
_CLR_WARN = imgui.ImVec4(0.95, 0.75, 0.35, 1.0)
_CLR_ERR = imgui.ImVec4(0.90, 0.40, 0.35, 1.0)
_CLR_DIM = imgui.ImVec4(0.60, 0.60, 0.60, 1.0)
_KIND_CLR = {
    "RX": imgui.ImVec4(0.40, 0.85, 0.55, 1.0),
    "TX": imgui.ImVec4(0.45, 0.65, 1.00, 1.0),
    "PX": imgui.ImVec4(0.85, 0.70, 0.40, 1.0),
    "SYS": imgui.ImVec4(0.62, 0.62, 0.62, 1.0),
}


class DeviceExtension(UIExtensionBase):
    """Device (Serial/Parallel) — 监视面板 + `ext.device.*` ops。

    窗口生命周期（dev protocol §7 完备性示范）:
      close_policy="disable" — 用户点击窗口 X = 停用扩展（Extensions 菜单勾选同步消失）;
      on_ui_event("closed") 收尾 = 停止监视（释放端口）。
    """

    id = "device"
    name = "Device (Serial/Parallel)"
    version = "0.1.0"

    _WINDOW_NAME = "Serial/Parallel Monitor"

    def __init__(self) -> None:
        self._ctx = None
        self._settings = {
            "port": "", "baud": 115200,
            "newline": 1,                    # index into _NEWLINE_CHOICES (1 = "\n")
            "hex_mode": False, "send_text": "",
            "p_addr": 0x3FF8, "p_value": "1.0", "p_fmt": "bytes",
        }
        self._ports: list[dict] = []
        self._ports_ts = 0.0
        self._ui_error = ""
        self._ui_error_ts = 0.0

    # ════════════════════════════════════════════════════════════
    # 生命周期（协议 §5）
    # ════════════════════════════════════════════════════════════

    def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._load_settings()
        self._install(ctx)
        ctx.log(f"monitor panel ready ('{self._WINDOW_NAME}')")

    def on_enable(self) -> None:
        if self._ctx is not None:
            self._install(self._ctx)   # 幂等 — disable 后 enable 重走

    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件（UIExtensionBase 抽象方法实现）。

        "closed": 用户关闭了监视面板 —— 即时收尾: 停掉监视（释放端口）。
        close_policy="disable" 下, 宿主另将请求停用本扩展（菜单勾选随窗口关闭同步消失）。
        """
        if event == "closed":
            from Application.Functions.SerialParallelDevice import stop_watch
            stop_watch()
            if self._ctx is not None:
                self._ctx.log(f"monitor panel closed by user — watch stopped ('{name}')")

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
        ops.register("status", self._op_status, summary="SPD 运行/监视/并口状态")
        ops.register("list_ports", lambda args: {"ports": self._list_ports_now()},
                     summary="枚举本机串口")
        ops.register("watch", self._op_watch,
                     summary="{action: start|stop, port?, baud?} 启停实时监视")
        ops.register("send", self._op_send,
                     summary="{text?|hex?, port?, baud?, newline?} 入队串口发送（非阻塞）")
        ops.register("monitor_snapshot", self._op_snapshot,
                     summary="{max_events?} 事件流快照（agent 监视通道）")
        ops.register("write_parallel", self._op_write_parallel,
                     summary="{value, address?, fmt?} 写并口（5ms 自动复位）")

    # ════════════════════════════════════════════════════════════
    # ops 实现（agent 通道 — 协议 §9; 全部可在无 UI 环境调用）
    # ════════════════════════════════════════════════════════════

    def _op_status(self, args) -> dict:
        from Application.Functions.SerialParallelDevice import (
            is_running, parallel_status, watch_state)
        return {"io_running": is_running(), "watch": watch_state(),
                "parallel": parallel_status(), "settings": dict(self._settings)}

    def _op_watch(self, args) -> dict:
        args = args or {}
        from Application.Functions.SerialParallelDevice import (
            is_running, start, start_watch, stop_watch, watch_state)
        if str(args.get("action", "start")).lower() == "stop":
            return {"watch": stop_watch()}
        port = str(args.get("port") or self._settings.get("port") or "")
        baud = int(args.get("baud") or self._settings.get("baud") or 115200)
        if not port:
            raise ValueError("port is required (pass port= or set panel settings first)")
        if not is_running():
            start()                     # spd-io 线程缺失时自动启动（幂等）
        self._settings["port"], self._settings["baud"] = port, baud
        self._save_settings()
        return {"watch": start_watch(port, baud)}

    def _op_send(self, args) -> dict:
        args = args or {}
        from Application.Functions.SerialParallelDevice import is_running, send, start
        port = str(args.get("port") or self._settings.get("port") or "")
        baud = int(args.get("baud") or self._settings.get("baud") or 115200)
        if not port:
            raise ValueError("port is required")
        if args.get("hex") is not None:
            try:
                data = bytes.fromhex(str(args["hex"]).replace(" ", ""))
            except ValueError as e:
                raise ValueError(f"hex parse failed: {e}") from e
        else:
            data = str(args.get("text", "")).encode("utf-8")
        nl = str(args.get("newline") or "")
        if nl in ("\\n", "lf"):
            data += b"\n"
        elif nl in ("\\r\\n", "crlf"):
            data += b"\r\n"
        if not is_running():
            start()
        send(port, baud, data)          # 模块内部队列 — 非阻塞
        return {"queued": True, "port": port, "baud": baud, "bytes": len(data)}

    def _op_snapshot(self, args) -> dict:
        from Application.Functions.SerialParallelDevice import monitor_snapshot
        return monitor_snapshot(int((args or {}).get("max_events", 200)))

    def _op_write_parallel(self, args) -> dict:
        args = args or {}
        from Application.Functions.SerialParallelDevice import (
            is_running, parallel_ready, start, write_parallel)
        if not parallel_ready():
            raise ValueError("parallel driver (InpOut) not available on this system")
        address = int(args.get("address", self._settings.get("p_addr", 0x3FF8)))
        value = args.get("value", self._settings.get("p_value", "0"))
        fmt = str(args.get("fmt", self._settings.get("p_fmt", "bytes")))
        if not is_running():
            start()
        write_parallel(address, value, fmt)
        return {"queued": True, "address": address, "fmt": fmt}

    # ════════════════════════════════════════════════════════════
    # 设置持久化（协议 §11 — ctx.data_dir/settings.json）
    # ════════════════════════════════════════════════════════════

    def _settings_path(self) -> str:
        return os.path.join(self._ctx.data_dir, "settings.json")

    def _load_settings(self) -> None:
        try:
            with open(self._settings_path(), encoding="utf-8") as fh:
                saved = json.load(fh)
            for key in self._settings:
                if key in saved:
                    self._settings[key] = saved[key]
        except FileNotFoundError:
            pass
        except Exception as e:          # noqa: BLE001 — 损坏设置不致命
            self._ctx.log(f"settings load failed: {e!r}")

    def _save_settings(self) -> None:
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as fh:
                json.dump(self._settings, fh, ensure_ascii=False, indent=2)
        except Exception as e:          # noqa: BLE001
            self._ctx.log(f"settings save failed: {e!r}")

    # ════════════════════════════════════════════════════════════
    # 面板绘制（渲染线程帧内 — 只读快照, 零阻塞; 协议 §7）
    # ════════════════════════════════════════════════════════════

    def _list_ports_now(self) -> list[dict]:
        from Application.Functions.SerialParallelDevice import list_serial_ports
        self._ports = list_serial_ports()
        self._ports_ts = time.perf_counter()
        return self._ports

    def _draw_monitor(self) -> None:
        from Application.Functions.SerialParallelDevice import (
            is_running, monitor_snapshot)
        now = time.perf_counter()
        if now - self._ports_ts > _PORT_CACHE_TTL:
            self._list_ports_now()
        snap = monitor_snapshot(_STREAM_ROWS)

        if imgui.begin_tab_bar("##spd_tabs"):
            if imgui.begin_tab_item("Serial")[0]:
                self._draw_serial_tab(is_running())
                imgui.end_tab_item()
            if imgui.begin_tab_item("Parallel")[0]:
                self._draw_parallel_tab()
                imgui.end_tab_item()
            imgui.end_tab_bar()

        imgui.separator()
        self._draw_stream(snap, now)

    # ── Serial 页 ──────────────────────────────────────────────

    def _draw_serial_tab(self, io_running: bool) -> None:
        from Application.Functions.SerialParallelDevice import (
            start, start_watch, stop_watch, watch_state)
        s = self._settings

        # 状态行
        imgui.text_disabled("spd-io:")
        imgui.same_line()
        if io_running:
            imgui.text_colored(_CLR_OK, "running")
        else:
            imgui.text_colored(_CLR_WARN, "stopped (watch/send 时自动启动)")
        watch = watch_state()
        if watch["active"]:
            imgui.same_line()
            imgui.text_disabled("|")
            imgui.same_line()
            col = _CLR_OK if watch["opened"] else _CLR_WARN
            imgui.text_colored(col, f"watching {watch['port']}@{watch['baud']}"
                                    f" ({'open' if watch['opened'] else 'waiting'})")

        # ── 端口: [自由度: L2] 文本输入为主（域开放）+ [L1] 枚举拾取器 ──
        imgui.set_next_item_width(190)
        changed, val = imgui.input_text("Port##spd_port", s["port"], 128)
        if changed:
            s["port"] = val
            self._save_settings()
        imgui.same_line()
        if imgui.button("Refresh##spd_refresh"):            # [自由度: L0]
            self._list_ports_now()
        imgui.same_line()
        preview = (f"{len(self._ports)} found" if self._ports
                   else "(none enumerated — 可手输端口名)")
        if imgui.begin_combo("##spd_port_pick", preview):    # [自由度: L1]
            for p in self._ports:
                label = p["device"] + (f" — {p['description']}" if p["description"] else "")
                if imgui.selectable(label + "##spd_pick", False)[0]:
                    s["port"] = p["device"]
                    self._save_settings()
            imgui.end_combo()

        # ── 波特率: [自由度: L1] 受控枚举 ──
        if imgui.begin_combo("Baud##spd_baud", str(s["baud"])):
            for b in _COMMON_BAUDS:
                if imgui.selectable(str(b) + "##spd_b", b == s["baud"])[0]:
                    s["baud"] = int(b)
                    self._save_settings()
            imgui.end_combo()

        # ── 监视启停: [自由度: L0] ──
        if not watch["active"]:
            if imgui.button("Start Watch##spd_watch"):
                if not s["port"]:
                    self._set_error("port required")
                else:
                    if not io_running:
                        start()
                    start_watch(s["port"], int(s["baud"]))
        else:
            if imgui.button("Stop Watch##spd_watch"):
                stop_watch()

        imgui.separator()

        # ── 发送区 ──
        imgui.set_next_item_width(280)
        changed, val = imgui.input_text("##spd_send", s["send_text"], 1024)   # [L2]
        if changed:
            s["send_text"] = val
        imgui.same_line()
        nl_label = _NEWLINE_CHOICES[s["newline"]][0]
        if imgui.begin_combo("##spd_nl", f"newline: {nl_label}"):             # [L1]
            for i, (lbl, _data) in enumerate(_NEWLINE_CHOICES):
                if imgui.selectable(lbl + "##spd_nli", i == s["newline"])[0]:
                    s["newline"] = i
                    self._save_settings()
            imgui.end_combo()
        imgui.same_line()
        changed, hv = imgui.checkbox("hex##spd_hex", s["hex_mode"])           # [L0]
        if changed:
            s["hex_mode"] = hv
            self._save_settings()
        imgui.same_line()
        if imgui.button("Send##spd_send_btn"):                                # [L0]
            self._do_send()

    def _do_send(self) -> None:
        from Application.Functions.SerialParallelDevice import is_running, send, start
        s = self._settings
        if not s["port"]:
            self._set_error("port required")
            return
        try:
            if s["hex_mode"]:
                data = bytes.fromhex(str(s["send_text"]).replace(" ", ""))
            else:
                data = str(s["send_text"]).encode("utf-8")
        except ValueError as e:
            self._set_error(f"hex parse failed: {e}")
            return
        data += _NEWLINE_CHOICES[s["newline"]][1]
        if not is_running():
            start()
        send(s["port"], int(s["baud"]), data)

    # ── Parallel 页 ────────────────────────────────────────────

    def _draw_parallel_tab(self) -> None:
        from Application.Functions.SerialParallelDevice import (
            PARALLEL_ADDRS, parallel_ready, write_parallel)
        s = self._settings
        ready = parallel_ready()

        if ready:
            imgui.text_colored(_CLR_OK, "InpOut driver: available")
        else:
            imgui.text_colored(_CLR_DIM, "InpOut driver: not available (Windows-only)")

        # ── 地址: [自由度: L1] 受控枚举（trigger 口 + LPT） ──
        if imgui.begin_combo("Address##spd_paddr", f"0x{int(s['p_addr']):04X}"):
            for a in PARALLEL_ADDRS:
                if imgui.selectable(f"0x{a:04X}##spd_pa", a == int(s["p_addr"]))[0]:
                    s["p_addr"] = a
                    self._save_settings()
            imgui.end_combo()
        imgui.same_line()
        # ── 编码格式: [自由度: L1] ──
        if imgui.begin_combo("##spd_pfmt", s["p_fmt"]):
            for f in _PAR_FMTS:
                if imgui.selectable(f + "##spd_pf", f == s["p_fmt"])[0]:
                    s["p_fmt"] = f
                    self._save_settings()
            imgui.end_combo()

        # ── 值: [自由度: L2] 开放输入（bytes=数字 / string=文本） ──
        imgui.set_next_item_width(200)
        changed, val = imgui.input_text("Value##spd_pval", str(s["p_value"]), 128)
        if changed:
            s["p_value"] = val
            self._save_settings()
        imgui.same_line()
        if not ready:
            imgui.begin_disabled(True)
        if imgui.button("Write (5ms auto-reset)##spd_pwrite"):                # [L0]
            try:
                write_parallel(int(s["p_addr"]), s["p_value"], s["p_fmt"])
            except Exception as e:          # noqa: BLE001 — 受控展示
                self._set_error(f"parallel write: {e!r}")
        if not ready:
            imgui.end_disabled()

    # ── 事件流 / 统计 ──────────────────────────────────────────

    def _draw_stream(self, snap: dict, now: float) -> None:
        stats = snap["stats"]
        imgui.text_disabled(
            f"TX {stats['tx_count']} ({stats['tx_bytes']}B)   "
            f"RX {stats['rx_count']} ({stats['rx_bytes']}B)   "
            f"PX {stats['parallel_writes']}")
        if stats.get("last_error"):
            imgui.same_line()
            imgui.text_colored(_CLR_ERR, f"last error: {stats['last_error']}")
        if self._ui_error and (now - self._ui_error_ts) < 10.0:
            imgui.same_line()
            imgui.text_colored(_CLR_ERR, f"✗ {self._ui_error}")

        if imgui.begin_child("##spd_stream", (0, 220), True):
            events = snap.get("events") or []
            if not events:
                imgui.text_disabled("(no events — Start Watch 后接收/发送将显示在这里)")
            for ev in events:
                imgui.text_colored(_KIND_CLR.get(ev["kind"], _CLR_DIM), f"{ev['kind']}")
                imgui.same_line()
                imgui.text_disabled(f"{ev['t']:10.3f}")
                imgui.same_line()
                hex_part = ev["hex"]
                if len(hex_part) > 96:
                    hex_part = hex_part[:96] + " …"
                line = hex_part or ""
                if ev["text"]:
                    line += f"  |  {ev['text'][:48]}"
                imgui.text(line)
                if ev["note"]:
                    imgui.same_line()
                    imgui.text_disabled(f"[{ev['note']}]")
            imgui.end_child()

    # ── 工具 ──────────────────────────────────────────────────

    def _set_error(self, msg: str) -> None:
        self._ui_error = str(msg)
        self._ui_error_ts = time.perf_counter()
        print(f"[device] UI error: {msg}")


def create_extension() -> DeviceExtension:
    """入口工厂（extension.json → entry: extension.py:create_extension）。"""
    return DeviceExtension()
