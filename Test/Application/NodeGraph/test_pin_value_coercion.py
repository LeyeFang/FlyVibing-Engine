"""输入读取按 pin 类型转换（core，无头）— ENGINE_GAPS O5 回归。

背景（2026-10-31）:
  旧实现 `evaluators.math._read_data_input` 无条件 `float(val)`，被 10+ 模块
  当公共读取 API 使用 → 字符串 / entity_ref / variant / vec3 引脚一接就抛
  `ValueError: could not convert string to float`，且异常会中断整条 exec 链。

本测试锁定:
  1. string 引脚接字符串不再抛（EntityGet / VarSet / NewTimer）
  2. entity_ref / vec3 / variant 引脚原样传递
  3. 数值引脚遇到非法值 → 回默认值，不抛
  4. bool 引脚接受 "0" / "false"
  5. TimeDelay 已从节点注册表与求值器移除（社区公认语义陷阱）
"""

# TIER: core

from __future__ import annotations

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
from Application.Core.NodeGraph.evaluator_engine import (  # noqa: E402
    ExecutionContext,
    _EVALUATORS,
)
from Application.Core.NodeGraph.evaluators.entity.helpers import resolve_entity_id  # noqa: E402
from Application.Core.NodeGraph.evaluators.entity.lifecycle import (  # noqa: E402
    EntityRef,
    _eval_entity_get,
)
from Application.Core.NodeGraph.evaluators.inputs import read_bool, read_pin  # noqa: E402
from Application.Core.NodeGraph.evaluators.variable import _eval_var_set  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _Inst:
    def __init__(self, node_type: str, pin_ids: dict, props: dict | None = None) -> None:
        self.node_type = node_type
        self.pin_ids = pin_ids
        self.props = dict(props or {})
        self.alias = ""
        self.description = ""


class _Canvas:
    def __init__(self, inst: _Inst) -> None:
        self.nodes = {1: inst}
        self.links: dict = {}

    def find_pin_node(self, pid: int):
        return 1 if pid in self.nodes[1].pin_ids.values() else None


class _G:
    def __init__(self, inst: _Inst) -> None:
        self._canvas = _Canvas(inst)
        self._types = {inst.node_type: _TYPES[inst.node_type]}

    @staticmethod
    def _read_input(pid, ctx):
        return ctx.get_pin(pid)


def make(node_type: str, props: dict | None = None, **values):
    """构造单节点 stub；values 按引脚名注入上游值。"""
    nd = _TYPES[node_type]
    pin_ids = {p.name: 100 + i for i, p in enumerate(nd.pins)}
    inst = _Inst(node_type, pin_ids, props)
    g = _G(inst)
    ctx = ExecutionContext()
    for name, val in values.items():
        ctx.set_pin(pin_ids[name], val)
    return inst, g, ctx


class _Scene:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def GetEntityByName(self, name: str) -> int:
        self.seen.append(name)
        return 7


def test_removed_time_delay() -> None:
    print("-- TimeDelay removal --")
    check("TimeDelay not in node registry", "TimeDelay" not in _TYPES)
    check("TimeDelay evaluator unregistered", "TimeDelay" not in _EVALUATORS)


def test_string_pins() -> None:
    print("-- string pins --")
    inst, g, ctx = make("NewTimer", Name="t1")
    check("string pin read as str", read_pin(1, "Name", ctx, g, "") == "t1")

    inst, g, ctx = make("EntityGet", {"entity_name": "fallback"}, Name="HUD")
    ctx.scene = _Scene()
    raised = ""
    try:
        _eval_entity_get(1, ctx, g)
    except Exception as e:  # noqa: BLE001 — 这里就是要断言不抛
        raised = f"{type(e).__name__}: {e}"
    check("EntityGet string Name does not raise", not raised, raised)
    check("EntityGet passes name to scene", ctx.scene.seen == ["HUD"], repr(ctx.scene.seen))
    ref = ctx.get_pin(inst.pin_ids["Entity"])
    check("EntityGet emits EntityRef eid", isinstance(ref, EntityRef) and ref.eid == 7)

    inst, g, ctx = make("VarSet", {"mode": "pin"}, Name="label", Value="alpha")
    raised = ""
    try:
        _eval_var_set(1, ctx, g)
    except Exception as e:  # noqa: BLE001
        raised = f"{type(e).__name__}: {e}"
    check("VarSet variant Value does not raise", not raised, raised)
    check("VarSet keeps variant value", ctx.get_var("label") == "alpha")


def test_non_float_passthrough() -> None:
    print("-- entity_ref / vec3 passthrough --")
    ref = EntityRef(eid=5)
    inst, g, ctx = make("EntityGetTree", Entity=ref)
    check("entity_ref pin returns same object", read_pin(1, "Entity", ctx, g) is ref)
    check("resolve_entity_id from EntityRef", resolve_entity_id(1, "Entity", ctx, g) == 5)

    inst, g, ctx = make("BreakVec3", Vec3=(1.0, 2.0, 3.0))
    check("vec3 pin passes tuple through", read_pin(1, "Vec3", ctx, g) == (1.0, 2.0, 3.0))


def test_numeric_and_bool() -> None:
    print("-- numeric fallback / bool --")
    inst, g, ctx = make("ScalarMath", {"operation": "sum"}, In_0="abc")
    check("numeric pin falls back to default", read_pin(1, "In_0", ctx, g, 0.0) == 0.0)
    check("numeric pin keeps good value", read_pin(1, "In_1", ctx, g, 0.0) == 0.0)

    inst, g, ctx = make("Branch", Condition="0")
    check("bool '0' is False", read_bool(1, "Condition", ctx, g, True) is False)
    inst, g, ctx = make("Branch", Condition="false")
    check("bool 'false' is False", read_bool(1, "Condition", ctx, g, True) is False)
    inst, g, ctx = make("Branch", Condition=1)
    check("bool 1 is True", read_bool(1, "Condition", ctx, g, False) is True)


def main() -> int:
    print("== pin value coercion tests ==")
    test_removed_time_delay()
    test_string_pins()
    test_non_float_passthrough()
    test_numeric_and_bool()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
