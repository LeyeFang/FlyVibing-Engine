"""Evaluators: Entity — 共享辅助函数。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator
from ..inputs import read_pin


def resolve_entity_id(node_id: int, pin_name: str,
                      ctx: ExecutionContext, g: GraphEvaluator) -> int | None:
    """从 data input pin 解析实体 ID — 支持 int / float / EntityRef 三种类型。

    走统一的类型感知读取层；entity_ref 引脚原样返回，不会被 float() 强转。
    """
    from .lifecycle import EntityRef  # noqa: F811
    val = read_pin(node_id, pin_name, ctx, g, None)
    if val is None:
        return None
    if isinstance(val, EntityRef):
        return val.eid
    if isinstance(val, (int, float)):
        return int(val)
    return None


def normalize_entity_list(value) -> list[int]:
    """把 entity_list / EntityRef / int / 序列 统一成去重、保序的 eid 列表。"""
    from .lifecycle import EntityRef  # noqa: F811

    if value is None:
        return []
    if isinstance(value, EntityRef):
        return [int(value.eid)] if int(value.eid) >= 0 else []
    if isinstance(value, (int, float)):
        return [int(value)] if int(value) >= 0 else []
    if isinstance(value, (list, tuple, set)):
        out: list[int] = []
        for item in value:
            for eid in normalize_entity_list(item):
                if eid not in out:
                    out.append(eid)
        return out
    return []


def read_entity_list(node_id: int, pin_name: str,
                     ctx: ExecutionContext, g: GraphEvaluator) -> list[int]:
    """读取 entity_list 输入（类型感知读取；不做 float() 强转）。"""
    return normalize_entity_list(read_pin(node_id, pin_name, ctx, g, None))


def collect_descendants(scene, entity_id: int) -> list[int]:
    """先序遍历实体及其全部子孙（eid 列表，含自身）。"""
    out: list[int] = [int(entity_id)]
    try:
        children = scene.GetEntityChildren(int(entity_id))
    except Exception:  # noqa: BLE001 — 无层级 API 时退化为单实体
        return out
    for child in children or []:
        for eid in collect_descendants(scene, int(child)):
            if eid not in out:
                out.append(eid)
    return out
