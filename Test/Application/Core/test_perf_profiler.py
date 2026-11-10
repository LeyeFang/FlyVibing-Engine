"""Regression: FrameProfiler 统计完整性与线程安全 + PerfStatsLayer 产物结构。

为什么需要
    2026-11-10 成品性能统计（`PlayerEntry --stats-json`）建立在
    `FrameProfiler.snapshot_stats()` 之上。它必须：
      - 在渲染线程持续 tick 时被主线程安全读取（旧实现 `list(deque)` 会撞
        "deque mutated during iteration"）；
      - 分位数单调（p50 ≤ p90 ≤ p95 ≤ p99 ≤ max）；
      - 卡顿桶只统计超过阈值的帧；
      - stop() 之后窗口清空（二次 init 不混入旧帧）。
"""
# TIER: core

from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.Stats.FrameProfiler import FrameProfiler  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _feed(prof: FrameProfiler, times_ms: list[float]) -> None:
    """用可控帧时间喂数据（直接操作 deque，跳过 perf_counter 抖动）。"""
    prof.start(interval=1.0, window_size=max(16, len(times_ms)))
    for ms in times_ms:
        with prof._lock:
            prof._frame_times_ms.append(ms)


def main() -> int:
    # ── A. 空窗口不炸 ──
    p0 = FrameProfiler()
    s0 = p0.snapshot_stats()
    check("未 start 时返回零值", s0["window_frames"] == 0 and s0["avg_fps"] == 0.0, str(s0))
    check("零值仍含 stalls 键", set(s0["stalls"]) == {"16", "33", "50", "100"}, str(s0["stalls"]))

    # ── B. 分位数与卡顿桶 ──
    times = [10.0] * 90 + [20.0] * 9 + [60.0]          # 100 帧
    p1 = FrameProfiler()
    _feed(p1, times)
    s = p1.snapshot_stats()
    check("窗口帧数正确", s["window_frames"] == 100, str(s["window_frames"]))
    check("avg_fps = 1000/mean", abs(s["avg_fps"] - 1000.0 / (sum(times) / 100)) < 0.2,
          f"{s['avg_fps']}")
    check("分位数单调", s["p50_ms"] <= s["p90_ms"] <= s["p95_ms"] <= s["p99_ms"] <= s["max_ms"],
          str(s))
    check("p50 = 10ms", s["p50_ms"] == 10.0, str(s["p50_ms"]))
    check("max = 60ms", s["max_ms"] == 60.0, str(s["max_ms"]))
    check("卡顿 >16.7ms = 10 帧", s["stalls"]["16"] == 10, str(s["stalls"]))
    check("卡顿 >50ms = 1 帧", s["stalls"]["50"] == 1, str(s["stalls"]))
    check("卡顿 >100ms = 0 帧", s["stalls"]["100"] == 0, str(s["stalls"]))
    check("std 非零", s["std_ms"] > 0.0, str(s["std_ms"]))

    # ── C. stop() 清空窗口（二次 init 不混旧帧）──
    p1.stop()
    check("stop 后窗口归零", p1.snapshot_stats()["window_frames"] == 0,
          str(p1.snapshot_stats()["window_frames"]))
    p1.start(interval=1.0, window_size=64)
    p1.tick()
    time.sleep(0.01)
    p1.tick()
    check("stop 后重新 start 能用", p1.snapshot_stats()["window_frames"] >= 1,
          str(p1.snapshot_stats()))

    # ── D. 并发读取（渲染线程 tick / 主线程 snapshot）──
    p2 = FrameProfiler()
    p2.start(interval=1.0, window_size=200)
    stop_flag = threading.Event()
    errors: list[str] = []

    def _writer() -> None:
        try:
            while not stop_flag.is_set():
                p2.tick()
                time.sleep(0.0002)
        except BaseException as exc:                # noqa: BLE001
            errors.append(f"writer: {type(exc).__name__}: {exc}")

    th = threading.Thread(target=_writer, daemon=True)
    th.start()
    try:
        for _ in range(400):
            p2.snapshot_stats()
            p2.get_current_stats()
    finally:
        stop_flag.set()
        th.join(timeout=2.0)
    check("并发 snapshot 无异常", not errors, "; ".join(errors[:2]))
    check("并发后窗口有数据", p2.snapshot_stats()["window_frames"] > 0,
          str(p2.snapshot_stats()["window_frames"]))

    # ── E. PerfStatsLayer 可用且不依赖窗口 ──
    try:
        from Application.Runtime.PerfStatsLayer import PerfStatsLayer, _rss_mb

        ok_import = True
    except Exception as exc:                        # noqa: BLE001
        ok_import = False
        print(f"  (import failed: {exc})")
    check("PerfStatsLayer 可导入", ok_import)
    if ok_import:
        check("_rss_mb 返回正值", (_rss_mb() or 0) > 0, str(_rss_mb()))
        PerfStatsLayer.configure(os.path.join(_ROOT, "Test", "_runs", "_perf_layer_probe.json"),
                                 interval=0.5)
        PerfStatsLayer.OnAttach()
        PerfStatsLayer.OnUpdate()
        PerfStatsLayer.OnDetach()
        out = os.path.join(_ROOT, "Test", "_runs", "_perf_layer_probe.json")
        check("summary 落盘", os.path.isfile(out), out)
        if os.path.isfile(out):
            import json

            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            check("summary 含 frames/cpu/threads",
                  {"frames", "cpu", "threads"} <= set(data), str(list(data)))
            check("summary 记录 GIL 状态",
                  "gil_enabled" in (data.get("python") or {}), str(data.get("python")))
            try:
                os.remove(out)
                os.remove(out + ".jsonl")
            except OSError:
                pass

    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
