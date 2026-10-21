"""Compare 成员/区间操作 + SetTimer 宽松初始化 — 无头测试。

覆盖:
  1. SetTimer create_if_missing=true: 不先 NewTimer 也能创建并设置值
  2. SetTimer create_if_missing=false: 缺失时保持不创建（旧行为）
  3. Compare in / not_in(out) / between（含 include_end）/ and-or-not-xor
  4. MakeList 跳过未连接输入
  5. 数值/字符串 eq 保持兼容

运行: python Utils/Dev/test_runner.py --only compare_timer_lazy
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.NodeGraph import (  # noqa: E402
    ExecutionContext,
    GraphEvaluator,
    NodeCanvas,
    _TYPES,
)

_RESULTS = {"pass": 0, "fail": 0}
_seq = [5000]


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _node(type_name: str, props: dict | None = None) -> dict:
    pids: dict[str, int] = {}
    for p in _TYPES[type_name].pins:
        _seq[0] += 1
        pids[p.name] = _seq[0]
    return {"node_type": type_name, "pos": [0.0, 0.0],
            "props": props or {}, "pin_ids": pids}


def _graph(nodes: dict[int, dict], links: list[tuple]) -> dict:
    links_d: dict[str, dict] = {}
    for i, (fn, fp, tn, tp) in enumerate(links):
        links_d[str(i + 1)] = {
            "from_pin": nodes[fn]["pin_ids"][fp],
            "to_pin": nodes[tn]["pin_ids"][tp],
        }
    return {
        "version": "0.1.0",
        "nodes": {str(nid): nd for nid, nd in nodes.items()},
        "links": links_d,
        "next_id": _seq[0] + 1,
    }


def _eval_pin(g: GraphEvaluator, pin_id: int, ctx: ExecutionContext):
    ctx._pin_values.clear()
    g._eval_guard.clear()
    g._ensure_pin_evaluated(pin_id, ctx)
    return ctx.get_pin(pin_id)


def test_set_timer_lazy() -> None:
    print("── 1. SetTimer lazy create ──")
    nodes = {
        1: _node("OnGameStart"),
        2: _node("SetTimer", {"timer_name": "auto", "operate": "set_time",
                              "mode": "manual", "value": 2.0,
                              "create_if_missing": True}),
        3: _node("SetTimer", {"timer_name": "strict", "operate": "reset",
                              "create_if_missing": False}),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, [
        (1, "exec", 2, "exec_in"),
        (2, "exec_out", 3, "exec_in"),
    ]))
    ctx = ExecutionContext()
    g = GraphEvaluator(canvas, _TYPES)
    g.trigger("OnGameStart", ctx)
    check("create_if_missing=true 创建 timer", ctx.has_timer("auto"))
    check("set_time 初值 = 2.0", ctx.get_timer("auto") == 2.0,
          str(ctx.get_timer("auto")))
    check("SetTimer 计入 _set_count（TimeTrigger 哨兵可见）",
          ctx._timers["auto"].get("_set_count") == 1,
          str(ctx._timers["auto"]))
    ctx.elapsed_time = 1.0
    check("timer 随时间推进到 3.0", ctx.get_timer("auto") == 3.0,
          str(ctx.get_timer("auto")))
    check("create_if_missing=false 不创建", not ctx.has_timer("strict"))

    reset_nodes = {
        1: _node("OnGameStart"),
        2: _node("SetTimer", {"timer_name": "reset_auto", "operate": "reset",
                              "create_if_missing": True}),
    }
    canvas2 = NodeCanvas.from_dict(_graph(reset_nodes, [(1, "exec", 2, "exec_in")]))
    ctx2 = ExecutionContext()
    GraphEvaluator(canvas2, _TYPES).trigger("OnGameStart", ctx2)
    check("reset 也宽松创建 timer", ctx2.has_timer("reset_auto"))
    check("reset 初值 = 0.0", ctx2.get_timer("reset_auto") == 0.0,
          str(ctx2.get_timer("reset_auto")))
    check("reset 计入 _set_count（TimeTrigger 可触发）",
          ctx2._timers["reset_auto"].get("_set_count") == 1,
          str(ctx2._timers["reset_auto"]))


def _compare_graph(operation: str, a: float, b: float, c: float | None,
                   include_end: bool = False):
    nodes = {
        1: _node("Constant", {"value": a}),
        2: _node("Constant", {"value": b}),
        3: _node("Compare", {"operation": operation, "include_end": include_end}),
    }
    links = [(1, "Result", 3, "A"), (2, "Result", 3, "B")]
    if c is not None:
        nodes[4] = _node("Constant", {"value": c})
        links.append((4, "Result", 3, "C"))
    canvas = NodeCanvas.from_dict(_graph(nodes, links))
    ctx = ExecutionContext()
    g = GraphEvaluator(canvas, _TYPES)
    result = _eval_pin(g, canvas.nodes[3].pin_ids["Result"], ctx)
    return result


def test_compare() -> None:
    print("── 2. Compare in / not_in(out) / between / bool ──")
    nodes = {
        1: _node("Constant", {"value": 4.0}),
        2: _node("Constant", {"value": 3.0}),
        3: _node("Constant", {"value": 4.0}),
        4: _node("Constant", {"value": 5.0}),
        5: _node("MakeList"),
        6: _node("Compare", {"operation": "in"}),
        7: _node("Compare", {"operation": "out"}),
    }
    links = [
        (2, "Result", 5, "Item_0"),
        (3, "Result", 5, "Item_1"),
        (4, "Result", 5, "Item_2"),
        (1, "Result", 6, "A"), (5, "List", 6, "B"),
        (1, "Result", 7, "A"), (5, "List", 7, "B"),
    ]
    canvas = NodeCanvas.from_dict(_graph(nodes, links))
    ctx = ExecutionContext()
    g = GraphEvaluator(canvas, _TYPES)
    check("MakeList 跳过未连接项（len=3）",
          _eval_pin(g, canvas.nodes[5].pin_ids["List"], ctx) == [3.0, 4.0, 5.0],
          str(_eval_pin(g, canvas.nodes[5].pin_ids["List"], ctx)))
    check("4 in [3,4,5] = True",
          _eval_pin(g, canvas.nodes[6].pin_ids["Result"], ctx) == 1.0)
    check("4 out [3,4,5] = False (out 为 not_in 别名)",
          _eval_pin(g, canvas.nodes[7].pin_ids["Result"], ctx) == 0.0)

    check("between 2 in [1,3) = True",
          _compare_graph("between", 2.0, 1.0, 3.0) == 1.0)
    check("between 3 in [1,3) = False",
          _compare_graph("between", 3.0, 1.0, 3.0) == 0.0)
    check("between include_end 3 in [1,3] = True",
          _compare_graph("between", 3.0, 1.0, 3.0, include_end=True) == 1.0)
    check("and 1 && 1 = True", _compare_graph("and", 1.0, 1.0, None) == 1.0)
    check("and 1 && 0 = False", _compare_graph("and", 1.0, 0.0, None) == 0.0)
    check("or 0 || 1 = True", _compare_graph("or", 0.0, 1.0, None) == 1.0)
    check("not 0 = True", _compare_graph("not", 0.0, 1.0, None) == 1.0)
    check("xor 1,1 = False", _compare_graph("xor", 1.0, 1.0, None) == 0.0)
    check("数值 gt 仍兼容", _compare_graph("gt", 4.0, 3.0, None) == 1.0)


def main() -> int:
    print("=" * 60)
    print("Compare membership + SetTimer lazy init")
    print("=" * 60)
    test_set_timer_lazy()
    test_compare()
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"\nResults: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
