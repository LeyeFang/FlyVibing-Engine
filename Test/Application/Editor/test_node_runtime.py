"""
Test: Node Graph Runtime — 节点图驱动 GameRuntime（复用 ScenePanel 启停）
═══════════════════════════════════════════════════════════════════════════════

复用主线 ScenePanel 的 Play/Stop 按钮启动真 GameRuntime (PIE 模式)。
节点图: 编辑器中已有的 OnFrameUpdate → Get Time → Print（自动连线）。

连线说明:
  OnFrameUpdate.exec ──→ Get Time.exec_in
  Get Time.exec_out  ──→ Print.exec_in
  Get Time.Elapsed   ──→ Print.Value

运行: python Test/Application/Editor/test_node_runtime.py
操作:
  1. Scene 面板点击 ▶ Run → 启动 GameRuntime（弹出 PIE 窗口）
  2. 控制台每帧输出 [Node:Print] <elapsed_time>
  3. Scene 面板点击 ■ Stop → 停止
  4. ESC → 退出
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
# 初始图：找到编辑器中已有的 OnFrameUpdate，挂 GetTime + Print
# ═══════════════════════════════════════════════════════════════

def _build_initial_graph(canvas: NodeCanvas) -> None:
    """搭建 '每隔1秒触发 PrintString' 的示例图。

    ═══════════════════════════════════════════════════════════════
    Pin 速查表
    ═══════════════════════════════════════════════════════════════
    exec  pin (白色三角形):  执行流 — 左边进、右边出，决定"谁先谁后"
    data  pin (彩色圆形):    数据流 — 传数值，不决定执行顺序
    ═══════════════════════════════════════════════════════════════

    图结构:
      OnGameStart.exec ──→ VarSet("next_time", Manual=1).exec_in
             ↑ 游戏启动时执行一次，初始化变量 next_time = 1

      OnFrameUpdate.exec ──→ TimeTrigger(Pin模式).exec_in
             ↑ 每帧检查：引擎时间 ≥ next_time？

      TimeTrigger.out_0 ──→ VarSet("next_time", Pin).exec_in
             ↑ 触发时：把 next_time 加 1 后存回去

      VarSet.exec_out ──→ PrintString("tick").exec_in
             ↑ 更新完变量后：打印 "tick"

      Data 链路（不需要 exec，自动求值）:
        VarGet("next_time").Value ──→ MathAdd.A       }   VarGet 读当前值
        Constant(1.0).Result      ──→ MathAdd.B       }   + Constant 提供 +1
        MathAdd.Result            ──→ VarSet.Value     }   → 写回 VarSet
        VarGet("next_time").Value ──→ TimeTrigger.Time }   TimeTrigger 读阈值
    """

    # ── 找已有的默认事件节点 ──
    n_start = n_update = None
    for nid, inst in canvas.nodes.items():
        if inst.node_type == "OnGameStart":
            n_start = nid
        elif inst.node_type == "OnFrameUpdate":
            n_update = nid
    if n_start is None or n_update is None:
        print("[Graph] Event nodes not found — abort")
        return

    # ── 创建节点 ──
    n_vs_init  = canvas.add_node("VarSet",      (400, 60))    # 初始化 next_time=1
    n_vg       = canvas.add_node("VarGet",      (400, 260))   # 读 next_time
    n_const    = canvas.add_node("Constant",    (180, 360))   # 常量 1.0
    n_add      = canvas.add_node("MathAdd",     (400, 400))   # next_time + 1
    n_trig     = canvas.add_node("TimeTrigger", (680, 100))   # 时间触发器
    n_print    = canvas.add_node("PrintString", (980, 140))   # 打印
    n_vs_inc   = canvas.add_node("VarSet",      (680, 360))   # 更新 next_time

    # ── 配置节点属性 ──
    canvas.nodes[n_vs_init].props.update(
        {"var_name": "next_time", "mode": "manual", "value": 1.0})
    canvas.nodes[n_vg].props.update(
        {"var_name": "next_time"})
    canvas.nodes[n_const].props.update(
        {"value": 1.0})
    canvas.nodes[n_trig].props.update(
        {"mode": "pin"})                          # Pin 模式: 阈值从 Time pin 读
    canvas.nodes[n_print].props.update(
        {"message": "tick"})
    canvas.nodes[n_vs_inc].props.update(
        {"var_name": "next_time", "mode": "pin"}) # Pin 模式: 值从 Value pin 读

    def _pin(node_id: int, name: str) -> int:
        inst = canvas.nodes[node_id]
        nd = _TYPES[inst.node_type]
        for p in nd.pins:
            if p.name == name:
                return inst.pin_ids[p.name]
        raise KeyError(f"Pin '{name}' not found in {inst.node_type}")

    # ══════════════════════════════════════════════════════════
    # Exec 连线（执行顺序）
    # ══════════════════════════════════════════════════════════
    canvas.add_link(_pin(n_start,   "exec"),    _pin(n_vs_init, "exec_in"))
    canvas.add_link(_pin(n_update,  "exec"),    _pin(n_trig,    "exec_in"))
    canvas.add_link(_pin(n_trig,    "out_0"),   _pin(n_vs_inc,  "exec_in"))
    canvas.add_link(_pin(n_vs_inc,  "exec_out"), _pin(n_print,   "exec_in"))

    # ══════════════════════════════════════════════════════════
    # Data 连线（数值传递，引擎自动按需求值）
    # ══════════════════════════════════════════════════════════
    canvas.add_link(_pin(n_vg,    "Value"),  _pin(n_add,   "A"))
    canvas.add_link(_pin(n_const, "Result"), _pin(n_add,   "B"))
    canvas.add_link(_pin(n_add,   "Result"), _pin(n_vs_inc, "Value"))
    canvas.add_link(_pin(n_vg,    "Value"),  _pin(n_trig,  "Time"))

    print("[Graph] Built: 1s interval trigger → PrintString")
    print("  OnGameStart ──→ VarSet(next_time=1)")
    print("  OnFrameUpdate ──→ TimeTrigger(Pin: reads VarGet)")
    print("  TimeTrigger.out_0 ──→ VarSet(next_time+1) ──→ PrintString(tick)")


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

    # ── 3. ImGui ──
    imgui.create_context()
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.docking_enable
    io.set_ini_filename(os.path.join(os.path.dirname(__file__), "imgui.ini"))
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
