"""
Evaluators: IO 节点 (SerialSend, ParallelSend, PathVar, TextFileWrite)。

SerialSend   — 通过串口发送信号，支持 Manual / Pin 双模式，String / Bytes 双格式。
ParallelSend — 通过并口发送 uint8 值 (1–255)，Manual / Pin 双模式，5ms 后自动复位。
PathVar      — 输出文件/目录路径字符串。
TextFileWrite — 将内容写入文本文件，支持 Manual / Pin 双模式，w/a 模式，分隔符。
实际 I/O 由 Functions/SerialParallelDevice 线程池执行，本求值器只做入队。
"""

import os
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
            port = str(inst.props.get("port", "COM1"))
        port = str(port)

        baud_raw = _read_input_raw(node_id, "BaudRate", ctx, g, 0)
        if baud_raw is None or baud_raw == 0:
            baud = int(inst.props.get("baud_rate", 9600))
        else:
            baud = int(baud_raw)

        value = _read_input_raw(node_id, "Value", ctx, g, 0)
        if value is None:
            value = 0.0

    # ── 编码 + 入队 ──
    if ctx.dry_run:
        ctx.emit_log(node_id, "SerialSend", "send",
                     f"port={port}, baud={baud}, fmt={fmt}, val={value}")
        return

    from Application.Functions.SerialParallelDevice import send as spd_send
    from Application.Functions.SerialParallelDevice.protocol import encode

    payload = encode(value, fmt)
    spd_send(port, baud, payload)

    # debug: 首 4 字节 hex
    _hex = payload[:4].hex(' ') if len(payload) >= 4 else payload.hex()
    print(f"[SerialSend] {port}@{baud} fmt={fmt} val={value} → {len(payload)}B [{_hex}]")

register_evaluator("SerialSend", _eval_serial_send)


# ── ParallelSend ───────────────────────────────────────────

def _eval_parallel_send(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """ParallelSend — 通过并口发送一个 uint8 值 (1–255)。

    Manual 模式: Address / Value 全部从节点属性读取。
    Pin 模式:    Address / Value 全部从上游连线读取。

    实际写入由 Functions/SerialParallelDevice 的独立 I/O 线程执行，
    写入后 5ms 自动复位为零。本函数仅做参数读取 + 入队 — 不阻塞逻辑线程。
    """
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

    # ── 钳位到 1–255 (0 留给自动复位) ──
    try:
        ival = max(1, min(255, int(float(value))))
    except (TypeError, ValueError):
        ival = 1

    # ── 编码 + 入队 ──
    if ctx.dry_run:
        ctx.emit_log(node_id, "ParallelSend", "write",
                     f"addr=0x{address:04X}, val=0x{ival:02X} ({ival})")
        return

    from Application.Functions.SerialParallelDevice import write_parallel

    write_parallel(address, ival, "byte")
    print(f"[ParallelSend] 0x{address:04X} ← 0x{ival:02X} ({ival})")

register_evaluator("ParallelSend", _eval_parallel_send)


# ── 辅助：写入 output pin（不做类型转换）──────────────────

def _write_output_raw(node_id: int, pin_name: str, value: Any,
                      ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """将任意值写入指定 data output pin（不做 float 强转）。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)


# ── PathVar ────────────────────────────────────────────────

def _eval_path_var(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """PathVar — 输出一个文件/目录路径字符串（纯数据节点，懒求值）。"""
    inst = g._canvas.nodes[node_id]
    path = str(inst.props.get("path", ""))
    _write_output_raw(node_id, "Path", path, ctx, g)

register_evaluator("PathVar", _eval_path_var)


# ── TextFileWrite ──────────────────────────────────────────

_DELIMITER_MAP = {
    "none":   "",
    "space":  " ",
    "newline": "\n",
    "tab":    "\t",
    "comma":  ",",
}


def _eval_text_file_write(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """TextFileWrite — 将内容写入文本文件。

    Manual 模式: FilePath / FileName / Value 全部从控件读取。
    Pin 模式:    FilePath / FileName / Value 全部从上游连线读取（props fallback）。

    WriteMode (w/a) 和 Delimiter 始终从 props 读取，不受 mode 影响。
    文件不存在时自动创建（无论 w 还是 a 模式）。
    FileName 自动补 .txt 后缀。
    """
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")
    write_mode = inst.props.get("write_mode", "w")
    delimiter_key = inst.props.get("delimiter", "none")
    delim = _DELIMITER_MAP.get(delimiter_key, "")

    # ── FilePath ──
    file_path = _read_input_raw(node_id, "FilePath", ctx, g, None)
    if file_path is None or (isinstance(file_path, str) and not file_path.strip()):
        file_path = str(inst.props.get("file_path", ""))
    file_path = str(file_path).strip()

    # ── FileName ──
    if mode == "manual":
        file_name = str(inst.props.get("file_name", "output.txt"))
    else:
        file_name = _read_input_raw(node_id, "FileName", ctx, g, "")
        if file_name is None or (isinstance(file_name, str) and not file_name.strip()):
            file_name = str(inst.props.get("file_name", "output.txt"))
    file_name = str(file_name).strip()

    # ── 自动补 .txt 后缀 ──
    if not file_name.endswith(".txt"):
        file_name += ".txt"

    # ── Value ──
    if mode == "manual":
        value = inst.props.get("value", "")
    else:
        value = _read_input_raw(node_id, "Value", ctx, g, "")
        if value is None:
            value = ""

    # ── 写入内容: Python print() 语义 → str(value) ──
    content = str(value)

    # ── 构造完整路径 ──
    if file_path:
        os.makedirs(file_path, exist_ok=True)
        full_path = os.path.join(file_path, file_name)
    else:
        # 无目录 → 当前工作目录
        full_path = file_name

    # ── 写入 ──
    if ctx.dry_run:
        ctx.emit_log(node_id, "TextFileWrite", "write",
                     f"mode={write_mode}, path={full_path}, "
                     f"content={content[:80]}{'...' if len(content)>80 else ''}, "
                     f"delim={delimiter_key}")
        return

    try:
        with open(full_path, write_mode, encoding="utf-8") as f:
            f.write(content + delim)
        print(f"[TextFileWrite] {write_mode} {len(content)} chars → {full_path}"
              f"  delim={delimiter_key}")
    except OSError as e:
        print(f"[TextFileWrite] ERROR: {e}")

register_evaluator("TextFileWrite", _eval_text_file_write)
