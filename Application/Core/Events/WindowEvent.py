from Application.Core.Events.Event import Event


class WindowCloseEvent(Event):
    """窗口关闭信号 — 无数据负载。"""

    def __init__(self) -> None:
        super().__init__()

    @property
    def log_info(self) -> str:
        return "Window Close !!"

    @classmethod
    def Pack(cls) -> None:
        super().Pack()


class WindowResizeEvent(Event):
    """窗口尺寸变更 — 携带新宽高。"""

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self.width: int = width
        self.height: int = height

    @property
    def log_info(self) -> str:
        return f"Window Size: (width, height) = ({self.width}, {self.height})"

    @classmethod
    def Pack(cls, width: int, height: int) -> None:
        super().Pack(width, height)

    def unpack(self) -> tuple[int, int]:
        return self.width, self.height
