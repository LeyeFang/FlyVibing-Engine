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


def _eval_serial_send(node_id: int, ctx, g) -> None:
    inst = g._canvas.nodes[node_id]
    port = str(inst.props.get("port", "")).strip()
    baud = int(inst.props.get("baud_rate", 9600))
    fmt = inst.props.get("format", "bytes")
    value = _read_input_raw(node_id, "Value", ctx, g, 0)
    if value is None:
        value = 0.0
    if not port:
        ctx.emit_log(node_id, "SerialSend", "error",
                     "no port configured (set 'port' to COMx or @device name)")
        if not ctx.dry_run:
            print("[SerialSend] skipped: no port configured (COM1 default removed)")
        return
    if ctx.dry_run:
        ctx.emit_log(node_id, "SerialSend", "send",
                     f"port={port}, baud={baud}, fmt={fmt}, val={value}")
        return
    from Application.Functions.SerialParallelDevice import send as spd_send
    from Application.Functions.SerialParallelDevice.protocol import encode

    try:
        payload = encode(value, fmt)
        spd_send(port, baud, payload)
    except Exception as e:  # noqa: BLE001 — 显式告警, 禁止静默吞错
        ctx.emit_log(node_id, "SerialSend", "error", f"{port}@{baud}: {e}")
        print(f"[SerialSend] {port}@{baud} FAILED: {e}")
        return
    _hex = payload[:4].hex(" ") if len(payload) >= 4 else payload.hex()
    print(f"[SerialSend] {port}@{baud} fmt={fmt} val={value} → {len(payload)}B [{_hex}]")


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

    write_parallel(address, ival, "byte")
    print(f"[ParallelSend] 0x{address:04X} ← 0x{ival:02X} ({ival})")


def register() -> dict:
    return {
        "id": "device",
        "name": "Device (Serial/Parallel)",
        "owner": "device",
        "nodes": [
            {
                "type": "SerialSend",
                "label": "Serial Send",
                "category": "IO",
                "color": (0.878, 0.620, 0.314),
                "props_text": "Send signal via serial port.",
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
                ],
            },
            {
                "type": "ParallelSend",
                "label": "Parallel Send",
                "category": "IO",
                "color": (0.878, 0.620, 0.314),
                "props_text": "Send uint8 via LPT port",
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
