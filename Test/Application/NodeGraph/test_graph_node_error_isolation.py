"""exec 链节点级异常隔离（core，无头）。

背景（2026-10-31）:
  旧实现 `_walk_exec` 直接调用求值器，任何一个节点抛异常都会把**整条 exec 链 /
  整帧触发**一起中断（数据节点懒求值那条路反而有 try/except，策略不一致）。
  ENGINE_GAPS O5 的现场表现即此。

本测试锁定:
  1. 节点求值抛异常时 `trigger()` 不向上抛；
  2. 出错节点之后的下游不执行（分支隔离），但同一触发内的其它分支不受影响；
  3. 错误日志限流（同一节点+异常类型只打印一次）。
"""

# TIER: core

from __future__ import annotations

import contextlib
import io
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.NodeGraph import _TYPES  # noqa: E402
from Application.Core.NodeGraph.data_model import NodeTypeDef, PinDef  # noqa: E402
from Application.Core.NodeGraph.evaluator_engine import (  # noqa: E402
    ExecutionContext,
    GraphEvaluator,
    register_evaluator,
    unregister_evaluator,
)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


# ── 测试用节点类型（不进全局 _TYPES，只挂在本测试的 types 表上）──
_BAD_TYPE = NodeTypeDef(
    "_TestBad", "Test Bad", "Debug", (1.0, 0.4, 0.4),
    [
        PinDef(9002, "exec_in", "exec", "input"),
        PinDef(9003, "exec_out", "exec", "output"),
    ],
)
_OK_TYPE = NodeTypeDef(
    "_TestOk", "Test Ok", "Debug", (0.4, 1.0, 0.4),
    [PinDef(9004, "exec_in", "exec", "input")],
)


class _Inst:
    def __init__(self, node_type: str, pin_ids: dict) -> None:
        self.node_type = node_type
        self.pin_ids = pin_ids
        self.props: dict = {}
        self.alias = ""
        self.description = ""


class _Link:
    def __init__(self, from_pin: int, to_pin: int) -> None:
        self.from_pin = from_pin
        self.to_pin = to_pin


class _Canvas:
    def __init__(self, nodes: dict, links: dict) -> None:
        self.nodes = nodes
        self.links = links

    def find_pin_node(self, pid: int):
        for nid, inst in self.nodes.items():
            if pid in inst.pin_ids.values():
                return nid
        return None


def build_graph():
    event_nd = _TYPES["OnFrameUpdate"]
    event_pins = {p.name: 9000 + i for i, p in enumerate(event_nd.pins)}
    nodes = {
        1: _Inst("OnFrameUpdate", event_pins),
        2: _Inst("_TestBad", {"exec_in": 9002, "exec_out": 9003}),
        3: _Inst("_TestOk", {"exec_in": 9004}),
    }
    links = {
        1: _Link(event_pins["exec"], 9002),
        2: _Link(9003, 9004),
    }
    types = dict(_TYPES)
    types["_TestBad"] = _BAD_TYPE
    types["_TestOk"] = _OK_TYPE
    return _Canvas(nodes, links), types


def main() -> int:
    print("== exec chain error isolation tests ==")
    ok_calls = {"n": 0}

    def _boom(node_id, ctx, g):
        raise RuntimeError("boom")

    def _ok(node_id, ctx, g):
        ok_calls["n"] += 1

    register_evaluator("_TestBad", _boom)
    register_evaluator("_TestOk", _ok)
    try:
        canvas, types = build_graph()
        g = GraphEvaluator(canvas, types)
        ctx = ExecutionContext()

        buf = io.StringIO()
        raised = ""
        with contextlib.redirect_stdout(buf):
            try:
                g.trigger("OnFrameUpdate", ctx)
            except Exception as e:  # noqa: BLE001 — 这里就是要断言不抛
                raised = f"{type(e).__name__}: {e}"
        out1 = buf.getvalue()
        check("trigger does not propagate node error", not raised, raised)
        check("downstream of failing node skipped", ok_calls["n"] == 0, str(ok_calls["n"]))
        check("error counted once", g._error_counts.get((2, "RuntimeError")) == 1)
        check("error logged once", out1.count("ERROR in node #2") == 1, out1)

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            g.trigger("OnFrameUpdate", ctx)
        check("second trigger still isolated", ok_calls["n"] == 0)
        check("error count accumulates", g._error_counts.get((2, "RuntimeError")) == 2)
        check("repeat error not spam-logged", buf2.getvalue().count("ERROR in node #2") == 0,
              buf2.getvalue())
    finally:
        unregister_evaluator("_TestBad")
        unregister_evaluator("_TestOk")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
