from Application.Core.Layers.Layer import Layer

import dearpygui.dearpygui as dpg


class ImguiLayer(Layer):
    @classmethod
    def OnAttach(cls):
        return super().OnAttach()

    @classmethod
    def OnDetach(cls):
        return super().OnDetach()

    @classmethod
    def OnEvent(cls, event):
        return super().OnEvent(event)

    @classmethod
    def OnUpdate(cls):
        return super().OnUpdate()
