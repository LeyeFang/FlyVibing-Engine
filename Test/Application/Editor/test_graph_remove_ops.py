"""graph.remove_node / graph.unlink op 回归（core，无头）。

背景（2026-11-01，用户反馈 A1）:
  agent 迭代建图只有 `graph.add` / `graph.link`，没有删除 op —— 改错只能
  `graph.export` → 手改 JSON → `graph.import`。本测试锁定新增的两个 op：
  - `graph.remove_node`（级联删连线，批量 nodes=[...]，缺失 id 进 missing）
  - `graph.unlink`（按 link id 或 from/to 引脚）
"""

# TIER: core

from __future__ import annotations

import os
import sys
from unittest import mock

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

from Application.Core.NodeGraph import NodeCanvas  # noqa: E402
from Application.Editor.Services import LiveCommandServer as LCS  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def build_canvas():
    canvas = NodeCanvas()
    a = canvas.add_node("OnGameStart", (0.0, 0.0))
    b = canvas.add_node("EntityGet", (120.0, 0.0))
    c = canvas.add_node("EntitySetRenderVisible", (240.0, 0.0))
    pa = canvas.nodes[a].pin_ids
    pb = canvas.nodes[b].pin_ids
    l1 = canvas.add_link(pa["exec"], pb["exec_in"])
    l2 = canvas.add_link(pb["Entity"], canvas.nodes[c].pin_ids["EntityID"])
    return canvas, a, b, c, l1, l2


def main() -> int:
    print("== graph remove ops ==")

    canvas, a, b, c, l1, l2 = build_canvas()
    with mock.patch.object(LCS, "_node_canvas", lambda: canvas):
        res = LCS.LiveCommandServer._op_graph_unlink({"link": l1})
        check("unlink by link id", res["removed"] and l1 not in canvas.links, str(res))
        check("unlink keeps other links", l2 in canvas.links)

        res = LCS.LiveCommandServer._op_graph_unlink(
            {"from": {"node": b, "pin": "Entity"},
             "to": {"node": c, "pin": "EntityID"}})
        check("unlink by pin pair", res["link_id"] == l2 and l2 not in canvas.links, str(res))

        try:
            LCS.LiveCommandServer._op_graph_unlink(
                {"from": {"node": a, "pin": "exec"},
                 "to": {"node": b, "pin": "exec_in"}})
            missing_raised = False
        except ValueError:
            missing_raised = True
        check("unlink missing link raises", missing_raised)

        res = LCS.LiveCommandServer._op_graph_remove_node({"node": b})
        check("remove_node removes node", b not in canvas.nodes)
        check("remove_node reports type", res["removed"][0]["type"] == "EntityGet", str(res))

        canvas2, a2, b2, c2, l12, l22 = build_canvas()
        with mock.patch.object(LCS, "_node_canvas", lambda: canvas2):
            res = LCS.LiveCommandServer._op_graph_remove_node({"nodes": [a2, 99999]})
            check("batch remove keeps missing ids", res["missing"] == [99999], str(res))
            check("batch remove cascade links",
                  l12 not in canvas2.links and l22 in canvas2.links, str(res["removed"]))

        try:
            LCS.LiveCommandServer._op_graph_remove_node({"node": 99999})
            missing_raised = False
        except ValueError:
            missing_raised = True
        check("remove missing node raises", missing_raised)

        canvas3, a3, b3, c3, l13, _ = build_canvas()
        with mock.patch.object(LCS, "_node_canvas", lambda: canvas3):
            res = LCS.LiveCommandServer._op_graph_link(
                {"from": {"node": a3, "pin": "exec"},
                 "to": {"node": b3, "pin": "exec_in"}})
            check("duplicate link reports created=False", res.get("created") is False, str(res))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
