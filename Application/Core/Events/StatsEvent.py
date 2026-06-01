from Application.Core.Events.Event import Event


class PerformanceStatsEvent(Event):

    fps: float = 0
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        fps: float,
        frame_time_std_ms: float,
        p1_low_fps: float
    ) -> None:
        cls.fps = fps
        cls.log_info = f"Average FPS={fps:.2f}, 1%-low-StdDev={frame_time_std_ms:.2f}ms, 1%-low-FPS={p1_low_fps:.2f}"
        super().Pack()

    @classmethod
    def Unpack(
        cls
    ) -> float:
        return cls.fps
