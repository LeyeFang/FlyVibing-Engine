"""
Test: BCI 算法（FBCSP / CCA）— 超参解析 / 训练推理 / 模型落盘 / 节点图干跑 / 校验
═══════════════════════════════════════════════════════════════

测试范围:
  - parse_fbcsp_spec: 钳位 / 非法频带丢弃 / 封顶 / 空频带 = 普通 CSP 说明
  - FBCSP 训练+推理: 可分数据 LDA / SVM / 普通 CSP 准确率; 失败路径（类数/fs）
  - 模型落盘回读: save → load → 同数据同预测（标签/置信一致）
  - CCA: 合成 SSVEP 频率锁定; 频率组 <2 / 窗口过短 错误路径
  - 引用校验: bci_reference_errors + static_check_graph (bci_reference)
  - 节点图干跑: Init → (预置数据集) Train(干跑同步) → Test → 模型/数据集 dryrun# 清理

运行: python Test/Application/Functions/test_bci_algorithm.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import numpy as np

from Application.Functions.BCIAlgorithm import (
    append_epoch,
    list_datasets,
    list_entries,
    load_fbcsp_model,
    parse_fbcsp_spec,
    predict_cca,
    predict_fbcsp,
    reset_all,
    save_fbcsp_model,
    train_fbcsp,
)
from Application.Functions.VirtualDevice import close_all
from Application.Core.NodeGraph.graph_constraints import bci_reference_errors
from Application.Core.NodeGraph.validation.checks import static_check_graph
from Application.Core.NodeGraph.validation.dry_run import run_dry_run
from flyvibing_node_editor.graph_builder import GraphBuilder
from flyvibing_node_editor.node_graph_validator import validate_static

_PASS = 0
_FAIL = 0


def check(cond: bool, name: str) -> bool:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}")
    return cond


# ═══════════════════════════════════════════════════════════════
# 1. 超参解析
# ═══════════════════════════════════════════════════════════════

def test_spec_parse():
    print("── parse_fbcsp_spec ──")
    spec, note = parse_fbcsp_spec({})
    check(spec["n_components"] == 2 and spec["classifier"] == "LDA"
          and spec["bands"] == [], f"defaults → plain CSP ({spec})")
    check("普通 CSP" in note, f"empty-bands note ({note})")

    spec, note = parse_fbcsp_spec({
        "n_components": 99, "classifier": "RF",
        "bands": [[4, 8], [0, 5], [8, 13], [30, 4], [1, 500]],
    })
    check(spec["n_components"] == 8, "n_components clamped to 8")
    check(spec["classifier"] == "LDA" and "LDA" in note,
          f"invalid classifier → LDA ({note})")
    check(spec["bands"] == [[4.0, 8.0], [8.0, 13.0], [1.0, 500.0]],
          f"invalid bands dropped ({spec['bands']})")

    spec, note = parse_fbcsp_spec({"bands": [[4 + i, 5 + i] for i in range(20)]})
    check(len(spec["bands"]) == 16 and "封顶" in note,
          f"bands capped at 16 ({len(spec['bands'])})")


# ═══════════════════════════════════════════════════════════════
# 2. FBCSP 训练 / 推理
# ═══════════════════════════════════════════════════════════════

def _synth_class(amp, n, seed, ch=4, t_len=256, fs=256, f=11.0):
    """类 c: ch0 叠加 amp 幅度的 f Hz 正弦; 其余为噪声。"""
    rng = np.random.default_rng(seed)
    t = np.arange(t_len) / fs
    out = []
    for _ in range(n):
        x = rng.standard_normal((ch, t_len)) * 5.0
        x[0] += amp * np.sin(2.0 * np.pi * f * t)
        out.append(x.astype(np.float32))
    return out


def _accuracy(model, x_list, y_list) -> float:
    hit = 0
    for x, y in zip(x_list, y_list):
        label, _conf, _d = predict_fbcsp(model, x)
        hit += int(label == y)
    return hit / max(1, len(x_list))


def test_fbcsp_train_predict():
    print("── FBCSP train / predict ──")
    x_tr = _synth_class(30, 20, 1) + _synth_class(3, 20, 2)
    y_tr = [1.0] * 20 + [2.0] * 20
    x_te = _synth_class(30, 10, 11) + _synth_class(3, 10, 12)
    y_te = [1.0] * 10 + [2.0] * 10

    model, detail = train_fbcsp(
        {"n_components": 2, "classifier": "LDA", "bands": [[8, 14]]},
        x_tr, y_tr, 256)
    check(model is not None, f"LDA train ok ({detail[:80]}...)")
    if model:
        acc = _accuracy(model, x_te, y_te)
        check(acc >= 0.9, f"LDA held-out acc {acc:.2f} >= 0.9")

    model_csp, detail = train_fbcsp(
        {"n_components": 2, "classifier": "LDA", "bands": []}, x_tr, y_tr, 256)
    check(model_csp is not None and _accuracy(model_csp, x_te, y_te) >= 0.85,
          "plain CSP (bands=[]) acc >= 0.85")

    model_svm, detail = train_fbcsp(
        {"n_components": 2, "classifier": "SVM", "bands": [[8, 14]]},
        x_tr, y_tr, 256)
    check(model_svm is not None and _accuracy(model_svm, x_te, y_te) >= 0.85,
          "SVM acc >= 0.85")

    bad, why = train_fbcsp({"n_components": 2, "classifier": "LDA", "bands": []},
                           x_tr[:10], [1.0] * 9 + [2.0] * 1 + [3.0] * 0, 256)
    # 9×1 + 1×2 = 2 类 — 换真实 3 类集:
    bad, why = train_fbcsp({"n_components": 2, "classifier": "LDA", "bands": []},
                           x_tr[:9], [1.0, 2.0, 3.0] + [1.0] * 6, 256)
    check(bad is None and "2 classes" in why, f"3 classes → error ({why})")
    bad, why = train_fbcsp({"n_components": 2, "classifier": "LDA", "bands": []},
                           x_tr, y_tr, 0)
    check(bad is None and "fs" in why, f"fs=0 → error ({why})")


# ═══════════════════════════════════════════════════════════════
# 3. 模型落盘 / 回读
# ═══════════════════════════════════════════════════════════════

def test_model_roundtrip():
    print("── Model save / load roundtrip ──")
    tmp = tempfile.mkdtemp(prefix="mge_fbcsp_")
    try:
        x_tr = _synth_class(30, 12, 31) + _synth_class(3, 12, 32)
        y_tr = [1.0] * 12 + [2.0] * 12
        model, _ = train_fbcsp(
            {"n_components": 2, "classifier": "LDA", "bands": [[8, 14]]},
            x_tr, y_tr, 256)
        path = os.path.join(tmp, "model.npz")
        ok, detail = save_fbcsp_model(model, path)
        check(ok and os.path.isfile(path), f"save ok ({detail[:60]})")

        model2, detail = load_fbcsp_model(path)
        check(model2 is not None, f"load ok ({detail})")
        x = _synth_class(30, 1, 99)[0]
        l1, c1, _ = predict_fbcsp(model, x)
        l2, c2, _ = predict_fbcsp(model2, x)
        check(l1 == l2 and abs(c1 - c2) < 1e-9,
              f"identical prediction (label={l1}, conf={c1:.3f})")

        other = os.path.join(tmp, "other.npz")
        np.savez(other, algo=np.array("CCA"))
        bad, why = load_fbcsp_model(other)
        check(bad is None and "not an FBCSP" in why, "foreign file rejected")
        bad, why = load_fbcsp_model("")
        check(bad is None, "empty path rejected")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 4. CCA
# ═══════════════════════════════════════════════════════════════

def test_cca():
    print("── CCA (SSVEP, training-free) ──")
    fs, t_len = 256, 1024
    t = np.arange(t_len) / fs
    rng = np.random.default_rng(3)

    def ssvep(f, seed):
        local = np.random.default_rng(seed)
        x = local.standard_normal((4, t_len)) * 10.0
        x += 25.0 * np.sin(2.0 * np.pi * f * t)[None, :]
        return x

    idx, score, freq, why = predict_cca(ssvep(12.0, 1), fs, [10.0, 12.0, 15.0], 2)
    check(idx == 1 and freq == 12.0, f"12Hz → idx 1 ({idx}, {why})")
    check(score >= 0.6, f"strong lock score {score:.2f} >= 0.6")

    idx, score, freq, _ = predict_cca(ssvep(15.0, 2), fs, [10.0, 12.0, 15.0], 2)
    check(idx == 2 and freq == 15.0, f"15Hz → idx 2 ({idx})")

    bad, _s, _f, why = predict_cca(ssvep(12.0, 3), fs, [12.0], 2)
    check(bad is None and "at least 2" in why, f"freqs < 2 → error ({why})")
    bad, _s, _f, why = predict_cca(np.zeros((4, 8)), fs, [10.0, 12.0], 2)
    check(bad is None and "too short" in why, f"short window → error ({why})")
    # 注意: rng 仅用于保持与种子一致性 (未直接使用)
    _ = rng


# ═══════════════════════════════════════════════════════════════
# 5. 引用校验
# ═══════════════════════════════════════════════════════════════

def test_reference_validation():
    print("── BCI reference validation ──")
    errs = bci_reference_errors({
        "1": {"node_type": "TrainFBCSP",
              "props": {"model_name": "M", "dataset_name": "D"}},
    })
    check(any("InitFBCSP" in e for e in errs), f"train w/o Init → error ({errs[:1]})")
    check(any("EpochAppend" in e for e in errs), "train w/o dataset source → error")

    errs = bci_reference_errors({
        "1": {"node_type": "InitFBCSP", "props": {"model_name": "M"}},
        "2": {"node_type": "EpochAppend", "props": {"epochs_name": "D"}},
        "3": {"node_type": "TrainFBCSP",
              "props": {"model_name": "M", "dataset_name": "D", "mode": "train"}},
        "4": {"node_type": "TestFBCSP", "props": {"model_name": "M"}},
        "5": {"node_type": "TestCCA", "props": {"freqs": [10.0, 12.0]}},
    })
    check(errs == [], f"fully bound graph → clean ({errs})")

    errs = bci_reference_errors({
        "1": {"node_type": "TrainFBCSP",
              "props": {"mode": "load", "model_name": "L"}},
        "2": {"node_type": "TestCCA", "props": {"freqs": [12.0]}},
    })
    check(any("model_path" in e for e in errs), "load w/o path → error")
    check(any("at least 2" in e for e in errs), "cca 1 freq → error")

    # static_check_graph 集成
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    tr = g.fbscp_train("FBCSP", dataset="EPOCHS")
    g.link(GS, "exec", tr, "exec_in")
    entries = static_check_graph(g.build())
    codes = [e["code"] for e in entries]
    check(codes.count("bci_reference") >= 1, f"static code flagged ({codes})")


# ═══════════════════════════════════════════════════════════════
# 6. 节点图干跑（Train 干跑同步 + Test + 清理）
# ═══════════════════════════════════════════════════════════════

def _seed_dry_dataset():
    """预置 dryrun#EPOCHS（模拟捕获环节; 干跑图测试聚焦 Train/Test 节点）。"""
    for x in _synth_class(25, 8, 41):
        append_epoch("dryrun#EPOCHS", x, 1.0, fs=256)
    for x in _synth_class(3, 8, 42):
        append_epoch("dryrun#EPOCHS", x, 2.0, fs=256)


def _build_bci_graph() -> GraphBuilder:
    g = GraphBuilder()
    GS, _FU, GP = g.event_nodes()

    i1 = g.siggen_init("SG1", channels=4, buffer_seconds=1.0)
    s1 = g.siggen_start("SG1")
    fb_init = g.fbscp_init("FBCSP", n_components=2, classifier="LDA",
                           bands=[[8, 14]])
    g.link(GS, "exec", i1, "exec_in")
    g.chain(i1, s1, fb_init)

    getn = g.siggen_get("SG1")
    tr = g.fbscp_train("FBCSP", dataset="EPOCHS")
    te = g.fbscp_test("FBCSP")
    pr = g.node("Print", ["exec_in", "exec_out", "Value"])
    g.link(GP, "exec", tr, "exec_in")
    g.chain(tr, pr)
    g.link(getn, "Data", te, "Data")
    g.link(getn, "Samples", te, "Samples")
    g.link(te, "Label", pr, "Value")
    stop = g.siggen_stop("SG1")
    kill = g.siggen_kill("SG1")
    g.chain(pr, stop, kill)

    # 静态校验需要一个画布 epoch 源（数据线全连, exec 不接 — 干跑不会污染预置数据集）
    ap = g.epoch_append("EPOCHS")
    lab = g.node("Constant", ["Result"], {"value": 1.0})
    g.link(getn, "Data", ap, "Data")
    g.link(getn, "Samples", ap, "Samples")
    g.link(getn, "Fs", ap, "Fs")
    g.link(lab, "Result", ap, "Label")
    return g


def test_graph_dry_run():
    print("── Graph dry-run (Init + Train(sync) + Test) ──")
    close_all()
    reset_all()
    _seed_dry_dataset()

    g = _build_bci_graph()
    graph = g.build()
    errors = validate_static(graph)
    check(not errors, f"static validation clean ({errors[:2]})")

    result = run_dry_run(graph, frames=20, seed=0)
    logs = result.get("log", [])
    acts = [(e["node_type"], e["action"], e["detail"]) for e in logs]

    init_ev = [a for a in acts if a[1] == "fbcsp_init"]
    train_ev = [a for a in acts if a[1] == "fbcsp_train"]
    test_ev = [a for a in acts if a[1] == "fbcsp_test"]
    err_ev = [a for a in acts if a[1] == "error"
              and a[0] in ("InitFBCSP", "TrainFBCSP", "TestFBCSP")]
    check(bool(init_ev), f"fbcsp_init event ({init_ev[:1]})")
    check(bool(train_ev) and "train_acc" in train_ev[-1][2],
          f"fbcsp_train event ({train_ev[-1][2][:70]}...)" if train_ev else "no train event")
    check(bool(test_ev) and "label=" in test_ev[-1][2],
          f"fbcsp_test event ({test_ev[-1][2]})" if test_ev else "no test event")
    check(not err_ev, f"no errors ({err_ev[:2]})")

    check(list_entries() == [], f"models purged after dry-run ({list_entries()})")
    check(list_datasets() == [], f"datasets purged after dry-run ({list_datasets()})")
    close_all()


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("BCI Algorithm (FBCSP / CCA) — Unit Tests")
    print("=" * 60)

    test_spec_parse()
    test_fbcsp_train_predict()
    test_model_roundtrip()
    test_cca()
    test_reference_validation()
    test_graph_dry_run()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
