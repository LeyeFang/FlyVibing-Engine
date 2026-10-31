from Application.Core.Events.Event import Event


class WindowCloseEvent(Event):
    """窗口关闭信号 — 无数据负载。

    source: "window"（标题栏关闭/系统退出）或 "escape"（ESC 释放触发的安全关闭）。
    RuntimeInputLayer 可据此只拦截 ESC，而不影响用户点关闭按钮。
    """

    def __init__(self, source: str = "window") -> None:
        super().__init__()
        self.source: str = str(source or "window")

    @property
    def log_info(self) -> str:
        return f"Window Close !! (source={self.source})"

    @classmethod
    def Pack(cls, source: str = "window", **kwargs) -> None:
        super().Pack(source=source, **kwargs)


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
    def Pack(cls, width: int, height: int, **kwargs) -> None:
        super().Pack(width, height, **kwargs)

    def unpack(self) -> tuple[int, int]:
        return self.width, self.height
