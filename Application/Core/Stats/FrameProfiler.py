import time
import math
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

    def start(
        self,
        interval: float = 1.0,
        window_size: int = 1000
    ) -> None:
        """初始化性能分析器（在进入渲染循环前调用一次）。"""
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

    def _compute_percentile_1p(
        self
    ) -> float:
        """返回 1% low 帧时间（毫秒）。"""
        if self._frame_times_ms is None or len(self._frame_times_ms) < 2:
            return 0.0
        frames = list(self._frame_times_ms)
        frames.sort()
        n = len(frames)
        idx_p1 = min(int(0.99 * n), n - 1)
        return frames[idx_p1]

    def _compute_1p_low_std(
        self
    ) -> float:
        """返回最差 1% 帧时间的标准差（毫秒）。"""
        if self._frame_times_ms is None or len(self._frame_times_ms) < 2:
            return 0.0
        frames = list(self._frame_times_ms)
        frames.sort()
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
        return {
            "window_frames": len(self._frame_times_ms) if self._frame_times_ms else 0,
            "p1_low_ms": p1_ms,
            "frame_time_std_ms": std_ms,
            "p1_low_fps": 1000.0 / p1_ms if p1_ms > 0 else 0.0,
        }
