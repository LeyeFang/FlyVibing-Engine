import time
from collections import deque
from typing import Optional

from Application.Core.Events.StatsEvent import PerformanceStatsEvent


tik_tok_time = time.perf_counter()
def tic():
    global tik_tok_time
    tik_tok_time = time.perf_counter()


def toc():
    global tik_tok_time
    return time.perf_counter() - tik_tok_time


def sleep(time_in_s: float):
    start_time = time.perf_counter()
    # time.sleep(time_in_s)
    while (time.perf_counter()-start_time) < time_in_s:
        pass


def GetRunTime():
    return time.perf_counter() - FrameProfiler._start_time


class FrameProfiler:
    # 类变量（全局状态）
    _interval: float = 1.0                 # 上报间隔（秒）
    _window_size: int = 1500               # 滑动窗口大小（保留最近1500帧）
    _frame_times_ms: Optional[deque] = None   # 存储帧耗时（毫秒）
    _last_tick_time: Optional[float] = None   # 上一帧的时间点
    _last_report_time: float = 0.0            # 上次上报的时间点
    _frame_count_since_report: int = 0        # 本区间内累计帧数
    _is_started: bool = False                 # 是否已调用 Start
    _start_time: float = 0.0

    @classmethod
    def Init(
        cls
    ) -> None:
        pass

    @classmethod
    def Start(
        cls,
        interval: float = 1.0,
        window_size: int = 1000
    ) -> None:
        """
        初始化性能分析器（在进入主循环前调用一次）
        :param interval:     统计上报间隔（秒），默认 1 秒
        :param window_size:  保存最近多少帧用于百分位计算，默认 1500
        """
        cls._interval = interval
        cls._window_size = window_size
        cls._frame_times_ms = deque(maxlen=window_size)
        cls._last_tick_time = None
        cls._last_report_time = time.perf_counter()
        cls._next_report_time = 3
        cls._frame_count_since_report = 0
        cls._start_time = time.perf_counter()
        cls._is_started = True

    @classmethod
    def Tick(
        cls
    ) -> None:
        """
        每帧调用一次（在游戏循环的每帧末尾调用）。
        记录帧耗时，并每隔 interval 秒计算并上报 1% low / 10% low 数据。
        """
        if not cls._is_started:
            return  # 未初始化，忽略
        now = time.perf_counter()
        # 计算本帧耗时（毫秒）
        if cls._last_tick_time is not None:
            dt_ms = (now - cls._last_tick_time) * 1000.0
            if dt_ms > 0:
                cls._frame_times_ms.append(dt_ms)
        cls._last_tick_time = now
        cls._frame_count_since_report += 1
        # 判断是否需要上报
        if now - cls._start_time >= cls._next_report_time:
            elapsed = now - cls._last_report_time
            cls._report_and_reset(now, elapsed)
            cls._next_report_time += 1
            cls._last_report_time = now

    @classmethod
    def _report_and_reset(
        cls,
        now: float,
        elapsed: float
    ) -> None:
        """计算百分位数据，通过事件发送，然后重置区间计数器（不清除窗口）"""
        # 1. 平均 FPS（本区间内）
        avg_fps = cls._frame_count_since_report / elapsed
        # 2. 1% low 和 10% low 帧时间（毫秒）
        p1_ms, p10_ms = cls._compute_percentiles()
        # 转换为 FPS
        p1_fps = 1000.0 / p1_ms if p1_ms > 0 else 0.0
        p10_fps = 1000.0 / p10_ms if p10_ms > 0 else 0.0
        # 3. 发送事件（你可以根据需要调整参数格式）
        #    方案A：发送一个包含所有统计信息的字典
        PerformanceStatsEvent.Pack(
            fps=avg_fps,
            p10_low_fps=p10_fps,
            p1_low_fps=p1_fps,
        )
        # 方案B（如果你希望保持旧的简单接口，只发送 1% low FPS）：
        # PerformanceStatsEvent.Pack(p1_fps)
        # 重置区间计数器（窗口数据保留）
        cls._frame_count_since_report = 0

    @classmethod
    def _compute_percentiles(
        cls
    ) -> tuple[float, float]:
        """
        对当前窗口内的帧时间升序排序，返回 (1% low 帧时间ms, 10% low 帧时间ms)
        若窗口不足 2 帧，返回 (0, 0)
        """
        if cls._frame_times_ms is None or len(cls._frame_times_ms) < 2:
            return 0.0, 0.0
        frames = list(cls._frame_times_ms)
        frames.sort()  # 升序
        n = len(frames)
        # 1% low → 第 99% 分位点（最差的那 1% 帧的上限）
        idx_p1 = min(int(0.99 * n), n - 1)
        # 10% low → 第 90% 分位点
        idx_p10 = min(int(0.90 * n), n - 1)
        return frames[idx_p1], frames[idx_p10]

    # ---------- 可选：调试用 ----------
    @classmethod
    def GetCurrentStats(cls) -> dict:
        """立即返回当前统计（用于调试，不触发上报）"""
        p1_ms, p10_ms = cls._compute_percentiles()
        return {
            "window_frames": len(cls._frame_times_ms) if cls._frame_times_ms else 0,
            "p1_low_ms": p1_ms,
            "p10_low_ms": p10_ms,
            "p1_low_fps": 1000.0 / p1_ms if p1_ms > 0 else 0.0,
            "p10_low_fps": 1000.0 / p10_ms if p10_ms > 0 else 0.0,
        }


FrameProfiler._start_time = time.perf_counter()
