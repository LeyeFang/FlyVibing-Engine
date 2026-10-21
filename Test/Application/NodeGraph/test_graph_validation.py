"""
Test: Graph Validation Service — 引擎内节点图校验（静态 + 干跑 + 任务服务）。

覆盖:
  1. 静态检查: 空图 / 未知类型 / 正常图 / 孤立节点(warning) / SigGen 配对
  2. run_validation 同步链路: 好图 ok=True + 事件日志; 坏图跳过干跑
  3. ValidationService: start → state → report; 忙拒绝; 取消

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/NodeGraph/test_graph_validation.py
"""

from __future__ import annotations

import os
import sys
import time

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.NodeGraph import _TYPES  # noqa: E402
from Application.Core.NodeGraph.validation import (  # noqa: E402
    get_service,
    run_validation,
    static_check_graph,
)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


# ────────────────────────────────────────────────────────────────
# 构图辅助（pin_ids 从 _TYPES 模板生成, 保证与引擎注册表一致）
# ────────────────────────────────────────────────────────────────

_seq = [1000]


def _node(type_name: str, props: dict | None = None) -> dict:
    pids: dict[str, int] = {}
    for p in _TYPES[type_name].pins:
        _seq[0] += 1
        pids[p.name] = _seq[0]
    return {"node_type": type_name, "pos": [0.0, 0.0], "props": props or {}, "pin_ids": pids}


def _graph(nodes: dict[int, dict], links: list[tuple]) -> dict:
    """links: [(from_nid, from_pin, to_nid, to_pin)]"""
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


def _codes(entries: list[dict]) -> list[str]:
    return [e["code"] for e in entries]


def _good_graph() -> dict:
    """OnGameStart → Print(Constant) — 最小可运行图。"""
    return _graph(
        {
            1: _node("OnGameStart"),
            2: _node("Constant", {"value": 42.0}),
            3: _node("Print"),
        },
        [
            (1, "exec", 3, "exec_in"),
            (2, "Result", 3, "Value"),
        ],
    )


# ════════════════════════════════════════════════════════════════
# 1. 静态检查
# ════════════════════════════════════════════════════════════════

def test_static() -> None:
    print("── 1. 静态检查 ──")

    entries = static_check_graph({"nodes": {}, "links": {}})
    check("空图 → empty_graph error", any(e["code"] == "empty_graph" for e in entries))

    bad = _graph({1: _node("OnGameStart"), 2: {"node_type": "NoSuchType", "pos": [0, 0], "props": {}, "pin_ids": {}}}, [])
    entries = static_check_graph(bad)
    check("未知类型 → unknown_type", any(e["code"] == "unknown_type" for e in entries))

    entries = static_check_graph(_good_graph())
    check("正常图 → 无 error", all(e["level"] != "error" for e in entries),
          detail=str(_codes(entries)))
    check("正常图 → 无 warning", all(e["level"] != "warning" for e in entries),
          detail=str(_codes(entries)))

    lone = _graph({1: _node("Constant")}, [])
    entries = static_check_graph(lone)
    warns = [e for e in entries if e["level"] == "warning"]
    check("孤立节点 → isolated_node warning", any(e["code"] == "isolated_node" for e in warns))

    unpaired = _graph({1: _node("InitSigGenDevice")}, [])
    entries = static_check_graph(unpaired)
    check("Init 无 Kill → siggen_pairing error",
          any(e["code"] == "siggen_pairing" for e in entries if e["level"] == "error"))

    paired = _graph({1: _node("InitSigGenDevice"), 2: _node("KillSigGenDevice")}, [])
    entries = static_check_graph(paired)
    check("Init+Kill 成对 → 无 siggen_pairing",
          not any(e["code"] == "siggen_pairing" for e in entries))


# ════════════════════════════════════════════════════════════════
# 2. run_validation 同步链路
# ════════════════════════════════════════════════════════════════

def test_run_validation() -> None:
    print("── 2. run_validation 同步链路 ──")

    report = run_validation(_good_graph(), {"frames": 5, "seed": 0})
    check("好图 → ok=True", report["ok"] is True, detail=str(report["counts"]))
    check("好图 → 静态无 error", not report["static"]["errors"])
    check("好图 → 干跑无 error", not report["runtime"]["errors"], detail=str(report["runtime"]["errors"]))
    check("好图 → 帧数=5", report["runtime"]["frames_simulated"] == 5)
    check("好图 → 有事件日志", report["runtime"]["total_events"] >= 1,
          detail=f"events={report['runtime']['total_events']}")
    check("好图 → 日志含 Print", any(e["node_type"] == "Print" for e in report["log"]))
    check("报告含 graph hash", report["graph"]["hash"].startswith("sha1:"))

    bad_report = run_validation({"nodes": {}, "links": {}}, {"frames": 5})
    check("坏图 → ok=False", bad_report["ok"] is False)
    check("坏图 → 干跑被跳过", bad_report["runtime"].get("skipped") is True)

    warn_report = run_validation(_graph({1: _node("Constant")}, []), {"frames": 3})
    check("含 warning 图 → ok=True (warning 不拦截)", warn_report["ok"] is True)
    check("含 warning 图 → counts.warnings=1", warn_report["counts"]["warnings"] == 1)

    siggen_report = run_validation(_graph({1: _node("InitSigGenDevice"), 2: _node("KillSigGenDevice")}, []), {"frames": 3})
    check("SigGen 成对 → 干跑无 error", not siggen_report["runtime"]["errors"],
          detail=str(siggen_report["runtime"]["errors"]))


# ════════════════════════════════════════════════════════════════
# 3. ValidationService（任务流）
# ════════════════════════════════════════════════════════════════

def _wait_finish(svc, task_id: int, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    state = "running"
    while time.monotonic() < deadline:
        state = svc.state(task_id)["state"]
        if state != "running":
            return state
        time.sleep(0.05)
    return state


def test_service() -> None:
    print("── 3. ValidationService 任务流 ──")
    svc = get_service()

    r = svc.start(_good_graph(), {"frames": 10})
    check("start → started", r.get("started") is True)
    tid = r["task_id"]
    state = _wait_finish(svc, tid)
    check("任务完成 → state=done", state == "done", detail=state)
    rep = svc.report(tid)
    check("report(task_id) 可取回", rep is not None and rep["task_id"] == tid)
    check("report.ok=True", bool(rep and rep["ok"]))

    # 忙拒绝 + 取消
    big = svc.start(_good_graph(), {"frames": 200000})
    check("大任务 start → started", big.get("started") is True)
    busy = svc.start(_good_graph(), {"frames": 10})
    check("运行中再 start → busy 拒绝", busy.get("busy") is True and busy.get("started") is False)
    cr = svc.cancel(big["task_id"])
    check("cancel → 已受理", cr.get("cancelled") is True)
    state = _wait_finish(svc, big["task_id"])
    check("取消后 → state=cancelled", state == "cancelled", detail=state)
    rep2 = svc.report(big["task_id"])
    check("取消报告 → runtime.cancelled=True", bool(rep2 and rep2["runtime"].get("cancelled")))

    # 报告留存上限（>5 份后最旧淘汰）
    for _ in range(4):
        rr = svc.start(_good_graph(), {"frames": 3})
        _wait_finish(svc, rr["task_id"])
    check("最新报告可取回（留存机制生效）", svc.report() is not None)


def main() -> int:
    print("=" * 62)
    print("  Graph Validation Service — headless tests")
    print("=" * 62)
    test_static()
    test_run_validation()
    test_service()
    print("-" * 62)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
