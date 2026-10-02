"""
Evaluators: Epoch 节点 (EpochAppend / EpochCount / EpochClear / EpochSave / EpochLoad)。

门面: Application.Functions.BCIAlgorithm（epoch 数据集注册表; (ok, detail) 契约）。
干跑: "dryrun#" 命名空间（与设备层一致; 校验服务跑完清理）。

绑定规则（与设备族同款）:
  - Append/Load 键 = props.epochs_name 或 epochs#<nid> 回退;
  - 引用节点空名 + 画布唯一源（Append/Load）→ 自动绑定; 否则报错;
  - EpochAppend 读 Data/Samples/Fs/Label 四个输入 pin（Samples/Fs 可选; Data/Label 必接）。
"""

from __future__ import annotations

from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..graph_constraints import EPOCH_APPEND, EPOCH_LOAD, epoch_key

_DRY_PREFIX = "dryrun#"


def _key(node_id: int, inst, ctx) -> str:
    """Append/Load 的数据集键 — epochs_name 或 epochs#<node_id> 回退。"""
    key = epoch_key(node_id, inst.props)
    return _DRY_PREFIX + key if getattr(ctx, "dry_run", False) else key


def _ref(node_id: int, inst, ctx, g: GraphEvaluator) -> tuple[str, str]:
    """引用节点的键 — 显式名 / 空名 + 画布唯一源自动绑定。Returns: (key, err)。"""
    raw = str(inst.props.get("epochs_name", "")).strip()
    if raw:
        key = raw
    else:
        sources = [epoch_key(nid, other.props)
                   for nid, other in g._canvas.nodes.items()
                   if other.node_type in (EPOCH_APPEND, EPOCH_LOAD)]
        if len(sources) == 1:
            key = sources[0]
        else:
            return "", (f"ambiguous/unbound dataset reference — set epochs_name "
                        f"(canvas sources: {', '.join(sorted(sources)) or 'none'})")
    return (_DRY_PREFIX + key if getattr(ctx, "dry_run", False) else key), ""


def _read_pin(node_id: int, name: str, ctx: ExecutionContext,
              g: GraphEvaluator) -> Any:
    inst = g._canvas.nodes[node_id]
    pid = inst.pin_ids.get(name)
    if pid is None:
        return None
    return g._read_input(pid, ctx)


def _write_out(node_id: int, pin_name: str, value: Any,
               ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    pid = inst.pin_ids.get(pin_name)
    if pid is not None:
        ctx.set_pin(pid, value)


# ── Evaluators ───────────────────────────────────────────────

def _eval_append(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """EpochAppend — 读 Data/Samples/Fs/Label 追加一条 epoch（dim0）。"""
    from Application.Functions.BCIAlgorithm import append_epoch

    inst = g._canvas.nodes[node_id]
    key = _key(node_id, inst, ctx)
    data = _read_pin(node_id, "Data", ctx, g)
    if data is None:
        ctx.emit_log(node_id, "EpochAppend", "error",
                     "Data pin is empty/not connected — link Get*Data.Data")
        return
    label = _read_pin(node_id, "Label", ctx, g)
    if label is None:
        ctx.emit_log(node_id, "EpochAppend", "error",
                     "Label pin is empty/not connected — link a numeric label")
        return
    samples = _read_pin(node_id, "Samples", ctx, g)
    if samples is not None:
        try:
            if int(samples) <= 0:
                ctx.emit_log(node_id, "EpochAppend", "epoch_skip",
                             "no valid samples yet (Samples=0) — epoch skipped")
                return
        except (TypeError, ValueError):
            pass
    ok, detail = append_epoch(key, data, label,
                              samples=samples,
                              fs=_read_pin(node_id, "Fs", ctx, g))
    ctx.emit_log(node_id, "EpochAppend", "epoch_append" if ok else "error", detail)


def _eval_count(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """EpochCount — 输出 Count / Classes / Channels / Fs（纯数据节点）。"""
    from Application.Functions.BCIAlgorithm import epoch_stats

    inst = g._canvas.nodes[node_id]
    key, err = _ref(node_id, inst, ctx, g)
    if err:
        ctx.emit_log(node_id, "EpochCount", "error", err)
        return
    stats, why = epoch_stats(key)
    if stats is None:
        ctx.emit_log(node_id, "EpochCount", "error", why)
        return
    _write_out(node_id, "Count", stats["count"], ctx, g)
    _write_out(node_id, "Classes", stats["classes"], ctx, g)
    _write_out(node_id, "Channels", stats["channels"], ctx, g)
    _write_out(node_id, "Fs", float(stats["fs"]), ctx, g)


def _eval_clear(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """EpochClear — 清空数据集（幂等）。"""
    from Application.Functions.BCIAlgorithm import clear_epochs

    inst = g._canvas.nodes[node_id]
    key, err = _ref(node_id, inst, ctx, g)
    if err:
        ctx.emit_log(node_id, "EpochClear", "error", err)
        return
    ok, detail = clear_epochs(key)
    ctx.emit_log(node_id, "EpochClear", "epoch_clear" if ok else "error", detail)


def _eval_save(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """EpochSave — 落盘 npz（干跑只计算目标路径）。"""
    from Application.Functions.BCIAlgorithm import save_epochs

    inst = g._canvas.nodes[node_id]
    key, err = _ref(node_id, inst, ctx, g)
    if err:
        ctx.emit_log(node_id, "EpochSave", "error", err)
        return
    save_dir = str(inst.props.get("save_dir", "")).strip() or "."
    ok, detail = save_epochs(key, save_dir, dry_run=ctx.dry_run)
    ctx.emit_log(node_id, "EpochSave", "epoch_save" if ok else "error", detail)


def _eval_load(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """EpochLoad — 从 npz 载入（读文件无副作用且确定性, 干跑同样执行）。"""
    from Application.Functions.BCIAlgorithm import load_epochs

    inst = g._canvas.nodes[node_id]
    key = _key(node_id, inst, ctx)
    file_path = str(inst.props.get("file_path", "")).strip()
    mode = str(inst.props.get("mode", "replace"))
    ok, detail = load_epochs(key, file_path, mode)
    ctx.emit_log(node_id, "EpochLoad", "epoch_load" if ok else "error", detail)


register_evaluator("EpochAppend", _eval_append)
register_evaluator("EpochCount", _eval_count)
register_evaluator("EpochClear", _eval_clear)
register_evaluator("EpochSave", _eval_save)
register_evaluator("EpochLoad", _eval_load)
