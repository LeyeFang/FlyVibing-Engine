from __future__ import annotations
from typing import TYPE_CHECKING
from abc import ABC, abstractmethod

from Application.Core.Events.Event import Event
if TYPE_CHECKING:
    from Application.Application import Application


class Layer(ABC):

    app: Application

    @classmethod
    @abstractmethod
    def OnAttach(
        cls
    ):
        cls.app = Application.GetApplication()

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

