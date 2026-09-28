"""
Evaluators: Gtec 节点 (InitGtecDevice / StartGtecRecord / StopGtecRecord /
KillGtecDevice / GetGtecData)。

后端路由:
  - ctx.dry_run=True  → EEGDevice 空跑后端 (确定性合成数据; MCP 干跑验证路径)
  - ctx.dry_run=False → 真实 pygds 后端 (不可用时记录 error, 不抛异常)

副作用只发生在真实模式; 干跑模式通过 ctx.emit_log() 输出"本应执行"的动作, 参数一致。
会话绑定: device_name 为空时 → 若画布运行时仅注册了一个会话则自动绑定 (resolve_session)。
"""

from __future__ import annotations

from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from Application.Functions.EEGDevice import (
    GtecConfig,
)
from Application.Functions.EEGDevice import get_data as _gtec_get_data
from Application.Functions.EEGDevice import init_session as _gtec_init
from Application.Functions.EEGDevice import kill_device as _gtec_kill
from Application.Functions.EEGDevice import start_record as _gtec_start
from Application.Functions.EEGDevice import stop_record as _gtec_stop


# ── 辅助 ─────────────────────────────────────────────────────

def _ref_name(inst) -> str:
    """Start/Stop/Kill/Get 的会话引用名（空 = 让注册表自动绑定唯一会话）。"""
    return str(inst.props.get("device_name", "")).strip()


def _init_name(node_id: int, inst) -> str:
    """Init 的会话键 — 未命名时回退 gtec#<node_id>（与画布/校验器一致）。"""
    return _ref_name(inst) or f"gtec#{node_id}"


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

def _eval_init_gtec(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """InitGtecDevice — 打开 + 配置设备, 注册会话。

    干跑模式: 创建空跑会话（合成数据），保证后续 Start/Get/Stop 链路可验证。
    """
    inst = g._canvas.nodes[node_id]
    cfg = GtecConfig.from_props(inst.props)
    name = _init_name(node_id, inst)
    session, detail = _gtec_init(name, cfg, dry_run=ctx.dry_run)
    if session is None:
        ctx.emit_log(node_id, "InitGtecDevice", "error", detail)
        print(f"[Node:InitGtecDevice] {detail}")
        return
    ctx.emit_log(node_id, "InitGtecDevice", "init", detail)


def _eval_start_gtec(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """StartGtecRecord — 开始采集（重复调用无害）。"""
    inst = g._canvas.nodes[node_id]
    ok, detail = _gtec_start(_ref_name(inst), elapsed_s=ctx.elapsed_time)
    ctx.emit_log(node_id, "StartGtecRecord", "record_start" if ok else "error", detail)


def _eval_stop_gtec(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """StopGtecRecord — 停止采集并保存（session = 全量, buffer = 当前窗口）。"""
    inst = g._canvas.nodes[node_id]
    scope = str(inst.props.get("save_scope", "session"))
    ok, detail = _gtec_stop(_ref_name(inst), save_scope=scope, elapsed_s=ctx.elapsed_time)
    ctx.emit_log(node_id, "StopGtecRecord", "record_stop" if ok else "error", detail)


def _eval_kill_gtec(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """KillGtecDevice — 停止 + 释放设备（不保存）。"""
    inst = g._canvas.nodes[node_id]
    ok, detail = _gtec_kill(_ref_name(inst))
    ctx.emit_log(node_id, "KillGtecDevice", "device_kill" if ok else "error", detail)


def _eval_get_gtec(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """GetGtecData — 非销毁读取窗口缓冲副本（纯数据节点，懒求值）。

    输出: Data (channels × capacity 的 float32 副本), Channels, Samples(有效), Fs。
    """
    inst = g._canvas.nodes[node_id]
    name = _ref_name(inst)
    result, why = _gtec_get_data(name, elapsed_s=ctx.elapsed_time)
    if result is None:
        ctx.emit_log(node_id, "GetGtecData", "error", why)
        return
    _write_out(node_id, "Data", result["data"], ctx, g)
    _write_out(node_id, "Channels", result["channels"], ctx, g)
    _write_out(node_id, "Samples", result["samples"], ctx, g)
    _write_out(node_id, "Fs", result["fs"], ctx, g)
    ctx.emit_log(
        node_id, "GetGtecData", "get_data",
        f"'{name or 'auto'}' shape=({result['channels']},{result['capacity']}) "
        f"valid={result['samples']} fs={result['fs']} stub={result['stub']} "
        f"state={result['state']}",
    )


register_evaluator("InitGtecDevice", _eval_init_gtec)
register_evaluator("StartGtecRecord", _eval_start_gtec)
register_evaluator("StopGtecRecord", _eval_stop_gtec)
register_evaluator("KillGtecDevice", _eval_kill_gtec)
register_evaluator("GetGtecData", _eval_get_gtec)
