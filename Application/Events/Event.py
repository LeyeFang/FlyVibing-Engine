from abc import ABCMeta, abstractmethod


class MetaEvent(ABCMeta):
    """元类：让 Event 的子类在 print 时显示其 log_info"""

    def __str__(cls):
        # 优先返回子类中定义的 log_info
        log_info = getattr(cls, 'log_info', None)
        if log_info is not None:
            return log_info
        # 如果子类没有定义 log_info，则回退到默认表示
        return super().__str__()

    def __repr__(cls):
        log_info = getattr(cls, 'log_info', None)
        if log_info is not None:
            return f"{log_info}"
        return super().__repr__()


class Event(metaclass=MetaEvent):

    log_info: str

    @classmethod
    @abstractmethod
    def Pack():
        ...

    @classmethod
    @abstractmethod
    def UnPack(cls):
        ...
