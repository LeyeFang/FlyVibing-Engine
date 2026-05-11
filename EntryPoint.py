from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer


Application.Create(window_type='GLFW')
Application.PushLayer(DebugLayer)
Application.Run()
