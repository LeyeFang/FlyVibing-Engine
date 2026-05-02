from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application
from Application.Core.Renderer import Renderer

import vulkan as vk


class vulkanRenderer(Renderer):

    @classmethod
    def Create(
        cls,
        app: Application
    ) -> vulkanRenderer:
        pass

    @classmethod
    def Update(
        cls
    ) -> None:
        pass

    @classmethod
    def OnEvent(
        cls
    ) -> None:
        pass
