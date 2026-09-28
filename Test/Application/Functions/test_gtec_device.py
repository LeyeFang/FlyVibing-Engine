"""
Test: EEGDevice (Gtec) — 设备层 + 节点干跑链路单元测试
═══════════════════════════════════════════════════════════════

测试范围:
  - GtecConfig 解析 / 钳位 / 滤波器生效语义 (未填不生效, 类型不匹配忽略)
  - 空跑后端 (GtecStubBackend) 会话生命周期: init → start → get → stop → kill
  - 节点图干跑 (MCP validate_graph 同路径): Init→Start→Get→Stop→Kill 全链路
  - Init/Kill 强制配对: 静态校验错误 + 编辑器删除级联

运行: python Test/Application/Functions/test_gtec_device.py
"""

from __future__ import annotations

import sys, os

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import numpy as np

from Application.Functions.EEGDevice import (
    GtecConfig,
    close_all,
    get_data,
    init_session,
    kill_device,
    list_sessions,
    start_record,
    stop_record,
)
from Application.Core.NodeGraph import NodeCanvas, _TYPES
from Application.Core.NodeGraph.graph_constraints import (
    gtec_cascade_deletes,
    gtec_pairing_errors,
)
from Utils.NodeEditor.graph_builder import GraphBuilder
from Utils.NodeEditor.node_graph_validator import validate_static

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
# 1. 配置解析 / 滤波器语义
# ═══════════════════════════════════════════════════════════════

def test_config_semantics():
    print("── GtecConfig semantics ──")

    # 默认值
    cfg = GtecConfig.from_props({})
    check(cfg.template == "64ch" and cfg.channels == 64, "default template 64ch")
    check(cfg.sampling_rate == 512, "default rate 512")
    check(abs(cfg.buffer_seconds - 10.0) < 1e-9, "default buffer 10s")
    check(cfg.buffer_capacity() == 5120, f"capacity 10s@512 = {cfg.buffer_capacity()}")
    check(cfg.save_dir == ".", "default save_dir '.'")

    # 非法值回退
    cfg = GtecConfig.from_props({
        "template": "999ch", "sampling_rate": 12345, "notch": "75",
        "filter_type": "xxx", "export_format": "docx",
    })
    check(cfg.template == "64ch" and cfg.sampling_rate == 512
          and cfg.notch == "off" and cfg.filter_type == "none"
          and cfg.export_format == "npz", "invalid values fall back")

    # highpass: 只用 low_cut
    f = GtecConfig.from_props(
        {"filter_type": "highpass", "low_cut": 0.1, "high_cut": 100.0}).effective_filters()
    check(f["low"] == 0.1 and f["high"] is None, "highpass uses low_cut only")
    check("high_cut 忽略" in f["note"], f"highpass note ({f['note']})")

    # lowpass: 只用 high_cut (填了 low_cut 1Hz 也不生效 — 需求示例)
    f = GtecConfig.from_props(
        {"filter_type": "lowpass", "low_cut": 1.0, "high_cut": 40.0}).effective_filters()
    check(f["low"] is None and f["high"] == 40.0, "lowpass ignores low_cut (1Hz example)")
    check("low_cut 忽略" in f["note"], "lowpass note mentions ignored low_cut")

    # lowpass 未填 high_cut → 不启用
    f = GtecConfig.from_props({"filter_type": "lowpass"}).effective_filters()
    check(f["low"] is None and f["high"] is None
          and "不启用" in f["note"], "lowpass without high_cut → no filter")

    # bandpass 只填一侧 → 单侧生效
    f = GtecConfig.from_props(
        {"filter_type": "bandpass", "high_cut": 50.0}).effective_filters()
    check(f["low"] is None and f["high"] == 50.0, "bandpass one-sided → high only")

    # notch
    f = GtecConfig.from_props({"notch": "50"}).effective_filters()
    check(f["notch_hz"] == 50, "notch 50 Hz")

    # buffer 钳位
    cfg = GtecConfig.from_props({"buffer_seconds": -5.0})
    check(cfg.buffer_seconds >= 0.1, "buffer clamped to >= 0.1")


# ═══════════════════════════════════════════════════════════════
# 2. 空跑会话生命周期
# ═══════════════════════════════════════════════════════════════

def test_stub_session_lifecycle():
    print("── Stub session lifecycle ──")
    close_all()

    cfg = GtecConfig.from_props({
        "device_name": "STUB1", "template": "64ch", "sampling_rate": 512,
        "buffer_seconds": 1.0,
    })
    session, detail = init_session("STUB1", cfg, dry_run=True)
    check(session is not None, f"init_session ok ({detail[:60]}...)")
    check(list_sessions() == ["STUB1"], f"registered: {list_sessions()}")

    ok, detail = start_record("STUB1", elapsed_s=0.5)
    check(ok, f"start_record ok ({detail})")

    # 1.0s 后读取 → 512 采样写入缓冲 (1s @ 512Hz)
    result, why = get_data("STUB1", elapsed_s=1.5)
    check(result is not None, f"get_data ok ({why})")
    if result:
        data = result["data"]
        check(data.shape == (64, 512), f"shape (channels, capacity) = {data.shape}")
        check(data.dtype == np.float32, f"dtype {data.dtype}")
        check(result["samples"] == 512, f"valid samples = {result['samples']}")
        check(result["stub"] is True, "stub flag True")
        check(float(np.abs(data).max()) > 0.0, "synthetic data non-zero")
        # 非销毁: 再次读取同样形状
        again, _ = get_data("STUB1", elapsed_s=1.5)
        check(again is not None and again["data"].shape == (64, 512), "second read non-destructive")

    # stop → 干跑不落盘, 但给出目标路径
    ok, detail = stop_record("STUB1", save_scope="session", elapsed_s=1.5)
    check(ok, f"stop_record ok ({detail[:70]}...)")
    check("dry-run" in detail and ".npz" in detail, "stop plans npz path without writing")

    # kill → 注销
    ok, detail = kill_device("STUB1")
    check(ok, f"kill_device ok ({detail})")
    check(list_sessions() == [], "session unregistered after kill")

    # 未注册 → 明确错误
    ok, detail = start_record("NOPE")
    check(not ok and "not registered" in detail, f"unknown device error: {detail}")
    check(close_all() == 0, "close_all on empty registry = 0")


# ═══════════════════════════════════════════════════════════════
# 3. 节点图干跑 (MCP validate_graph 同路径)
# ═══════════════════════════════════════════════════════════════

def _build_gtec_graph() -> GraphBuilder:
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()

    init = g.gtec_init("HIAMP", template="64ch", rate=512, notch="50",
                       filter_type="bandpass", low_cut=0.1, high_cut=100.0,
                       buffer_seconds=2.0)
    start = g.gtec_start("HIAMP")
    g.link(GS, "exec", init, "exec_in")
    g.chain(init, start)

    # 每帧读取 Samples (触发 GetGtecData 懒求值) → Print
    getn = g.gtec_get("HIAMP")
    pr = g.node("Print", ["exec_in", "exec_out", "Value"])
    g.link(FU, "exec", pr, "exec_in")
    g.link(getn, "Samples", pr, "Value")

    stop = g.gtec_stop("HIAMP", scope="session")
    kill = g.gtec_kill("HIAMP")
    g.link(GP, "exec", stop, "exec_in")
    g.chain(stop, kill)
    return g


def test_graph_dry_run():
    print("── Graph dry-run (MCP path) ──")
    close_all()

    g = _build_gtec_graph()
    graph = g.build()

    errors = validate_static(graph)
    check(not errors, f"static validation clean ({errors[:2]})")

    report = g.validate(max_frames=30)
    check(report.passed, f"dry-run passed ({report.dry_run})")
    if report.dry_run:
        types = report.dry_run.get("events_by_type", {})
        for t in ("InitGtecDevice", "StartGtecRecord", "GetGtecData",
                  "StopGtecRecord", "KillGtecDevice"):
            check(t in types, f"dry-run event: {t} ({types.get(t, 0)}x)")

    check(list_sessions() == [], "dry-run left no registered sessions")


# ═══════════════════════════════════════════════════════════════
# 4. Init/Kill 强制配对: 校验 + 删除级联
# ═══════════════════════════════════════════════════════════════

def test_pairing_validation():
    print("── Init/Kill pairing validation ──")

    # Init 无 Kill → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.gtec_init("HIAMP"), "exec_in")
    errors = validate_static(g.build())
    check(any("KillGtecDevice" in e for e in errors), f"init without kill → error ({errors[:1]})")

    # Kill 无 Init → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.gtec_kill("HIAMP"), "exec_in")
    errors = validate_static(g.build())
    check(any("InitGtecDevice" in e for e in errors), "kill without init → error")

    # 名称不匹配 → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.gtec_init("A"), "exec_in")
    g.link(GS, "exec", g.gtec_kill("B"), "exec_in")
    errors = validate_static(g.build())
    check(any("no matching InitGtecDevice" in e for e in errors), "name mismatch → error")

    # 配对 → 无 gtec 错误
    g = _build_gtec_graph()
    errors = [e for e in validate_static(g.build()) if "Gtec" in e or "GtecDevice" in e]
    check(not errors, f"paired graph clean ({errors[:2]})")


def test_deletion_cascade():
    print("── Init/Kill deletion cascade ──")
    canvas = NodeCanvas()
    init_nid = canvas.add_node("InitGtecDevice", (0, 0))
    kill_nid = canvas.add_node("KillGtecDevice", (0, 100))
    other_nid = canvas.add_node("Print", (0, 200))
    canvas.nodes[init_nid].props["device_name"] = "HIAMP"
    canvas.nodes[kill_nid].props["device_name"] = "HIAMP"
    check(init_nid > 0 and kill_nid > 0, "canvas nodes created")

    # 删 Init → 级联 Kill (无关节点保留)
    expand = gtec_cascade_deletes(canvas, [init_nid])
    check(kill_nid in expand and other_nid not in expand,
          f"delete init → cascade kill {sorted(expand)}")

    # 删 Kill → 级联 Init
    expand = gtec_cascade_deletes(canvas, [kill_nid])
    check(init_nid in expand, f"delete kill → cascade init {sorted(expand)}")

    # Kill 空名 + 仅 1 个 Init → 自动绑定
    canvas2 = NodeCanvas()
    i2 = canvas2.add_node("InitGtecDevice", (0, 0))
    k2 = canvas2.add_node("KillGtecDevice", (0, 100))
    canvas2.nodes[i2].props["device_name"] = "HIAMP"
    expand = gtec_cascade_deletes(canvas2, [k2])
    check(i2 in expand, "empty-name kill auto-binds single init")

    # 两 Init + 空名 Kill → 歧义, 不级联
    canvas3 = NodeCanvas()
    i3a = canvas3.add_node("InitGtecDevice", (0, 0))
    i3b = canvas3.add_node("InitGtecDevice", (0, 50))
    k3 = canvas3.add_node("KillGtecDevice", (0, 100))
    canvas3.nodes[i3a].props["device_name"] = "A"
    canvas3.nodes[i3b].props["device_name"] = "B"
    expand = gtec_cascade_deletes(canvas3, [k3])
    check(expand == {k3}, "ambiguous empty-name kill → no cascade")

    # 静态校验同样判定歧义
    errors = gtec_pairing_errors({
        "1": {"node_type": "InitGtecDevice", "props": {"device_name": "A"}},
        "2": {"node_type": "InitGtecDevice", "props": {"device_name": "B"}},
        "3": {"node_type": "KillGtecDevice", "props": {}},
    })
    check(any("ambiguous" in e for e in errors), f"ambiguous binding error ({errors[:1]})")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("EEGDevice (Gtec) — Unit Tests")
    print("=" * 60)

    test_config_semantics()
    test_stub_session_lifecycle()
    test_graph_dry_run()
    test_pairing_validation()
    test_deletion_cascade()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
