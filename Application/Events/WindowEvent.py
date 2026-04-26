from Application.Events.Event import Event


class WindowCloseEvent(Event):

    log_info = "Window Close !!"

    @classmethod
    def Pack(cls):
        super().Pack()


class WindowResizeEvent(Event):

    width: int = None
    height: int = None
    log_info = f"Window Size: (width, height) = ({width}, {height})"

    @classmethod
    def Pack(
        cls,
        width: int,
        height: int
    ) -> None:
        cls.width = width
        cls.height = height
        cls.log_info = f"Window Size: (width, height) = ({width}, {height})"
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return cls.width, cls.height
