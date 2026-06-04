from Application.Core.Timer.Timer import GetRunTime

from abc import ABCMeta, abstractmethod
from typing import Any


app_callback_func: callable = None


class MetaEvent(ABCMeta):
    """元类：让 Event 的子类在 print 时显示其 log_info"""

    def __str__(cls):
        """print(event) 会调用 str(event)，即此方法。"""
        log_info = getattr(cls, 'log_info', None)
        if log_info:
            return f"Time: {GetRunTime():.4f}, Event: {cls.__name__}, {log_info}"
        return f"Time: {GetRunTime():.4f}, Event: {cls.__name__}"

    def __repr__(cls):
        return cls.__str__()


class Event(metaclass=MetaEvent):

    log_info: str

    @classmethod
    @abstractmethod
    def Pack(
        cls
    ) -> None:
        app_callback_func(cls)

    @classmethod
    @abstractmethod
    def UnPack(cls) -> Any:
        ...


def BindPackCallback(
    cb_func: callable
):
    global app_callback_func
    app_callback_func = cb_func
