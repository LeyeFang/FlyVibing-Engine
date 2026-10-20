import sys
import os

# 确保工作区根目录在 sys.path 中（因为入口脚本在 Application/ 子目录下）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Application.Editor.EditorHost import EditorHost
from Application.Editor.EditorModule import EditorModule
from Application.Editor.StartupOptions import apply_startup_options


try:
    apply_startup_options()
except Exception as e:  # noqa: BLE001 — 启动参数错误应快速失败，不带着错误设置启动
    print(f"[Startup] invalid options: {e}")
    raise SystemExit(2)


EditorHost.init(window_type='GLFW', renderer_type='OpenGL')

EditorHost.load_module(EditorModule())

EditorHost.run()
