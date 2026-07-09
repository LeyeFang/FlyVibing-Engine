"""
GameRuntime — 游戏运行时（Engine 子类）。

两种启动模式:
  start() — 非阻塞 (PIE)
             逻辑跑在独立线程，编辑器控制生命周期。
  run()   — 阻塞 (导出/独立运行)
             逻辑跑在主线程。

上下文隔离:
  GameRuntime 通过 type() 动态创建渲染器子类，使其类变量
  (registered_entities、_pick_fbo 等) 与编辑器完全隔离，
  避免同一进程内不同 GL 上下文之间 GPU 句柄互相覆盖。
"""

from __future__ import annotations

from typing import Union

from Application.Core.Engine import Engine, RendererType, WindowType
from Application.Core.Events.EngineEvent import EngineLifecycleEvent
from Application.Core.Window.Window import Window
from Application.Core.Renderer.Renderer import Renderer


class GameRuntime(Engine):
    """游戏运行时 — 可被编辑器管理（PIE）或独立运行（导出）。"""

    # ── 缓存的隔离渲染器子类 ──
    _isolated_renderer_cls: type = None
    _isolated_renderer_type = None

    # ════════════════════════════════════════════════════════════
    # 工厂方法
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls) -> Window:
        """创建运行时窗口 — 独立的 GLFW 子窗口 (OpenGL 上下文)。"""
        from Application.Runtime.RuntimeWindow import RuntimeWindow
        RuntimeWindow.Create()
        return RuntimeWindow

    @classmethod
    def _create_renderer(cls) -> Renderer:
        """创建运行时渲染器 — 使用动态子类隔离 Editor 和 GameRuntime 的类变量。

        背景:
          所有渲染器类 (OpenGLRenderer / ZenGLRenderer) 使用 @classmethod 单例，
          GPU 句柄 (_pick_fbo)、资源注册表 (registered_entities)、
          命令队列 (_command_queue) 等全部存储在类变量中。

          如果 Editor 和 GameRuntime 直接共用同一个渲染器类，
          一方创建/销毁 GPU 资源会覆盖另一方的句柄，
          在不同 OpenGL 上下文之间产生悬空引用或状态污染。

        解决方案:
          通过 type() 动态创建渲染器基类的无状态子类。
          新子类继承所有方法，但类变量写入独立的 __dict__，
          与编辑器的渲染器类完全隔离。
        """
        cls.window.MakeContextCurrent()
        renderer_base = cls._get_renderer_class(cls.renderer_type)

        # ── 检查缓存的隔离子类是否仍匹配当前后端 ──
        if (cls._isolated_renderer_type != cls.renderer_type
                or cls._isolated_renderer_cls is None):
            iso_name = f'Runtime_{renderer_base.__name__}'
            iso_cls = type(iso_name, (renderer_base,), {})

            # 将基类 MRO 中所有可变容器类变量拷贝到子类的 __dict__
            # （dict/list/set 在 Python 中是引用类型，
            #   不拷贝会导致子类与父类共享同一个容器对象）
            _mutable = (dict, list, set)
            for base in renderer_base.__mro__:
                for k, v in base.__dict__.items():
                    if k.startswith('__'):
                        continue
                    if isinstance(v, _mutable) and k not in iso_cls.__dict__:
                        setattr(iso_cls, k, type(v)())

            cls._isolated_renderer_cls = iso_cls
            cls._isolated_renderer_type = cls.renderer_type

        renderer = cls._isolated_renderer_cls.Create(window=cls.window)

        # ── 重置从 Editor 继承的 GPU 句柄 (int 类型, 动态子类不会自动拷贝) ──
        #     PostProcess 的 FBO、shader、config 在 Editor 的 GL 上下文中创建,
        #     对 GameRuntime 的独立 GL 上下文无效。清零后 _render_highlight 会自动跳过。
        _iso = cls._isolated_renderer_cls
        _iso._highlight_config = None
        _iso._highlight_enabled = False
        for _attr in (
            '_pp_fbo', '_pp_color_tex', '_pp_id_tex', '_pp_ds_rbo',
            '_pp_edge_tex', '_pp_edge_fbo',
            '_pp_mrt_prog', '_pp_edge_prog', '_pp_composite_prog',
            '_pp_quad_vao', '_pp_fbo_w', '_pp_fbo_h',
        ):
            setattr(_iso, _attr, 0)

        return renderer

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def start(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> 'GameRuntime':
        """非阻塞启动 (PIE 模式)。"""
        cls._state()['_logic_thread_enabled'] = True
        cls.init(window_type=window_type, renderer_type=renderer_type)
        # ── 帧同步: PIE 作为 slave, 等待 Editor 每帧完成后再渲染 ──
        from Application.Editor.EditorHost import EditorHost
        if EditorHost._frame_sync is not None:
            cls._frame_sync = EditorHost._frame_sync  # 共享同一个 FrameSync
            cls._is_frame_sync_master = False
        EngineLifecycleEvent.Pack(stage="start", message="Started in PIE mode", engine=cls)
        return cls

    @classmethod
    def run(
        cls,
        window_type: Union[WindowType, str] = WindowType.GLFW,
        renderer_type: Union[RendererType, str] = RendererType.OpenGL,
    ) -> None:
        """阻塞启动 (导出模式)。"""
        cls.init(window_type=window_type, renderer_type=renderer_type)
        EngineLifecycleEvent.Pack(stage="start", message="Started in export mode", engine=cls)
        super().run()

    # ════════════════════════════════════════════════════════════
    # 控制接口 (PIE)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def stop(cls) -> None:
        """请求停止 Runtime 并清理状态，允许再次 start()。"""
        # 必须在 run_state=False 之前派发事件 —
        # 否则渲染线程的 finally 块会先清空 layer_stack，DebugLayer 收不到事件。
        EngineLifecycleEvent.Pack(stage="stop", message="Stopped and cleaned up", engine=cls)
        cls.run_state = False
        cls._join_threads()
        if cls.window is not None:
            try:
                cls.window.Therminate()
            except Exception:
                pass
        cls._state()['_initialized'] = False
        cls._state()['_logic_thread_enabled'] = False
        cls._state()['layer_stack'].clear()
        # 重置时间，避免下次 start() 前 push_layer 的 OnAttach 拿到旧时间
        cls._state()['_elapsed_time'] = 0.0
        cls._state()['_delta_time'] = 0.0
        cls.window = None
        cls.renderer = None
        cls.renderer_thread = None
        cls._logic_thread = None
        # ── 脱离帧同步 ──
        cls._frame_sync = None
        cls._is_frame_sync_master = False

    @classmethod
    def is_running(cls) -> bool:
        """Runtime 是否仍在运行。"""
        if not cls.run_state:
            return False
        r = cls.renderer_thread
        l = cls._logic_thread
        return (r is not None and r.is_alive()) or (l is not None and l.is_alive())
