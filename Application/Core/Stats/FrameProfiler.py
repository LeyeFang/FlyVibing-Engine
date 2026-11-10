import time
import math
import threading
from collections import deque
from typing import Optional, TYPE_CHECKING

from Application.Core.Events.StatsEvent import PerformanceStatsEvent
from Application.Core.Timer.Timer import ResetStartTime

if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class FrameProfiler:
    """每 Engine 独立的帧性能分析器。

    由 Engine._get_profiler() 创建并持有。
    每个 Engine 的渲染线程各自调用 tick()，互不干扰。
    """

    def __init__(self, engine: 'Engine' = None) -> None:
        self._engine = engine          # 所属 Engine（用于 PerformanceStatsEvent 路由）
        self._interval: float = 1.0
        self._window_size: int = 1000
        self._frame_times_ms: Optional[deque] = None
        self._last_tick_time: Optional[float] = None
        self._last_report_time: float = 0.0
        self._frame_count_since_report: int = 0
        self._is_started: bool = False
        self._start_time: float = 0.0
        self._next_report_time: float = 3.0
        # ★ 读写锁: tick() 在渲染线程 append，而统计消费方（成品 stats 层 /
        #   renderer.snapshot op）在主线程读 —— 2026-11-10 加锁前用 `list(deque)`
        #   取值会撞 "deque mutated during iteration"。
        self._lock = threading.Lock()

    def start(
        self,
        interval: float = 1.0,
        window_size: int = 1000
    ) -> None:
        """初始化性能分析器（在进入渲染循环前调用一次）。"""
        with self._lock:
            self._interval = interval
            self._window_size = window_size
            self._frame_times_ms = deque(maxlen=window_size)
        self._last_tick_time = None
        self._last_report_time = time.perf_counter()
        self._next_report_time = 3
        self._frame_count_since_report = 0
        self._start_time = time.perf_counter()
        self._is_started = True
        ResetStartTime()

    def stop(self) -> None:
        """停止采样（渲染线程退出时调用；可再次 start() 复用同一实例）。

        为什么要显式 stop: `Engine._render_loop` 的 finally 分支一直调用
        `self._get_profiler().stop()`，但本类此前没有该方法 —— 调用被
        try/except 吞掉，`_is_started` 永远为 True。二次 init（PIE 重跑 /
        编辑器重启引擎）时旧窗口的帧时间仍混在 deque 里，`p1_low` 看起来
        异常差且无法解释。
        """
        self._is_started = False
        self._last_tick_time = None
        with self._lock:
            if self._frame_times_ms is not None:
                self._frame_times_ms.clear()

    def tick(
        self
    ) -> None:
        """每帧调用一次，记录帧耗时并周期性上报。"""
        if not self._is_started:
            return
        now = time.perf_counter()
        if self._last_tick_time is not None:
            dt_ms = (now - self._last_tick_time) * 1000.0
            if dt_ms > 0:
                with self._lock:
                    if self._frame_times_ms is not None:
                        self._frame_times_ms.append(dt_ms)
        self._last_tick_time = now
        self._frame_count_since_report += 1
        if now - self._start_time >= self._next_report_time:
            elapsed = now - self._last_report_time
            self._report_and_reset(now, elapsed)
            self._next_report_time += 1
            self._last_report_time = now

    def _report_and_reset(
        self,
        now: float,
        elapsed: float
    ) -> None:
        """计算百分位数据并通过事件上报。"""
        avg_fps = self._frame_count_since_report / elapsed
        p1_ms = self._compute_percentile_1p()
        p1_fps = 1000.0 / p1_ms if p1_ms > 0 else 0.0
        std_ms = self._compute_1p_low_std()
        # 上报时指定所属 Engine，使事件正确路由
        PerformanceStatsEvent.Pack(
            fps=avg_fps,
            frame_time_std_ms=std_ms,
            p1_low_fps=p1_fps,
            engine=self._engine,
        )
        self._frame_count_since_report = 0

    def _frames_snapshot(
        self
    ) -> list[float]:
        """线程安全地取一份帧时间副本（已排序）。"""
        with self._lock:
            if not self._frame_times_ms:
                return []
            return sorted(self._frame_times_ms)

    def _compute_percentile_1p(
        self
    ) -> float:
        """返回 1% low 帧时间（毫秒）。"""
        frames = self._frames_snapshot()
        if len(frames) < 2:
            return 0.0
        n = len(frames)
        idx_p1 = min(int(0.99 * n), n - 1)
        return frames[idx_p1]

    def _compute_1p_low_std(
        self
    ) -> float:
        """返回最差 1% 帧时间的标准差（毫秒）。"""
        frames = self._frames_snapshot()
        if len(frames) < 2:
            return 0.0
        n = len(frames)
        idx_p1 = min(int(0.99 * n), n - 1)
        worst_frames = frames[idx_p1:]
        k = len(worst_frames)
        if k < 2:
            return 0.0
        mean = sum(worst_frames) / k
        variance = sum((x - mean) ** 2 for x in worst_frames) / k
        return math.sqrt(variance)

    def get_current_stats(self) -> dict:
        """立即返回当前统计（调试用，不触发上报）。"""
        p1_ms = self._compute_percentile_1p()
        std_ms = self._compute_1p_low_std()
        with self._lock:
            count = len(self._frame_times_ms) if self._frame_times_ms else 0
        return {
            "window_frames": count,
            "p1_low_ms": p1_ms,
            "frame_time_std_ms": std_ms,
            "p1_low_fps": 1000.0 / p1_ms if p1_ms > 0 else 0.0,
        }

    # ── 成品统计（导出游戏 / --stats-json 消费）──────────────

    def snapshot_stats(self) -> dict:
        """返回**完整**帧时间分布（线程安全，不触发上报）。

        与 `get_current_stats()` 的区别: 后者只是 3 个兼容字段，看不出是
        "均匀慢" 还是 "偶发卡顿"。成品导出后离线看不懂帧率分布，就是这里缺的。

        Returns:
            {
              "frames": int,            窗口内帧数（= min(总量, window_size)）
              "mean_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms",
              "p1_low_ms", "p1_low_fps", "avg_fps",
              "std_ms",
              "stalls": {"16": n, "33": n, "50": n, "100": n},  # 超过阈值的帧数
              "window_size": int,
            }
        """
        frames = self._frames_snapshot()
        n = len(frames)
        out = {
            "window_size": int(self._window_size),
            "window_frames": n,
            "mean_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0,
            "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0,
            "p1_low_ms": 0.0, "p1_low_fps": 0.0, "avg_fps": 0.0,
            "std_ms": 0.0,
            "stalls": {"16": 0, "33": 0, "50": 0, "100": 0},
        }
        if n == 0:
            return out

        def _pct(q: float) -> float:
            return frames[min(int(q * (n - 1)), n - 1)]

        mean = sum(frames) / n
        p1_ms = _pct(0.99)
        out.update({
            "mean_ms": round(mean, 3),
            "p50_ms": round(_pct(0.50), 3),
            "p90_ms": round(_pct(0.90), 3),
            "p95_ms": round(_pct(0.95), 3),
            "p99_ms": round(p1_ms, 3),
            "max_ms": round(frames[-1], 3),
            "p1_low_ms": round(p1_ms, 3),
            "p1_low_fps": round(1000.0 / p1_ms, 1) if p1_ms > 0 else 0.0,
            "avg_fps": round(1000.0 / mean, 1) if mean > 0 else 0.0,
            "std_ms": round(math.sqrt(sum((x - mean) ** 2 for x in frames) / n), 3),
            "stalls": {
                "16": sum(1 for x in frames if x > 16.7),
                "33": sum(1 for x in frames if x > 33.3),
                "50": sum(1 for x in frames if x > 50.0),
                "100": sum(1 for x in frames if x > 100.0),
            },
        })
        return out
