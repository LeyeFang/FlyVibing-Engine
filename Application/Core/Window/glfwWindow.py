from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.InputEvent import *
from Application.Core.Window.Window import Window
from Application.Core.Renderer.RenderCommand import ResizeCommand
from Application.Core.Input.InputPipeline import InputPipeline

from enum import Enum
import ctypes
from ctypes import wintypes
import glfw


# ═══════════════════════════════════════════════════════════════
# WindowMode — 窗口显示模式
# ═══════════════════════════════════════════════════════════════

class WindowMode(Enum):
    """窗口显示模式。

    WINDOWED   — 普通窗口，有标题栏和边框，可拖拽缩放
    BORDERLESS — 无边框窗口，覆盖整个显示器 (全屏窗口化)
    FULLSCREEN — 独占全屏模式 (切换显示分辨率)
    """
    WINDOWED = "windowed"
    BORDERLESS = "borderless"
    FULLSCREEN = "fullscreen"


# ═══════════════════════════════════════════════════════════════
# Win32 API — 透明窗口 + 鼠标穿透
# ═══════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32

_GWL_EXSTYLE = -20
_GWL_STYLE = -16
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_HWND_TOPMOST = -1

# Win32 窗口样式 — 用于剥离/恢复标题栏和边框 (保持 WS_OVERLAPPED 以兼容 DWM 玻璃效果)
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_SYSMENU = 0x00080000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_CHROME_MASK = _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX

_SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED

_user32.GetWindowLongPtrW.restype = ctypes.c_longlong
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetWindowLongPtrW.restype = ctypes.c_longlong
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]


def _win32_add_style(hwnd: int, style_bit: int) -> bool:
    """添加 Win32 扩展窗口样式。返回 True 表示状态变更。"""
    s = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    if s & style_bit:
        return False
    _user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, s | style_bit)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)
    return True


def _win32_remove_style(hwnd: int, style_bit: int) -> bool:
    """移除 Win32 扩展窗口样式。返回 True 表示状态变更。"""
    s = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    if not (s & style_bit):
        return False
    _user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, s & ~style_bit)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)
    return True


def _win32_has_style(hwnd: int, style_bit: int) -> bool:
    """检查 Win32 扩展窗口样式是否已设置。"""
    return bool(_user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE) & style_bit)


def _win32_set_topmost(hwnd: int) -> None:
    """将窗口置顶 (HWND_TOPMOST) — 不含 SWP_NOZORDER，必须改变 z-order。"""
    _user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
                         _SWP_FLAGS & ~0x0004)  # 去掉 SWP_NOZORDER


def _win32_strip_chrome(hwnd: int) -> None:
    """剥离标题栏和边框 — 仅修改样式，不改变窗口尺寸。"""
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style & ~_WS_CHROME_MASK)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)


def _win32_restore_chrome(hwnd: int) -> None:
    """恢复标题栏和边框 — 仅修改样式，不改变窗口尺寸。"""
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style | _WS_CHROME_MASK)
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)


# ═══════════════════════════════════════════════════════════════
# glfwWindow
# ═══════════════════════════════════════════════════════════════

class glfwWindow(Window):

    glfw_window = None

    # ── 窗口模式标志 (子类在 Create 前设置) ──
    _transparent: bool = False    # 透明帧缓冲 (TRANSPARENT_FRAMEBUFFER + WS_EX_LAYERED)
    _topmost: bool = False        # 窗口置顶 (HWND_TOPMOST)
    _click_through: bool = False  # 每帧根据命中测试切换鼠标穿透 (WS_EX_TRANSPARENT)

    # ── 窗口显示模式 ──
    _window_mode: WindowMode = WindowMode.WINDOWED
    _saved_window_rect: tuple[int, int, int, int] | None = None  # (x, y, w, h) 用于退出全屏时恢复

    @classmethod
    def Create(
        cls
    ):
        cls.glfw_window = cls._create_window()
        glfw.set_window_size_callback(cls.glfw_window, cls._window_resize_event_callback)
        # ── 输入管线: GLFW 回调 + InputState + 拖拽/移动分流 ──
        cls._input_pipeline = InputPipeline(cls.glfw_window)
        cls._input_pipeline.on_key = cls._make_key_hook()
        cls._input_pipeline.on_mouse_button = cls._make_mouse_button_hook()
        cls._input_pipeline.on_drag = cls._make_drag_hook()
        cls._input_pipeline.on_move = cls._make_move_hook()
        cls._input_pipeline.on_scroll = cls._make_scroll_hook()
        return cls

    @classmethod
    def Update(
        cls
    ) -> None:
        # ── 点击穿透: 在 poll_events 之前根据命中测试切换 WS_EX_TRANSPARENT ──
        if cls._click_through and cls.glfw_window is not None:
            cls._update_click_through_state()
        glfw.poll_events()
        if glfw.window_should_close(cls.glfw_window):
            WindowCloseEvent.Pack(engine=cls._engine)

    @classmethod
    def GetSize(
        cls
    ) -> tuple[int, int]:
        return glfw.get_framebuffer_size(cls.glfw_window)

    @classmethod
    def SetTitle(cls, title: str) -> None:
        """设置窗口标题。"""
        if cls.glfw_window is not None:
            glfw.set_window_title(cls.glfw_window, title)

    @classmethod
    def GetNativeHandle(cls):
        """返回 GLFW 原生窗口句柄 (GLFWwindow 指针)。"""
        return cls.glfw_window

    @classmethod
    def Therminate(
        cls
    ):
        """销毁自身 GLFW 窗口。

        不调用 glfw.terminate() — 该操作由子类 (如 EditorWindow) 根据自身角色决定。
        RuntimeWindow / PreviewRuntimeWindow 不应终止整个 GLFW，
        因为编辑器窗口仍需要 GLFW 处于初始化状态。
        """
        if cls.glfw_window is not None:
            glfw.destroy_window(cls.glfw_window)
            cls.glfw_window = None

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if isinstance(event, WindowCloseEvent):
            pass

    # ════════════════════════════════════════════════════════════
    # 系统分辨率查询（GLFW 实现）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _get_system_resolution(cls) -> tuple[int, int]:
        """获取主显示器当前分辨率（通过 GLFW）。"""
        monitor = glfw.get_primary_monitor()
        if monitor is None:
            # 回退默认
            return 1920, 1080
        video_mode = glfw.get_video_mode(monitor)
        if video_mode is None:
            return 1920, 1080
        return video_mode.size.width, video_mode.size.height

    # ════════════════════════════════════════════════════════════
    # 窗口创建
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _create_window(cls):
        # 1. 初始化 GLFW
        if not glfw.init():
            print("无法初始化 GLFW")
            return
        # 2. 设置窗口提示 (子类重写 _set_window_hints)
        cls._set_window_hints()

        # ── 透明帧缓冲 (基类统一处理, 无需子类重复) ──
        if cls._transparent:
            if cls._window_mode == WindowMode.FULLSCREEN:
                print("[glfwWindow] WARNING: Transparent framebuffer is not supported "
                      "in exclusive fullscreen mode — use BORDERLESS for transparent overlay")
            else:
                glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)

        # ── BORDERLESS: 不用 GLFW 的 DECORATED=FALSE (会导致 WS_POPUP, DWM 不兼容)
        #    改为先创建正常窗口, 再用 Win32 剥离标题栏/边框 ——
        #    3. 取比当前显示器小一圈的常见分辨率（保持同比例）
        monitor = glfw.get_primary_monitor()
        sys_w, sys_h = cls._get_system_resolution()
        width, height = cls._compute_default_size()

        # ── 根据模式选择分辨率 + monitor 参数 ──
        if cls._window_mode == WindowMode.WINDOWED:
            # 普通窗口: 无 monitor
            use_monitor = None
        elif cls._window_mode == WindowMode.BORDERLESS:
            # 无边框全屏窗口化: 覆盖整个显示器, 无 monitor (窗口化)
            use_monitor = None
            width, height = sys_w, sys_h
        else:  # FULLSCREEN
            # 独占全屏: 使用主显示器
            use_monitor = monitor
            mode = glfw.get_video_mode(monitor)
            if mode is not None:
                width, height = mode.size.width, mode.size.height

        # 4. 创建窗口
        title = getattr(cls, '_window_title', 'MyGameEngine')
        glfw_window = glfw.create_window(
            width, height, title, use_monitor, None,
        )
        if not glfw_window:
            print("无法创建窗口")
            glfw.terminate()
            return

        # ── 无边框窗口定位到 (0,0) + 剥离 chrome ──
        if cls._window_mode == WindowMode.BORDERLESS:
            glfw.set_window_pos(glfw_window, 0, 0)

        # ── 保存初始窗口矩形 (用于退出全屏/无边框时恢复) ──
        if cls._window_mode == WindowMode.BORDERLESS:
            # 无边框启动时保存默认窗口尺寸 (非全屏分辨率), 切回 Windowed 时用
            dw, dh = cls._compute_default_size()
            cls._saved_window_rect = (100, 100, dw, dh)
        elif cls._window_mode != WindowMode.FULLSCREEN:
            x, y = glfw.get_window_pos(glfw_window)
            cls._saved_window_rect = (x, y, width, height)

        # ── BORDERLESS: Win32 剥离标题栏/边框 (保持 WS_OVERLAPPED 兼容 DWM) ──
        if cls._window_mode == WindowMode.BORDERLESS:
            hwnd = glfw.get_win32_window(glfw_window)
            _win32_strip_chrome(hwnd)

        print(f"[glfwWindow] Created: {width}x{height} mode={cls._window_mode.value}")

        # ── 透明窗口 Win32 设置 ──
        if cls._transparent:
            hwnd = glfw.get_win32_window(glfw_window)
            _win32_add_style(hwnd, _WS_EX_LAYERED)
            if cls._click_through:
                _win32_add_style(hwnd, _WS_EX_TRANSPARENT)
            print(f"[glfwWindow] Transparent window: LAYERED + "
                  f"TRANSPARENT={'ON' if cls._click_through else 'OFF'}")

        # ── 置顶 ──
        if cls._topmost:
            hwnd = glfw.get_win32_window(glfw_window)
            _win32_set_topmost(hwnd)
            print("[glfwWindow] Window set to TOPMOST")

        # 释放当前线程的 GL 上下文 — 渲染线程会通过 MakeContextCurrent 接管
        glfw.make_context_current(None)
        return glfw_window

    @classmethod
    def _set_window_hints(
        cls
    ) -> None:
        """子类重写以设置 GLFW 窗口提示 (OpenGL 上下文 / Vulkan NO_API 等)。

        默认不做任何设置，由 EditorWindow (OpenGL) 或 PreviewRuntimeWindow (Vulkan)
        等子类根据需要覆盖。
        """
        pass

    # ════════════════════════════════════════════════════════════
    # 窗口模式切换 (运行时)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_window_mode(cls) -> WindowMode:
        """返回当前窗口显示模式。"""
        return cls._window_mode

    @classmethod
    def set_window_mode(cls, mode: WindowMode) -> None:
        """运行时切换窗口显示模式。

        切换逻辑:
          WINDOWED → FULLSCREEN: 保存当前位置/尺寸, 切换到主显示器独占全屏
          FULLSCREEN → WINDOWED: 恢复到之前保存的位置/尺寸
          WINDOWED → BORDERLESS: 保存当前位置/尺寸, 去掉边框, 覆盖整个显示器
          BORDERLESS → WINDOWED: 恢复边框, 恢复到之前保存的位置/尺寸

        无边框 (BORDERLESS) 与 WINDOWED 之间通过 set_window_attrib(DECORATED) + set_window_size 切换，
        不重建窗口。独占全屏 (FULLSCREEN) 通过 set_window_monitor 切换。
        """
        if mode == cls._window_mode:
            return
        if cls.glfw_window is None:
            print("[glfwWindow] set_window_mode: no window created yet — setting flag only")
            cls._window_mode = mode
            return

        prev = cls._window_mode
        monitor = glfw.get_primary_monitor()
        sys_w, sys_h = cls._get_system_resolution()

        if mode == WindowMode.FULLSCREEN:
            # ── 进入独占全屏 ──
            # 保存当前窗口矩形 (如果之前是窗口模式)
            if prev != WindowMode.FULLSCREEN:
                cls._saved_window_rect = cls._get_current_rect()
            vmode = glfw.get_video_mode(monitor)
            if vmode is not None:
                glfw.set_window_monitor(
                    cls.glfw_window, monitor,
                    0, 0, vmode.size.width, vmode.size.height,
                    vmode.refresh_rate,
                )

        elif mode == WindowMode.WINDOWED:
            if prev == WindowMode.FULLSCREEN:
                # ── 退出独占全屏 → 恢复窗口 ──
                r = cls._saved_window_rect or (100, 100, 800, 600)
                glfw.set_window_monitor(cls.glfw_window, None, r[0], r[1], r[2], r[3], 0)
            elif prev == WindowMode.BORDERLESS:
                # ── 退出无边框 → 恢复 Win32 chrome + 窗口尺寸 ──
                hwnd = glfw.get_win32_window(cls.glfw_window)
                _win32_restore_chrome(hwnd)
                r = cls._saved_window_rect or (100, 100, 800, 600)
                glfw.set_window_size(cls.glfw_window, r[2], r[3])
                glfw.set_window_pos(cls.glfw_window, r[0], r[1])

        elif mode == WindowMode.BORDERLESS:
            # ── 进入无边框窗口化 → Win32 剥离 chrome ──
            if prev != WindowMode.BORDERLESS:
                cls._saved_window_rect = cls._get_current_rect()
            hwnd = glfw.get_win32_window(cls.glfw_window)
            glfw.set_window_size(cls.glfw_window, sys_w, sys_h)
            glfw.set_window_pos(cls.glfw_window, 0, 0)
            _win32_strip_chrome(hwnd)

        cls._window_mode = mode
        print(f"[glfwWindow] Mode: {prev.value} → {mode.value}")

        # ★ 模式切换后重新应用透明/置顶样式 (GLFW 可能重置了 Win32 扩展样式)
        cls._reapply_win32_styles()

    @classmethod
    def _reapply_win32_styles(cls) -> None:
        """重新应用 Win32 扩展窗口样式 (透明 / 穿透 / 置顶)。

        GLFW 的 set_window_monitor / set_window_attrib 等操作可能
        在内部重建窗口, 导致之前设置的 WS_EX_LAYERED 等样式丢失。
        此方法在每次窗口模式切换后调用, 确保样式持久。
        """
        if cls.glfw_window is None:
            return
        hwnd = glfw.get_win32_window(cls.glfw_window)
        if cls._transparent:
            _win32_add_style(hwnd, _WS_EX_LAYERED)
            if cls._click_through:
                _win32_add_style(hwnd, _WS_EX_TRANSPARENT)
        if cls._topmost:
            _win32_set_topmost(hwnd)

    @classmethod
    def _get_current_rect(cls) -> tuple[int, int, int, int]:
        """返回当前窗口矩形 (x, y, w, h)。"""
        if cls.glfw_window is None:
            return (100, 100, 800, 600)
        x, y = glfw.get_window_pos(cls.glfw_window)
        w, h = glfw.get_window_size(cls.glfw_window)
        return (x, y, w, h)

    # ════════════════════════════════════════════════════════════
    # 输入钩子工厂 — 为 InputPipeline 提供与原有行为一致的钩子
    # 通过闭包捕获 cls (类引用), 使 cls._engine 在回调时动态解析
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _make_key_hook(cls):
        """键盘钩子 — 与原有 _key_callback 行为一致。"""
        _kls = cls
        def hook(key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.RELEASE:
                WindowCloseEvent.Pack(engine=_kls._engine)
            KeyboardButtonEvent.Pack(key, scancode, action, mods, engine=_kls._engine)
        return hook

    @classmethod
    def _make_mouse_button_hook(cls):
        """鼠标按键钩子 — 与原有 _mouse_callback 行为一致。"""
        _kls = cls
        def hook(button, action, mods, x, y):
            MouseButtonEvent.Pack(
                button=button, action=action, mods=mods,
                pos_x=int(x), pos_y=int(y), engine=_kls._engine,
            )
        return hook

    @classmethod
    def _make_drag_hook(cls):
        """鼠标拖拽钩子 — 与原有 _mouse_move_callbakc 拖拽分支一致。"""
        _kls = cls
        def hook(button, dx, dy, x, y):
            MouseGragEvent.Pack(int(x), int(y), engine=_kls._engine)
        return hook

    @classmethod
    def _make_move_hook(cls):
        """鼠标移动钩子 — 与原有 _mouse_move_callbakc 纯移动分支一致。"""
        _kls = cls
        def hook(x, y):
            MouseMoveEvent.Pack(int(x), int(y), engine=_kls._engine)
        return hook

    @classmethod
    def _make_scroll_hook(cls):
        """滚轮钩子 — 与原有 _scroll_callback 行为一致。"""
        _kls = cls
        def hook(xoff, yoff):
            ScrollerEvent.Pack(x_offset=int(xoff), y_offset=int(yoff), engine=_kls._engine)
        return hook

    # ════════════════════════════════════════════════════════════
    # 窗口 resize (非输入事件, 保持直接 GLFW 回调注册)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _window_resize_event_callback(
        cls,
        window,
        width,
        height
    ):
        # 直接通知渲染器 (GPU 资源重建走 Command, 不经过 Event)
        engine = cls._engine
        if engine is not None and engine.renderer is not None:
            engine.renderer.enqueue(ResizeCommand(width, height))
        # 通知其他层 (ImGui display_size 等)
        WindowResizeEvent.Pack(width, height, engine=cls._engine)

    # ════════════════════════════════════════════════════════════
    # 点击穿透 (Overlay 模式)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _update_click_through_state(cls) -> None:
        """每帧在 poll_events 之前调用 — 根据命中测试切换 WS_EX_TRANSPARENT。

        光标在非客户区 (标题栏/边框) → 强制关闭穿透 (窗口可操作)。
        光标在客户区内 → 调用 _is_click_through_target 判定:
          - True  → 关闭穿透 (捕获鼠标事件)
          - False → 开启穿透 (事件传到后方窗口)
        """
        hwnd = glfw.get_win32_window(cls.glfw_window)
        fbw, fbh = glfw.get_framebuffer_size(cls.glfw_window)
        cx, cy = glfw.get_cursor_pos(cls.glfw_window)

        in_client = (0.0 <= cx < fbw) and (0.0 <= cy < fbh)

        if not in_client:
            # 非客户区 — 强制关闭穿透，保证标题栏/边框可操作
            _win32_remove_style(hwnd, _WS_EX_TRANSPARENT)
        else:
            # 客户区内 — 根据子类覆写的命中测试判定
            ndc_x = (cx / fbw) * 2.0 - 1.0
            ndc_y = 1.0 - (cy / fbh) * 2.0
            if cls._is_click_through_target(ndc_x, ndc_y):
                _win32_remove_style(hwnd, _WS_EX_TRANSPARENT)
            else:
                _win32_add_style(hwnd, _WS_EX_TRANSPARENT)

        # ★ 每帧刷新置顶 — 防止穿透点击后窗口被挤到后方
        if cls._topmost:
            _win32_set_topmost(hwnd)

    @classmethod
    def _is_click_through_target(cls, ndc_x: float, ndc_y: float) -> bool:
        """判定 NDC 坐标是否应捕获鼠标事件 (不穿透)。

        子类覆写以实现自定义命中测试 (如检查是否在 UI 元素上)。
        默认: 所有客户区点击均捕获 (无穿透)。

        Returns:
            True  → 捕获鼠标 (关闭 WS_EX_TRANSPARENT)
            False → 穿透鼠标 (开启 WS_EX_TRANSPARENT)
        """
        return True  # 默认不穿透
