from abc import ABC, abstractmethod

# from Application import Application


class Window(ABC):

    app = None
    window = None

    @classmethod
    @abstractmethod
    def Create(cls, app):
        ...

    @classmethod
    @abstractmethod
    def Update(cls):
        ...

    @classmethod
    @abstractmethod
    def Therminate(cls):
        ...

    @classmethod
    @abstractmethod
    def GetSize(cls):
        ...

    @classmethod
    @abstractmethod
    def OnEvent(cls):
        ...
