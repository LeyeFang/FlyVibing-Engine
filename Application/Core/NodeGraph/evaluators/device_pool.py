"""
Evaluators: Device Pool 节点 (CreateDevicePool / AddToDevicePool / KillDevicePool)。

门面: Application.Functions.VirtualDevice 池注册表 (create_pool / destroy_pool / add_to_pool)。
干跑: 池与会话共用 "dryrun#" 命名空间（结束后由校验服务一并清理）。

时序 (CRITICAL): AddToDevicePool 读取 'device' 输入 pin 的会话键（同帧由 Init 评估器写入），
必须排在同一条 exec 链的 Init 之后; 未连接 / 未初始化 → 记录 error, 不抛异常。
"""

from __future__ import annotations

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..graph_constraints import pool_key

_DRY_PREFIX = "dryrun#"


def _create_key(node_id: int, inst, ctx) -> str:
    """Create 的池键 — pool_name 或 pool#<node_id> 回退（与画布/校验器一致）。"""
    key = pool_key(node_id, inst.props)
    return _DRY_PREFIX + key if getattr(ctx, "dry_run", False) else key


def _kill_key(node_id: int, inst, ctx, g: GraphEvaluator) -> tuple[str, str]:
    """Kill 的池键 — 显式名 / 空名 + 画布唯一 Create 自动绑定。Returns: (key, err)。"""
    raw = str(inst.props.get("pool_name", "")).strip()
    if raw:
        key = raw
    else:
        creates = [pool_key(nid, other.props)
                   for nid, other in g._canvas.nodes.items()
                   if other.node_type == "CreateDevicePool"]
        if len(creates) == 1:
            key = creates[0]
        else:
            return "", (f"ambiguous/unbound pool kill — set pool_name "
                        f"(canvas creates: {', '.join(creates) or 'none'})")
    return (_DRY_PREFIX + key if getattr(ctx, "dry_run", False) else key), ""


def _eval_create_pool(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """CreateDevicePool — 注册一个设备池（幂等）。"""
    from Application.Functions.VirtualDevice import create_pool

    inst = g._canvas.nodes[node_id]
    ok, detail = create_pool(_create_key(node_id, inst, ctx))
    ctx.emit_log(node_id, "CreateDevicePool", "pool_create" if ok else "error", detail)


def _eval_add_to_pool(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """AddToDevicePool — 读取 device pin 的会话键并加入所选池。"""
    from Application.Functions.VirtualDevice import add_to_pool

    inst = g._canvas.nodes[node_id]
    pool = str(inst.props.get("pool_name", "")).strip()
    if not pool:
        ctx.emit_log(node_id, "AddToDevicePool", "error",
                     "pool_name is empty — select a created pool")
        return
    if getattr(ctx, "dry_run", False):
        pool = _DRY_PREFIX + pool
    pid = inst.pin_ids.get("device")
    key = g._read_input(pid, ctx) if pid is not None else None
    if not key:
        ctx.emit_log(node_id, "AddToDevicePool", "error",
                     "device pin not connected (or its Init node has not run in this "
                     "exec chain) — link Init*Device.device → AddToDevicePool.device, "
                     "right after the Init node")
        return
    ok, detail = add_to_pool(pool, str(key))
    ctx.emit_log(node_id, "AddToDevicePool", "pool_add" if ok else "error", detail)


def _eval_kill_pool(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """KillDevicePool — 注销池（成员回落 global; 设备生命周期由各自 Kill 节点管理）。"""
    from Application.Functions.VirtualDevice import destroy_pool

    inst = g._canvas.nodes[node_id]
    key, err = _kill_key(node_id, inst, ctx, g)
    if err:
        ctx.emit_log(node_id, "KillDevicePool", "error", err)
        return
    ok, detail = destroy_pool(key)
    ctx.emit_log(node_id, "KillDevicePool", "pool_kill" if ok else "error", detail)


register_evaluator("CreateDevicePool", _eval_create_pool)
register_evaluator("AddToDevicePool", _eval_add_to_pool)
register_evaluator("KillDevicePool", _eval_kill_pool)
