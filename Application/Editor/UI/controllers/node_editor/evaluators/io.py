"""
Evaluators: IO 节点 (SerialSend)。

SerialSend — 通过串口发送信号，支持 Manual / Pin 双模式，String / Bytes 双格式。
实际串口 I/O 由 Functions/SerialParallelDevice 线程池执行，本求值器只做入队。
"""

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


# ── Evaluator ─────────────────────────────────────────────────

def _eval_serial_send(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """SerialSend — 通过串口发送一个值。

    Format: "string" → UTF-8 文本, "bytes" → float32 小端 4 字节
    Manual 模式: Port / BaudRate / Value 全部从节点属性读取。
    Pin 模式:    Port / BaudRate / Value 全部从上游连线读取。

    实际写入由 Functions/SerialParallelDevice 的独立 I/O 线程执行，
    本函数仅做参数读取 + 编码 + 入队 — 不阻塞逻辑线程。
    """
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")
    fmt = inst.props.get("format", "bytes")

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

    # ── 编码 + 入队 ──
    from Application.Functions.SerialParallelDevice import send as spd_send
    from Application.Functions.SerialParallelDevice.protocol import encode

    payload = encode(value, fmt)
    spd_send(port, baud, payload)

    # debug: 首 4 字节 hex
    _hex = payload[:4].hex(' ') if len(payload) >= 4 else payload.hex()
    print(f"[SerialSend] {port}@{baud} fmt={fmt} val={value} → {len(payload)}B [{_hex}]")

register_evaluator("SerialSend", _eval_serial_send)
