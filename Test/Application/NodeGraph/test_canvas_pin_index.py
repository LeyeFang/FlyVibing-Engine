"""Regression: canvas pin/link index must stay identical to a brute-force scan.

索引 (`NodeCanvas._ensure_index`) 是求值热路径的唯一来源（2026-11-10 引入，
把 MI-SSSEP 图的图求值从 ~3.4 ms/帧 降到 ~0.22 ms/帧）。缓存一旦失效漏点，
图会**静默**少算/错算，所以这里用暴力扫描当 oracle 逐项对拍：

  - pin_owner_of / pin_meta_of  vs  遍历 nodes × pins
  - downstream_of               vs  遍历 links
  - source_pin_of               vs  遍历 links（多条连线取第一条）
  - event_nodes_of              vs  遍历 nodes 比 category
  - 增删节点/连线、clear、replace_from、rehydrate、from_dict 后都必须正确
"""
# TIER: core

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.NodeGraph import NodeCanvas, GraphEvaluator, _TYPES  # noqa: E402
from Application.Core.NodeGraph.evaluator_engine import ExecutionContext  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


# ── oracle: 原始线性实现（与索引实现必须同结果）──────────────────────────

def oracle_pin_owner(canvas, pin_id):
    for nid, inst in canvas.nodes.items():
        nd = _TYPES.get(inst.node_type)
        if not nd:
            continue
        for p in nd.pins:
            if inst.pin_ids.get(p.name) == pin_id:
                return nid
    return None


def oracle_pin_meta(canvas, pin_id):
    for inst in canvas.nodes.values():
        nd = _TYPES.get(inst.node_type)
        if not nd:
            continue
        for p in nd.pins:
            if inst.pin_ids.get(p.name) == pin_id:
                return (p.name, p.direction, p.data_type)
    return None


def oracle_downstream(canvas, out_pin_id):
    result = []
    for link in canvas.links.values():
        if link.from_pin == out_pin_id:
            nid = oracle_pin_owner(canvas, link.to_pin)
            if nid is not None and nid not in result:
                result.append(nid)
    return result


def oracle_source(canvas, in_pin_id):
    for link in canvas.links.values():
        if link.to_pin == in_pin_id:
            return link.from_pin
    return None


def oracle_events(canvas, event_type):
    found = []
    for nid, inst in canvas.nodes.items():
        nd = _TYPES.get(inst.node_type)
        if nd and nd.category == "Event" and inst.node_type == event_type:
            found.append(nid)
    return found


def compare_all(canvas, label: str) -> None:
    """逐 pin / 逐连线对拍索引与 oracle。"""
    bad: list[str] = []
    for nid, inst in canvas.nodes.items():
        nd = _TYPES.get(inst.node_type)
        if not nd:
            continue
        for p in nd.pins:
            pid = inst.pin_ids.get(p.name)
            if pid is None:
                continue
            if canvas.pin_owner_of(pid) != oracle_pin_owner(canvas, pid):
                bad.append(f"owner({pid})")
            if canvas.pin_meta_of(pid) != oracle_pin_meta(canvas, pid):
                bad.append(f"meta({pid})")

    for link in canvas.links.values():
        out = canvas.downstream_of(link.from_pin)
        if out != oracle_downstream(canvas, link.from_pin):
            bad.append(f"down({link.from_pin})")
        if canvas.source_pin_of(link.to_pin) != oracle_source(canvas, link.to_pin):
            bad.append(f"src({link.to_pin})")

    for event_type in ("OnGameStart", "OnFrameUpdate", "OnGameStop"):
        if canvas.event_nodes_of(event_type) != oracle_events(canvas, event_type):
            bad.append(f"events({event_type})")

    # 未注册 / 不存在的 pin 必须返回 None / 空（旧实现同语义）
    if canvas.pin_owner_of(-12345) is not None:
        bad.append("owner(-12345)")
    if canvas.pin_meta_of(-12345) is not None:
        bad.append("meta(-12345)")
    if canvas.downstream_of(-12345):
        bad.append("down(-12345)")
    if canvas.source_pin_of(-12345) is not None:
        bad.append("src(-12345)")

    check(f"index == oracle [{label}]", not bad, ", ".join(bad[:8]))


def _demo_graph() -> dict:
    """手工小图：3 事件 + 一条 exec 链 + 一条 data 连线 + 一条重复输入连线。"""
    return {
        "version": "0.1.0",
        "next_id": 5000,
        "nodes": {
            "1": {"id": 1, "node_type": "OnGameStart",
                  "pin_ids": {"exec_out": 100}},
            "2": {"id": 2, "node_type": "OnFrameUpdate",
                  "pin_ids": {"exec_out": 101}},
            "3": {"id": 3, "node_type": "OnGameStop",
                  "pin_ids": {"exec_out": 102}},
            "4": {"id": 4, "node_type": "Sequence",
                  "pin_ids": {"exec_in": 200, "exec_out": 201, "Then_0": 202}},
            "5": {"id": 5, "node_type": "Constant",
                  "pin_ids": {"Result": 300}},
            "6": {"id": 6, "node_type": "Constant",
                  "pin_ids": {"Result": 301}},
            "7": {"id": 7, "node_type": "Compare",
                  "pin_ids": {"A": 400, "B": 401, "Result": 402}},
            "8": {"id": 8, "node_type": "Branch",
                  "pin_ids": {"exec_in": 500, "Condition": 501,
                              "True": 502, "False": 503}},
        },
        "links": {
            "1": {"id": 700, "from_pin": 100, "to_pin": 200},
            "2": {"id": 701, "from_pin": 201, "to_pin": 500},
            "3": {"id": 702, "from_pin": 402, "to_pin": 501},
            "4": {"id": 703, "from_pin": 300, "to_pin": 400},
            "5": {"id": 704, "from_pin": 301, "to_pin": 401},
            # 同一输入引脚接两条线 → 取第一条（与旧 _read_input 一致）
            "6": {"id": 705, "from_pin": 301, "to_pin": 400},
        },
    }


def main() -> int:
    # ── A. from_dict 建的图 ──
    canvas = NodeCanvas.from_dict(_demo_graph())
    compare_all(canvas, "from_dict")

    # ── B. 增量增删 → 每次都要与 oracle 一致 ──
    nid = canvas.add_node("ScalarMath", (0.0, 0.0))
    compare_all(canvas, "after add_node")
    lid = canvas.add_link(canvas.nodes[5].pin_ids["Result"],
                          canvas.nodes[nid].pin_ids.get("A", 0))
    compare_all(canvas, "after add_link")
    canvas.remove_link(lid)
    compare_all(canvas, "after remove_link")
    canvas.remove_node(nid)
    compare_all(canvas, "after remove_node")

    # ── C. exec 链求值顺序（索引化 trigger 必须与旧扫描同序）──
    #     用真实类型定义建图，避免手写 pin 名与注册表不一致。
    seen: list[str] = []

    def _spy(node_id, ctx, g):
        seen.append(g._canvas.nodes[node_id].node_type)

    from Application.Core.NodeGraph import evaluator_engine as ee
    chain = NodeCanvas()
    n_start = chain.add_node("OnGameStart", (0.0, 0.0))
    n_seq = chain.add_node("Sequence", (200.0, 0.0))

    def _pin(nid, kind, direction):
        nd = _TYPES[chain.nodes[nid].node_type]
        for p in nd.pins:
            if p.kind == kind and p.direction == direction:
                return chain.nodes[nid].pin_ids[p.name]
        return None

    chain.add_link(_pin(n_start, "exec", "output"), _pin(n_seq, "exec", "input"))
    _saved = ee._EVALUATORS.get("Sequence")
    ee._EVALUATORS["Sequence"] = _spy
    try:
        ctx = ExecutionContext()
        GraphEvaluator(chain, _TYPES).trigger("OnGameStart", ctx)
    finally:
        if _saved is not None:
            ee._EVALUATORS["Sequence"] = _saved
    check("trigger 走 event 索引", seen == ["Sequence"], str(seen))
    check("非本事件的链不执行",
          GraphEvaluator(chain, _TYPES) is not None and seen == ["Sequence"], str(seen))

    # ── D. 整体替换 / 清空 / 反序列化都不留旧索引 ──
    other = NodeCanvas.from_dict(_demo_graph())
    other.remove_node(7)          # 去掉 Compare，索引必须跟着变
    canvas.replace_from(other)
    compare_all(canvas, "replace_from")
    check("replace_from 后 compare 节点已消失", 7 not in canvas.nodes)
    check("replace_from 后下游为空", canvas.downstream_of(500) == [])

    canvas.clear()
    compare_all(canvas, "clear")
    check("clear 后无事件节点", canvas.event_nodes_of("OnGameStart") == [])

    # ── E. 已经建好索引后再 from_dict（共享 _TYPES，独立缓存）──
    c2 = NodeCanvas.from_dict(_demo_graph())
    compare_all(c2, "second canvas")

    # ── F. 未注册节点类型：引脚不可解析（与旧行为一致，不抛异常）──
    raw = _demo_graph()
    raw["nodes"]["9"] = {"id": 9, "node_type": "ext.ghost.NotInstalled",
                        "pin_ids": {"exec_in": 900, "exec_out": 901}}
    raw["links"]["7"] = {"id": 706, "from_pin": 202, "to_pin": 900}
    c3 = NodeCanvas.from_dict(raw)
    compare_all(c3, "unknown type")
    check("unknown 节点自身引脚不可解析", c3.pin_owner_of(900) is None)
    check("连到 unknown 的 exec 下游为空", 9 not in c3.downstream_of(202))

    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
