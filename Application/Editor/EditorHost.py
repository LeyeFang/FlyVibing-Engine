"""
EditorHost — 编辑器宿主（Engine 子类）。

职责:
  - 覆写 Engine 工厂方法: 创建 EditorWindow + openGLRenderer
  - 加载 EditorPlugin（编辑器功能包）
  - 提供编辑器全局便利 API (get_editor_window / get_editor_renderer)
  - 过渡期: 桥接 Event → Renderer（RHI 化后移除）

与 Engine 的关系:
  Engine       — 抽象模板（窗口+渲染器+层栈+渲染线程的通用逻辑）
  EditorHost   — 编辑器特化（继承 Engine, 填入编辑器具体类）
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING

from Application.Core.Engine import Engine
from Application.Core.Events.Event import Event
from Application.Core.Window.Window import Window
from Application.Core.Renderer.Renderer import Renderer
from Application.Core.Plugin import Plugin

if TYPE_CHECKING:
    from Application.Editor.EditorWindow import EditorWindow


class EditorHost(Engine):
    """编辑器宿主 — 继承 Engine, 特化为编辑器模式。

    覆写的工厂方法:
      - _create_window()    → EditorWindow (GLFW + OpenGL 上下文)
      - _create_renderer()  → openGLRenderer
    """

    # ── 编辑器专属状态 ──────────────────────────────────────────
    _editor_plugin: Plugin | None = None

    # ── 编辑器窗口/渲染器 (由 _create_window / _create_renderer 显式赋值) ──
    # Engine 基类用 window/renderer 管理生命周期，
    # editor_window/editor_renderer 是编辑器特化的稳定访问点，
    # 保证不管哪个子类调 init()，这两个属性始终可用。
    editor_window: 'EditorWindow' = None
    editor_renderer: Renderer = None

    # ════════════════════════════════════════════════════════════
    # 工厂方法（Engine 要求子类覆写）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls) -> 'EditorWindow':
        """创建编辑器窗口 (GLFW + OpenGL 上下文)。

        同时赋值 EditorHost.editor_window — 提供不依赖子类的稳定访问点。
        """
        from Application.Editor.EditorWindow import EditorWindow
        EditorHost.editor_window = EditorWindow.Create()
        return EditorHost.editor_window

    @classmethod
    def _create_renderer(cls) -> Renderer:
        """创建编辑器渲染器 — 根据 cls.renderer_type 选择后端。

        同时赋值 EditorHost.editor_renderer — 提供不依赖子类的稳定访问点。
        """
        cls.window.MakeContextCurrent()
        renderer_cls = cls._get_renderer_class(cls.renderer_type)
        EditorHost.editor_renderer = renderer_cls.Create()
        return EditorHost.editor_renderer

    # ════════════════════════════════════════════════════════════
    # 事件分发（过渡期: 桥接到 Renderer）
    # ════════════════════════════════════════════════════════════
    @classmethod
    def _on_event(cls, event: Event) -> None:
        """编辑器事件分发 — 额外桥接 Renderer.OnEvent。

        TODO: RHI 化后删除 renderer.OnEvent 调用。
              渲染器将通过 Command Queue 接收 resize/camera 更新。
        """
        # Engine 标准分发: Layer → Window
        super()._on_event(event)
        # 过渡期: 桥接 Renderer（处理 WindowResizeEvent 等）
        if cls.renderer is not None and not event.consumed:
            cls.renderer.OnEvent(event)

    # ════════════════════════════════════════════════════════════
    # 插件管理
    # ════════════════════════════════════════════════════════════
    @classmethod
    def load_plugin(cls, plugin: Plugin) -> None:
        """加载编辑器插件。

        调用时机: EditorHost.init() 之后、EditorHost.run() 之前。

        流程:
          1. 调用 plugin.on_load(engine) — 插件初始化
          2. 遍历 plugin.get_layers() — push 到引擎层栈

        Args:
            plugin: 插件实例 (如 EditorPlugin())
        """
        # 1. 插件初始化（主线程）
        plugin.on_load(cls)
        # 2. 推入插件拥有的 Layer
        for layer_cls in plugin.get_layers():
            cls.push_layer(layer_cls)
        cls._editor_plugin = plugin
        print(f"[EditorHost] Plugin loaded: {plugin.name} v{plugin.version}")

    @classmethod
    def unload_plugin(cls) -> None:
        """卸载编辑器插件（引擎关闭时自动调用）。"""
        if cls._editor_plugin is not None:
            cls._editor_plugin.on_unload()
            cls._editor_plugin = None

    # ════════════════════════════════════════════════════════════
    # 编辑器全局 API
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_editor_window(cls) -> 'EditorWindow':
        """获取编辑器窗口 — 返回 EditorHost.editor_window (不进子类查找)。"""
        return EditorHost.editor_window

    @classmethod
    def get_editor_renderer(cls) -> Renderer:
        """获取编辑器渲染器 — 返回 EditorHost.editor_renderer (不进子类查找)。"""
        return EditorHost.editor_renderer
