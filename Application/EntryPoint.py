import sys
import os

# 确保工作区根目录在 sys.path 中（因为入口脚本在 Application/ 子目录下）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Application.Editor.EditorHost import EditorHost
from Application.Editor.EditorModule import EditorModule


EditorHost.init(window_type='GLFW', renderer_type='OpenGL')


EditorHost.load_module(EditorModule())

EditorHost.run()
