"""
Standalone PIE Test — 不使用完整 Editor，直接测试 GameRuntime 启动/停止。

用法:
    python Test/Application/Runtime/test_pie_bare.py

预期:
    1. 主窗口出现（模拟编辑器）
    2. 3 秒后自动出现 Runtime 子窗口（模拟点 Play）
    3. Runtime 窗口运行 5 帧（~0.3 秒）
    4. Runtime 窗口关闭（模拟点 Stop）
    5. 主窗口继续运行 2 秒后全部退出

观察点:
    - 终端日志应显示完整的 [GRT:*] 和 [Engine:*] 追踪
    - Runtime 窗口应能正常创建和销毁
    - 无报错、无死锁
"""

from __future__ import annotations
import sys, os, time, threading, glfw

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.Engine import Engine
from Application.Core.Events.Event import BindPackCallback, _register_engine
from Application.Core.Input.InputState import _set_default_input_state
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Runtime.GameRuntime import GameRuntime
from Application.Runtime.RuntimeLayer import RuntimeLayer

# ═══════════════════════════════════════════════════════════════
# 简易 "编辑器" 主窗口
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("PIE Bare Test - GameRuntime start/stop")
    print("=" * 60)

    # -- Create main GLFW window (simulates editor window) --
    if not glfw.init():
        print("glfw.init() failed"); return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.VISIBLE, glfw.TRUE)

    main_window = glfw.create_window(800, 600, "EDITOR (main window)", None, None)
    if not main_window:
        glfw.terminate(); return
    glfw.make_context_current(main_window)
    glfw.swap_interval(1)

    # ── 注册事件回调 (模拟 EditorHost.init 的步骤 2) ──
    _register_engine(Engine)  # 用 Engine 作为"编辑器"引擎
    BindPackCallback(Engine._on_event)
    _set_default_input_state(Engine._get_input_state())

    # ── 初始化子系统 (模拟 EditorHost.init 的步骤 3) ──
    ResourceManager.Init(Engine)
    SceneManager.Init(Engine)

    print("[MAIN] Editor window ready. Will trigger PIE in 3 seconds...")
    print("[MAIN] Thread:", threading.current_thread().name)

    # ── 主循环 ──
    start_time = time.time()
    pie_started = False
    pie_stopped = False
    frame_count = 0

    while not glfw.window_should_close(main_window):
        glfw.poll_events()

        elapsed = time.time() - start_time

        # 3 秒后自动启动 PIE
        if elapsed > 3.0 and not pie_started:
            print("\n" + "-" * 40)
            print("[MAIN] [PLAY] Triggering GameRuntime.start()...")
            print("-" * 40)
            GameRuntime.push_layer(RuntimeLayer)
            GameRuntime.start()
            pie_started = True

        # PIE runs ~5s then auto-stop
        if pie_started and not pie_stopped:
            pie_elapsed = elapsed - 3.0
            if pie_elapsed > 5.0:
                print("\n" + "-" * 40)
                print("[MAIN] [STOP] Triggering GameRuntime.stop()...")
                print("-" * 40)
                GameRuntime.stop()
                pie_stopped = True

        # Stop after 2s, exit
        if pie_stopped:
            post_stop = elapsed - 8.0
            if post_stop > 2.0:
                print("[MAIN] Test complete, exiting.")
                break

        frame_count += 1
        time.sleep(0.016)

    # -- Cleanup --
    print(f"[MAIN] Frames: {frame_count}")
    if GameRuntime.window is not None:
        GameRuntime.window.Therminate()
    glfw.destroy_window(main_window)
    glfw.terminate()
    print("[MAIN] Done.")


if __name__ == '__main__':
    main()
