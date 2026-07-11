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

from Application.Core.Engine import Engine, FrameSync
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import EngineLifecycleEvent
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
    _active_scene: object | None = None     # 当前编辑的 Scene 对象
    _scenes: dict[str, object] = {}          # name → Scene (所有已创建的场景)

    # ── 编辑器窗口/渲染器 (由 _create_window / _create_renderer 显式赋值) ──
    # Engine 基类用 window/renderer 管理生命周期，
    # editor_window/editor_renderer 是编辑器特化的稳定访问点，
    # 保证不管哪个子类调 init()，这两个属性始终可用。
    editor_window: 'EditorWindow' = None
    editor_renderer: Renderer = None

    # ════════════════════════════════════════════════════════════
    # 场景管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_active_scene(cls) -> object | None:
        """返回当前编辑的 Scene 对象。"""
        return cls._active_scene

    @classmethod
    def set_active_scene(cls, scene: object) -> None:
        """设置当前编辑的 Scene 对象。"""
        cls._active_scene = scene

    @classmethod
    def list_scenes(cls) -> list[str]:
        """返回所有已创建场景的名称列表。"""
        # 合并 EditorHost._scenes 和 SceneManager 中的场景名
        names = set(cls._scenes.keys())
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            st = SceneManager._state_for(cls.__name__)
            names.update(st.scene.keys())
        except Exception:
            pass
        return sorted(names)

    @classmethod
    def create_scene(cls, name: str) -> object:
        """创建新场景并设为活跃。返回 Scene 对象。"""
        from Application.Core.Scene.Scene import Scene
        scene = Scene(name=name)
        cls._scenes[name] = scene
        if cls._active_scene is None:
            cls._active_scene = scene
        # 同步到 SceneManager
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            cls.scene.scene[name] = name
        except Exception:
            pass
        return scene

    @classmethod
    def switch_scene(cls, name: str) -> bool:
        """切换到指定名称的场景。返回是否成功。"""
        if name in cls._scenes:
            cls._active_scene = cls._scenes[name]
            return True
        return False

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
    def _create_renderer(cls, engine=None) -> Renderer:
        """创建编辑器渲染器。"""
        cls.window.MakeContextCurrent()
        renderer_cls = cls._get_renderer_class(cls.renderer_type)
        EditorHost.editor_renderer = renderer_cls.Create(window=cls.window, engine=engine or cls)
        return EditorHost.editor_renderer

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def init(cls, window_type='GLFW', renderer_type='ZenGL') -> 'EditorHost':
        """初始化编辑器 — 同时建立帧同步（Editor 是 master）。"""
        super().init(window_type=window_type, renderer_type=renderer_type)
        # ── 帧同步: Editor 是 master, PIE 是 slave ──
        cls._frame_sync = FrameSync()
        cls._is_frame_sync_master = True
        return cls

    # ════════════════════════════════════════════════════════════
    # 事件分发（过渡期: 桥接到 Renderer）
    # ════════════════════════════════════════════════════════════
    @classmethod
    def _on_event(cls, event: Event) -> None:
        """编辑器事件分发 — 全部经由 Layer 栈处理。

        Renderer 已完全解耦 Event 系统，仅通过 Command Queue 接收指令。
        """
        super()._on_event(event)

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
        EngineLifecycleEvent.Pack(
            stage="plugin",
            message=f"Plugin loaded: {plugin.name} v{plugin.version}",
            engine=cls
        )

    @classmethod
    def unload_plugin(cls) -> None:
        """卸载编辑器插件（引擎关闭时自动调用）。"""
        if cls._editor_plugin is not None:
            cls._editor_plugin.on_unload()
            cls._editor_plugin = None

    @classmethod
    def _unload_plugin(cls) -> None:
        """Engine.shutdown() 回调 — 卸载编辑器插件。"""
        cls.unload_plugin()

    # ════════════════════════════════════════════════════════════
    # 关闭流程（覆写 Engine.shutdown）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def shutdown(cls) -> None:
        """编辑器关闭 — 先停止 PIE，再走标准清理流程。

        必须先行停止 GameRuntime，因为：
        1. EditorWindow.Therminate() 会调用 glfw.terminate()，杀死所有 GLFW 窗口
        2. 若 Runtime 渲染线程还在跑，下一帧 SwapBuffer 会在已销毁的窗口上崩溃
        3. GameRuntime 的 GPU 资源 (Render Thread finally 块) 需要在 GLFW 存活时释放
        """
        # 1. 先行停止 PIE (如果正在运行)
        from Application.Runtime.GameRuntime import GameRuntime
        if GameRuntime._state().get('_initialized', False):
            EngineLifecycleEvent.Pack(
                stage="shutdown",
                message="Stopping PIE before editor shutdown",
                engine=cls
            )
            GameRuntime.stop()
            from Application.Editor.UI.controllers.SimulationController import SimulationController
            from Application.Editor.UI.controllers.SimulationController import SimulationState
            SimulationController._state = SimulationState.STOPPED
        # 2. 标准 Engine 关闭流程
        super().shutdown()

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
