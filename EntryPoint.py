from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer
from Application.Core.Layers.ImguiLayer import ImguiLayer


Application.Create(window_type='GLFW')
Application.PushLayer(ImguiLayer)
Application.PushLayer(DebugLayer)
Application.Run()
