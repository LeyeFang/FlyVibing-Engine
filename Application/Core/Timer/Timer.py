import time

from Application.Core.Events.StatsEvent import PerformanceStatsEvent


start_time: float = 0
start_time_ns: int = 0
app_run_time: float = 0


def _start_timer(
) -> None:
    global start_time, start_time_ns
    start_time = time.perf_counter()
    start_time_ns = time.perf_counter_ns()


def GetRunTime(
) -> float:
    app_run_time = time.perf_counter()
    return app_run_time - start_time


def GetRunTimeNano(
) -> float:
    app_run_time = time.perf_counter_ns()
    return app_run_time - start_time_ns


class FrameProfiler:
    """无累积误差的帧率统计器（每帧调用 tick，每秒自动报告）"""
    def __init__(self, report_interval=1.0):
        self.interval = report_interval
        self.frame_count = 0
        self.last_report = time.perf_counter()
        self.fps = 0.0


    @classmethod
    def Start(
        cls,
        interval: float
    ) -> None:
        cls.interval = interval
        cls.frame_count = 0
        cls.need_report = 1
        cls.start_time = time.perf_counter()
        cls.fps = 0.0

    @classmethod
    def Tick(
        cls
    ) -> None:
        cls.frame_count += 1
        run_time = time.perf_counter() - cls.start_time
        if run_time >= cls.need_report:
            cls.fps = cls.frame_count
            PerformanceStatsEvent.Pack(cls.fps)
            cls.frame_count = 0
            cls.need_report += cls.interval
