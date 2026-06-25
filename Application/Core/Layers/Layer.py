from __future__ import annotations
from typing import TYPE_CHECKING
from abc import ABC, abstractmethod

from Application.Core.Events.Event import Event
if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class Layer(ABC):

    app: 'Engine'

    @classmethod
    @abstractmethod
    def OnAttach(
        cls
    ):
        from Application.Core.Engine import Engine
        cls.app = Engine.get()

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
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        pass

    @classmethod
    @abstractmethod
    def OnRender(
        cls
    ) -> None:
        pass

