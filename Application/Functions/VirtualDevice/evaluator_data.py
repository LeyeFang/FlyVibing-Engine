"""Evaluator: SaveDeviceData — 不停采保存设备录制（session / buffer）。

语义:
  - 录制中（recording）保存 session = 本次开始以来的累计数据；保存不改变会话状态；
  - buffer = 当前窗口快照；
  - pump=True（默认）先按当前仿真时间补齐后端数据，保证文件样本数与同刻
    GetData / sample_count 对齐；
  - 干跑（ctx.dry_run / stub backend）只计算路径，written=0，不落盘。

输出:
  Path / MetaPath / Samples / Duration / Written / Ok
"""

from __future__ import annotations

from typing import Any

from Application.Core.NodeGraph.evaluator_engine import (
    ExecutionContext, GraphEvaluator, register_evaluator,
)
from Application.Functions.VirtualDevice import save_record as _save_record
from Application.Functions.VirtualDevice.evaluator_siggen import (
    _ref_name, _ref_pool, _write_out,
)


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in ("", "0", "false", "no", "off")


def _eval_save_device(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    scope = str(inst.props.get("save_scope", "session") or "session").strip().lower()
    if scope not in ("session", "buffer"):
        scope = "session"
    tag = str(inst.props.get("tag", "") or "").strip()
    pump = _as_bool(inst.props.get("pump", True), True)
    name = _ref_name(inst, ctx)
    ok, detail, info = _save_record(
        name, save_scope=scope, elapsed_s=float(getattr(ctx, "elapsed_time", 0.0)),
        pool=_ref_pool(inst, ctx), tag=tag, pump=pump)

    paths = list(info.get("paths") or [])
    data_path = next((str(p) for p in paths if not str(p).lower().endswith(".json")), "")
    meta_path = str(info.get("meta_path") or "")
    samples = int(info.get("samples", 0) or 0)
    duration = float(info.get("duration_s", 0.0) or 0.0)
    written = 1 if bool(info.get("written", False)) else 0
    _write_out(node_id, "Path", data_path, ctx, g)
    _write_out(node_id, "MetaPath", meta_path, ctx, g)
    _write_out(node_id, "Samples", samples, ctx, g)
    _write_out(node_id, "Duration", duration, ctx, g)
    _write_out(node_id, "Written", written, ctx, g)
    _write_out(node_id, "Ok", 1 if ok else 0, ctx, g)

    ctx.emit_log(node_id, "SaveDeviceData", "data_save" if ok else "error",
                 detail or "save failed")


register_evaluator("SaveDeviceData", _eval_save_device)
