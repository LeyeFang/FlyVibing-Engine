"""
Engine — 引擎核心运行时。

职责（最小内核）:
  - 持有 Window / Renderer 抽象引用（不关心具体子类）
  - 管理层栈 (LayerStack)
  - 管理渲染线程
  - 事件分发（主线程内部 pub-sub，不跨线程边界）
  - 提供全局单例访问

Engine 不做的事:
  - 不创建具体窗口类型（子类工厂方法）
  - 不创建具体渲染器类型（子类工厂方法）
  - 不持有 EditorWindow / EditorRenderer（EditorHost 的职责）
  - 不在 OnEvent 中调用 Renderer（RHI 后渲染器只接收 Command）

继承层次:
  Engine              ← 核心运行时
    ├── EditorHost     ← 编辑器宿主（强制 OpenGL + 加载 EditorPlugin）
    └── GameRuntime    ← 游戏运行时（干净打包，不含任何 Editor 模块）
"""

from __future__ import annotations

from enum import Enum
from typing import Union
import threading
from threading import Thread

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event, BindPackCallback, _register_engine, _is_first_bind
from Application.Core.Events.WindowEvent import WindowCloseEvent
from Application.Core.Input.InputState import InputState, _set_default_input_state
from Application.Core.Window.Window import Window
from Application.Core.Renderer.Renderer import Renderer
from Application.Core.Scene.SceneManager import SceneManager
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Stats.FrameProfiler import FrameProfiler


# ════════════════════════════════════════════════════════════════
# 枚举 — 所有渲染/窗口后端的类型标签
# ════════════════════════════════════════════════════════════════

class RendererType(Enum):
    OpenGL = "OpenGL"
    ZenGL = "ZenGL"
    Vulkan = "Vulkan"


class WindowType(Enum):
    GLFW = "GLFW"
    SDL2 = "SDL2"


# ════════════════════════════════════════════════════════════════
# Engine — 核心运行时
# ════════════════════════════════════════════════════════════════

class Engine:
    """引擎核心运行时 — 单例，所有方法均为 @classmethod。

    子类必须覆写:
      - _create_window()    → 返回 Window 实例
      - _create_renderer()  → 返回 Renderer 实例
    """

    # ── 枚举快捷方式（方便外部 import） ─────────────────────────
    RendererType = RendererType
    WindowType = WindowType

    # ── Per-subclass 状态注册表 ────────────────────────────────
    # 每个 Engine 子类（EditorHost / GameRuntime）拥有独立的状态字典。
    # 避免 layer_stack / renderer_ready 等可变类变量在子类间意外共享。
    _registry: dict[str, dict] = {}

    @classmethod
    def _state(cls) -> dict:
        """返回当前子类的私有状态字典。

        只有「可变且通过继承共享会有问题」的变量存入此字典。
        对于通过 cls.x = val 赋值即可自然隔离的变量（window、renderer、run_state 等），
        仍使用类变量方式，不需进 _state()。
        """
        name = cls.__name__
        if name not in cls._registry:
            cls._registry[name] = {
                '_initialized': False,
                'layer_stack': [],
                'renderer_ready': threading.Event(),
                'run_ready': threading.Event(),
                # True = 逻辑线程模式 (PIE: start() 非阻塞)
                # False = 内联模式 (导出/编辑器: run() 阻塞)
                '_logic_thread_enabled': False,
                # 输入状态 (InputState 实例, 由 _get_input_state 延迟创建)
                '_input_state': None,
            }
        return cls._registry[name]

    # ── 类变量默认值（通过 cls.x = val 写入子类 __dict__，天然隔离） ──
    window: Window = None
    renderer: Renderer = None
    window_type: WindowType = None
    renderer_type: RendererType = None
    run_state: bool = True
    renderer_thread: Thread | None = None
    _logic_thread: Thread | None = None
    target_frame_time: float = 0.0
    _instance: 'Engine' = None

    # ════════════════════════════════════════════════════════════
    # 工厂方法（子类覆写）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls) -> Window:
        """创建窗口 — 子类覆写以决定窗口类型。

        EditorHost 覆写 → 创建 EditorWindow (OpenGL 上下文)
        GameRuntime 覆写 → 创建 RuntimeWindow (可由用户选择 GL/Vulkan)
        """
        raise NotImplementedError(
            f"{cls.__name__} must override _create_window()"
        )

    @classmethod
    def _create_renderer(cls) -> Renderer:
        """创建渲染器 — 子类覆写以决定渲染后端。

        EditorHost 覆写 → openGLRenderer (ImGui 兼容)
        GameRuntime 覆写 → 用户选择的后端
        """
        raise NotImplementedError(
            f"{cls.__name__} must override _create_renderer()"
        )

    @classmethod
    def _get_renderer_class(
        cls,
        renderer_type: RendererType
    ):
        """根据 RendererType 返回对应的 Renderer 类。

        这是一个便利方法，子类的 _create_renderer 可以调用它。
        延迟导入以避免循环依赖。
        """
        if renderer_type == RendererType.OpenGL:
            from Application.Core.Renderer.OpenGL.openGLRenderer import openGLRenderer
            return openGLRenderer
        elif renderer_type == RendererType.ZenGL:
            from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer
            return ZenGLRenderer
        elif renderer_type == RendererType.Vulkan:
            from Application.Core.Renderer.Vulkan.vulkanRenderer import vulkanRenderer
            return vulkanRenderer
        else:
            raise ValueError(f"Unknown renderer type: {renderer_type}")

    @classmethod
    def _get_input_state(cls) -> InputState:
        """返回当前 Engine 的 InputState 实例（延迟创建）。"""
        st = cls._state()
        if st['_input_state'] is None:
            st['_input_state'] = InputState()
        return st['_input_state']

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def init(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> 'Engine':
        """初始化引擎核心 — 创建窗口 + 启动渲染线程。

        Args:
            window_type:   窗口后端类型 (WindowType.GLFW 或 'GLFW')
            renderer_type: 渲染后端类型 (RendererType.OpenGL 或 'OpenGL')

        Returns:
            Engine 类自身（用于链式调用）

        流程:
          1. 规范化枚举参数
          2. 绑定事件回调 → Engine.OnEvent
          3. 初始化 ResourceManager / SceneManager
          4. 调用子类 _create_window() 创建窗口
          5. 启动渲染线程
          6. 阻塞等待渲染器初始化完成
        """
        if cls._state()['_initialized']:
            return cls
        # 1. 规范化枚举
        if isinstance(window_type, str):
            window_type = WindowType(window_type)
        if isinstance(renderer_type, str):
            renderer_type = RendererType(renderer_type)
        cls.window_type = window_type
        cls.renderer_type = renderer_type
        # 2. 绑定事件回调 — 注册到 Event 的 Engine 回调注册表
        #    首次初始化的 Engine 同时设置全局回退还（兼容旧代码）
        _register_engine(cls)
        if _is_first_bind():
            BindPackCallback(cls._on_event)
            # 首个 Engine 设为默认 InputState（供模块级便利函数读取）
            _set_default_input_state(cls._get_input_state())
        # 3. 初始化子系统
        ResourceManager.Init(cls)
        SceneManager.Init(cls)
        # 4. 创建窗口（子类决定窗口类型）
        cls.window = cls._create_window()
        cls.window._engine = cls  # 窗口知道谁拥有它，事件路由到正确的 Engine
        # 5. 启动渲染线程
        cls.run_state = True
        cls.renderer_thread = Thread(target=cls._render_loop, daemon=True)
        cls.renderer_thread.start()
        # 5b. 如果启用逻辑线程模式，一并启动
        if cls._state()['_logic_thread_enabled']:
            cls._logic_thread = Thread(target=cls._logic_loop, daemon=True)
            cls._logic_thread.start()
        # 6. 等待渲染线程准备好
        cls._state()['renderer_ready'].wait()
        cls._instance = cls
        cls._state()['_initialized'] = True
        return cls

    @classmethod
    def run(cls) -> None:
        """主循环 — 阻塞，直到引擎结束。

        逻辑线程模式 (PIE)：_logic_loop 已在后台运行，此处等待线程结束。
        内联模式 (导出/编辑器)：在本线程上直接跑逻辑循环。
        """
        if cls._state()['_logic_thread_enabled']:
            # 逻辑已在后台线程跑，只需等待 + 清理
            cls._join_threads()
            cls.shutdown()
        else:
            # 传统行为：在调用线程上跑逻辑循环
            cls._state()['run_ready'].set()
            try:
                while cls.run_state:
                    cls.window.Update()
                    for layer in cls._state()['layer_stack']:
                        layer.OnUpdate()
                        if not cls.run_state:
                            break
            finally:
                cls.shutdown()

    @classmethod
    def _logic_loop(cls) -> None:
        """逻辑循环 — 独立线程运行 (PIE 模式)。"""
        cls._state()['run_ready'].set()
        while cls.run_state:
            cls.window.Update()
            for layer in cls._state()['layer_stack']:
                layer.OnUpdate()
                if not cls.run_state:
                    break

    @classmethod
    def shutdown(cls) -> None:
        """引擎关闭 — 逆序清理资源。"""
        cls.run_state = False
        # 等待渲染线程退出
        if cls._logic_thread is not None and cls._logic_thread.is_alive():
            cls._logic_thread.join(timeout=1.0)
        # 等待渲染线程退出
        if cls.renderer_thread is not None and cls.renderer_thread.is_alive():
            cls.renderer_thread.join(timeout=2.0)
        # 逆序 detach 层
        for layer in reversed(cls._state()['layer_stack']):
            try:
                layer.OnDetach()
            except Exception:
                pass
        cls._state()['layer_stack'].clear()
        # 清理窗口
        if cls.window is not None:
            try:
                cls.window.Therminate()
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════
    # 层栈管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def push_layer(
        cls,
        layer: Layer
    ) -> None:
        """推入一个 Layer 到栈顶。
        Layer.OnAttach() 在渲染线程的 run_ready 之后统一调用，
        不在 push 时立即调用（保持与现有行为一致）。
        """
        cls._state()['layer_stack'].append(layer)

    @classmethod
    def pop_layer(
        cls,
        layer: Layer
    ) -> None:
        """从栈顶弹出 Layer。"""
        if layer in cls._state()['layer_stack']:
            cls._state()['layer_stack'].remove(layer)
            layer.OnDetach()

    # ════════════════════════════════════════════════════════════
    # 事件分发（主线程内部）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _on_event(
        cls,
        event: Event
    ) -> None:
        """全局事件回调 — 由 Event.Pack() 触发。

        分发优先级:
          1. Layer 栈（从栈顶到栈底，允许上层拦截）
          2. Window（窗口级别事件）

        注意: 不再主动调用 Renderer.OnEvent。
              未来 RHI 化后，渲染器只接收 RenderCommand。
        """
        if event is None:
            return
        # 1. Layer 事件传播（从栈顶到栈底）
        for layer in reversed(cls._state()['layer_stack']):
            if event.consumed:
                break
            layer.OnEvent(event)
        # 2. Window 事件
        if cls.window is not None:
            cls.window.OnEvent(event)
        # 3. 全局终止事件
        if isinstance(event, WindowCloseEvent):
            cls.run_state = False

    # ════════════════════════════════════════════════════════════
    # 渲染线程
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _render_loop(cls) -> None:
        """渲染线程入口 — 创建渲染器 → 等待 run_ready → 进入渲染循环。
        流程:
          1. 创建渲染器（子类决定具体类型）
          2. 设置 renderer_ready 事件
          3. 等待 run_ready（主线程调用 run() 时设置）
          4. 调用所有 Layer.OnAttach()
          5. 进入渲染循环: StartFrame → Layer.OnRender → EndFrame → SwapBuffer
        """
        try:
            # 1. 创建渲染器（包含 GPU 上下文初始化和资源加载）
            cls.renderer = cls._create_renderer()
            # 2. 通知主线程：渲染器已就绪
            cls._state()['renderer_ready'].set()
            # 3. 等待主线程发令开始
            cls._state()['run_ready'].wait()
            # 4. 层初始化（在渲染线程，GL 上下文可用）
            for layer in cls._state()['layer_stack']:
                layer.OnAttach()
            # 5. 启动帧性能分析器
            FrameProfiler.Start(1)
            # 6. 渲染主循环
            while cls.run_state:
                cls._render_one_frame()
        except Exception as e:
            # 渲染线程异常 — 设置 run_state=False 让主线程退出
            cls.run_state = False
            raise e

    @classmethod
    def _render_one_frame(
        cls
    ) -> None:
        """渲染一帧 — 子类可覆写以扩展（如 EditorHost 在 EndFrame 后加 ImGui 绘制）。"""
        renderer = cls.renderer
        window = cls.window
        # ── 帧开始 ──
        renderer.StartFrame()
        # ── 层渲染 ──
        for layer in cls._state()['layer_stack']:
            layer.OnRender()
        # ── 帧结束 ──
        renderer.EndFrame()
        # ── 交换缓冲区 (OpenGL/ZenGL 需要; Vulkan 由 SwapChain 管理) ──
        if cls.renderer_type in (RendererType.OpenGL, RendererType.ZenGL):
            window.SwapBuffer()
        # ── 性能统计 ──
        FrameProfiler.Tick()

    # ════════════════════════════════════════════════════════════
    # 全局访问入口
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _join_threads(cls) -> None:
        """等待逻辑线程和渲染线程退出。"""
        if cls._logic_thread is not None and cls._logic_thread.is_alive():
            cls._logic_thread.join(timeout=2.0)
        if cls.renderer_thread is not None and cls.renderer_thread.is_alive():
            cls.renderer_thread.join(timeout=2.0)

    @classmethod
    def get(cls) -> 'Engine':
        """获取引擎单例 — 返回当前子类或最近初始化的 Engine 子类。"""
        # 优先返回当前子类的 _instance（如 EditorHost.get()）
        my_instance = cls.__dict__.get('_instance')
        if my_instance is not None:
            return my_instance
        # 回退：扫描 registry 找第一个已初始化的子类
        for name, st in cls._registry.items():
            if st.get('_initialized') and name != 'Engine':
                return st.get('_instance') or cls
        # 再回退：检查 Engine 自己的 _instance
        if cls._instance is not None:
            return cls._instance
        raise RuntimeError(
            "Engine not initialized. Call Engine.init() or a subclass init() first."
        )

    @classmethod
    def get_window(cls) -> Window:
        """获取当前窗口。"""
        return cls.window

    @classmethod
    def get_renderer(cls) -> Renderer:
        """获取当前渲染器。"""
        return cls.renderer

    @classmethod
    def get_window_backend(cls) -> WindowType:
        """获取窗口后端类型。"""
        return cls.window_type

    @classmethod
    def get_renderer_backend(cls) -> RendererType:
        """获取渲染后端类型。"""
        return cls.renderer_type

    @classmethod
    def set_target_frame(cls, frame: int) -> None:
        """设置目标帧率（0 = 不限）。"""
        cls.target_frame_time = float(1.0 / frame) if frame > 0 else 0.0
