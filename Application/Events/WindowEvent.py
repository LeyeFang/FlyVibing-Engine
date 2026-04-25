from Application.Events.Event import Event


class WindowCloseEvent(Event):
    ...


class WindowResizeEvent(Event):

    width: int = None
    height: int = None

    @classmethod
    def Pack(
        cls,
        width: int,
        height: int
    ) -> None:
        cls.width = width
        cls.height = height

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return cls.width, cls.height
