from Application.Events.Event import Event


class PerformanceStatsEvent(Event):

    fps: float = 0
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        fps: float
    ) -> None:
        cls.fps = fps
        cls.log_info = f"Avg FPS: {fps:.2f}"
        super().Pack()

    @classmethod
    def Unpack(
        cls
    ) -> float:
        return cls.fps
