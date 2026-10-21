"""
Test: graph_io — 图导入/导出共享实现（GUI 面板与 agent ops 单一来源）。

覆盖:
  1. prepare_import 输入校验（graph/path 二选一; 非法消息与 ops 文案一致）
  2. prepare_import 静态检查拒绝（unknown type → refusal dict; 不触碰画布）
  3. apply_to_canvas / NodeCanvas.replace_from（替换性 + 计数 + 旧内容清除）
  4. export_graph（inline / 自动 .json 落盘 / include_rules）

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/NodeGraph/test_graph_io.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.NodeGraph import _TYPES  # noqa: E402
from Application.Core.NodeGraph import graph_io  # noqa: E402
from Application.Core.NodeGraph.canvas import NodeCanvas  # noqa: E402

_results = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _results["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


_seq = [7000]


def _node(type_name: str) -> dict:
    pids: dict[str, int] = {}
    for p in _TYPES[type_name].pins:
        _seq[0] += 1
        pids[p.name] = _seq[0]
    return {"node_type": type_name, "pos": [0.0, 0.0], "props": {}, "pin_ids": pids}


def _good_graph() -> dict:
    """OnGameStart → Print — 最小静态可过图。"""
    n1, n2 = _node("OnGameStart"), _node("Print")
    return {
        "version": "0.1.0",
        "nodes": {"1": n1, "2": n2},
        "links": {"1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]}},
        "next_id": _seq[0] + 1,
    }


def main() -> int:
    print("== graph_io tests ==")
    tmp = tempfile.mkdtemp(prefix="graph_io_test_")
    try:
        # ── 1. 输入校验 ──
        try:
            graph_io.prepare_import()
            check("missing input -> ValueError", False, "no raise")
        except ValueError as e:
            check("missing input -> ValueError", "either" in str(e), str(e))

        try:
            graph_io.prepare_import(path=os.path.join(tmp, "nope.json"))
            check("missing file -> ValueError", False, "no raise")
        except ValueError as e:
            check("missing file -> ValueError", "file not found" in str(e), str(e))

        try:
            graph_io.prepare_import(graph={"links": {}})
            check("no nodes -> ValueError", False, "no raise")
        except ValueError as e:
            check("no nodes -> ValueError", "must be a dict with 'nodes'" in str(e), str(e))

        # ── 2. 静态检查 ──
        bad = _good_graph()
        bad["nodes"]["9"] = {"node_type": "NoSuchType", "pos": [0, 0], "props": {}, "pin_ids": {}}
        _data, refused = graph_io.prepare_import(graph=bad, validate_first=True)
        check(
            "static refusal shape",
            refused is not None and refused["imported"] is False and len(refused["static_errors"]) > 0,
            str(refused)[:200],
        )
        _data2, refused2 = graph_io.prepare_import(graph=bad, validate_first=False)
        check("validate_first=False passes", refused2 is None)

        # ── 3. 应用与替换 ──
        good = _good_graph()
        data, refused = graph_io.prepare_import(graph=good, validate_first=True)
        check("good graph passes", refused is None)
        canvas = NodeCanvas()
        result = graph_io.apply_to_canvas(canvas, data)
        check(
            "apply counts",
            result["imported"] and result["nodes"] == len(good["nodes"]) and result["links"] == len(good["links"]),
            str(result),
        )

        empty = NodeCanvas()
        empty.replace_from(canvas)
        check(
            "replace_from copies",
            len(empty.nodes) == len(canvas.nodes) and len(empty.links) == len(canvas.links),
        )
        check("replace_from independent dicts", empty._nodes is not canvas._nodes)

        canvas.replace_from(NodeCanvas.from_dict(_good_graph()))
        check("replace clears old content", len(canvas.nodes) == 2 and len(canvas.links) == 1)

        # ── 4. 导出 ──
        r = graph_io.export_graph(canvas, inline=False)
        check("export inline=False", "graph" not in r and r["nodes"] == 2, str(r))
        out = os.path.join(tmp, "sub", "g")
        r2 = graph_io.export_graph(canvas, path=out, include_rules=False, inline=False)
        check(
            "export auto .json + file exists",
            r2["saved_path"].endswith(".json") and os.path.isfile(r2["saved_path"]),
            r2["saved_path"],
        )
        with open(r2["saved_path"], "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        check("include_rules=False pops _rules", "_rules" not in saved)

        r3 = graph_io.export_graph(canvas, inline=True)
        check("export inline=True default has _rules", isinstance(r3.get("graph"), dict) and "_rules" in r3["graph"])

        # ── 5. 同一文件可回灌（panel/ops 往返一致性）──
        data3, refused3 = graph_io.prepare_import(path=r2["saved_path"], validate_first=True)
        check("roundtrip file import", refused3 is None and len(data3["nodes"]) == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = _results["pass"] + _results["fail"]
    ok = _results["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_results['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
