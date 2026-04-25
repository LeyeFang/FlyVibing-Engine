from abc import ABC, abstractmethod

from Application.Events.Event import Event


class Renderer(ABC):

    app = None
    drawable_obj = []

    @classmethod
    @abstractmethod
    def Create(cls):
        pass

    @classmethod
    @abstractmethod
    def CreateMesh(cls):
        ...

    @classmethod
    @abstractmethod
    def StartFrame(cls):
        ...

    @classmethod
    @abstractmethod
    def EndFrame(cls):
        ...

    @classmethod
    @abstractmethod
    def OnEvent(
        cls,
        event: Event
    ):
        ...
