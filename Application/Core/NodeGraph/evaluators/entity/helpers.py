"""Evaluators: Entity — 共享辅助函数。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator


def resolve_entity_id(node_id: int, pin_name: str,
                      ctx: ExecutionContext, g: GraphEvaluator) -> int | None:
    """从 data input pin 解析实体 ID — 支持 int / float / EntityRef 三种类型。

    直接使用 g._read_input 绕过 _read_data_input 的 float() 强转，
    避免 EntityRef → float 的 TypeError。
    """
    from .lifecycle import EntityRef  # noqa: F811
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is None:
                    return None
                if isinstance(val, EntityRef):
                    return val.eid
                if isinstance(val, (int, float)):
                    return int(val)
                return None
    return None
