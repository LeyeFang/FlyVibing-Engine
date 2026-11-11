"""Regression: PhaseProfiler 分相计时（1.2 性能归因的地基）。

为什么需要
    `FrameProfiler` 只回答"整帧多久"。实测成品 1.44–2.17 ms 里图求值只占
    0.20 ms，剩下 1.76 ms 没有出口 —— 而"没有出口"的数字会被误读（2026-11-10
    就把 p1_low 当成吞吐读过一次）。分相器必须保证：

      - **排他时间**正确：嵌套时父相扣除子相，不重复计数
        （否则每个相都"占满整帧"，报表自相矛盾）；
      - **未归因时间**非负且 <= 帧时长（`frame - top_level_sum`）；
      - **关闭时零成本**且不产出样本（不能因为"忘关"污染成品）；
      - **线程本地**：两个线程各自记录、互不干扰（free-threading 下不加锁）；
      - **栈失配不致命**：中途开关 / 异常路径不能让后续相认错孩子；
      - `stop()` / `set_enabled(True)` 都会清空样本（半帧数据比没数据更危险）。

TIER: core
"""

from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.Stats.PhaseProfiler import (  # noqa: E402
    NULL_SCOPE,
    PhaseProfiler,
)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _spin(ms: float) -> None:
    """忙等 ms 毫秒（比 sleep 更稳定 —— 我们要的是可测的耗时）。"""
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        pass


def _phases(snapshot: dict, thread: str = "") -> dict:
    threads = snapshot.get("threads") or {}
    if thread:
        return (threads.get(thread) or {}).get("phases") or {}
    for data in threads.values():
        if data.get("phases"):
            return data["phases"]
    return {}


def main() -> int:
    print("=" * 60)
    print("PhaseProfiler — phase attribution")
    print("=" * 60)

    # ── A. 关闭状态：零成本、零样本 ──
    off = PhaseProfiler(enabled=False)
    check("disabled phase() returns null scope", off.phase("x") is NULL_SCOPE)
    with off.phase("x"):
        _spin(2)
    off.counter("c", 1)
    off.end_frame(10.0)
    snap = off.snapshot()
    check("disabled produces no samples",
          all(not d.get("phases") for d in snap["threads"].values()), str(snap))
    check("disabled snapshot still well formed", snap["enabled"] is False, str(snap))

    # ── B. 基本记录 + 帧/未归因 ──
    p = PhaseProfiler(enabled=True)
    for _ in range(5):
        with p.phase("frame.total"):
            with p.phase("work"):
                _spin(2)
        p.end_frame(10.0)
    s = p.snapshot()
    phases = _phases(s)
    check("phase recorded", "work" in phases, str(list(phases)))
    check("phase has 5 samples", phases["work"]["excl"]["n"] == 5,
          str(phases["work"]["excl"]))
    frame = list(s["threads"].values())[0]["frame"]
    check("frame stats collected", frame["n"] == 5 and frame["mean"] == 10.0,
          str(frame))
    un = list(s["threads"].values())[0]["unattributed"]
    check("unattributed is non-negative", un["mean"] >= 0.0, str(un))
    check("unattributed <= frame", un["max"] <= 10.0, str(un))

    # ── C. 嵌套：父相排他 = 自身 - 子相 ──
    p2 = PhaseProfiler(enabled=True)
    with p2.phase("parent"):
        _spin(3)
        with p2.phase("child"):
            _spin(6)
        _spin(3)
    p2.end_frame(30.0)
    ph2 = _phases(p2.snapshot())
    parent_excl = ph2["parent"]["excl"]["mean"]
    parent_incl = ph2["parent"]["incl"]["mean"]
    child_excl = ph2["child"]["excl"]["mean"]
    check("parent inclusive >= child inclusive",
          parent_incl >= child_excl - 1e-6, f"{parent_incl} vs {child_excl}")
    check("parent exclusive excludes child",
          parent_excl < parent_incl * 0.9, f"excl={parent_excl} incl={parent_incl}")
    check("parent exclusive ~= 6ms (two 3ms spins), child ~= 6ms",
          parent_excl >= 4.0 and parent_excl <= 12.0 and child_excl >= 4.0,
          f"parent={parent_excl} child={child_excl}")
    check("nested phases are attributed to their own thread",
          len(p2.snapshot()["threads"]) == 1, str(list(p2.snapshot()["threads"])))

    # ── D. 三层嵌套：叶子排他 = 全部，根排他 <= 自身 ──
    p3 = PhaseProfiler(enabled=True)
    with p3.phase("a"):
        with p3.phase("b"):
            with p3.phase("c"):
                _spin(4)
    p3.end_frame(20.0)
    ph3 = _phases(p3.snapshot())
    check("deepest phase gets the work",
          ph3["c"]["excl"]["mean"] >= 3.0 > ph3["b"]["excl"]["mean"],
          str({k: v["excl"]["mean"] for k, v in ph3.items()}))
    check("all three levels present", set(ph3) == {"a", "b", "c"}, str(set(ph3)))

    # ── E. counter ──
    p4 = PhaseProfiler(enabled=True)
    for _ in range(4):
        p4.counter("draw_calls", 7)
        p4.counter("draw_calls", 3)
        p4.end_frame(5.0)
    counters = list(p4.snapshot()["threads"].values())[0]["counters"]
    check("counter accumulates within a frame", counters["draw_calls"]["mean"] == 10.0,
          str(counters))
    check("counter keeps one sample per frame", counters["draw_calls"]["n"] == 4,
          str(counters))

    # ── F. worst_frames ──
    p5 = PhaseProfiler(enabled=True, worst_frames=2)
    for ms in (5.0, 40.0, 12.0, 90.0, 8.0):
        with p5.phase("burn"):
            pass
        p5.end_frame(ms)
    worst = list(p5.snapshot()["threads"].values())[0]["worst_frames"]
    check("worst_frames keeps N", len(worst) == 2, str(len(worst)))
    check("worst_frames sorted desc", [w["frame_ms"] for w in worst] == [90.0, 40.0],
          str([w["frame_ms"] for w in worst]))
    check("worst frame carries breakdown",
          "burn" in worst[0]["phases"] and "(unattributed)" in worst[0]["phases"],
          str(worst[0]["phases"]))

    # ── G. 开关语义 ──
    p6 = PhaseProfiler(enabled=True)
    with p6.phase("before"):
        pass
    p6.end_frame(4.0)
    p6.set_enabled(False)
    check("disable keeps existing samples",
          "before" in _phases(p6.snapshot()), str(list(_phases(p6.snapshot()))))
    check("disabled phase is null", p6.phase("x") is NULL_SCOPE)
    p6.set_enabled(True)
    check("enabling clears samples", not _phases(p6.snapshot()),
          str(list(_phases(p6.snapshot()))))

    # ── H. 中途关闭不得让父相认错孩子（栈失配）──
    p7 = PhaseProfiler(enabled=True)
    with p7.phase("outer"):
        with p7.phase("inner"):
            p7.set_enabled(False)      # 模拟 op 中途 toggle
            _spin(1)
        _spin(1)
    p7.set_enabled(True)               # 重新打开（会清空）
    with p7.phase("clean"):
        _spin(2)
    p7.end_frame(20.0)
    ph7 = _phases(p7.snapshot())
    check("stack survives mid-frame toggle", set(ph7) == {"clean"}, str(set(ph7)))
    check("no negative exclusive after toggle", ph7["clean"]["excl"]["mean"] > 0.0,
          str(ph7["clean"]))

    # ── I. 线程隔离 ──
    p8 = PhaseProfiler(enabled=True)
    seen: dict = {}

    def _worker() -> None:
        for _ in range(3):
            with p8.phase("worker.work"):
                _spin(1)
            p8.end_frame(None)          # 非渲染线程：只冲刷，不参与帧账
        seen["name"] = threading.current_thread().name

    t = threading.Thread(target=_worker, name="phase-test-worker")
    t.start()
    t.join()
    for _ in range(3):
        with p8.phase("main.work"):
            _spin(1)
        p8.end_frame(5.0)
    s8 = p8.snapshot()
    check("two threads registered", len(s8["threads"]) >= 2, str(list(s8["threads"])))
    worker = s8["threads"].get("phase-test-worker") or {}
    check("worker phases separated from render phases",
          "worker.work" in (worker.get("phases") or {})
          and "main.work" not in (worker.get("phases") or {}),
          str(list(worker.get("phases") or {})))
    check("worker has no frame accounting (end_frame(None))",
          worker.get("frame", {}).get("n", 0) == 0, str(worker.get("frame")))
    check("worker samples are not lost",
          (worker.get("phases") or {}).get("worker.work", {}).get("excl", {}).get("n") == 3,
          str((worker.get("phases") or {}).get("worker.work")))

    # ── J. 两个 profiler 互不污染（EditorHost / GameRuntime 各一个）──
    pa = PhaseProfiler(enabled=True)
    pb = PhaseProfiler(enabled=True)
    with pa.phase("only_a"):
        pass
    pa.end_frame(3.0)
    with pb.phase("only_b"):
        pass
    pb.end_frame(3.0)
    check("profiler A sees only its own phase", set(_phases(pa.snapshot())) == {"only_a"},
          str(set(_phases(pa.snapshot()))))
    check("profiler B sees only its own phase", set(_phases(pb.snapshot())) == {"only_b"},
          str(set(_phases(pb.snapshot()))))

    # ── K. reset / report_text ──
    p9 = PhaseProfiler(enabled=True)
    with p9.phase("gone"):
        pass
    p9.end_frame(2.0)
    p9.reset()
    check("reset clears samples", not _phases(p9.snapshot()),
          str(list(_phases(p9.snapshot()))))
    with p9.phase("shown"):
        _spin(2)
    p9.end_frame(6.0)
    text = p9.report_text()
    check("report_text mentions the phase", "shown" in text, text[:200])
    check("report_text mentions frame/unaccounted",
          "frame" in text and "unaccounted" in text, text[:200])
    check("empty profiler report is graceful",
          "no phase samples" in PhaseProfiler().report_text())

    # ── L. 百分比与占比 ──
    p10 = PhaseProfiler(enabled=True)
    for _ in range(10):
        with p10.phase("half"):
            _spin(2)
        p10.end_frame(10.0)
    data = list(p10.snapshot()["threads"].values())[0]
    share = data["phases"]["half"]["share"]
    check("share is a fraction of the frame", 0.0 < share < 1.0, str(share))
    check("percentiles monotonic",
          (data["phases"]["half"]["excl"]["p50"]
           <= data["phases"]["half"]["excl"]["p95"]
           <= data["phases"]["half"]["excl"]["p99"]
           <= data["phases"]["half"]["excl"]["max"]),
          str(data["phases"]["half"]["excl"]))

    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    print("ALL TESTS PASSED" if not _RESULTS["fail"] else "TESTS FAILED")
    return 0 if not _RESULTS["fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
