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
  - Serial 页: 端口（枚举）/ 波特率 / 监视启停 / 发送（文本·hex / 换行策略）
  - Parallel 页: 驱动状态 / 地址集 / 编码格式（byte·bytes·string）/ 载荷预览 /
    脉冲宽度（自动归零延迟）/ 写入（首次点击自动拉起 spd-io — 编辑器租约）
  - 事件流: RX / TX / PX / SYS 环形缓冲快照 + 统计（tx/rx 计数、最后错误、线程状态）

I/O 线程所有权（单线程 + 租约 — 见 state.py）: 编辑器面板持 "editor" 租约
（写/发/监视时自动获取，扩展停用时释放）; GameRuntime 持 "runtime" 租约。
PIE 运行期间面板手势只增不减 — 关闭面板不会停掉正在跑实验的 I/O 线程（交权）。
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
# 并口编码格式 — (显示标签, 机器值)。
#   ★ "byte" 是设备触发码用的格式: 单字节 1-255 写到 base 地址。
#   "bytes" 是 float32 LE（4 字节, 占 base..base+3）— 写 1.0 时数据口得到 0x00,
#   设备看不到任何值; 且+2/+3 在标准 LPT 上分别是控制/状态寄存器。默认因此取 "byte"。
_PAR_FMTS = [("byte (uint8 1-255)", "byte"),
             ("bytes (float32 LE, 4B)", "bytes"),
             ("string (UTF-8 + LF)", "string")]
_PAR_FMT_KEYS = [key for _lbl, key in _PAR_FMTS]
# 并口自动复位延迟（脉冲宽度）候选 — ms
_RESET_MS_CHOICES = [1, 5, 10, 25, 50]

_SETTINGS_SCHEMA = 2      # 2 = 并口默认格式从 bytes(float32) 改为 byte(uint8)

_PORT_CACHE_TTL = 2.0     # 秒 — 串口枚举缓存
_STREAM_ROWS = 200        # 事件流显示上限

# 左置标签表单（标签在左、控件在右）: 标签列宽 / 控件列宽
_FORM_LABEL_W = 84.0
_FORM_INPUT_W = 200.0

_CLR_OK = imgui.ImVec4(0.45, 0.85, 0.55, 1.0)
_CLR_WARN = imgui.ImVec4(0.95, 0.75, 0.35, 1.0)
_CLR_ERR = imgui.ImVec4(0.90, 0.40, 0.35, 1.0)
_CLR_DIM = imgui.ImVec4(0.60, 0.60, 0.60, 1.0)

try:  # FontAwesome 图标（UI 文本只用图集内字符 — 见 dev protocol §7 / ui_protocol §12）
    from imgui_bundle import icons_fontawesome_6 as _fa6
except Exception:  # noqa: BLE001
    _fa6 = None


def _icon(name: str) -> str:
    """FontAwesome 图标常量（getattr 兜底 — 缺失时回退空串, 不产生 '?'）。"""
    return getattr(_fa6, name, "") if _fa6 is not None else ""


def describe_binding_impact(action: str, name: str, old_port: str,
                            new_port: str, baud: int,
                            node_refs: list[str]) -> list[str]:
    """改绑/解绑确认框正文（纯函数 — 无头可测，UI 只负责渲染）。

    `node_refs` 是当前场景里引用该逻辑名/端口的节点标签（`#434 SerialSend`）。
    解绑会让这些节点指向空（device_alias_unresolved），改绑会把它们接到新端口 ——
    两种都必须先让用户看见受影响范围。
    """
    refs = [str(r) for r in (node_refs or [])]
    head = []
    if action == "unbind":
        head.append(f"Unbind @{name} (currently {old_port or '(unbound)'})?")
        if refs:
            head.append(f"{len(refs)} node(s) in the current scene reference @{name}:")
            head.extend(f"    {r}" for r in refs[:8])
            if len(refs) > 8:
                head.append(f"    … and {len(refs) - 8} more")
            head.append("After unbinding these nodes point to nothing "
                        "(device_alias_unresolved) until you bind the name again.")
        else:
            head.append("No scene node references this name right now.")
    elif action == "rebind":
        head.append(f"Rebind @{name}: {old_port or '(unbound)'} -> {new_port} @{baud}?")
        if refs:
            head.append(f"{len(refs)} node(s) reference @{name}; they will talk to "
                        f"{new_port} after the change:")
            head.extend(f"    {r}" for r in refs[:8])
            if len(refs) > 8:
                head.append(f"    … and {len(refs) - 8} more")
        else:
            head.append("No scene node references this name right now.")
    else:
        head.append(f"{action}: @{name} -> {new_port or '(unbind)'}")
    return head
def parallel_payload(value_text, fmt: str) -> bytes:
    """并口值 → 待写入字节串（面板预览与写入前的**同一份校验**，纯函数可测）。

    Raises:
        ValueError — 值不合法（文案直接可展示给用户）。
    """
    from Application.Functions.SerialParallelDevice.protocol import encode
    key = str(fmt or "byte")
    if key not in _PAR_FMT_KEYS:
        raise ValueError(f"unknown format '{key}' (use {' / '.join(_PAR_FMT_KEYS)})")
    text = str(value_text if value_text is not None else "").strip()
    if key == "byte":
        try:
            raw = int(float(text))
        except (TypeError, ValueError):
            raise ValueError(f"'{text}' is not a number (byte needs an integer 1-255)")
        if raw == 0:
            raise ValueError("0 = line reset — a pulse never needs 0"
                             " (the line returns to 0 automatically)")
        if not 1 <= raw <= 255:
            raise ValueError(f"{raw} out of range (byte needs 1-255)")
        return encode(raw, "byte")
    if key == "bytes":
        try:
            num = float(text)
        except (TypeError, ValueError):
            raise ValueError(f"'{text}' is not a number (float32)")
        return encode(num, "bytes")
    return encode(value_text, "string")


def _par_fmt_label(key: str) -> str:
    """机器值 → 显示标签（未知值回退原样 — 旧设置容错）。"""
    for label, val in _PAR_FMTS:
        if val == key:
            return label
    return str(key)


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
    version = "0.5.0"

    _WINDOW_NAME = "Serial/Parallel Monitor"
    _MANAGER_NAME = "Device Manager"

    def __init__(self) -> None:
        self._ctx = None
        self._settings = {
            "schema": _SETTINGS_SCHEMA,
            "port": "", "baud": 115200,
            "newline": 1,                    # index into _NEWLINE_CHOICES (1 = "\n")
            "hex_mode": False, "send_text": "",
            "p_addr": 0x3FF8, "p_value": "1", "p_fmt": "byte",
            "reset_ms": 5,                   # 并口脉冲宽度（写非零后自动归零）
        }
        self._ports: list[dict] = []
        self._ports_ts = 0.0
        self._ui_error = ""
        self._ui_error_ts = 0.0
        self._last_write = ""        # 最近一次并口写入回显（地址 + 字节）
        # Device Manager 状态
        self._mgr_target = ""        # 目标端口（改绑/新建绑定用）
        self._mgr_new_name = ""      # 新建绑定名
        self._mgr_msg = ""           # 操作结果行（含错误）
        self._pending: dict | None = None   # 待确认动作（改绑/解绑）

    # ════════════════════════════════════════════════════════════
    # 生命周期（协议 §5）
    # ════════════════════════════════════════════════════════════

    def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._load_settings()
        self._install(ctx)
        ctx.log(f"panels ready ('{self._WINDOW_NAME}', '{self._MANAGER_NAME}')")

    def on_enable(self) -> None:
        if self._ctx is not None:
            self._install(self._ctx)   # 幂等 — disable 后 enable 重走
            try:
                res = self._op_autobind({})
                if res["bound"] or res["ambiguous"]:
                    self._ctx.log("autobind: " + json.dumps(res, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001 — 启动期自动重绑失败不阻塞面板
                self._ctx.log(f"autobind failed: {e!r}")

    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件（UIExtensionBase 抽象方法实现）。

        "closed": 用户关闭了监视面板 —— 即时收尾: 停掉监视（释放端口）。
        close_policy="disable" 下, 宿主另将请求停用本扩展（→ on_disable 释放编辑器租约）。
        """
        if event == "closed":
            if name == self._WINDOW_NAME:
                from Application.Functions.SerialParallelDevice import stop_watch
                stop_watch()
                if self._ctx is not None:
                    self._ctx.log(f"monitor panel closed by user — watch stopped ('{name}')")
            elif self._ctx is not None:
                self._ctx.log(f"device manager closed ('{name}') — bindings unchanged")

    def on_disable(self) -> None:
        """扩展停用 → 释放编辑器租约（交权语义）。

        PIE/成品仍持 runtime 租约时，`stop("editor")` **不会**停掉 spd-io 线程 ——
        这就是“PIE 开启则编辑器交权”的具体实现（单线程 + 多租约，不开第二条线程）。
        """
        self._release_editor_lease()

    def on_unload(self) -> None:
        self._release_editor_lease()

    def _release_editor_lease(self) -> None:
        """停止监视 + 释放编辑器租约（幂等 — 可重复调用）。"""
        try:
            from Application.Functions.SerialParallelDevice import (
                io_owner, stop, stop_watch)
            stop_watch()
            stop("editor")
            if self._ctx is not None:
                self._ctx.log(f"editor io lease released (owner now: {io_owner()})")
        except Exception as e:          # noqa: BLE001 — 收尾失败不阻塞宿主
            if self._ctx is not None:
                self._ctx.log(f"editor io lease release failed: {e!r}")

    def _install(self, ctx) -> None:
        """注册 UI 窗口 + 扩展 ops（幂等; 重复注册同名窗口静默跳过）。"""
        for window_name, draw_fn, policy, on_enable, pos, size in (
                (self._WINDOW_NAME, self._draw_monitor, "disable", True, None, None),
                (self._MANAGER_NAME, self._draw_manager, "hide", False,
                 (520.0, 120.0), (620.0, 380.0))):
            try:
                ctx.ui.register_window(window_name, draw_fn, close_policy=policy,
                                       show_on_enable=on_enable, first_pos=pos,
                                       first_size=size)
            except ValueError:
                pass                    # 已注册（重复装载路径）
            except Exception as e:      # noqa: BLE001 — 无 UI 环境: 记日志降级
                ctx.log(f"window registration failed ({window_name}): {e!r}")
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
                     summary="{value, address?, fmt?} 写并口（fmt 默认 byte 单字节 1-255; "
                             "写非零后按面板 pulse 自动归零）")
        ops.register("bind_alias", self._op_bind_alias,
                     summary="{name, port?, baud?, unbind?} 绑定/解绑逻辑设备名（机器侧注册表）")
        ops.register("autobind", self._op_autobind,
                     summary="{name?, dry_run?} 按 USB 指纹自动改绑逻辑设备名（仅唯一候选）")
        ops.register("bind_nodes", self._op_bind_nodes,
                     summary="{name, migrate_from?, dry_run?} 把引用物理端口的场景节点迁到 @name")

    # ════════════════════════════════════════════════════════════
    # ops 实现（agent 通道 — 协议 §9; 全部可在无 UI 环境调用）
    # ════════════════════════════════════════════════════════════

    def _op_status(self, args) -> dict:
        import Application.Core.DeviceRegistry as reg
        from Application.Functions.SerialParallelDevice import (
            io_owner, is_running, parallel_status, reset_delay_ms, watch_state)
        return {"io_running": is_running(), "io_owner": io_owner(),
                "reset_ms": reset_delay_ms(), "watch": watch_state(),
                "parallel": parallel_status(), "settings": dict(self._settings),
                "devices": [{"alias": "@" + name, "describe": reg.describe(name), **entry}
                            for name, entry in sorted(reg.all().items())]}

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
            start("editor")        # spd-io 线程缺失时自动获取编辑器租约（幂等）
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
            start("editor")
        send(port, baud, data, strict=True)   # 模块内部队列 — 非阻塞
        return {"queued": True, "port": port, "baud": baud, "bytes": len(data)}

    def _op_snapshot(self, args) -> dict:
        from Application.Functions.SerialParallelDevice import monitor_snapshot
        return monitor_snapshot(int((args or {}).get("max_events", 200)))

    def _op_write_parallel(self, args) -> dict:
        args = args or {}
        from Application.Functions.SerialParallelDevice import (
            io_owner, is_running, parallel_ready, start, write_parallel)
        if not parallel_ready():
            raise ValueError("parallel driver (InpOut) not available on this system")
        address = int(args.get("address", self._settings.get("p_addr", 0x3FF8)))
        value = args.get("value", self._settings.get("p_value", "1"))
        fmt = str(args.get("fmt", self._settings.get("p_fmt", "byte")))
        payload = parallel_payload(value, fmt)      # 与面板同一份校验（错误直接上升给 CLI）
        if not is_running():
            start("editor")
        write_parallel(address, value, fmt, strict=True)
        return {"queued": True, "address": address, "fmt": fmt,
                "bytes": payload.hex(" "), "io_owner": io_owner()}

    # ════════════════════════════════════════════════════════════
    # ops: 设备名（@alias）—— 两级设备身份（协议 device_io_protocol §10）
    # ════════════════════════════════════════════════════════════

    def _op_bind_alias(self, args) -> dict:
        """绑定/解绑逻辑设备名 → 物理端口（机器侧注册表; 面板按钮走同一实现）。"""
        args = args or {}
        import Application.Core.DeviceRegistry as reg
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required (e.g. name=mibox)")
        if args.get("unbind"):
            return {"alias": "@" + reg.parse_ref(name), "unbound": reg.unbind(name),
                    "devices": reg.all()}
        port = str(args.get("port") or self._settings.get("port") or "").strip()
        if not port:
            raise ValueError("port is required (pass port=COMx or set the panel port first)")
        baud = int(args.get("baud") or self._settings.get("baud") or 115200)
        entry = reg.bind(name, transport=str(args.get("transport") or "serial"),
                         port=port, baud=baud)
        # 绑定即采集 USB 指纹（serial 优先；无序列号记 vid:pid）
        try:
            from Application.Functions.SerialParallelDevice import identity
            info = next((p for p in self._list_ports_now()
                         if str(p.get("device") or "") == port), None)
            if info is not None:
                hint = identity.fingerprint(info)
                if hint:
                    reg.set_hint(name, **hint)
                    entry = reg.get(name) or entry
            elif self._ctx is not None:
                self._ctx.log(f"no USB fingerprint for {port} (manual or unplugged)")
        except Exception as e:  # noqa: BLE001 — 指纹采集失败不影响绑定
            if self._ctx is not None:
                self._ctx.log(f"fingerprint capture failed for {port}: {e!r}")
        # 绑定即同步面板当前端口（agent 显式传 port 时面板不应继续停在旧口）
        self._settings["port"], self._settings["baud"] = port, baud
        self._save_settings()
        return {"alias": "@" + reg.parse_ref(name), "entry": entry,
                "describe": reg.describe(name), "devices": reg.all()}

    def _op_autobind(self, args) -> dict:
        """按 USB 指纹自动改绑逻辑设备名（唯一候选才改；歧义/无匹配显式报告）。"""
        args = args or {}
        import Application.Core.DeviceRegistry as reg
        from Application.Functions.SerialParallelDevice import identity

        dry = bool(args.get("dry_run"))
        ports = self._list_ports_now()
        requested = str(args.get("name") or "").strip()
        if requested:
            name = reg.parse_ref(requested)
            if reg.get(name) is None:
                raise ValueError(f"@{name} is not bound — bind it first (bind_alias)")
            names = [name]
        else:
            names = sorted(reg.all().keys())

        out = {"dry_run": dry, "bound": [], "ambiguous": [],
               "unmatched": [], "unchanged": []}
        for name in names:
            entry = reg.get(name) or {}
            hint = dict(entry.get("hint") or {})
            cur_port = str(entry.get("port") or "")
            cur_info = next((p for p in ports
                             if str(p.get("device") or "") == cur_port), None)

            # 旧绑定没有 hint: 设备当前在位时补录指纹（不改变端口）。
            if cur_info is not None and not hint:
                hint = identity.fingerprint(cur_info)
                if hint and not dry:
                    reg.set_hint(name, **hint)

            if cur_info is not None and hint:
                cur_match = identity.match(hint, [cur_info])
                if cur_match["status"] == "matched":
                    out["unchanged"].append({"alias": "@" + name, "port": cur_port})
                    continue

            res = identity.match(hint, ports)
            if res["status"] == "matched":
                new_port = str(res["port"].get("device") or "")
                item = {"alias": "@" + name, "from": cur_port, "to": new_port,
                        "matched_by": res["reason"]}
                out["bound"].append(item)
                if not dry and new_port and new_port != cur_port:
                    reg.bind(name, port=new_port,
                             baud=int(entry.get("baud") or self._settings.get("baud") or 115200))
                    if self._ctx is not None:
                        self._ctx.log(
                            f"auto-bound @{name} -> {new_port} ({res['reason']})")
                    # 面板若正停在那个已失效的旧口，跟着换（保持面板与设备一致）
                    if str(self._settings.get("port") or "") == cur_port:
                        self._settings["port"] = new_port
                        self._save_settings()
            elif res["status"] == "ambiguous":
                item = {"alias": "@" + name,
                        "candidates": [c.get("device") for c in res["candidates"]]}
                out["ambiguous"].append(item)
                if self._ctx is not None:
                    self._ctx.log(
                        f"auto-bind @{name} ambiguous: {item['candidates']} — not changed")
            else:
                out["unmatched"].append({"alias": "@" + name, "reason": res["reason"]})
        return out

    def _op_bind_nodes(self, args) -> dict:
        """把场景里指向某物理端口的节点一键迁到逻辑设备名（面板按钮走同一实现）。

        args: `{name, migrate_from?, dry_run?}` —— `migrate_from` 省略时用该别名
        当前绑定的物理端口（即"把裸 COMx 的节点迁到 @name"）。
        """
        args = args or {}
        import Application.Core.DeviceRegistry as reg
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        alias = "@" + reg.parse_ref(name)
        migrate_from = str(args.get("migrate_from") or "").strip()
        if not migrate_from:
            entry = reg.get(name)
            if entry is None:
                raise ValueError(f"{alias} is not bound — bind it first (bind_alias)")
            migrate_from = str(entry.get("port") or "")
        if not migrate_from:
            raise ValueError(f"{alias} has no bound port to migrate from")
        graph = getattr(self._ctx, "graph", None)
        if graph is None:
            raise ValueError("graph capability unavailable (manifest needs "
                             "capabilities: [..., \"graph\"])")
        if not graph.available():
            raise ValueError("no active node graph (open a scene with a node graph first)")
        targets = graph.find("port", equals=migrate_from)
        if args.get("dry_run"):
            return {"alias": alias, "migrate_from": migrate_from,
                    "would_migrate": [n["id"] for n in targets], "migrated": []}
        migrated = []
        for node in targets:
            graph.set_props(node["id"], {"port": alias})
            migrated.append(node["id"])
        if self._ctx is not None:
            self._ctx.log(f"migrated {len(migrated)} node(s) {migrate_from} -> {alias}")
        return {"alias": alias, "migrate_from": migrate_from, "migrated": migrated}

    # ════════════════════════════════════════════════════════════
    # 面板: 设备名段（实验室 = 发现/检定/绑定; 设计真相仍在场景）
    # ════════════════════════════════════════════════════════════

    def _nodes_with_port(self, port: str) -> list:
        """当前图中 `props.port == port` 的节点（无图/无能力 → []）。"""
        if not port:
            return []
        graph = getattr(self._ctx, "graph", None)
        if graph is None:
            return []
        try:
            return graph.find("port", equals=port) if graph.available() else []
        except Exception:  # noqa: BLE001 — 无图环境降级
            return []

    def _guard(self, op_name: str, args: dict) -> None:
        """面板按钮 → **与 agent 同一操作实现**（动作单点），结果显式显示（禁静默）。"""
        fn = {"bind_alias": self._op_bind_alias,
              "bind_nodes": self._op_bind_nodes,
              "autobind": self._op_autobind}.get(op_name)
        if fn is None:
            self._mgr_msg = f"error: unknown panel op {op_name}"
            return
        try:
            res = fn(args or {})
            self._mgr_msg = "ok: " + json.dumps(res, ensure_ascii=False)[:120]
        except Exception as e:  # noqa: BLE001 — 显式显示 + 记日志
            self._mgr_msg = f"error: {e}"
            if self._ctx is not None:
                self._ctx.log(f"{op_name} failed: {e}")

    # ── Device Manager: 绑定/改绑/解绑（含节点影响确认） ────────

    def _node_refs(self, name: str, port: str) -> list[str]:
        """当前场景中引用 @name 或该物理端口的节点（`#434 SerialSend` 形式）。"""
        seen: set[int] = set()
        refs: list[str] = []
        for needle in (("@" + name) if name else "", port or ""):
            for item in self._nodes_with_port(needle):
                nid = int(item.get("id", -1))
                if nid in seen:
                    continue
                seen.add(nid)
                refs.append(f"#{nid} {item.get('type', '?')}")
        return refs

    def _alias_summary(self) -> str:
        """监视面板一行摘要（详情在 Device Manager）。"""
        import Application.Core.DeviceRegistry as reg
        devices = reg.all()
        if not devices:
            return "no @alias bound — open Device Manager"
        parts = [f"@{n} -> {entry.get('port') or '(unbound)'}"
                 for n, entry in sorted(devices.items())]
        return ", ".join(parts)[:90]

    def _show_manager(self) -> None:
        """把 Device Manager 窗口置为可见（View 菜单同路径）。"""
        try:
            ui = getattr(self._ctx, "ui", None) if self._ctx is not None else None
            if ui is not None and hasattr(ui, "show_window"):
                ui.show_window(self._MANAGER_NAME)
        except Exception as e:  # noqa: BLE001 — 打开窗口失败不拖垮帧
            self._set_error(f"open Device Manager: {e!r}")

    def _port_combo(self, label: str, key: str, current: str,
                    width: float = 230.0) -> str | None:
        """端口下拉（以枚举结果为准）。返回新选项或 None；当前值不在列表时标 “(not found)”。"""
        entries: dict[str, str] = {}
        for p in self._ports:
            dev = str(p.get("device") or "")
            if not dev:
                continue
            desc = str(p.get("description") or "")
            vid, pid = p.get("vid"), p.get("pid")
            tag = f" [{vid:04X}:{pid:04X}]" if isinstance(vid, int) and isinstance(pid, int) else ""
            entries[dev] = (f"{dev} — {desc}{tag}" if desc else f"{dev}{tag}")
        cur = str(current or "")
        if cur and cur not in entries:
            suffix = " (alias)" if cur.startswith("@") else " (not found)"
            entries[cur] = f"{cur}{suffix}"
        preview = entries.get(cur) or "(select a discovered port)"
        chosen = None
        self._form_label(label)
        imgui.set_next_item_width(float(width))
        if imgui.begin_combo(f"##spd_{key}", preview):
            for dev, text in entries.items():
                if imgui.selectable(text + f"##{key}_{dev}", dev == cur)[0]:
                    chosen = dev
            if not entries:
                imgui.text_disabled("no ports discovered")
            imgui.end_combo()
        return chosen

    def _draw_manager(self) -> None:
        """Device Manager — 独立面板: 发现端口、绑定/改绑/解绑逻辑设备名。

        解绑/改绑会改变场景节点的设备指向 → 一律先弹确认框（列出受影响节点）。
        """
        import Application.Core.DeviceRegistry as reg
        now = time.perf_counter()
        if now - self._ports_ts > _PORT_CACHE_TTL:
            self._list_ports_now()

        imgui.text_disabled(f"Discovered ports ({len(self._ports)})")
        picked = self._port_combo("Target port", "mgr_target",
                                  self._mgr_target or str(self._settings.get("port") or ""),
                                  width=260)
        if picked:
            self._mgr_target = picked
            self._settings["port"] = picked
            self._save_settings()
        imgui.same_line()
        if imgui.button(f"{_icon('ICON_FA_ARROWS_ROTATE') or 'Refresh'}##spd_mgr_refresh"):
            self._list_ports_now()

        target = self._mgr_target or str(self._settings.get("port") or "")
        baud = int(self._settings.get("baud") or 115200)
        devices = reg.all()
        imgui.separator()
        imgui.text_disabled(f"Bound devices ({len(devices)})")
        if not devices:
            imgui.text_disabled("(none — select a port above, type a name below, then Bind)")
        for name in sorted(devices):
            entry = devices[name]
            port = str(entry.get("port") or "")
            refs = self._node_refs(name, port)
            col = _CLR_OK if port else _CLR_WARN
            imgui.text_colored(col, f"@{name}")
            imgui.same_line()
            imgui.text_disabled(f"-> {port or '(unbound)'} @{int(entry.get('baud') or baud)}")
            hint = entry.get("hint") or {}
            if hint.get("usb_serial"):
                imgui.same_line()
                imgui.text_disabled(f"| USB serial {hint['usb_serial']}")
            elif hint.get("vid_pid"):
                imgui.same_line()
                imgui.text_disabled(f"| {hint['vid_pid']}")
            if refs:
                imgui.same_line()
                imgui.text_disabled(f"| {len(refs)} node(s)")

            imgui.same_line()
            if imgui.small_button(f"Rebind##mgr_rb_{name}"):
                if not target:
                    self._mgr_msg = "error: select a target port first"
                elif target == port:
                    self._mgr_msg = f"@{name} already bound to {port}"
                else:
                    self._request_confirm("rebind", name, port, target, baud, refs)
            imgui.same_line()
            if imgui.small_button(f"Unbind##mgr_ub_{name}"):
                self._request_confirm("unbind", name, port, "", baud, refs)
            if port and port != target:
                n_raw = len(self._nodes_with_port(port))
                if n_raw:
                    imgui.same_line()
                    if imgui.small_button(f"Migrate {n_raw} -> @{name}##mgr_mg_{name}"):
                        self._guard("bind_nodes", {"name": name})

        imgui.separator()
        changed, val = self._labeled_input("New binding", "mgr_new_name", self._mgr_new_name,
                                          width=160)
        if changed:
            self._mgr_new_name = val
        imgui.same_line()
        if imgui.small_button(f"{_icon('ICON_FA_TAG')} Bind target port##mgr_bind"):
            if not self._mgr_new_name.strip():
                self._mgr_msg = "error: device name required"
            elif not target:
                self._mgr_msg = "error: select a target port first"
            else:
                self._guard("bind_alias", {"name": self._mgr_new_name.strip(),
                                           "port": target, "baud": baud})
        imgui.same_line()
        if imgui.small_button(f"{_icon('ICON_FA_MAGNIFYING_GLASS')} Auto-detect##mgr_autobind"):
            self._guard("autobind", {})
        if imgui.is_item_hovered():
            imgui.set_tooltip("match USB fingerprint (serial > vid:pid)")
        self._mgr_msg = self._mgr_msg or ""
        if self._mgr_msg:
            imgui.text_disabled(self._mgr_msg)
        self._draw_confirm_popup()

    def _request_confirm(self, action: str, name: str, old_port: str,
                         new_port: str, baud: int, refs: list[str]) -> None:
        self._pending = {
            "open": True,
            "action": action,
            "name": name,
            "old_port": old_port,
            "new_port": new_port,
            "baud": int(baud),
            "lines": describe_binding_impact(action, name, old_port, new_port, baud, refs),
        }

    def _apply_pending(self) -> None:
        pending = self._pending or {}
        action = pending.get("action")
        name = str(pending.get("name") or "")
        if action == "unbind":
            self._guard("bind_alias", {"name": name, "unbind": True})
        elif action == "rebind":
            self._guard("bind_alias", {"name": name,
                                       "port": pending.get("new_port"),
                                       "baud": pending.get("baud")})
        self._pending = None

    def _draw_confirm_popup(self) -> None:
        """影响确认弹窗（改绑/解绑会把场景节点从旧设备改到新设备 / 指向空）。"""
        pending = self._pending
        if pending is None:
            return
        if pending.get("open"):
            imgui.open_popup("Confirm device change##spd_confirm")
            pending["open"] = False
        imgui.set_next_window_size((480.0, 0.0), imgui.Cond_.always)
        opened = imgui.begin_popup_modal("Confirm device change##spd_confirm")[0]
        if opened:
            try:
                lines = list(pending.get("lines") or [])
                if lines:
                    imgui.text(lines[0])
                for line in lines[1:]:
                    imgui.text_wrapped(line)
                imgui.spacing()
                if imgui.button("Cancel##spd_confirm_cancel"):
                    self._pending = None
                    imgui.close_current_popup()
                imgui.same_line()
                if imgui.button(f"{_icon('ICON_FA_CHECK') or 'OK'} Confirm##spd_confirm_ok"):
                    self._apply_pending()
                    imgui.close_current_popup()
            finally:
                imgui.end_popup()

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
            saved = {}
        except Exception as e:          # noqa: BLE001 — 损坏设置不致命
            saved = {}
            self._ctx.log(f"settings load failed: {e!r}")

        # ── 迁移 schema 1 → 2 ──
        #    旧默认 p_fmt="bytes"(float32) 写 1.0 会把数据口打成 0x00, 设备看不到;
        #    升级为 "byte"(单字节触发码) 并把值重置为 1。其余字段不动。
        try:
            old_schema = int(saved.get("schema", 1))
        except (TypeError, ValueError):
            old_schema = 1
        if old_schema < _SETTINGS_SCHEMA:
            if self._settings.get("p_fmt") not in _PAR_FMT_KEYS:
                self._settings["p_fmt"] = "byte"
            elif self._settings.get("p_fmt") == "bytes":
                self._settings["p_fmt"] = "byte"
            self._settings["p_value"] = "1"
            self._settings["schema"] = _SETTINGS_SCHEMA
            self._save_settings()

        # 并口脉冲宽度是**全局设备设置**（节点写入同样生效）— 重新装载即恢复
        try:
            from Application.Functions.SerialParallelDevice import set_reset_delay
            set_reset_delay(float(self._settings.get("reset_ms", 5)))
        except Exception as e:          # noqa: BLE001
            self._ctx.log(f"reset delay apply failed: {e!r}")

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

    # ── 左置标签表单（标签列 + 控件列对齐） ─────────────────────
    #
    # ★ imgui_bundle 的 `input_text(label, text, flags=0)` 第三参数是 **flags**，
    #   不是缓冲区长度。旧代码传 128/1024 会把 1024(=Password) 当标志 → 输入显示成
    #   `**`。这里统一走 `input_text(..., 0)`，长度交给 Python 绑定自己管理。
    #
    # ★ begin_combo/end_combo 必须**就地成对**（不开 helper 包一层）: 配对守卫
    #   按文件计数 begin/end，间接封装会被当成不平衡。

    def _form_label(self, label: str) -> None:
        """在字段左侧画标签，并把光标移到同一行的输入列。"""
        x0 = float(imgui.get_cursor_pos_x())
        imgui.align_text_to_frame_padding()
        imgui.text(label)
        imgui.same_line(x0 + _FORM_LABEL_W)

    def _labeled_input(self, label: str, key: str, value: str,
                       width: float = _FORM_INPUT_W):
        self._form_label(label)
        imgui.set_next_item_width(float(width))
        return imgui.input_text(f"##spd_{key}", str(value), 0)

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
        from Application.Functions.SerialParallelDevice import io_owner
        owner = io_owner()
        imgui.text_disabled("spd-io:")
        imgui.same_line()
        if io_running:
            imgui.text_colored(_CLR_OK, f"running ({owner})")
            if owner == "runtime":
                imgui.same_line()
                imgui.text_disabled("|")
                imgui.same_line()
                imgui.text_colored(_CLR_WARN, "PIE owns I/O — panel punches through")
        else:
            imgui.text_colored(_CLR_WARN, "stopped (auto-start on watch/send/write)")
        watch = watch_state()
        if watch["active"]:
            imgui.same_line()
            imgui.text_disabled("|")
            imgui.same_line()
            col = _CLR_OK if watch["opened"] else _CLR_WARN
            imgui.text_colored(col, f"watching {watch['port']}@{watch['baud']}"
                                    f" ({'open' if watch['opened'] else 'waiting'})")

        # ── 端口: [自由度: L1] 只列**枚举到的**端口（发现即选，不再手输） ──
        picked = self._port_combo("Port", "port", s["port"], width=230)
        if picked and picked != s["port"]:
            s["port"] = picked
            self._save_settings()
        imgui.same_line()
        if imgui.button(f"{_icon('ICON_FA_ARROWS_ROTATE') or 'Refresh'}##spd_refresh"):
            self._list_ports_now()                  # 只刷新枚举缓存，不改绑定
        if imgui.is_item_hovered():
            imgui.set_tooltip("Re-enumerate serial ports")

        # ── 波特率: [自由度: L1] 受控枚举 ──
        self._form_label("Baud")
        imgui.set_next_item_width(150)
        if imgui.begin_combo("##spd_baud", str(s["baud"])):
            for b in _COMMON_BAUDS:
                if imgui.selectable(str(b) + "##spd_b", b == s["baud"])[0]:
                    s["baud"] = int(b)
                    self._save_settings()
            imgui.end_combo()

        # ── 设备管理: 独立面板（绑定/改绑/解绑 + 节点影响确认） ──
        self._form_label("Devices")
        if imgui.button(f"{_icon('ICON_FA_SLIDERS')} Device Manager##spd_open_mgr"):
            self._show_manager()
        imgui.same_line()
        imgui.text_disabled(self._alias_summary())

        # ── 监视启停: [自由度: L0] ──
        self._form_label("Monitor")
        if not watch["active"]:
            if imgui.button(f"{_icon('ICON_FA_PLAY')} Start Watch##spd_watch"):
                if not s["port"]:
                    self._set_error("port required")
                else:
                    if not io_running:
                        start("editor")     # 编辑器租约（PIE 运行时不抢占）
                    start_watch(s["port"], int(s["baud"]))
        else:
            if imgui.button(f"{_icon('ICON_FA_STOP')} Stop Watch##spd_watch"):
                stop_watch()

        imgui.separator()

        # ── 发送区 ──
        changed, val = self._labeled_input("Send", "send", s["send_text"], width=260)
        if changed:
            s["send_text"] = val
        imgui.same_line()
        nl_label = _NEWLINE_CHOICES[s["newline"]][0]
        imgui.set_next_item_width(150)
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
        if imgui.button(f"{_icon('ICON_FA_PAPER_PLANE')} Send##spd_send_btn"):                                # [L0]
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
            start("editor")
        try:
            send(s["port"], int(s["baud"]), data, strict=True)
        except Exception as e:          # noqa: BLE001 — 受控展示（不静默丢包）
            self._set_error(f"serial send: {e}")

    # ── Parallel 页 ────────────────────────────────────────────

    def _draw_parallel_tab(self) -> None:
        from Application.Functions.SerialParallelDevice import (
            PARALLEL_ADDRS, is_running, parallel_ready, reset_delay_ms)
        s = self._settings
        ready = parallel_ready()
        running = is_running()

        if ready:
            imgui.text_colored(_CLR_OK, "InpOut driver: available")
        else:
            imgui.text_colored(_CLR_DIM, "InpOut driver: not available (Windows-only)")
        imgui.same_line()
        imgui.text_disabled("|")
        imgui.same_line()
        imgui.text_colored(_CLR_OK if running else _CLR_WARN,
                           f"spd-io: {'running' if running else 'stopped (auto-start on Write)'}")

        # ── 地址: [自由度: L1] 受控枚举（trigger 口 + LPT） ──
        self._form_label("Address")
        imgui.set_next_item_width(150)
        if imgui.begin_combo("##spd_paddr", f"0x{int(s['p_addr']):04X}"):
            for a in PARALLEL_ADDRS:
                if imgui.selectable(f"0x{a:04X}##spd_pa", a == int(s["p_addr"]))[0]:
                    s["p_addr"] = a
                    self._save_settings()
            imgui.end_combo()

        # ── 编码格式: [自由度: L1] byte(单字节触发码) / bytes(float32) / string ──
        self._form_label("Format")
        imgui.set_next_item_width(200)
        if imgui.begin_combo("##spd_pfmt", _par_fmt_label(str(s["p_fmt"]))):
            for label, key in _PAR_FMTS:
                if imgui.selectable(label + "##spd_pf", key == s["p_fmt"])[0]:
                    s["p_fmt"] = key
                    self._save_settings()
            imgui.end_combo()

        # ── 值: [自由度: L2] 开放输入（byte=整数 1-255 / bytes=浮点 / string=文本） ──
        changed, val = self._labeled_input("Value", "pval", str(s["p_value"]), width=200)
        if changed:
            s["p_value"] = val
            self._save_settings()

        # ── 脉冲宽度（写非零后自动归零）: [自由度: L1] ──
        self._form_label("Pulse")
        imgui.set_next_item_width(150)
        if imgui.begin_combo("##spd_preset", f"{int(s['reset_ms'])} ms"):
            for ms in _RESET_MS_CHOICES:
                if imgui.selectable(f"{ms} ms##spd_rm", ms == int(s["reset_ms"]))[0]:
                    s["reset_ms"] = int(ms)
                    self._save_settings()
                    from Application.Functions.SerialParallelDevice import set_reset_delay
                    set_reset_delay(ms)          # 全局设备设置 — 节点写入同样使用
            imgui.end_combo()
        imgui.same_line()
        imgui.text_disabled(f"(now {reset_delay_ms():g} ms) auto-zero after write")

        # ── 载荷预览 + 校验（与写入前同一份校验 — 设备看不到值时可对比此字节） ──
        payload = None
        try:
            payload = parallel_payload(str(s["p_value"]), str(s["p_fmt"]))
            imgui.text_disabled(f"-> 0x{int(s['p_addr']):04X} <- {payload.hex(' ')} ({len(payload)}B)")
            if str(s["p_fmt"]) == "bytes" and int(s["p_addr"]) in (0x3FF8, 0x3FF0, 0x3FE8):
                imgui.same_line()
                imgui.text_colored(_CLR_WARN, "float32 writes 4 bytes (base..base+3) — "
                                              "trigger ports expect a single byte")
        except ValueError as e:
            imgui.text_colored(_CLR_ERR, f"{e}")

        imgui.same_line()
        if not ready:
            imgui.begin_disabled(True)
        if imgui.button(f"{_icon('ICON_FA_BOLT')} Write##spd_pwrite"):                # [L0]
            self._do_parallel_write()
        if not ready:
            imgui.end_disabled()
        if self._last_write:
            imgui.same_line()
            imgui.text_colored(_CLR_OK, f"last: {self._last_write}")

    def _do_parallel_write(self) -> None:
        """面板并口写入: 先校验 → 确保 spd-io 在跑（★ 此前缺失 = 静默丢弃）→ 严格入队。"""
        from Application.Functions.SerialParallelDevice import (
            is_running, parallel_ready, start, write_parallel)
        s = self._settings
        if not parallel_ready():
            self._set_error("parallel driver (InpOut) not available "
                            "— run as admin / install InpOut32")
            return
        try:
            payload = parallel_payload(str(s["p_value"]), str(s["p_fmt"]))
        except ValueError as e:
            self._set_error(f"parallel value: {e}")
            return
        if not is_running():
            start("editor")             # 面板自己拉起 I/O 线程（获取编辑器租约）
        try:
            write_parallel(int(s["p_addr"]), s["p_value"], s["p_fmt"], strict=True)
        except Exception as e:          # noqa: BLE001 — 受控展示
            self._set_error(f"parallel write: {e}")
            return
        self._last_write = f"0x{int(s['p_addr']):04X} <- {payload.hex(' ')} ({len(payload)}B)"

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
            imgui.text_colored(_CLR_ERR,
                               f"{_icon('ICON_FA_TRIANGLE_EXCLAMATION') or '!'} {self._ui_error}")

        # ★ BeginChild/EndChild 必须无条件配对（全裁剪/最小化时 BeginChild 返回 False
        #   也必须 EndChild — 否则窗口栈失衡、渲染循环断言崩溃）
        stream_visible = imgui.begin_child("##spd_stream", (0, 220), True)
        try:
            if stream_visible:
                self._draw_stream_rows(snap)
        finally:
            imgui.end_child()

    def _draw_stream_rows(self, snap: dict) -> None:
        events = snap.get("events") or []
        if not events:
            imgui.text_disabled("(no events — Start Watch to see TX/RX activity here)")
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

    # ── 工具 ──────────────────────────────────────────────────

    def _set_error(self, msg: str) -> None:
        self._ui_error = str(msg)
        self._ui_error_ts = time.perf_counter()
        print(f"[device] UI error: {msg}")


def create_extension() -> DeviceExtension:
    """入口工厂（extension.json → entry: extension.py:create_extension）。"""
    return DeviceExtension()
