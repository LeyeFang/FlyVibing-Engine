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

from dataclasses import dataclass
from typing import Callable, Union
import traceback

from Application.Core.Engine import Engine, RendererType, WindowType
from Application.Core.Events.EngineEvent import EngineLifecycleEvent
from Application.Core.Window.Window import Window
from Application.Core.Renderer.Renderer import Renderer

# PIE READY 屏障等待上限 (秒) — 章 T M2 (threading_protocol.md 谓词)
_READY_TIMEOUT = 15.0


@dataclass
class RuntimeHostBridge:
    """宿主（编辑器 PIE / 独立播放器）向运行时注入的可选回调。

    运行时据此保持对宿主零反向依赖；独立运行时不注入（全部为 None）:
      - frame_sync:            共享帧同步对象（PIE 与编辑器同步; 独立运行 None）
      - sync_scene_from_host:  启动前把宿主场景状态同步进运行时（PIE; 独立运行 None）
      - protected_entity_ids:  停止时保留的实体集合（编辑器拥有的摄像机等; None = 全部清理）
      - clear_color:           运行首帧前注入的清屏色 (r,g,b,a) — 工程背景色;
                               None = 渲染器默认 (Overlay 透明模式由 OverlayInputLayer 自行设置)
    """

    frame_sync: object | None = None
    sync_scene_from_host: Callable[[], None] | None = None
    protected_entity_ids: Callable[[], set] | None = None
    clear_color: 'tuple[float, float, float, float] | None' = None


class GameRuntime(Engine):
    """游戏运行时 — 可被编辑器管理（PIE）或独立运行（导出）。"""

    # ── 宿主桥接（PIE/编辑器注入; 独立运行保持 None — 零反向依赖）──
    _host_bridge: 'RuntimeHostBridge | None' = None
    # 逻辑线程限帧 (章 T M2): 实测无限制时 ~63kHz busy-spin — 240 保低延迟且不烧核
    logic_target_fps: float = 240.0

    @classmethod
    def set_host_bridge(cls, bridge: 'RuntimeHostBridge') -> None:
        """注入宿主桥接（编辑器 PIE 启动前调用）。"""
        cls._host_bridge = bridge

    @classmethod
    def clear_host_bridge(cls) -> None:
        """清除宿主桥接（PIE 停止后调用）。"""
        cls._host_bridge = None

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
    def _create_renderer(cls, engine=None) -> Renderer:
        """创建运行时渲染器 — 每次调用返回独立实例，与 Editor 完全隔离。"""
        cls.window.MakeContextCurrent()
        renderer_cls = cls._get_renderer_class(cls.renderer_type)
        return renderer_cls.Create(window=cls.window, engine=engine or cls)

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
        # ── 宿主注入的背景色: renderer_ready 后、首帧前入队 ──
        #    PIE init 不阻塞 renderer_ready（避免 poll 回调死锁）→ 此处显式等待，
        #    命令在首个 StartFrame 被消费 → 第一帧清屏色即正确。
        bridge = cls._host_bridge
        if bridge is not None and bridge.clear_color is not None:
            cls._state()['renderer_ready'].wait(timeout=5.0)
            if cls.renderer is not None:
                from Application.Core.Renderer.RenderCommand import SetClearColorCommand
                _cr, _cg, _cb, _ca = (float(c) for c in bridge.clear_color)
                cls.renderer.enqueue(SetClearColorCommand(_cr, _cg, _cb, _ca))
        # ── 宿主桥接（PIE）: 启动前同步宿主场景 + 共享帧同步 ──
        #    独立运行无桥接 → 全部跳过（对 Editor 零反向依赖）
        try:
            if bridge is not None and bridge.sync_scene_from_host is not None:
                # ★ 章 T M2: 失败不再吞错 — 抛错→清理→调用方置错误态
                bridge.sync_scene_from_host()
            # ── Overlay 模式: 透明背景由 OverlayInputLayer.OnAttach 设置 ──
            # (OnAttach 在渲染线程创建渲染器后、首帧前调用，保证确定性)
            # ── 帧同步: PIE 作为 slave, 等待 Editor 每帧完成后再渲染 ──
            if bridge is not None and bridge.frame_sync is not None:
                cls._frame_sync = bridge.frame_sync  # 共享同一个 FrameSync
                cls._is_frame_sync_master = False
            # ── 启动设备 I/O 线程 ──
            from Application.Functions.SerialParallelDevice import start as spd_start
            spd_start()
            # ── 清理上次运行可能残留的 EEG 会话（异常退出保护）──
            try:  # 设备层缺省时跳过（可选组件）
                from Application.Functions.EEGDevice import close_all

                close_all()
            except Exception:  # noqa: BLE001
                pass
            # ── 清理上次运行可能残留的 epoch 数据集（同一安全网）──
            try:
                from Application.Functions.BCIAlgorithm import reset_all as epoch_reset
                epoch_reset()
            except Exception:
                pass
            # ── ★ READY 屏障 (章 T M2): 等全部 Layer.OnAttach 完成 = 内容注册完毕 ──
            #    同步失败/挂起 → 显式抛错（调用方置错误态），不再静默进入"半加载"运行
            if not cls._state()['layers_attached'].wait(timeout=_READY_TIMEOUT):
                raise RuntimeError(
                    f"GameRuntime layers not attached within {_READY_TIMEOUT}s — "
                    "content registration stalled (see threading_protocol.md)"
                )
        except Exception as e:
            # 显式失败: 清理半初始化运行时后上抛 (禁止吞错 — threading_protocol.md §2)
            print(f"[GameRuntime] START FAILED: {type(e).__name__}: {e}")
            try:
                cls.stop()
            except Exception:
                traceback.print_exc()
            raise
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
        from Application.Functions.SerialParallelDevice import start as spd_start
        spd_start()
        EngineLifecycleEvent.Pack(stage="start", message="Started in export mode", engine=cls)
        super().run()

    # ════════════════════════════════════════════════════════════
    # 控制接口 (PIE)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def stop(cls) -> None:
        """请求停止 Runtime 并清理状态，允许再次 start()。"""
        # ── 停止设备 I/O 线程 ──
        from Application.Functions.SerialParallelDevice import stop as spd_stop
        spd_stop()
        # ── 清理 Runtime 实体（保留宿主保护实体）──
        if cls.scene is not None:
            # ★ 保护实体由宿主注入（编辑器摄像机等）; 独立运行默认空集 → 全部清理
            protected: set[str] = set()
            bridge = cls._host_bridge
            if bridge is not None and bridge.protected_entity_ids is not None:
                try:
                    protected = {str(x) for x in bridge.protected_entity_ids()}
                except Exception as e:
                    print(f"[GameRuntime] host protected_entity_ids failed: {e}")
            # ★ 使用 SceneManager.DeleteEntity 递归删除子实体，
            #    避免 esper.delete_entity 裸删导致子实体泄露
            for eid_str in list(cls.scene.entities.keys()):
                if eid_str in protected:
                    continue
                cls.scene.DeleteEntity(int(eid_str))
            cls.scene.entities.clear()
            cls.scene._entity_names.clear()
            cls.scene._entity_parent.clear()
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
        # ★ 清除隔离子类缓存 — 确保下次 start() 创建全新的 GL 资源
        cls._isolated_renderer_cls = None
        cls._isolated_renderer_type = None
        # ── 脱离帧同步 ──
        cls._frame_sync = None
        cls._is_frame_sync_master = False
        # ── 最后的安全网: 关闭所有仍存活的 EEG 会话（不保存）──
        #    图内 Stop/Kill 设备节点已在 OnGameStop 链路执行完毕;
        #    此处兜底处理图里没有 Kill 节点 / 异常路径的情况。
        try:  # 设备层缺省时跳过（可选组件）
            from Application.Functions.EEGDevice import close_all

            _closed = close_all()
            if _closed:
                print(f"[GameRuntime] device safety: closed {_closed} leftover session(s)")
        except Exception:  # noqa: BLE001
            pass
        # ── epoch 数据集安全网（同一兜底语义）──
        try:
            from Application.Functions.BCIAlgorithm import reset_all as epoch_reset
            _n = epoch_reset()
            if _n:
                print(f"[GameRuntime] Epoch safety: cleared {_n} leftover dataset(s)")
        except Exception:
            pass

    @classmethod
    def is_running(cls) -> bool:
        """Runtime 是否仍在运行。"""
        if not cls.run_state:
            return False
        r = cls.renderer_thread
        l = cls._logic_thread
        return (r is not None and r.is_alive()) or (l is not None and l.is_alive())
