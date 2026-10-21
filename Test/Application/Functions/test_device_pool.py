"""
Test: Device Pool — 设备池注册表 / 池节点评估 / 校验配对 / 干跑隔离 / 场景兼容
═══════════════════════════════════════════════════════════════

测试范围:
  - 门面池注册表: create / destroy / add(排他移动) / pool_of / members / close_all 清理
  - resolve_session 池作用域自动绑定 (global / 显式池 / 未知池 / 多设备歧义)
  - 静态校验: Create/Kill 配对; Add 池引用; device pin 未连/多池连线
  - 删除级联: Create ⇄ Kill 配对 (与设备级联共用 device_cascade_deletes)
  - 画布清单 device_inventory (UI 下拉数据源)
  - 旧场景兼容: Init 缺 device pin → 校验不报错; NodeCanvas.from_dict 自动补 pin
  - 干跑全链路: Create → Init → Add → Start → Get(pool) → Stop → Kill → KillPool
      (池/会话 dryrun# 隔离 + 结束后无残留)

运行: python Test/Application/Functions/test_device_pool.py
"""

from __future__ import annotations

import os
import sys

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

from Application.Functions.VirtualDevice import (
    GLOBAL_POOL,
    SigGenConfig,
    add_to_pool,
    close_all,
    create_pool,
    destroy_pool,
    init_session,
    kill_device,
    list_pools,
    list_sessions,
    pool_members,
    pool_of,
    resolve_session,
)
from Application.Core.NodeGraph import NodeCanvas
from Application.Core.NodeGraph.graph_constraints import (
    device_cascade_deletes,
    device_inventory,
    pool_cascade_deletes,
    pool_pairing_errors,
    pool_reference_errors,
)
from Application.Core.NodeGraph.validation.checks import static_check_graph
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


def _init(name: str):
    cfg = SigGenConfig.from_props({"device_name": name, "channels": 2,
                                   "buffer_seconds": 0.5})
    return init_session(name, cfg, dry_run=True)


# ═══════════════════════════════════════════════════════════════
# 1. 池注册表 (门面)
# ═══════════════════════════════════════════════════════════════

def test_pool_registry():
    print("── Pool registry (facade) ──")
    close_all()

    ok, _ = create_pool("P1")
    check(ok, "create pool P1")
    ok, detail = create_pool("P1")
    check(ok and "already" in detail, f"create idempotent ({detail})")
    ok, _ = create_pool("")
    check(not ok, "create empty name → fail")
    ok, _ = create_pool(GLOBAL_POOL)
    check(not ok, "create 'global' → fail (implicit)")

    _init("A"); _init("B")
    ok, _ = add_to_pool("P1", "A")
    check(ok, "add A → P1")
    ok, detail = add_to_pool("P1", "A")
    check(ok and "already" in detail, f"add idempotent ({detail})")
    check(pool_of("A") == "P1", "pool_of(A) == P1")
    check(pool_members("P1") == ["A"], f"members P1 = {pool_members('P1')}")
    check(pool_members(GLOBAL_POOL) == ["B"], "global holds unpooled B")

    create_pool("P2")
    ok, detail = add_to_pool("P2", "A")
    check(ok and "moved from 'P1'" in detail, f"move A P1→P2 ({detail})")
    check(pool_members("P1") == [] and pool_members("P2") == ["A"],
          "exclusive membership (moved)")

    ok, _ = add_to_pool(GLOBAL_POOL, "A")
    check(ok and pool_of("A") == "global", "add to global = leave pool")

    ok, _ = add_to_pool("PX", "A")
    check(not ok, "add to unknown pool → fail")
    ok, _ = add_to_pool("P2", "ZZ")
    check(not ok, "add unknown device → fail")

    add_to_pool("P2", "B")
    ok, detail = destroy_pool("P2")
    check(ok and "→ global" in detail, f"destroy P2 ({detail})")
    check(pool_of("B") == "global", "member falls back to global after destroy")
    ok, _ = destroy_pool("P2")
    check(not ok, "destroy again → fail")

    add_to_pool("P1", "B")
    kill_device("B")
    check(pool_members("P1") == [], "kill_device dequeues membership")

    create_pool("P3")
    close_all()
    names = [p["name"] for p in list_pools()]
    check(names == [GLOBAL_POOL], f"close_all clears pools ({names})")


# ═══════════════════════════════════════════════════════════════
# 2. resolve_session 池作用域
# ═══════════════════════════════════════════════════════════════

def test_resolve_scoping():
    print("── resolve_session pool scoping ──")
    close_all()
    _init("S1"); _init("S2")
    create_pool("PX")
    add_to_pool("PX", "S2")

    s, why = resolve_session("", pool="PX")
    check(s is not None and s.name == "S2", f"pool PX auto-bind ({why})")
    s, why = resolve_session("", pool=GLOBAL_POOL)
    check(s is not None and s.name == "S1", f"global auto-bind ({why})")
    s, why = resolve_session("", pool="PZ")
    check(s is None and "not created" in why, f"unknown pool → error ({why})")
    s, why = resolve_session("S1", pool="PX")
    check(s is not None and s.name == "S1", "explicit name wins over pool")

    add_to_pool("PX", "S1")
    s, why = resolve_session("", pool="PX")
    check(s is None and "multiple" in why, f"multi-device pool → error ({why})")

    s, why = resolve_session("")
    check(s is None and "multiple" in why, "pool=None legacy ambiguity preserved")
    close_all()
    _init("S3")
    s, why = resolve_session("")
    check(s is not None and s.name == "S3", "pool=None single session auto-bind (legacy)")
    close_all()


# ═══════════════════════════════════════════════════════════════
# 3. 静态校验
# ═══════════════════════════════════════════════════════════════

def test_static_checks():
    print("── Pool static validation ──")

    errs = pool_pairing_errors(
        {"1": {"node_type": "CreateDevicePool", "props": {"pool_name": "A"}}})
    check(any("requires a matching KillDevicePool" in e for e in errs),
          "create without kill → error")
    errs = pool_pairing_errors(
        {"1": {"node_type": "KillDevicePool", "props": {"pool_name": "A"}}})
    check(any("requires a CreateDevicePool" in e for e in errs),
          "kill without create → error")
    errs = pool_pairing_errors({
        "1": {"node_type": "CreateDevicePool", "props": {"pool_name": "A"}},
        "2": {"node_type": "KillDevicePool", "props": {"pool_name": "A"}},
    })
    check(errs == [], f"paired pools clean ({errs[:1]})")

    errs = pool_reference_errors({
        "1": {"node_type": "CreateDevicePool", "props": {"pool_name": "A"}},
        "2": {"node_type": "CreateDevicePool", "props": {"pool_name": "A"}},
    })
    check(any("duplicate pool" in e for e in errs), "duplicate pool key → error")

    # Add / Get 引用未注册池
    g = _build_pool_graph()
    nodes = dict(g.build()["nodes"])
    add_nid = next(n for n, d in nodes.items() if d["node_type"] == "AddToDevicePool")
    nodes[add_nid]["props"]["pool_name"] = "Q"
    errs = pool_reference_errors(nodes)
    check(any("no CreateDevicePool" in e for e in errs), "Add → unknown pool error")

    # device pin 未连接
    g2 = GraphBuilder()
    GSx, _FUx, _GPx = g2.event_nodes()
    cp2 = g2.pool_create("p")
    init2 = g2.siggen_init("S", channels=2)
    add2 = g2.node("AddToDevicePool", ["exec_in", "exec_out", "device"],
                   {"pool_name": "p"})
    g2.siggen_kill("S")
    g2.pool_kill("p")
    g2.link(GSx, "exec", cp2, "exec_in")
    g2.chain(cp2, init2, add2)
    entries = static_check_graph(g2.build())
    codes = [e["code"] for e in entries]
    check("device_pin_unconnected" in codes,
          f"unconnected device pin flagged ({codes})")

    # 多池连线 (同一 device pin → 两个 Add)
    g3 = GraphBuilder()
    GS3, _a3, _b3 = g3.event_nodes()
    cp3 = g3.pool_create("p")
    init3 = g3.siggen_init("S", channels=2)
    g3.pool_add(init3, "p")
    g3.pool_add(init3, "p")
    g3.siggen_kill("S")
    g3.pool_kill("p")
    g3.link(GS3, "exec", cp3, "exec_in")
    entries = static_check_graph(g3.build())
    codes = [e["code"] for e in entries]
    check("device_multi_pool" in codes, f"multi-pool fanout flagged ({codes})")

    # 旧场景兼容: Init 缺 device pin
    g4 = GraphBuilder()
    GS4, _c4, _d4 = g4.event_nodes()
    init4 = g4.siggen_init("S", channels=2)
    g4.siggen_kill("S")
    g4.link(GS4, "exec", init4, "exec_in")
    data = g4.build()
    data["nodes"][str(init4)]["pin_ids"].pop("device", None)   # 模拟旧场景
    entries = static_check_graph(data)
    check(not any(e["code"] == "missing_pin" for e in entries),
          "legacy scene: missing device pin not flagged")
    canvas = NodeCanvas.from_dict(data)
    check("device" in canvas.nodes[init4].pin_ids, "from_dict heals missing device pin")


# ═══════════════════════════════════════════════════════════════
# 4. 删除级联
# ═══════════════════════════════════════════════════════════════

def test_pool_cascade():
    print("── Pool deletion cascade ──")
    canvas = NodeCanvas()
    cp = canvas.add_node("CreateDevicePool", (0, 0))
    ck = canvas.add_node("KillDevicePool", (0, 100))
    other = canvas.add_node("Print", (0, 200))
    canvas.nodes[cp].props["pool_name"] = "P"
    canvas.nodes[ck].props["pool_name"] = "P"
    expand = pool_cascade_deletes(canvas, [cp])
    check(ck in expand and other not in expand,
          f"delete create → cascade kill {sorted(expand)}")
    expand = device_cascade_deletes(canvas, [ck])
    check(cp in expand, "device_cascade_deletes includes pool pair")

    canvas2 = NodeCanvas()
    c2 = canvas2.add_node("CreateDevicePool", (0, 0))
    k2 = canvas2.add_node("KillDevicePool", (0, 100))
    canvas2.nodes[c2].props["pool_name"] = "P"
    expand = pool_cascade_deletes(canvas2, [k2])
    check(c2 in expand, "empty-name pool kill auto-binds single create")


# ═══════════════════════════════════════════════════════════════
# 5. 画布清单 (UI 下拉数据源)
# ═══════════════════════════════════════════════════════════════

def test_inventory():
    print("── Device inventory (UI source) ──")
    canvas = NodeCanvas()
    cp = canvas.add_node("CreateDevicePool", (0, 0))
    init = canvas.add_node("InitSigGenDevice", (0, 100))
    add = canvas.add_node("AddToDevicePool", (0, 200))
    init2 = canvas.add_node("InitSigGenDevice", (0, 300))
    canvas.nodes[cp].props["pool_name"] = "eeg"
    canvas.nodes[init].props["device_name"] = "A"
    canvas.nodes[init2].props["device_name"] = "B"
    canvas.nodes[add].props["pool_name"] = "eeg"
    canvas.add_link(canvas.nodes[init].pin_ids["device"],
                    canvas.nodes[add].pin_ids["device"])
    inv = device_inventory(canvas)
    check(inv["pools"]["eeg"]["members"] == ["A"],
          f"pool members {inv['pools']['eeg']['members']}")
    check(inv["global"] == ["B"], f"global {inv['global']}")


# ═══════════════════════════════════════════════════════════════
# 6. 干跑全链路 (MCP 同路径)
# ═══════════════════════════════════════════════════════════════

def _build_pool_graph() -> GraphBuilder:
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()

    cp = g.pool_create("eeg")
    init = g.siggen_init("SG1", channels=2, frequency=10.0, buffer_seconds=1.0)
    add = g.pool_add(init, "eeg")
    start = g.siggen_start(name="", pool="eeg")
    g.link(GS, "exec", cp, "exec_in")
    g.chain(cp, init, add, start)

    getn = g.siggen_get(name="", pool="eeg")
    pr = g.node("Print", ["exec_in", "exec_out", "Value"])
    g.link(FU, "exec", pr, "exec_in")
    g.link(getn, "Samples", pr, "Value")

    stop = g.siggen_stop(name="", pool="eeg")
    kill = g.siggen_kill("SG1")
    pk = g.pool_kill("eeg")
    g.link(GP, "exec", stop, "exec_in")
    g.chain(stop, kill, pk)
    return g


def test_graph_dry_run_with_pool():
    print("── Graph dry-run with pool (MCP path) ──")
    close_all()

    g = _build_pool_graph()
    graph = g.build()

    errors = validate_static(graph)
    check(not errors, f"static validation clean ({errors[:2]})")

    report = g.validate(max_frames=30)
    check(report.passed, f"dry-run passed ({report.dry_run})")
    if report.dry_run:
        types = report.dry_run.get("events_by_type", {})
        for t in ("CreateDevicePool", "AddToDevicePool", "InitSigGenDevice",
                  "GetSigGenData", "KillDevicePool"):
            check(t in types, f"dry-run event: {t} ({types.get(t, 0)}x)")

    check(list_sessions() == [], "dry-run left no sessions")
    left = [p["name"] for p in list_pools() if p["name"] != GLOBAL_POOL]
    check(left == [], f"dry-run left no pools ({left})")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Device Pool — Unit Tests")
    print("=" * 60)

    test_pool_registry()
    test_resolve_scoping()
    test_static_checks()
    test_pool_cascade()
    test_inventory()
    test_graph_dry_run_with_pool()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
