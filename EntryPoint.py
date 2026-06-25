import sys

from Application.Editor.EditorHost import EditorHost
from Application.Editor.EditorPlugin import EditorPlugin


EditorHost.init(window_type='GLFW', renderer_type='OpenGL')

print(sys.version_info[:2])
EditorHost.load_plugin(EditorPlugin())

EditorHost.run()
