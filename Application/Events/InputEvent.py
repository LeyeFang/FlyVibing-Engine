from Application.Events.Event import Event


class MouseMoveEvent(Event):
    pos_x: int = 0
    pos_y: int = 0

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return cls.pos_x, cls.pos_y


class MouseButtonEvent(Event):
    botton: int = 0
    state: int = 0

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return


class KeyboardButtonEvent(Event):

    key: int = 0

    @classmethod
    def UnPack(
        cls
    ) -> tuple[int]:
        return
