"""
Test: Node Graph Runtime — 节点图驱动 GameRuntime（复用 ScenePanel 启停）
═══════════════════════════════════════════════════════════════════════════════

复用主线 ScenePanel 的 Play/Stop 按钮启动真 GameRuntime (PIE 模式)。
节点图: 运行 10s 后自动退出 — 测试 Compare / Branch / ExitGame 新节点。

连线说明:
  OnFrameUpdate.exec ──→ Get Time.exec_in
  Get Time.exec_out   ──→ Branch.exec_in

  Get Time.Elapsed ──→ Compare.A          } 数据: 比较 elapsed >= 10?
  Constant(10.0)   ──→ Compare.B          }
  Compare.Result   ──→ Branch.Condition

  Branch.True  ──→ PrintString("10s reached, exiting...").exec_in
                   PrintString.exec_out ──→ ExitGame.exec_in
  Branch.False ──→ Print(Elapsed).exec_in

运行: python Test/Application/Editor/test_node_runtime.py
操作:
  1. Scene 面板点击 ▶ Run → 启动 GameRuntime
  2. 控制台每帧输出 elapsed time
  3. 10s 后自动输出 "10s reached, exiting..." → GameRuntime 停止
  4. ESC → 退出编辑器
"""

from __future__ import annotations
import sys, os, ctypes

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import glfw
from imgui_bundle import imgui
from OpenGL import GL as gl

from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager

from Application.Editor.EditorHost import EditorHost
from Application.Editor.UI.UIManager import UIManager
from Application.Editor.UI.panels import NodeEditorPanel
from Application.Editor.UI.controllers.NodeEditorController import (
    _TYPES, NodeCanvas,
)
from Application.Editor.UI.controllers.SimulationController import (
    SimulationController,
)

# ── Controller auto-register ──
from Application.Editor.UI.controllers.SimulationController import SimulationController as _SC  # noqa
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController  # noqa
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController  # noqa
from Application.Editor.UI.controllers.ViewportController import ViewportController  # noqa
from Application.Editor.UI.panels import ScenePanel

from Application.Runtime.GameRuntime import GameRuntime
from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer

from Test._test_harness import MockApp, MockWindow


# ═══════════════════════════════════════════════════════════════
# 初始图：运行 10s 后自动退出 (测试 Compare / Branch / ExitGame)
# ═══════════════════════════════════════════════════════════════

def _build_initial_graph(canvas: NodeCanvas) -> None:
    """搭建 '10s 后自动退出' 的示例图。

    图结构:
      OnFrameUpdate.exec ──→ Get Time.exec_in
        ↑ 每帧触发

      Get Time.exec_out ──→ Branch.exec_in
        ↑ 获取运行时长后进入条件分支

      Get Time.Elapsed ──→ Compare.A       }
      Constant(10.0)    ──→ Compare.B       }  数据: elapsed >= 10?
      Compare.Result    ──→ Branch.Condition }

      Branch.True  ──→ PrintString("10s reached, exiting...")
                         └─ exec_out ──→ ExitGame
        ↑ 时间到 → 打印消息 → 退出

      Branch.False ──→ Print(Elapsed)
        ↑ 时间未到 → 打印当前运行时长
    """

    # ── 找已有的默认事件节点 ──
    n_update = None
    for nid, inst in canvas.nodes.items():
        if inst.node_type == "OnFrameUpdate":
            n_update = nid
    if n_update is None:
        print("[Graph] OnFrameUpdate not found — abort")
        return

    # ── 创建节点 ──
    n_time    = canvas.add_node("TimeGetElapsed", (400, 60))
    n_const   = canvas.add_node("Constant",       (180, 200))
    n_cmp     = canvas.add_node("Compare",        (400, 200))
    n_branch  = canvas.add_node("Branch",         (680, 80))
    n_print_t = canvas.add_node("PrintString",    (980, 40))   # True 分支
    n_exit    = canvas.add_node("ExitGame",       (1280, 40))
    n_print_f = canvas.add_node("Print",          (980, 160))  # False 分支

    # ── 配置节点属性 ──
    canvas.nodes[n_const].props.update({"value": 10.0})
    canvas.nodes[n_cmp].props.update({"operation": "gte"})       # >=
    canvas.nodes[n_print_t].props.update({"message": "10s reached, exiting..."})

    def _pin(node_id: int, name: str) -> int:
        inst = canvas.nodes[node_id]
        nd = _TYPES[inst.node_type]
        for p in nd.pins:
            if p.name == name:
                return inst.pin_ids[p.name]
        raise KeyError(f"Pin '{name}' not found in {inst.node_type}")

    # ══════════════════════════════════════════════════════════
    # Exec 连线
    # ══════════════════════════════════════════════════════════
    canvas.add_link(_pin(n_update, "exec"),    _pin(n_time,    "exec_in"))
    canvas.add_link(_pin(n_time,   "exec_out"), _pin(n_branch,  "exec_in"))
    canvas.add_link(_pin(n_branch, "True"),    _pin(n_print_t, "exec_in"))
    canvas.add_link(_pin(n_print_t,"exec_out"), _pin(n_exit,    "exec_in"))
    canvas.add_link(_pin(n_branch, "False"),   _pin(n_print_f, "exec_in"))

    # ══════════════════════════════════════════════════════════
    # Data 连线
    # ══════════════════════════════════════════════════════════
    canvas.add_link(_pin(n_time,  "Elapsed"), _pin(n_cmp,    "A"))
    canvas.add_link(_pin(n_const, "Result"),  _pin(n_cmp,    "B"))
    canvas.add_link(_pin(n_cmp,   "Result"),  _pin(n_branch, "Condition"))
    canvas.add_link(_pin(n_time,  "Elapsed"), _pin(n_print_f,"Value"))

    print("[Graph] Built: 10s auto-exit")
    print("  OnFrameUpdate ──→ GetTime ──→ Branch(Condition: Elapsed >= 10)")
    print("  Branch.True  ──→ PrintString ──→ ExitGame")
    print("  Branch.False ──→ Print(Elapsed)")


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
        1600, 900, "Node Graph Runtime — PIE (ESC to exit)", None, None
    )
    if not window:
        glfw.terminate()
        raise RuntimeError("Window creation failed")
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 2. 引擎最小引导 ──
    mock_window = MockWindow(window)
    mock_app = MockApp()
    mock_app.editor_window = mock_window
    BindPackCallback(lambda e: None)
    ResourceManager.Init(mock_app)
    SceneManager.Init(mock_app)

    # ★ 为 EditorHost 初始化 SceneManager（ScenePanel 依赖 EditorHost.scene）
    SceneManager.Init(EditorHost)
    EditorHost.scene = SceneManager._state_for("EditorHost")

    # ── 3. ImGui ──
    imgui.create_context()
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.docking_enable
    io.set_ini_filename("")
    for fp in [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(fp):
            io.fonts.add_font_from_file_ttf(fp, 17.0)
            break
    glfw_window_ptr = ctypes.cast(window, ctypes.c_void_p).value
    imgui.backends.glfw_init_for_opengl(glfw_window_ptr, True)
    imgui.backends.opengl3_init("#version 440 core")

    # ── 4. 注册面板（ScenePanel 自带 Play/Stop） ──
    from Application.Editor.EditorCamera import EditorCamera
    EditorCamera.get_instance()
    UIManager.register(ScenePanel())
    ne_panel = NodeEditorPanel()
    UIManager.register(ne_panel)

    # ── 5. 状态 ──
    _graph_initialized = False
    print("[NodeRuntime] Ready — use Scene panel ▶ Run / ■ Stop")
    print("[NodeRuntime] ESC to exit")

    gl.glClearColor(0.11, 0.11, 0.11, 1.0)
    glfw.swap_buffers(window)

    # ── 6. 主循环 ──
    while not glfw.window_should_close(window):
        glfw.poll_events()

        # ── 确保主窗口 GL 上下文 (PIE 启动后会被 Runtime 窗口切换) ──
        glfw.make_context_current(window)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()

        if imgui.is_key_pressed(imgui.Key.escape, False):
            if SimulationController.is_running() or SimulationController._pending_stop:
                SimulationController._try_consume_stop()
            glfw.set_window_should_close(window, True)

        # ── 延迟构建初始图（等 NodeEditorPanel 首次 draw 创建 canvas） ──
        if not _graph_initialized and ne_panel._canvas is not None:
            _build_initial_graph(ne_panel._canvas)
            _graph_initialized = True

        # ── 消费 SimulationController pending 标记 ──
        if SimulationController._pending_start:
            SimulationController._try_consume_start()
            print("[NodeRuntime] PIE started — check console for [Node:Print]")

        if SimulationController._pending_stop:
            SimulationController._try_consume_stop()
            print("[NodeRuntime] PIE stopped")

        # ── 主线 UI ──
        UIManager.draw_all()

        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
        glfw.swap_buffers(window)

    # ── 7. 清理 ──
    if SimulationController.is_running():
        SimulationController._try_consume_stop()
    imgui.backends.opengl3_shutdown()
    imgui.backends.glfw_shutdown()
    imgui.destroy_context()
    glfw.terminate()
    print("[NodeRuntime] Done")


if __name__ == "__main__":
    main()
