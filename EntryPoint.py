from Application.Application import Application
from Application.Layers.DebugLayer import DebugLayer


Application.Create()
Application.PushLayer(DebugLayer)
Application.Run()
