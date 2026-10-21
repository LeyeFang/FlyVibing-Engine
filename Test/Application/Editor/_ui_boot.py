"""UI 场景引导 — test_live_ui / ui_scenario 共享的最小编辑器 UI 宿主。

职责:
  - GLFW 窗口（GL 4.4 core; 可隐藏）+ 引擎子系统（ResourceManager / SceneManager）
  - imgui 上下文/字体/GLFW+OpenGL3 后端（禁用 imgui.ini 持久化 — 测试隔离）
  - 主线面板注册（Scene / Node Editor / Resources）+ 帧循环
  - glReadPixels 抓帧快照（**右后缓冲, swap 前读取 → 含 ImGui UI**）

原则与 test_live_ui 相同: 刚好让 Controller/Panel 不崩的最小引导;
不含 3D 渲染器 / gizmo / EditorHost。
"""

from __future__ import annotations

import ctypes
import os
import sys

# ── 路径引导（同其他 Test 文件） ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

import glfw
import numpy as np
from imgui_bundle import imgui
from OpenGL import GL as gl

from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager

# ★ 先导入真 Controller（触发 auto-register 到 ControllerRegistry），再注册 Panel
#   （ScenePanel 需要全部 5 个: Simulation/SceneBrowser/ResourceBrowser/Viewport/Selection）
from Application.Editor.UI.controllers.SimulationController import SimulationController  # noqa: F401
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ViewportController import ViewportController  # noqa: F401
from Application.Editor.UI.controllers.SelectionController import SelectionController  # noqa: F401
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, SettingsPanel, NodeEditorPanel, ResourcePanel
from Application.Editor.EditorCamera import EditorCamera


# ── 最小 Mock（与 Test._test_harness 同接口; 本文件自包含 — 不拉 pyrr 等重依赖）──


class _MockWindow:
    """包装 GLFW 窗口，匹配 EditorWindow 接口 (GetSize)。"""

    def __init__(self, glfw_window) -> None:
        self._glfw = glfw_window
        self.glfw_window = glfw_window

    def GetSize(self):
        return glfw.get_framebuffer_size(self._glfw)


def load_font(io) -> None:
    """加载字体 + Font Awesome 6 图标 — 与主线 EditorLayer 相同。"""
    from imgui_bundle import hello_imgui as _hi

    _resource_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "Resource"))
    _hi.set_assets_folder(_resource_dir)

    for rel_path in ("Fonts/Inter-Regular.ttf", "Fonts/segoeui.ttf", "Fonts/arial.ttf"):
        if _hi.asset_exists(rel_path):
            _hi.load_font_ttf_with_font_awesome_icons(rel_path, 17.0)
            return
    io.fonts.add_font_default()


class UiBoot:
    """最小 UI 宿主。用法:
        boot = UiBoot(hidden=True).create()
        boot.frames(3)
        snap = boot.frame(snapshot="boot", out_dir=out_dir)
        boot.close()
    """

    def __init__(self, width: int = 1600, height: int = 900, hidden: bool = False,
                 title: str = "UI Scenario") -> None:
        self.width = width
        self.height = height
        self.hidden = hidden
        self.title = title
        self.window = None

    # ── 生命周期 ──

    def create(self) -> "UiBoot":
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        if self.hidden:
            glfw.window_hint(glfw.VISIBLE, glfw.FALSE)

        self.window = glfw.create_window(self.width, self.height, self.title, None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("glfw.create_window() failed")
        glfw.make_context_current(self.window)
        glfw.swap_interval(0 if self.hidden else 1)

        # ── 引擎子系统（最小化引导 — 以 EditorHost 身份, 与生产 Engine.Init 同路径:
        #    SceneManager 注册名 = "EditorHost", 默认实体(cameras+cube)自动创建,
        #    EditorHost.scene / Controller 的 EditorHost.scene 调用全部生效）──
        from Application.Editor.EditorHost import EditorHost

        EditorHost.editor_window = _MockWindow(self.window)
        EditorHost.renderer = None
        BindPackCallback(lambda e: None)
        ResourceManager.Init(EditorHost)
        SceneManager.Init(EditorHost)
        EditorHost.scene = SceneManager._state_for(EditorHost.__name__)

        # ── ImGui ──
        imgui.create_context()
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable
        io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
        from flyvibing_extension_kit.imgui_headless import disable_ini
        disable_ini(io)  # ★ 禁止布局持久化（唯一入口 — 见 imgui_headless；不产生 imgui.ini）
        load_font(io)
        glfw_ptr = ctypes.cast(self.window, ctypes.c_void_p).value
        imgui.backends.glfw_init_for_opengl(glfw_ptr, True)
        imgui.backends.opengl3_init("#version 440 core")

        # EditorCamera 单例（ViewportController.switch_to_2d/3d 需要）
        EditorCamera.get_instance()

        # ── 主线面板注册（重置 UIManager 静态态 → 同进程多次 boot 不叠加）──
        UIManager._panels.clear()
        UIManager._dock_layout_done = False
        UIManager._style_applied = False
        UIManager.register(ScenePanel())
        UIManager.register(ResourcePanel())
        UIManager.register(NodeEditorPanel())
        # 与 EditorImguiLayer._init_ui_panels 保持一致（新增内建面板时两处同步）
        UIManager.register(SettingsPanel())

        gl.glClearColor(0.11, 0.11, 0.11, 1.0)
        return self

    def close(self) -> None:
        try:
            imgui.backends.opengl3_shutdown()
            imgui.backends.glfw_shutdown()
            imgui.destroy_context()
        finally:
            glfw.terminate()
            self.window = None

    # ── 帧循环 ──

    def frame(self, snapshot: str | None = None, out_dir: str | None = None) -> dict | None:
        """渲染一帧; snapshot 非空时在 swap **之前**读回后缓冲（含 ImGui UI）→ PNG。"""
        glfw.poll_events()
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())

        snap = None
        if snapshot:
            snap = self._capture(snapshot, out_dir)
        glfw.swap_buffers(self.window)
        return snap

    def frames(self, n: int) -> None:
        for _ in range(n):
            self.frame()

    # ── 抓帧 ──

    def _capture(self, name: str, out_dir: str | None) -> dict:
        w, h = glfw.get_framebuffer_size(self.window)
        gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, buf)
        arr = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(h, w, 4)[::-1]  # GL bottom-up → top-down

        from PIL import Image

        out_dir = out_dir or "."
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.png")
        Image.frombytes("RGBA", (w, h), np.ascontiguousarray(arr).tobytes()).save(path, "PNG")
        return {
            "name": name,
            "path": path,
            "width": w,
            "height": h,
            "bytes": os.path.getsize(path),
            "std": round(float(arr[..., :3].std()), 2),  # 非均匀度 — 全黑画面≈0
        }
