from Application.Core.Events.Event import Event


class PerformanceStatsEvent(Event):
    """性能统计事件 — 携带 FPS / 帧时间标准差 / 1% Low。"""

    def __init__(self, fps: float, frame_time_std_ms: float, p1_low_fps: float) -> None:
        super().__init__()
        self.fps: float = fps
        self.frame_time_std_ms: float = frame_time_std_ms
        self.p1_low_fps: float = p1_low_fps

    @property
    def log_info(self) -> str:
        return (
            f"avgFPS={self.fps:.1f}, "
            f"1%-low-StdDev={self.frame_time_std_ms:.2f}ms, "
            f"1%-low={self.p1_low_fps:.1f}"
        )

    @classmethod
    def Pack(cls, fps: float, frame_time_std_ms: float, p1_low_fps: float) -> None:
        super().Pack(fps, frame_time_std_ms, p1_low_fps)

    def unpack(self) -> float:
        return self.fps
