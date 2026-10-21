"""
Evaluators: SigGen 节点 (InitSigGenDevice / StartSigGenRecord / StopSigGenRecord /
KillSigGenDevice / GetSigGenData)。

后端路由 (VirtualDevice 门面按 cfg.device=VIRTUAL 选择 VirtualSigGenBackend):
  - ctx.dry_run=True  → 虚拟后端干跑模式 (确定性合成; 不落盘 — MCP 干跑验证路径)
  - ctx.dry_run=False → 虚拟后端真实模式 (合成 + 落盘 npz/csv)

副作用 (写文件) 只发生在真实模式; 干跑模式通过 ctx.emit_log() 输出"本应执行"的动作,
参数一致。会话绑定: device_name 为空时 → 若画布运行时仅注册了一个会话则自动绑定
(resolve_session)。
"""

from __future__ import annotations

from typing import Any

from Application.Core.NodeGraph.evaluator_engine import (
    ExecutionContext, GraphEvaluator, register_evaluator,
)
from Application.Functions.VirtualDevice import SigGenConfig
from Application.Functions.VirtualDevice import get_data as _sg_get_data
from Application.Functions.VirtualDevice import init_session as _sg_init
from Application.Functions.VirtualDevice import kill_device as _sg_kill
from Application.Functions.VirtualDevice import start_record as _sg_start
from Application.Functions.VirtualDevice import stop_record as _sg_stop


# ── 辅助 ─────────────────────────────────────────────────────

_DRY_PREFIX = "dryrun#"


def _ref_name(inst, ctx=None) -> str:
    """Start/Stop/Kill/Get 的会话引用名（空 = 让注册表自动绑定唯一会话）。

    干跑 (ctx.dry_run) 命名空间: 有名字 → 加 dryrun# 前缀;
    空名字 → 优先在 dryrun# 前缀会话内自动绑定（避免与真实会话混淆）。
    注意: 仅当未设置 pool 作用域时该兑底生效（pool 优先, 交给 resolve_session(pool)）。
    """
    raw = str(inst.props.get("device_name", "")).strip()
    if ctx is None or not getattr(ctx, "dry_run", False):
        return raw
    if raw:
        return _DRY_PREFIX + raw
    if str(inst.props.get("pool", "")).strip():
        return ""
    try:
        from Application.Functions.VirtualDevice import list_sessions

        dry = [n for n in list_sessions() if n.startswith(_DRY_PREFIX)]
        if len(dry) == 1:
            return dry[0]
    except Exception:  # noqa: BLE001 — 设备层不可用时退回自动绑定语义
        pass
    return ""


def _ref_pool(inst, ctx=None):
    """引用节点的池作用域 (props.pool); 空 = None (旧语义: 全注册表)。

    干跑: 非 global 的显式池加 dryrun# 前缀（与 Create 评估器命名空间一致）。
    """
    raw = str(inst.props.get("pool", "")).strip()
    if not raw:
        return None
    if getattr(ctx, "dry_run", False) and raw != "global":
        return _DRY_PREFIX + raw
    return raw


def _init_name(node_id: int, inst, ctx) -> str:
    """Init 的会话键 — 未命名时回退 siggen#<node_id>（与画布/校验器一致）。

    干跑时整体加 dryrun# 前缀（会话隔离, 结束后由校验服务清理）。
    """
    name = str(inst.props.get("device_name", "")).strip() or f"siggen#{node_id}"
    if getattr(ctx, "dry_run", False):
        return _DRY_PREFIX + name
    return name


def _write_out(node_id: int, pin_name: str, value: Any,
               ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """写 data output pin（不做类型转换）。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            pid = inst.pin_ids.get(p.name)
            if pid is not None:
                ctx.set_pin(pid, value)


# ── Evaluators ───────────────────────────────────────────────

def _eval_init_siggen(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """InitSigGenDevice — 创建 + 配置虚拟正弦源, 注册会话。

    干跑模式同样创建虚拟会话（确定性合成）, 但后端不落盘 — 后续链路可验证。
    """
    inst = g._canvas.nodes[node_id]
    cfg = SigGenConfig.from_props(inst.props)
    name = _init_name(node_id, inst, ctx)
    session, detail = _sg_init(name, cfg, dry_run=ctx.dry_run)
    if session is None:
        ctx.emit_log(node_id, "InitSigGenDevice", "error", detail)
        print(f"[Node:InitSigGenDevice] {detail}")
        return
    # device pin: 供 AddToDevicePool 读取的会话键 (同一 exec 链触发内有效)
    _write_out(node_id, "device", name, ctx, g)
    ctx.emit_log(node_id, "InitSigGenDevice", "init", detail)


def _eval_start_siggen(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """StartSigGenRecord — 开始采集（重复调用无害）。"""
    inst = g._canvas.nodes[node_id]
    ok, detail = _sg_start(_ref_name(inst, ctx), elapsed_s=ctx.elapsed_time,
                           pool=_ref_pool(inst, ctx))
    ctx.emit_log(node_id, "StartSigGenRecord", "record_start" if ok else "error", detail)


def _eval_stop_siggen(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """StopSigGenRecord — 停止采集并保存（session = 全量, buffer = 当前窗口）。"""
    inst = g._canvas.nodes[node_id]
    scope = str(inst.props.get("save_scope", "session"))
    ok, detail = _sg_stop(_ref_name(inst, ctx), save_scope=scope,
                          elapsed_s=ctx.elapsed_time, pool=_ref_pool(inst, ctx))
    ctx.emit_log(node_id, "StopSigGenRecord", "record_stop" if ok else "error", detail)


def _eval_kill_siggen(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """KillSigGenDevice — 停止 + 释放设备（不保存）。"""
    inst = g._canvas.nodes[node_id]
    ok, detail = _sg_kill(_ref_name(inst, ctx), pool=_ref_pool(inst, ctx))
    ctx.emit_log(node_id, "KillSigGenDevice", "device_kill" if ok else "error", detail)


def _eval_get_siggen(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """GetSigGenData — 非销毁读取窗口缓冲副本（纯数据节点，懒求值）。

    输出: Data (channels × capacity 的 float32 副本), Channels, Samples(有效), Fs。
    """
    inst = g._canvas.nodes[node_id]
    name = _ref_name(inst, ctx)
    result, why = _sg_get_data(name, elapsed_s=ctx.elapsed_time,
                               pool=_ref_pool(inst, ctx))
    if result is None:
        ctx.emit_log(node_id, "GetSigGenData", "error", why)
        return
    _write_out(node_id, "Data", result["data"], ctx, g)
    _write_out(node_id, "Channels", result["channels"], ctx, g)
    _write_out(node_id, "Samples", result["samples"], ctx, g)
    _write_out(node_id, "Fs", result["fs"], ctx, g)
    ctx.emit_log(
        node_id, "GetSigGenData", "get_data",
        f"'{name or 'auto'}' shape=({result['channels']},{result['capacity']}) "
        f"valid={result['samples']} fs={result['fs']} stub={result['stub']} "
        f"state={result['state']}",
    )


register_evaluator("InitSigGenDevice", _eval_init_siggen)
register_evaluator("StartSigGenRecord", _eval_start_siggen)
register_evaluator("StopSigGenRecord", _eval_stop_siggen)
register_evaluator("KillSigGenDevice", _eval_kill_siggen)
register_evaluator("GetSigGenData", _eval_get_siggen)
