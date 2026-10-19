"""Evaluators: entity_list 节点 — 树遍历 / 打包 / 合并 / 批量显隐与销毁。

设计:
  - entity_list 是**纯数据**（EntityRef 列表），不能存编辑器场景 id —
    PIE/成品里实体由 EntitySpawn 生成，id 会重新分配。
  - `EntityListSetVisible` 统一走 `SceneManager.SetEntitiesRenderVisible`
    （单批命令，同帧生效）；`EntityListDestroy` 逐实体删除（子树语义）。
"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input, _write_data_output
from .helpers import (
    collect_descendants,
    normalize_entity_list,
    read_entity_list,
    resolve_entity_id,
)


def _entity_refs(eids: list[int]) -> list:
    from .lifecycle import EntityRef

    return [EntityRef(eid=int(e)) for e in eids]


def _write_list(node_id: int, value, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    _write_data_output(node_id, "Entities", _entity_refs(value), ctx, g)
    _write_data_output(node_id, "Count", len(value), ctx, g)


# ── EntityGetTree ──────────────────────────────────────────────

def _eval_entity_get_tree(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid = resolve_entity_id(node_id, "Entity", ctx, g)
    eids: list[int] = []
    if eid is not None and eid >= 0 and ctx.scene is not None:
        eids = collect_descendants(ctx.scene, eid)
        try:
            eids = [e for e in eids if ctx.scene.EntityExists(e)]
        except Exception:  # noqa: BLE001 — 无 EntityExists 时保留原列表
            pass
    _write_list(node_id, eids, ctx, g)


# ── EntityPack ─────────────────────────────────────────────────

def _eval_entity_pack(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eids: list[int] = []
    for i in range(1, 5):
        eid = resolve_entity_id(node_id, f"Entity{i}", ctx, g)
        if eid is not None and eid >= 0 and eid not in eids:
            eids.append(eid)
    _write_list(node_id, eids, ctx, g)


# ── EntityListMerge ────────────────────────────────────────────

def _eval_entity_list_merge(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    merged: list[int] = []
    for pin in ("A", "B"):
        for eid in read_entity_list(node_id, pin, ctx, g):
            if eid not in merged:
                merged.append(eid)
    _write_list(node_id, merged, ctx, g)


# ── EntityListSetVisible ───────────────────────────────────────

def _eval_entity_list_set_visible(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eids = read_entity_list(node_id, "Entities", ctx, g)
    visible = bool(int(_read_data_input(node_id, "Visible", ctx, g, 1)))

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntityListSetVisible", "set_list_visible",
                     f"eids={eids}, visible={visible}")
        return

    if not eids or ctx.scene is None:
        return
    try:
        live = [e for e in eids if ctx.scene.EntityExists(e)]
    except Exception:  # noqa: BLE001
        live = eids
    if not live:
        return
    try:
        ctx.scene.SetEntitiesRenderVisible(live, visible=visible)  # 单批原子
    except AttributeError:
        for eid in live:
            ctx.scene.SetEntityRenderVisible(eid, visible=visible)


# ── EntityListDestroy ──────────────────────────────────────────

def _eval_entity_list_destroy(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eids = read_entity_list(node_id, "Entities", ctx, g)

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntityListDestroy", "destroy_list", f"eids={eids}")
        return

    if not eids or ctx.scene is None:
        return
    # 先删根、后删子：DeleteEntity 是子树语义，重复删除由 EntityExists 兜底
    for eid in eids:
        try:
            if ctx.scene.EntityExists(eid):
                ctx.scene.DeleteEntity(eid)
        except Exception:  # noqa: BLE001 — 单个实体失败不阻断其余
            continue


register_evaluator("EntityGetTree", _eval_entity_get_tree)
register_evaluator("EntityPack", _eval_entity_pack)
register_evaluator("EntityListMerge", _eval_entity_list_merge)
register_evaluator("EntityListSetVisible", _eval_entity_list_set_visible)
register_evaluator("EntityListDestroy", _eval_entity_list_destroy)
