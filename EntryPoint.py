import sys

from Application.Application import Application
from Application.Core.Layers.DebugLayer import DebugLayer
from Application.Editor.ImguiLayer import ImguiLayer


Application.Create(renderer_type='ModernGL')

print(sys.version_info[:2])
Application.PushLayer(ImguiLayer)
Application.PushLayer(DebugLayer)

Application.Run()
