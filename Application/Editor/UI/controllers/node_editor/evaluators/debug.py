"""
Evaluators: Debug 节点 (Print, PrintString)。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_print(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Print — 读取 Value input pin，打印到控制台。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    val_pin = next((p for p in nd.pins if p.name == "Value"), None)
    if val_pin is None:
        return
    inst_pin_id = inst.pin_ids.get(val_pin.name)
    if inst_pin_id is None:
        return
    value = g._read_input(inst_pin_id, ctx)
    print(f"[Node:Print] {value}")

register_evaluator("Print", _eval_print)


def _eval_print_string(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """PrintString — 打印节点内自定义文本框的内容。"""
    inst = g._canvas.nodes.get(node_id)
    if inst is None:
        return
    message = inst.props.get("message", "")
    print(f"[PrintString] {message}")

register_evaluator("PrintString", _eval_print_string)
