"""Evaluators: EntityGroupSetVisible 节点 — 一组实体原子显隐。

语义:
  - Entity1..Entity4 (entity_ref, optional): 至多 4 个目标; 未连线的引脚自动跳过;
  - Visible (bool): 默认 True (未连线时);
  - 全部目标经 `SceneManager.SetEntitiesRenderVisible` 以**单批命令**下发给渲染器 —
    渲染帧边界不会把这一组切成两半 (CommandQueue 原子批; 修复多部件 cue 分帧出现)。

典型用法 (MI-SSSEP cue):
  cue 分支 → [EntityGet(L_body)…] 或 EntitySpawn 直连 →
  EntityGroupSetVisible(Entity1=L_body, Entity2=L_head, Visible=true) → exec_out
"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input
from .helpers import resolve_entity_id

_MAX_ENTITY_INPUTS = 4


def _eval_entity_group_set_visible(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eids: list[int] = []
    for i in range(1, _MAX_ENTITY_INPUTS + 1):
        eid = resolve_entity_id(node_id, f"Entity{i}", ctx, g)
        if eid is not None and eid >= 0 and eid not in eids:
            eids.append(eid)
    visible_val = _read_data_input(node_id, "Visible", ctx, g, 1)
    visible = bool(int(visible_val))

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntityGroupSetVisible", "set_group_visible",
                     f"eids={eids}, visible={visible}")
        return

    if not eids or ctx.scene is None:
        return
    live = [e for e in eids if ctx.scene.EntityExists(e)]
    if live:
        ctx.scene.SetEntitiesRenderVisible(live, visible=visible)


register_evaluator("EntityGroupSetVisible", _eval_entity_group_set_visible)
