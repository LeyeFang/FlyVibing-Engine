from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer


Application.Create(window_type='SDL2')
Application.PushLayer(DebugLayer)
Application.Run()
