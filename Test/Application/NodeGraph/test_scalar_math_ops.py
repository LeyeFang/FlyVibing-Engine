"""ScalarMath operation 命名/别名回归测试（core，无头）。

背景（2026-10-20）: 节点组宏 phase0_trigger 写入 `operation: "mul"`，
但求值器只认 `"multiply"`，未知值静默落入 `sum`，导致 MI<<5 变成 MI+32。
本测试锁定: 短名/长名等价、未知值必须显式报错。
"""

# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)

from Application.Core.NodeGraph import _TYPES
from Application.Core.NodeGraph.evaluator_engine import ExecutionContext
from Application.Core.NodeGraph.evaluators.math import _eval_scalar_math

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _Inst:
    node_type = "ScalarMath"

    def __init__(self, op: str) -> None:
        self.props = {"operation": op}
        self.pin_ids = {"In_0": 101, "In_1": 102, "Result": 103}


class _Canvas:
    def __init__(self, inst: _Inst) -> None:
        self.nodes = {1: inst}


class _G:
    def __init__(self, inst: _Inst) -> None:
        self._canvas = _Canvas(inst)
        self._types = {"ScalarMath": _TYPES["ScalarMath"]}

    @staticmethod
    def _read_input(pid, ctx):
        return ctx.get_pin(pid)


def eval_op(op: str, a: float, b: float) -> float:
    inst = _Inst(op)
    g = _G(inst)
    ctx = ExecutionContext()
    ctx.set_pin(101, a)
    ctx.set_pin(102, b)
    _eval_scalar_math(1, ctx, g)
    return ctx.get_pin(103)


print("-- ScalarMath operations --")
check("sum", eval_op("sum", 3, 32) == 35)
check("add alias", eval_op("add", 3, 32) == 35)
check("sub", eval_op("sub", 32, 3) == 29)
check("subtract alias", eval_op("subtract", 32, 3) == 29)
check("mul (phase0_trigger macro value)", eval_op("mul", 3, 32) == 96,
      f"got {eval_op('mul', 3, 32)!r}")
check("multiply alias", eval_op("multiply", 3, 32) == 96)
check("div", eval_op("div", 32, 8) == 4)
check("divide alias", eval_op("divide", 32, 8) == 4)
check("uppercase MUL", eval_op("MUL", 3, 32) == 96)

try:
    eval_op("bogus", 1, 2)
    check("unknown op raises", False)
except ValueError as e:
    check("unknown op raises", "unknown operation" in str(e), str(e))

print("-" * 60)
ok = _RESULTS["fail"] == 0
print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']})")
sys.exit(0 if ok else 1)
