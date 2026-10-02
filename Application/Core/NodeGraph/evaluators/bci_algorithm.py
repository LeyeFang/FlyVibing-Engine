"""
Evaluators: BCI 算法节点 (InitFBCSP / TrainFBCSP / TestFBCSP / TestCCA)。

门面: Application.Functions.BCIAlgorithm（spec/模型注册表 + FBCSP/CCA + SyncJob）。
干跑: "dryrun#" 命名空间（模型/数据集）; 训练走同步路径（确定性）。

训练语义（同步等待）:
  - TrainFBCSP 首次被走到: 快照数据集 →（真实: SyncJob 线程; 干跑: 同步执行）;
    训练期间节点 _blocked（下游暂停, 每帧被走到时上报进度）;
  - 完成: 注册模型 → 解除 _blocked →【同一次遍历】继续下行（恰好一次）;
  - 之后保持 blocked（one-shot, 同 TimeTrigger; 重训=换图/重跑）;
  - 失败: 记录 error 且不再下行（不重试）;
  - 硬约束: 必须挂在可重复触发的链上（OnGameStart-only 链会永久卡住）。

绑定规则（与设备族同款）:
  - 键 = props.model_name 或 model#<nid> 回退; 干跑加 dryrun# 前缀;
  - Train(train) 的 spec 引用 / Test 的模型引用 / Train 的 dataset 引用:
    空名 + 画布唯一源 → 自动绑定; 否则报错。
"""

from __future__ import annotations

from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..graph_constraints import ALGO_INIT, ALGO_TRAIN, epoch_source_keys, model_key

_DRY_PREFIX = "dryrun#"


# ── 键解析辅助 ──────────────────────────────────────────────

def _dry(key: str, ctx) -> str:
    return _DRY_PREFIX + key if getattr(ctx, "dry_run", False) else key


def _own_key(node_id: int, inst, ctx) -> str:
    return _dry(model_key(node_id, inst.props), ctx)


def _ref_key(node_id: int, inst, ctx, g: GraphEvaluator,
             source_types) -> tuple[str, str]:
    """模型引用键 — 显式名 / 空名 + 画布唯一源自动绑定。Returns: (key, err)。"""
    raw = str(inst.props.get("model_name", "")).strip()
    if raw:
        key = raw
    else:
        sources = [model_key(nid, other.props)
                   for nid, other in g._canvas.nodes.items()
                   if other.node_type in source_types]
        if len(sources) == 1:
            key = sources[0]
        else:
            return "", (f"ambiguous/unbound model reference — set model_name "
                        f"(canvas sources: {', '.join(sorted(sources)) or 'none'})")
    return _dry(key, ctx), ""


def _epoch_ref(node_id: int, inst, ctx, g: GraphEvaluator) -> tuple[str, str]:
    """数据集引用键 — 显式名 / 空名 + 画布唯一 epoch 源自动绑定。"""
    raw = str(inst.props.get("dataset_name", "")).strip()
    if raw:
        key = raw
    else:
        src_map = epoch_source_keys({nid: {"node_type": o.node_type,
                                           "props": o.props}
                                     for nid, o in g._canvas.nodes.items()})
        sources = sorted(src_map.keys())
        if len(sources) == 1:
            key = sources[0]
        else:
            return "", (f"ambiguous/unbound dataset reference — set dataset_name "
                        f"(canvas sources: {', '.join(sources) or 'none'})")
    return _dry(key, ctx), ""


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


def _trim(data, samples):
    """按 Samples（有效长度）裁剪窗口; 失败时原样返回。"""
    try:
        import numpy as np

        arr = np.asarray(data)
        if samples is not None and arr.ndim == 2:
            n = int(samples)
            if 0 < n <= arr.shape[1]:
                return arr[:, :n]
        return arr
    except Exception:  # noqa: BLE001
        return data


def _fail(node_id: int, node_type: str, ctx, g: GraphEvaluator, msg: str) -> None:
    """失败路径: 记录 error 且保持 blocked（不再下行, 不重试）。"""
    ctx.emit_log(node_id, node_type, "error", msg)
    g.set_state(node_id, "fired", True)
    g.set_state(node_id, "_blocked", True)


# ── InitFBCSP ───────────────────────────────────────────────

def _eval_init_fbcsp(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    from Application.Functions.BCIAlgorithm import parse_fbcsp_spec, register_spec

    inst = g._canvas.nodes[node_id]
    key = _own_key(node_id, inst, ctx)
    spec, note = parse_fbcsp_spec(inst.props)
    ok, detail = register_spec(key, "FBCSP", spec)
    extra = f" | {note}" if note else ""
    ctx.emit_log(node_id, "InitFBCSP", "fbcsp_init" if ok else "error", detail + extra)


# ── TrainFBCSP（同步等待训练）───────────────────────────────

def _eval_train_fbcsp(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    from Application.Functions.BCIAlgorithm import (
        SyncJob, get_entry, load_fbcsp_model, save_fbcsp_model, set_model,
        snapshot_epochs, train_fbcsp,
    )

    inst = g._canvas.nodes[node_id]

    # one-shot: 完成/失败后保持 blocked（不重复触发, 同 TimeTrigger 语义）
    if g.get_state(node_id, "fired", False):
        g.set_state(node_id, "_blocked", True)
        return

    mode = str(inst.props.get("mode", "train")).strip().lower()
    key = _own_key(node_id, inst, ctx)

    # ── load 模式: 离线模型文件入口（同步, 无阻塞）──
    if mode == "load":
        model_path = str(inst.props.get("model_path", "")).strip()
        model, detail = load_fbcsp_model(model_path)
        if model is None:
            _fail(node_id, "TrainFBCSP", ctx, g, f"load: {detail}")
            return
        ok, d2 = set_model(key, "FBCSP", model)
        ctx.emit_log(node_id, "TrainFBCSP", "fbcsp_load" if ok else "error",
                     f"{d2}; {detail}; train_acc={model.get('train_accuracy', 0.0):.2f}")
        g.set_state(node_id, "fired", True)
        g.set_state(node_id, "_blocked", False)     # 成功: 同一遍历继续下行
        return

    # ── train 模式 ──
    job = g.get_state(node_id, "job")
    if job is None:
        spec_key, err = _ref_key(node_id, inst, ctx, g, (ALGO_INIT,))
        if err:
            _fail(node_id, "TrainFBCSP", ctx, g, err)
            return
        entry, why = get_entry(spec_key)
        if entry is None or entry.get("kind") != "spec":
            _fail(node_id, "TrainFBCSP", ctx, g,
                  f"spec '{spec_key}' not registered — is InitFBCSP executed "
                  f"BEFORE TrainFBCSP on the same chain? ({why or entry})")
            return
        ds_key, err = _epoch_ref(node_id, inst, ctx, g)
        if err:
            _fail(node_id, "TrainFBCSP", ctx, g, err)
            return
        snap, why = snapshot_epochs(ds_key)
        if snap is None:
            _fail(node_id, "TrainFBCSP", ctx, g, f"dataset: {why}")
            return

        spec = dict(entry["spec"])
        save_path = str(inst.props.get("save_path", "")).strip()

        def _work(progress=None):
            model, detail = train_fbcsp(spec, snap["X"], snap["y"], snap["fs"],
                                        progress_cb=progress)
            if model is None:
                raise RuntimeError(detail)
            return model

        if ctx.dry_run:
            # 干跑: 同步训练（确定性; 无线程）
            try:
                model = _work()
            except Exception as e:  # noqa: BLE001 — 训练失败转 error 日志
                _fail(node_id, "TrainFBCSP", ctx, g, f"train: {e}")
                return
            ok, d2 = set_model(spec_key, "FBCSP", model)
            note = f" | dry-run: would save → {save_path}" if save_path else ""
            ctx.emit_log(node_id, "TrainFBCSP", "fbcsp_train" if ok else "error",
                         f"{d2}; epochs={snap['count']} "
                         f"train_acc={model['train_accuracy']:.2f}{note}")
            g.set_state(node_id, "fired", True)
            g.set_state(node_id, "_blocked", False)  # 干跑同步: 继续下行
            return

        job = SyncJob.run_async(_work, name=f"fbcsp-{node_id}")
        g.set_state(node_id, "job", job)
        g.set_state(node_id, "spec_key", spec_key)
        g.set_state(node_id, "last_pct", 0)
        ctx.emit_log(node_id, "TrainFBCSP", "train_start",
                     f"training '{spec_key}' on '{ds_key}' ({snap['count']} epochs): "
                     f"{spec['classifier']}, bands={spec['bands'] or 'CSP(全带)'}, "
                     f"n_components={spec['n_components']}")
        g.set_state(node_id, "_blocked", True)
        return

    # ── 轮询（同步等待: 训练完成 → 同一遍历继续下行）──
    snap = job.snapshot()
    if snap["status"] == "running":
        pct = int(snap["progress"] * 100)
        if pct - int(g.get_state(node_id, "last_pct", 0)) >= 20:
            g.set_state(node_id, "last_pct", pct)
            ctx.emit_log(node_id, "TrainFBCSP", "train_progress",
                         f"{pct}% ({snap['elapsed']:.1f}s)")
        g.set_state(node_id, "_blocked", True)
        return
    if snap["status"] == "error":
        _fail(node_id, "TrainFBCSP", ctx, g, f"train failed: {snap['error']}")
        return

    model = job.result
    spec_key = g.get_state(node_id, "spec_key", "")
    ok, d2 = set_model(spec_key, "FBCSP", model)
    note = ""
    save_path = str(inst.props.get("save_path", "")).strip()
    if save_path and model is not None:
        _ok, w_detail = save_fbcsp_model(model, save_path)
        note = f" | {w_detail}"
    ctx.emit_log(node_id, "TrainFBCSP", "fbcsp_train" if ok else "error",
                 f"{d2}; epochs={model.get('train_epochs')} "
                 f"train_acc={model.get('train_accuracy', 0.0):.2f} "
                 f"({snap['elapsed']:.1f}s){note}")
    g.set_state(node_id, "fired", True)
    g.set_state(node_id, "_blocked", False)      # 完成: 同一遍历继续下行


# ── TestFBCSP / TestCCA（纯数据节点）────────────────────────

def _eval_test_fbcsp(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    from Application.Functions.BCIAlgorithm import get_entry, predict_fbcsp

    inst = g._canvas.nodes[node_id]
    key, err = _ref_key(node_id, inst, ctx, g, (ALGO_TRAIN,))
    if err:
        ctx.emit_log(node_id, "TestFBCSP", "error", err)
        return
    entry, why = get_entry(key)
    if entry is None or entry.get("kind") != "model":
        ctx.emit_log(node_id, "TestFBCSP", "error",
                     f"model '{key}' not trained/loaded yet ({why or entry})")
        return
    data = _read_pin(node_id, "Data", ctx, g)
    if data is None:
        ctx.emit_log(node_id, "TestFBCSP", "error",
                     "Data pin is empty/not connected — link Get*Data.Data")
        return
    data = _trim(data, _read_pin(node_id, "Samples", ctx, g))
    label, conf, detail = predict_fbcsp(entry["model"], data)
    if label is None:
        ctx.emit_log(node_id, "TestFBCSP", "error", f"predict: {detail}")
        return
    _write_out(node_id, "Label", int(label), ctx, g)
    _write_out(node_id, "Confidence", float(conf), ctx, g)
    ctx.emit_log(node_id, "TestFBCSP", "fbcsp_test",
                 f"label={int(label)} conf={conf:.2f} (model '{key}')")


def _eval_test_cca(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    from Application.Functions.BCIAlgorithm import predict_cca

    inst = g._canvas.nodes[node_id]
    freqs = inst.props.get("freqs") or []
    if not isinstance(freqs, (list, tuple)):
        freqs = []
    try:
        harmonics = int(float(inst.props.get("n_harmonics", 3) or 3))
    except (TypeError, ValueError):
        harmonics = 3

    data = _read_pin(node_id, "Data", ctx, g)
    if data is None:
        ctx.emit_log(node_id, "TestCCA", "error",
                     "Data pin is empty/not connected — link Get*Data.Data")
        return
    fs = _read_pin(node_id, "Fs", ctx, g)
    if fs is None:
        ctx.emit_log(node_id, "TestCCA", "error",
                     "Fs pin is empty/not connected — link Get*Data.Fs")
        return
    data = _trim(data, _read_pin(node_id, "Samples", ctx, g))
    idx, score, freq, detail = predict_cca(data, fs, freqs, harmonics)
    if idx is None:
        ctx.emit_log(node_id, "TestCCA", "error", detail)
        return
    _write_out(node_id, "Label", int(idx), ctx, g)
    _write_out(node_id, "Score", float(score), ctx, g)
    _write_out(node_id, "Freq", float(freq), ctx, g)
    ctx.emit_log(node_id, "TestCCA", "cca_test",
                 f"label={idx} freq={freq:g}Hz score={score:.3f} "
                 f"({len(freqs)} refs, h={harmonics})")


register_evaluator("InitFBCSP", _eval_init_fbcsp)
register_evaluator("TrainFBCSP", _eval_train_fbcsp)
register_evaluator("TestFBCSP", _eval_test_fbcsp)
register_evaluator("TestCCA", _eval_test_cca)
