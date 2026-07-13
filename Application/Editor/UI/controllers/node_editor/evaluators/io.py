"""
Evaluators: IO 节点 (SerialSend)。

SerialSend — 通过串口发送信号，支持 Manual / Pin 双模式，String / Bytes 双格式。
"""

import struct
import threading
from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


# ── 辅助：读取 data input pin 的值（不做类型转换）─────────────

def _read_input_raw(node_id: int, pin_name: str, ctx: ExecutionContext,
                    g: GraphEvaluator, default: Any = None) -> Any:
    """读取指定 data input pin 的值，若未连接则返回 default（不做 float 强转）。"""
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


# ── 串口连接缓存（模块级，跨帧复用） ───────────────────────────

_serial_lock = threading.Lock()
_serial_connections: dict[str, object] = {}  # "PORT:BAUD" → pyserial.Serial


def _get_or_open_serial(port: str, baud: int):
    """获取或打开串口连接。返回 pyserial.Serial 实例或 None。"""
    key = f"{port}:{baud}"
    with _serial_lock:
        if key in _serial_connections:
            ser = _serial_connections[key]
            try:
                if ser.is_open:
                    return ser
            except Exception:
                pass
            # 已失效，移除旧连接
            del _serial_connections[key]

        try:
            import serial
            ser = serial.Serial(port, baud, timeout=0.1)
            _serial_connections[key] = ser
            return ser
        except Exception as e:
            print(f"[SerialSend] Failed to open {port}@{baud}: {e}")
            return None


# ── Evaluator ─────────────────────────────────────────────────

def _eval_serial_send(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """SerialSend — 通过串口发送一个值。

    Format (始终有效): "string" → UTF-8 文本, "bytes" → float32 小端 4 字节
    Manual 模式: Port / BaudRate / Value 全部从节点属性读取。
    Pin 模式:    Port / BaudRate / Value 全部从上游连线读取。
    """
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")
    fmt = inst.props.get("format", "string")

    if mode == "manual":
        port = str(inst.props.get("port", "COM1"))
        baud = int(inst.props.get("baud_rate", 9600))
        value = inst.props.get("value", 0.0)
    else:
        port = _read_input_raw(node_id, "Port", ctx, g, "")
        if not port:
            port = "COM1"
        port = str(port)

        baud_raw = _read_input_raw(node_id, "BaudRate", ctx, g, 0)
        baud = int(baud_raw) if baud_raw else 9600

        value = _read_input_raw(node_id, "Value", ctx, g, 0)
        if value is None:
            value = 0.0

    # ── 按格式编码 ──
    if fmt == "bytes":
        try:
            payload = struct.pack("<f", float(value))
        except (TypeError, ValueError, struct.error):
            print(f"[SerialSend] Invalid numeric value: {value!r}, sending 0.0")
            payload = struct.pack("<f", 0.0)
    else:
        payload = str(value).encode("utf-8")

    ser = _get_or_open_serial(port, baud)
    if ser is not None:
        try:
            ser.write(payload)
        except Exception as e:
            print(f"[SerialSend] Write error on {port}@{baud}: {e}")

register_evaluator("SerialSend", _eval_serial_send)
