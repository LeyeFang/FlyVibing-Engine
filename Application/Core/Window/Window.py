from __future__ import annotations
from Application import Application
from Application.Core.Events.Event import Event

from abc import ABC, abstractmethod


class Window(ABC):

    app = None
    window = None

    @classmethod
    @abstractmethod
    def Create(cls, app: Application):
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
    def OnEvent(cls, event: Event):
        ...
