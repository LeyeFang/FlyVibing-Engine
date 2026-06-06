import sys

from Application.Application import Application
from Test.DebugLayer import DebugLayer
from Application.Editor.EditorLayer import EditorLayer


Application.Create(renderer_type='ModernGL')

print(sys.version_info[:2])
Application.PushLayer(EditorLayer)
Application.PushLayer(DebugLayer)

Application.Run()
