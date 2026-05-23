from Application.Core.Layers.Layer import Layer


class BCILayer(Layer):

    device = None

    @classmethod
    def OnAttach(cls):
        return super().OnAttach()

    @classmethod
    def OnDetach(cls):
        return super().OnDetach()

    @classmethod
    def OnUpdate(cls):
        return super().OnUpdate()

    @classmethod
    def OnEvent(cls, event):
        return super().OnEvent(event)

