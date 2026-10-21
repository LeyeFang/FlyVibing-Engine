"""
Test: EpochDataset（BCI 算法域数据集）— 注册表 / 捕获链路 / 落盘回读 / 校验 / 干跑隔离
═══════════════════════════════════════════════════════════════

测试范围:
  - 注册表语义: append(dim0) / trim(Samples) / label / 通道与 fs 一致性 / clear / stats
  - 落盘回读: save (pad+lengths) → load → 变长 epoch 保真; dry-run 不落盘
  - 捕获链路（干跑）: SigGen 会话 → Get → EpochAppend(逐帧) → EpochCount → 校验/清理
  - 引用校验: epoch_reference_errors + static_check_graph (epoch_reference / epoch_pin_unconnected)
  - 清理: reset_all / clear_matching 前缀语义

运行: python Test/Application/Functions/test_epoch_dataset.py
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
    clear_epochs,
    clear_matching,
    epoch_stats,
    list_datasets,
    load_epochs,
    reset_all,
    save_epochs,
)
from Application.Functions.VirtualDevice import close_all
from Application.Core.NodeGraph.graph_constraints import epoch_reference_errors
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
# 1. 注册表语义
# ═══════════════════════════════════════════════════════════════

def test_registry_semantics():
    print("── Registry semantics ──")
    reset_all()
    data = np.arange(2 * 100, dtype=np.float32).reshape(2, 100)

    ok, detail = append_epoch("EP", data, 1.0, fs=256)
    check(ok and "epoch #1" in detail, f"append #1 ({detail})")
    ok, detail = append_epoch("EP", data[:, :40], 2, samples=25, fs=256)
    check(ok and "epoch #2" in detail, f"append #2 trimmed ({detail})")
    ok, detail = append_epoch("EP", data, 1.0, fs=256)
    check(ok and "epoch #3" in detail, f"append #3 ({detail})")

    ok, detail = append_epoch("EP", np.zeros((3, 50), np.float32), 1.0, fs=256)
    check(not ok and "channel mismatch" in detail,
          f"channel mismatch → fail ({detail})")
    ok, detail = append_epoch("EP", np.zeros((2, 50), np.float32), 1.0, fs=512)
    check(not ok and "sampling rate" in detail, f"fs mismatch → fail ({detail})")
    ok, detail = append_epoch("EP", data, "bad")
    check(not ok and "label" in detail, f"non-numeric label → fail ({detail})")

    stats, why = epoch_stats("EP")
    check(stats == {"count": 3, "classes": 2, "channels": 2, "fs": 256},
          f"stats {stats} {why}")

    ok, _ = clear_epochs("EP")
    stats, _ = epoch_stats("EP")
    check(ok and stats is None, "clear removes dataset")
    ok, _ = clear_epochs("EP")
    check(ok, "clear idempotent")


# ═══════════════════════════════════════════════════════════════
# 2. 落盘 / 回读（pad + lengths）
# ═══════════════════════════════════════════════════════════════

def test_save_load_roundtrip():
    print("── Save / Load roundtrip (pad + lengths) ──")
    reset_all()
    tmp = tempfile.mkdtemp(prefix="mge_epoch_")
    try:
        data = np.random.default_rng(0).standard_normal((2, 100)).astype(np.float32)
        append_epoch("SRC", data, 1.0, fs=256)
        append_epoch("SRC", data[:, :37], 2.0, samples=37, fs=256)

        n_before = len(os.listdir(tmp))
        ok, detail = save_epochs("SRC", tmp, dry_run=True)
        check(ok and "dry-run" in detail and len(os.listdir(tmp)) == n_before,
              f"dry-run save writes nothing ({detail[:66]}...)")

        ok, detail = save_epochs("SRC", tmp, dry_run=False)
        files = [f for f in os.listdir(tmp) if f.endswith(".npz")]
        check(ok and len(files) == 1, f"saved npz ({files})")
        path = os.path.join(tmp, files[0])
        with np.load(path) as npz:
            check(npz["X"].shape == (2, 2, 100), f"pad shape {npz['X'].shape}")
            check(npz["lengths"].tolist() == [100, 37],
                  f"lengths {npz['lengths'].tolist()}")

        ok, detail = load_epochs("DST", path)
        check(ok and "2 epoch" in detail, f"load ok ({detail})")
        ok, _ = save_epochs("DST", tmp, dry_run=False)
        files = sorted(f for f in os.listdir(tmp) if f.endswith(".npz"))
        with np.load(os.path.join(tmp, files[-1])) as npz2:
            check(npz2["lengths"].tolist() == [100, 37],
                  f"roundtrip lengths preserved ({npz2['lengths'].tolist()})")

        ok, detail = load_epochs("DST", os.path.join(tmp, "missing.npz"))
        check(not ok and "not found" in detail, "missing file → fail")
    finally:
        reset_all()
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 3. 捕获链路（干跑: 会话 → Get → Append → Count）
# ═══════════════════════════════════════════════════════════════

def _build_epoch_graph() -> GraphBuilder:
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()

    init = g.siggen_init("SG1", channels=2, buffer_seconds=1.0)
    start = g.siggen_start("SG1")
    g.link(GS, "exec", init, "exec_in")
    g.chain(init, start)

    getn = g.siggen_get("SG1")
    ap = g.epoch_append("EPOCHS")
    lab = g.node("Constant", ["Result"], {"value": 1.0})
    g.link(FU, "exec", ap, "exec_in")
    g.link(getn, "Data", ap, "Data")
    g.link(getn, "Samples", ap, "Samples")
    g.link(getn, "Fs", ap, "Fs")
    g.link(lab, "Result", ap, "Label")

    cnt = g.epoch_count("EPOCHS")
    pr = g.node("Print", ["exec_in", "exec_out", "Value"])
    g.link(FU, "exec", pr, "exec_in")
    g.link(cnt, "Count", pr, "Value")

    stop = g.siggen_stop("SG1")
    kill = g.siggen_kill("SG1")
    g.link(GP, "exec", stop, "exec_in")
    g.chain(stop, kill)
    return g


def test_graph_capture_dry_run():
    print("── Graph capture (dry-run: session → get → append) ──")
    close_all()
    reset_all()

    g = _build_epoch_graph()
    graph = g.build()
    errors = validate_static(graph)
    check(not errors, f"static validation clean ({errors[:2]})")

    result = run_dry_run(graph, frames=30, seed=0)
    logs = result.get("log", [])
    appends = [e for e in logs if e["action"] == "epoch_append"]
    skips = [e for e in logs if e["action"] == "epoch_skip"]
    err_ev = [e for e in logs if e["action"] == "error"
              and e["node_type"] in ("EpochAppend", "EpochCount")]
    check(len(appends) >= 25, f"epoch_append events captured ({len(appends)})")
    check(not skips and not err_ev,
          f"no skips/errors (skip={len(skips)}, err={len(err_ev)})")
    if appends:
        last = appends[-1]["detail"]
        check(f"epoch #{len(appends)}" in last,
              f"sequential counter ({last[:64]})")

    left = list_datasets()
    check(left == [], f"dry-run datasets purged ({left})")
    from Application.Functions.VirtualDevice import list_sessions

    killed = result.get("killed_sessions") or []
    left_sessions = list_sessions()
    check(left_sessions == [],
          f"no dry sessions left (cleanup={killed}, remaining={left_sessions})")
    close_all()


# ═══════════════════════════════════════════════════════════════
# 4. 引用校验
# ═══════════════════════════════════════════════════════════════

def test_reference_validation():
    print("── Reference validation ──")
    errs = epoch_reference_errors({
        "1": {"node_type": "EpochAppend", "props": {"epochs_name": "A"}},
        "2": {"node_type": "EpochCount", "props": {"epochs_name": "NOPE"}},
    })
    check(any("no EpochAppend" in e for e in errs),
          f"explicit unknown ref → error ({errs[:1]})")

    errs = epoch_reference_errors({
        "1": {"node_type": "EpochAppend", "props": {"epochs_name": "A"}},
        "2": {"node_type": "EpochAppend", "props": {"epochs_name": "B"}},
        "3": {"node_type": "EpochSave", "props": {}},
    })
    check(any("unbound" in e for e in errs), "empty + 2 sources → error")

    errs = epoch_reference_errors({
        "1": {"node_type": "EpochAppend", "props": {}},
        "2": {"node_type": "EpochCount", "props": {}},
    })
    check(errs == [], f"single source + empty ref → auto-bind ok ({errs})")

    # static_check_graph 集成: Append 的 Data/Label 未连
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()
    init = g.siggen_init("SG1", channels=2, buffer_seconds=1.0)
    g.link(GS, "exec", init, "exec_in")
    ap = g.epoch_append("EPOCHS")
    g.link(FU, "exec", ap, "exec_in")
    kill = g.siggen_kill("SG1")
    g.link(GP, "exec", kill, "exec_in")
    entries = static_check_graph(g.build())
    codes = [e["code"] for e in entries]
    check(codes.count("epoch_pin_unconnected") == 2,
          f"unconnected Data/Label flagged ({codes})")


# ═══════════════════════════════════════════════════════════════
# 5. 清理语义
# ═══════════════════════════════════════════════════════════════

def test_cleanup_semantics():
    print("── Cleanup semantics ──")
    reset_all()
    append_epoch("REAL", np.zeros((1, 10), np.float32), 1.0)
    append_epoch("dryrun#TMP", np.zeros((1, 10), np.float32), 1.0)
    n = clear_matching("dryrun#")
    check(n == 1 and list_datasets() == ["REAL"],
          f"prefix clear keeps real ({list_datasets()})")
    n = reset_all()
    check(n == 1 and list_datasets() == [], "reset_all clears remaining")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("EpochDataset — Unit Tests")
    print("=" * 60)

    test_registry_semantics()
    test_save_load_roundtrip()
    test_graph_capture_dry_run()
    test_reference_validation()
    test_cleanup_semantics()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
