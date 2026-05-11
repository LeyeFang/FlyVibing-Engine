from Application.Core.Events.Event import Event


class PerformanceStatsEvent(Event):

    fps: float = 0
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        fps: float,
        p10_low_fps: float,
        p1_low_fps: float
    ) -> None:
        cls.fps = fps
        cls.log_info = f"Average FPS={fps:.2f}, 10%-low-FPS={p10_low_fps:.2f}, 1%-low-FPS={p1_low_fps:.2f}"
        super().Pack()

    @classmethod
    def Unpack(
        cls
    ) -> float:
        return cls.fps
