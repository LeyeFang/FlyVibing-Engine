"""PerfStatsLayer — 成品（导出游戏）性能统计层。

为什么需要它
    编辑器有 `renderer.snapshot` 可以随时问帧率；**导出的成品没有出口** ——
    用户说"卡"，我们只能让他截图 FPS，或者干脆无法复现。本层把成品运行期的
    帧时间分布、卡顿计数、进程 CPU/内存、线程清单落成 JSON，事后可分析。

产出（`--stats-json <path>`）
    <path>                  结束时写一次完整摘要（JSON object）
    <path>.jsonl            每 interval 秒追加一行采样（趋势 / 定位"从第几秒变慢"）

采样内容
    - `frames`: FrameProfiler.snapshot_stats()（mean/p50/p90/p95/p99/max、卡顿桶）
    - `cpu`:    进程 CPU 秒数（time.process_time）与占单核百分比
    - `rss_mb`: 进程常驻内存（Windows psapi；其他平台为 None）
    - `gc`:     三代回收计数（看是否有 GC 抖动）
    - `threads`: 线程名 + daemon（看是否线程泄漏）

线程模型
    `OnUpdate` 在逻辑/主线程；读数全部走线程安全接口（FrameProfiler 内部有锁），
    **不在本层做任何引擎状态修改**。
"""

from __future__ import annotations

import gc
import json
import os
import sys
import threading
import time

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event


# ── 进程指标（跨平台尽量给值，取不到就 None）────────────────

def _rss_mb() -> float | None:
    """进程常驻内存（MB）。Windows 用 psapi，其他平台走 resource。"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            h = k32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
            if not h:
                return None
            try:
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(_PMC)
                if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    return None
                return round(pmc.WorkingSetSize / 1048576.0, 1)
            finally:
                k32.CloseHandle(h)
        import resource  # type: ignore[import-not-found]

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:  # noqa: BLE001 — 指标取不到不影响主流程
        return None


class PerfStatsLayer(Layer):
    """成品性能统计层（只在导出游戏 / `--stats-json` 时挂载）。"""

    _path: str | None = None
    _interval: float = 1.0
    _engine = None
    _started: bool = False
    _t_start: float = 0.0
    _cpu_start: float = 0.0
    _gc_start: tuple = (0, 0, 0)
    _next_sample: float = 0.0
    _rows: list = []
    _stream = None
    _elapsed: float = 0.0

    # ── 配置 ────────────────────────────────────────────────

    @classmethod
    def configure(cls, path: str, interval: float = 1.0,
                  engine=None) -> None:
        """设置输出路径与采样间隔。必须在 push_layer 之前调用。

        `engine` 用于拿 FrameProfiler（分相统计）—— 不传则只报整帧。
        """
        cls._path = os.path.abspath(path)
        cls._interval = max(0.1, float(interval or 1.0))
        cls._engine = engine
        cls._rows = []
        cls._started = False

    # ── Layer 生命周期 ───────────────────────────────────────

    @classmethod
    def OnAttach(cls) -> None:
        cls._t_start = time.perf_counter()
        cls._cpu_start = time.process_time()
        try:
            cls._gc_start = tuple(gc.get_count())
        except Exception:  # noqa: BLE001
            cls._gc_start = (0, 0, 0)
        cls._next_sample = cls._t_start + cls._interval
        cls._rows = []
        cls._started = True
        if cls._path:
            os.makedirs(os.path.dirname(cls._path) or ".", exist_ok=True)
            try:
                cls._stream = open(cls._path + ".jsonl", "w", encoding="utf-8")
            except OSError as exc:
                print(f"[PerfStats] cannot open jsonl: {exc}")
                cls._stream = None
        print(f"[PerfStats] sampling every {cls._interval:.2f}s → "
              f"{cls._path or '(disabled)'}")

    @classmethod
    def OnDetach(cls) -> None:
        cls._started = False
        # 先固定时长与 CPU，再关流 — 否则写摘要时读不到真实结束时刻
        cls._elapsed = (time.perf_counter() - cls._t_start) if cls._t_start else 0.0
        if cls._stream is not None:
            try:
                cls._stream.close()
            except OSError:
                pass
            cls._stream = None
        cls._write_summary()

    @classmethod
    def OnUpdate(cls) -> None:
        if not cls._started:
            return
        now = time.perf_counter()
        if now < cls._next_sample:
            return
        cls._next_sample = now + cls._interval
        row = cls._sample(now)
        cls._rows.append(row)
        if cls._stream is not None:
            try:
                cls._stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                cls._stream.flush()
            except OSError:
                pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    @classmethod
    def OnRender(cls) -> None:
        pass

    # ── 采样 / 汇总 ─────────────────────────────────────────

    @classmethod
    def _frame_stats(cls) -> dict:
        eng = cls._engine
        if eng is None:
            from Application.Runtime.GameRuntime import GameRuntime
            eng = GameRuntime
        try:
            return eng._get_profiler().snapshot_stats()
        except Exception:  # noqa: BLE001 — 成品不能在统计上崩
            return {}

    @classmethod
    def _phase_snapshot(cls) -> dict:
        """分相统计快照（未启用分相时返回空 dict，不污染产物）。"""
        eng = cls._engine
        if eng is None:
            from Application.Runtime.GameRuntime import GameRuntime
            eng = GameRuntime
        try:
            phases = eng._get_profiler().phases
            if not phases.enabled:
                return {}
            return phases.snapshot()
        except Exception:  # noqa: BLE001
            return {}

    @classmethod
    def _sample(cls, now: float) -> dict:
        elapsed = now - cls._t_start
        cpu = time.process_time() - cls._cpu_start
        return {
            "t_s": round(elapsed, 2),
            "fps": cls._frame_stats().get("avg_fps"),
            "frames": cls._frame_stats(),
            "cpu_s": round(cpu, 2),
            "cpu_pct_core": round(100.0 * cpu / elapsed, 1) if elapsed > 0 else 0.0,
            "rss_mb": _rss_mb(),
        }

    @classmethod
    def _write_summary(cls) -> None:
        if not cls._path:
            return
        elapsed = cls._elapsed
        cpu = time.process_time() - cls._cpu_start
        try:
            gc_now = tuple(gc.get_count())
        except Exception:  # noqa: BLE001
            gc_now = (0, 0, 0)
        try:
            gc_collections = [int(g.get("collections", 0)) for g in gc.get_stats()]
        except Exception:  # noqa: BLE001
            gc_collections = []
        frames = cls._frame_stats()
        summary = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(elapsed, 2),
            "frames": frames,
            "cpu": {
                "process_s": round(cpu, 2),
                "pct_of_one_core": round(100.0 * cpu / elapsed, 1) if elapsed > 0 else 0.0,
                "cores": os.cpu_count(),
            },
            "rss_mb": _rss_mb(),
            "gc": {
                "start": list(cls._gc_start),
                "end": list(gc_now),
                "collections": gc_collections,
            },
            "threads": [{"name": t.name, "daemon": t.daemon, "alive": t.is_alive()}
                        for t in threading.enumerate()],
            "python": {"version": sys.version.split()[0],
                       "gil_enabled": (sys._is_gil_enabled()
                                       if hasattr(sys, "_is_gil_enabled") else None)},
            "samples": len(cls._rows),
        }
        # ── 分相归因（1.2）: 整帧数字回答不了"时间花在哪" ──
        phases = cls._phase_snapshot()
        if phases:
            summary["phases"] = phases
        try:
            with open(cls._path, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=1)
            print(f"[PerfStats] summary → {cls._path}")
        except OSError as exc:
            print(f"[PerfStats] cannot write summary: {exc}")
        cls._print_human(summary)

    @classmethod
    def _print_human(cls, s: dict) -> None:
        f = s.get("frames") or {}
        if not f:
            print("[PerfStats] no frame samples")
            return
        stalls = f.get("stalls") or {}
        print(f"[PerfStats] {s['duration_s']:.1f}s | avg {f.get('avg_fps')} fps "
              f"({f.get('mean_ms')} ms) | p50 {f.get('p50_ms')} "
              f"p95 {f.get('p95_ms')} p99 {f.get('p99_ms')} max {f.get('max_ms')} ms")
        print(f"[PerfStats] stalls >16.7ms {stalls.get('16')}  >33.3ms {stalls.get('33')}  "
              f">50ms {stalls.get('50')}  >100ms {stalls.get('100')} "
              f"(of {f.get('window_frames')} frames)")
        print(f"[PerfStats] cpu {s['cpu']['process_s']}s "
              f"({s['cpu']['pct_of_one_core']}% of one core) | rss {s.get('rss_mb')} MB")
