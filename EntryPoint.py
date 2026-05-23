import sys

from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer

Application.Create(window_type='GLFW')

if sys.version_info[:2] == (3, 12):
    from Application.Core.Layers.ImguiLayer import ImguiLayer
    Application.PushLayer(ImguiLayer)
Application.PushLayer(DebugLayer)

Application.Run()
