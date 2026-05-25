import sys

from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer

Application.Create(renderer_type='ModernGL')

print(sys.version_info[:2])
if sys.version_info[:2] == (3, 12):
    from Application.Core.Layers.ImguiLayer import ImguiLayer
    Application.PushLayer(ImguiLayer)
Application.PushLayer(DebugLayer)

Application.Run()
