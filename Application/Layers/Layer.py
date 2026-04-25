from abc import ABC, abstractmethod
from Application.Events.Event import Event


class Layer(ABC):
    @classmethod
    @abstractmethod
    def OnAttach(
        cls,
        app
    ):
        pass

    @classmethod
    @abstractmethod
    def OnDetach(cls):
        pass

    @classmethod
    @abstractmethod
    def OnUpdate(cls):
        pass

    @classmethod
    @abstractmethod
    def OnMessage(cls):
        pass

    @classmethod
    @abstractmethod
    def OnEvent(
        cls,
        event: Event
    ):
        pass
