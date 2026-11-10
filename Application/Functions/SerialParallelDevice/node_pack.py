"""Device extension node pack — SerialSend / ParallelSend.

节点类型与求值器从核心迁出（2026-10-20）。type 名保持不变（MI-SSSEP
兼容红线）；NodeGraph 自动发现本文件（不需要扩展 enable）。

本文件必须是**纯声明/纯求值器**（不 import Editor / imgui）；控件由
声明式 fields 或现有 Node Editor 控件提供。
"""

from __future__ import annotations

from typing import Any


def _read_input_raw(node_id: int, pin_name: str, ctx, g, default: Any = None) -> Any:
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    return val
    return default


def _payload_preview(payload: bytes, fmt: str) -> str:
    """日志用载荷预览: 文本行给 repr('40,14\\n'), 二进制给 hex。"""
    if fmt == "string":
        try:
            return repr(payload.decode("utf-8"))
        except UnicodeDecodeError:
            pass
    return payload.hex(" ")


def _eval_serial_send(node_id: int, ctx, g) -> None:
    inst = g._canvas.nodes[node_id]
    port = str(inst.props.get("port", "")).strip()
    baud = int(inst.props.get("baud_rate", 9600))
    fmt = str(inst.props.get("format", "bytes") or "bytes")
    # 行协议头/尾 — 例: 刺激器要 `40,14`（重复率 40 Hz + 条件码 14）→ prefix="40,"
    prefix = str(inst.props.get("prefix", "") or "")
    suffix = str(inst.props.get("suffix", "") or "")
    value = _read_input_raw(node_id, "Value", ctx, g, 0)
    if value is None:
        value = 0.0
    if not port:
        ctx.emit_log(node_id, "SerialSend", "error",
                     "no port configured (set 'port' to COMx or @device name)")
        if not ctx.dry_run:
            print("[SerialSend] skipped: no port configured (COM1 default removed)")
        return
    from Application.Functions.SerialParallelDevice.protocol import encode

    # 载荷只在这里构造一次 — 干跑日志与实发字节必定一致
    try:
        payload = encode(value, fmt, prefix=prefix, suffix=suffix)
    except Exception as e:  # noqa: BLE001 — 载荷不合法显式告警（禁止静默）
        ctx.emit_log(node_id, "SerialSend", "error", f"payload: {e}")
        print(f"[SerialSend] payload FAILED: {e}")
        return
    line = _payload_preview(payload, fmt)
    if ctx.dry_run:
        # 注: `val=` 必须在尾（L2 用例按 "val=" 截取）— 新字段插在它之前
        ctx.emit_log(node_id, "SerialSend", "send",
                     f"port={port}, baud={baud}, fmt={fmt}, "
                     f"line={line}, val={value}")
        return
    from Application.Functions.SerialParallelDevice import send as spd_send

    try:
        ok = spd_send(port, baud, payload)
    except Exception as e:  # noqa: BLE001 — 显式告警, 禁止静默吞错
        ctx.emit_log(node_id, "SerialSend", "error", f"{port}@{baud}: {e}")
        print(f"[SerialSend] {port}@{baud} FAILED: {e}")
        return
    if not ok:
        # I/O 线程未运行（扩展被停用 / 运行期入口未启动）→ 节点日志显式告警
        ctx.emit_log(node_id, "SerialSend", "error",
                     f"{port}@{baud}: I/O thread not running — {len(payload)}B dropped")
        return
    print(f"[SerialSend] {port}@{baud} fmt={fmt} line={line} → {len(payload)}B")


def _eval_parallel_send(node_id: int, ctx, g) -> None:
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")
    if mode == "manual":
        address = int(inst.props.get("address", 0x3FF8))
        value = inst.props.get("value", 1)
    else:
        addr_raw = _read_input_raw(node_id, "Address", ctx, g, None)
        if addr_raw is None:
            address = int(inst.props.get("address", 0x3FF8))
        else:
            try:
                address = int(float(addr_raw))
            except (TypeError, ValueError):
                address = int(inst.props.get("address", 0x3FF8))
        value = _read_input_raw(node_id, "Value", ctx, g, 1)
        if value is None:
            value = 1
    try:
        ival = max(1, min(255, int(float(value))))
    except (TypeError, ValueError):
        ival = 1
    if ctx.dry_run:
        ctx.emit_log(node_id, "ParallelSend", "write",
                     f"addr=0x{address:04X}, val=0x{ival:02X} ({ival})")
        return
    from Application.Functions.SerialParallelDevice import write_parallel

    ok = write_parallel(address, ival, "byte")
    if not ok:
        # 线程未运行 / 驱动不可用 → 节点日志显式告警（不打断图执行）
        ctx.emit_log(node_id, "ParallelSend", "error",
                     f"addr=0x{address:04X}, val=0x{ival:02X}: "
                     f"I/O thread or driver unavailable — dropped")
        return
    print(f"[ParallelSend] 0x{address:04X} ← 0x{ival:02X} ({ival})")


def register() -> dict:
    return {
        "id": "device",
        "name": "Device (Serial/Parallel)",
        "owner": "device",
        "signature": "@Official",
        "nodes": [
            {
                "type": "SerialSend",
                "label": "Serial Send",
                "category": "IO",
                "color": (0.878, 0.620, 0.314),
                "props_text": "Send one value over serial on exec. props: port (COMx or "
                              "@alias; empty = explicit error + skip, never guessed); "
                              "baud_rate (default 9600); format ('bytes' = float32 LE 4 bytes, "
                              "'string' = UTF-8 text line); prefix/suffix (string only - frame "
                              "the value, e.g. prefix '40,' + value 14 -> '40,14' + LF; CR/LF "
                              "in prefix/suffix rejected). An unbound @alias raises an explicit "
                              "error (no silent fallback to a default port).",
                "evaluator": _eval_serial_send,
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "Value", "kind": "data", "direction": "input", "data_type": "variant"},
                ],
                "fields": [
                    {"key": "port", "label": "Port", "kind": "serial_port"},
                    {"key": "baud_rate", "label": "Baud", "kind": "int", "default": 9600, "min": 1},
                    {"key": "format", "label": "Format", "kind": "enum",
                     "choices": [["Bytes (float32 LE)", "bytes"], ["String (UTF-8)", "string"]],
                     "default": "bytes"},
                    # 行协议头/尾（仅 format=string）— 空 = 旧行为（str(value) + "\n"）
                    {"key": "prefix", "label": "Prefix", "kind": "text", "default": ""},
                    {"key": "suffix", "label": "Suffix", "kind": "text", "default": ""},
                ],
            },
            {
                "type": "ParallelSend",
                "label": "Parallel Send",
                "category": "IO",
                "color": (0.878, 0.620, 0.314),
                "props_text": "Write one uint8 to an LPT data port on exec. props: mode "
                              "('manual' = use props value; 'pin' = read Address/Value pins); "
                              "address (0x3FF8 LPT1 / 0x3FF0 LPT2 / 0x3FE8 LPT3); value 1-255 "
                              "(clamped; 0 is reserved for the auto reset). Every non-zero "
                              "write is reset to 0 after the configured pulse width (panel "
                              "Pulse, default 5 ms).",
                "evaluator": _eval_parallel_send,
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "Address", "kind": "data", "direction": "input", "data_type": "int"},
                    {"name": "Value", "kind": "data", "direction": "input", "data_type": "variant"},
                ],
                "fields": [
                    {"key": "address", "label": "Address", "kind": "enum",
                     "choices": [["0x3FF8 (LPT1)", 0x3FF8], ["0x3FF0 (LPT2)", 0x3FF0],
                                 ["0x3FE8 (LPT3)", 0x3FE8]],
                     "default": 0x3FF8},
                    {"key": "mode", "label": "Mode", "kind": "enum",
                     "choices": [["Manual", "manual"], ["Pin", "pin"]], "default": "manual"},
                    {"key": "value", "label": "Value (1-255)", "kind": "int",
                     "default": 1, "min": 1, "max": 255},
                ],
            },
        ],
        "menu": [("Device", [("Serial", [
            ("Serial Send", "SerialSend"),
            ("Parallel Send", "ParallelSend"),
        ])])],
    }
