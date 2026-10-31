"""SaveData 通用数据保存 — 无头测试。

覆盖:
  1. npz 单数组 / 多数组、npy、csv、json 落盘与 meta 侧车
  2. unique 命名 / tag / dry-run 不创建文件
  3. SaveData 节点在图中执行并输出 Path/Rows/Cols/Written/Ok

运行: python Utils/Dev/test_runner.py --only save_data
"""
# TIER: core

from __future__ import annotations

import csv
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

import numpy as np  # noqa: E402

from Application.Core.NodeGraph import (  # noqa: E402
    ExecutionContext,
    GraphEvaluator,
    NodeCanvas,
    _TYPES,
)
from Application.Core.NodeGraph.evaluators.io import save_data  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}
_seq = [9000]


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


def test_formats(tmp: str) -> None:
    print("── 1. formats / meta ──")
    arr = np.arange(6, dtype=np.float64).reshape(3, 2)

    r = save_data(arr, tmp, "single", fmt="npz", unique=False)
    check("npz single ok", r.ok and os.path.isfile(r.path), r.detail)
    check("npz single shape/rows/cols",
          r.rows == 3 and r.cols == 2 and r.samples == 3,
          f"{r.rows}x{r.cols}/{r.samples}")
    with np.load(r.path) as z:
        check("npz single key=data", "data" in z and z["data"].shape == (3, 2))
    check("meta sidecar exists", os.path.isfile(r.meta_path), r.meta_path)
    with open(r.meta_path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    check("meta fields", meta["format"] == "npz" and meta["rows"] == 3
          and meta["shape"] == [3, 2], str(meta)[:200])

    r2 = save_data({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]}, tmp, "multi",
                   fmt="npz", unique=False, compress=False)
    with np.load(r2.path) as z:
        check("npz multi keys", set(z.files) == {"a", "b"})
    check("npz multi rows/cols", r2.rows == 3 and r2.cols == 2,
          f"{r2.rows}x{r2.cols}")

    r3 = save_data(arr, tmp, "arr", fmt="npy", unique=False)
    check("npy roundtrip", r3.ok and np.array_equal(np.load(r3.path), arr))

    r4 = save_data(arr, tmp, "table", fmt="csv", unique=False,
                   csv_header="x,y")
    check("csv rows/cols", r4.rows == 3 and r4.cols == 2)
    with open(r4.path, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    check("csv header+data", rows[0] == ["x", "y"] and rows[1] == ["0.0", "1.0"],
          str(rows[:2]))

    r5 = save_data({"x": [1, 2], "y": [3, 4]}, tmp, "dictcsv",
                   fmt="csv", unique=False)
    with open(r5.path, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    check("csv dict auto header", rows[0] == ["x", "y"], str(rows[:1]))

    r6 = save_data({"values": np.array([1, 2, 3]), "ok": True},
                   tmp, "meta", fmt="json", unique=False)
    with open(r6.path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    check("json numpy serialization", obj == {"values": [1, 2, 3], "ok": True},
          str(obj))

    r7 = save_data([1], tmp, "no_meta", fmt="npy", unique=False, save_meta=False)
    check("save_meta=False omits sidecar", r7.ok and not r7.meta_path
          and not os.path.exists(os.path.join(tmp, "no_meta.npy.meta.json")),
          f"{r7.meta_path}")

    # CSV append: header once, then the second write appends a row.
    a1 = save_data([1], tmp, "append", fmt="csv", unique=False, csv_header="v")
    a2 = save_data([2], tmp, "append", fmt="csv", unique=False,
                   csv_header="v", csv_mode="a")
    with open(a2.path, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    check("csv append header once", a1.ok and a2.ok and rows == [["v"], ["1"], ["2"]],
          str(rows))


def test_unique_and_dry_run(tmp: str) -> None:
    print("── 2. unique / dry-run ──")
    a = save_data([1, 2], tmp, "run", fmt="npy", unique=True)
    b = save_data([3, 4], tmp, "run", fmt="npy", unique=True, tag="trial")
    check("unique paths differ", a.ok and b.ok and a.path != b.path,
          f"{a.path} vs {b.path}")
    check("tag appears in name", "_trial" in os.path.basename(b.path), b.path)

    before = set(os.listdir(tmp))
    d = save_data([1, 2, 3], tmp, "dry", fmt="npz", unique=False, dry_run=True)
    after = set(os.listdir(tmp))
    check("dry-run ok + written=0", d.ok and d.written == 0, d.detail)
    check("dry-run no files", before == after and not os.path.exists(d.path))
    check("dry-run path planned", d.path.endswith(".npz") and d.rows == 3, d.path)

    bad = save_data([1], tmp, "x", fmt="xml", unique=False)
    check("unsupported format rejected", not bad.ok and "unsupported" in bad.detail,
          bad.detail)


def test_graph_node(tmp: str) -> None:
    print("── 3. SaveData graph node ──")
    nodes = {
        1: _node("OnGameStart"),
        2: _node("SaveData", {
            "mode": "manual", "format": "npz", "file_path": tmp,
            "file_name": "from_graph", "unique": False,
            "value": "[10, 20, 30]", "save_meta": True,
        }),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, [(1, "exec", 2, "exec_in")]))
    ctx = ExecutionContext()
    g = GraphEvaluator(canvas, _TYPES)
    g.trigger("OnGameStart", ctx)

    pins = canvas.nodes[2].pin_ids
    path = ctx.get_pin(pins["Path"])
    check("graph writes file", bool(path) and os.path.isfile(path), str(path))
    check("graph outputs rows/cols", ctx.get_pin(pins["Rows"]) == 3
          and ctx.get_pin(pins["Cols"]) == 1,
          f"{ctx.get_pin(pins['Rows'])}x{ctx.get_pin(pins['Cols'])}")
    check("graph outputs written/ok", ctx.get_pin(pins["Written"]) == 1
          and ctx.get_pin(pins["Ok"]) == 1)
    with np.load(path) as z:
        check("graph data values", z["data"].tolist() == [10, 20, 30],
              str(z["data"].tolist()))

    dry_nodes = {
        1: _node("OnGameStart"),
        2: _node("SaveData", {
            "mode": "manual", "format": "json", "file_path": tmp,
            "file_name": "dry_graph", "unique": False, "value": "{\"a\": 1}",
        }),
    }
    dry_canvas = NodeCanvas.from_dict(_graph(dry_nodes, [(1, "exec", 2, "exec_in")]))
    dry_ctx = ExecutionContext()
    dry_ctx.dry_run = True
    GraphEvaluator(dry_canvas, _TYPES).trigger("OnGameStart", dry_ctx)
    dp = dry_canvas.nodes[2].pin_ids
    check("graph dry-run written=0/ok=1",
          dry_ctx.get_pin(dp["Written"]) == 0 and dry_ctx.get_pin(dp["Ok"]) == 1)
    check("graph dry-run no file", not os.path.exists(dry_ctx.get_pin(dp["Path"])))


def main() -> int:
    print("== SaveData tests ==")
    tmp = tempfile.mkdtemp(prefix="save_data_test_")
    try:
        test_formats(tmp)
        test_unique_and_dry_run(tmp)
        test_graph_node(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
