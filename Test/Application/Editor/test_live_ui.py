"""
Test: Live UI — 主线面板实时渲染测试
═══════════════════════════════════════════════════════════════════════════════

直接复用主线 ScenePanel 和 NodeEditorPanel，渲染完整的编辑器 UI。
纯 ImGui，无 3D 渲染，无 gizmo，无 transform 交互。

用途:
  - 实时预览主线 UI 面板的视觉改动（颜色 / 字体 / 间距 / 布局）
  - 验证面板级交互（标签页切换、实体选择、节点编辑）
  - 无需启动完整 EditorHost，秒级迭代 UI

与 test_editor_gui.py 的区别:
  test_editor_gui.py → 手写桩面板（假数据，不随主线更新）
  test_live_ui.py    → 复用主线 Panel 类（真实数据，随主线自动更新）

引导层:
  GLFW 窗口 + ResourceManager + SceneManager + Mock EditorCamera
  → 刚好让 Controller 不崩溃，但不过度初始化引擎

运行: python Test/Application/Editor/test_live_ui.py
退出: ESC
"""

from __future__ import annotations
import sys, os, ctypes

# ── 路径引导（同其他 Test 文件） ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import glfw
from imgui_bundle import imgui
from OpenGL import GL as gl

# ── 引擎最小引导 ──
from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer

# ── 主线 UI ──
# ★ 先导入真 Controller（触发 auto-register 到 ControllerRegistry），
#    再导入 Panel（Panel.__init__ 从 Registry 获取 Controller）。
from Application.Editor.UI.controllers.SimulationController import SimulationController  # noqa: F401
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ViewportController import ViewportController  # noqa: F401
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel, ResourcePanel

# ── EditorCamera（ViewportController 需要单例） ──
from Application.Editor.EditorCamera import EditorCamera

# ── Test 夹具 ──
from Test._test_harness import MockApp, MockWindow


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _create_test_entities(num: int = 3) -> list[int]:
    """创建少量测试 Entity，让 ScenePanel 的 Entities 标签页有数据可显示。"""
    cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')
    positions = [
        (-3.0, 0.0, -6.0),
        ( 0.0, 0.0, -6.0),
        ( 3.0, 0.0, -6.0),
    ][:num]

    entity_ids = []
    for pos in positions:
        eid = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(eid, MeshRenderer(mesh_id=cube_mesh_id))
        SceneManager.SetEntityTransform(eid, position_xyz=pos)
        entity_ids.append(eid)
    return entity_ids


def _load_font(io) -> None:
    """加载字体 + Font Awesome 6 图标 — 与主线 EditorLayer 相同。"""
    from imgui_bundle import hello_imgui as _hi

    _resource_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "Resource"))
    _hi.set_assets_folder(_resource_dir)

    font_candidates = [
        "Fonts/Inter-Regular.ttf",
        "Fonts/segoeui.ttf",
        "Fonts/arial.ttf",
    ]
    for rel_path in font_candidates:
        if _hi.asset_exists(rel_path):
            _hi.load_font_ttf_with_font_awesome_icons(rel_path, 17.0)
            return
    # 回退: 使用 imgui 内置等宽字体
    io.fonts.add_font_default()


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 1. GLFW 窗口 ──
    if not glfw.init():
        raise RuntimeError("glfw.init() failed")

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    window = glfw.create_window(
        1600, 900, "Live UI — Mainline Panels (ESC to exit)", None, None
    )
    if not window:
        glfw.terminate()
        raise RuntimeError("glfw.create_window() failed")
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 2. 引擎子系统（最小化初始化） ──
    mock_window = MockWindow(window)
    mock_app = MockApp()
    mock_app.editor_window = mock_window

    # 静默事件回调（避免未初始化的 Engine 导致 Pack 崩溃）
    BindPackCallback(lambda e: None)

    ResourceManager.Init(mock_app)
    SceneManager.Init(mock_app)

    # 创建测试 Entity — ScenePanel 会显示它们
    entity_ids = _create_test_entities(3)
    print(f"[Live UI] Created {len(entity_ids)} test entities: {entity_ids}")

    # ── 3. ImGui ──
    imgui.create_context()
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.docking_enable
    io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
    io.set_ini_filename(os.path.join(os.path.dirname(__file__), "imgui.ini"))
    _load_font(io)

    # GLFW + OpenGL3 后端
    glfw_window_ptr = ctypes.cast(window, ctypes.c_void_p).value
    imgui.backends.glfw_init_for_opengl(glfw_window_ptr, True)
    imgui.backends.opengl3_init("#version 440 core")

    # ── 4. EditorCamera 单例（ViewportController.switch_to_2d/3d 需要） ──
    EditorCamera.get_instance()

    # ── 5. 注册主线面板 ──
    UIManager.register(ScenePanel())
    UIManager.register(NodeEditorPanel())
    UIManager.register(ResourcePanel())

    # ── 6. 首帧预交换（避免白屏闪烁） ──
    gl.glClearColor(0.11, 0.11, 0.11, 1.0)
    glfw.swap_buffers(window)

    print("[Live UI] Ready — ESC to exit")
    print("  Panels  : Scene (real data), Node Editor (real canvas)")
    print("  Theme   : Blender dark (applied by UIManager)")
    print("  No 3D   : no openGLRenderer, no Grid, no ViewGizmo, no OutlinerID")
    print("  Control : SimulationController is live but engine is minimal (Play won't fully start)")

    # ── 7. 主循环 ──
    while not glfw.window_should_close(window):
        glfw.poll_events()

        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()

        # ESC 退出
        if imgui.is_key_pressed(imgui.Key.escape, False):
            glfw.set_window_should_close(window, True)

        # ★ 主线 UI 渲染 — 一键绘制全部面板
        UIManager.draw_all()

        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
        glfw.swap_buffers(window)

    # ── 8. 清理 ──
    imgui.backends.opengl3_shutdown()
    imgui.backends.glfw_shutdown()
    imgui.destroy_context()
    glfw.terminate()
    print("[Live UI] Done")


if __name__ == "__main__":
    main()
