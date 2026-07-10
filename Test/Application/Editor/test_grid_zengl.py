"""
Test: Camera-Following Grid (ZenGL) — 摄像机跟随网格 + 圆形淡化边缘
═══════════════════════════════════════════════════════════════

ZenGL 渲染后端版本。

验证:
  1. 网格中心跟随摄像机注视点 (orbit_target)
  2. 网格半径 = 摄像机距离 (orbit_distance)
  3. 0.8r ~ 1r 边缘逐渐虚化到透明

操作:
  中键拖拽  = 轨道旋转 (与主线一致)
  中键+Shift 拖拽 = 平移注视点
  滚轮      = 缩放
  ESC       = 退出

运行: python Test/Application/Editor/test_grid_camera_follow_zengl.py
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math, numpy as np, glfw

from Application.Editor.Gizmos.Grid import Grid

from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene


def main():
    # ── GLFW (ZenGL: SAMPLES=0, DEPTH_BITS=0) ──
    if not glfw.init():
        print("glfw.init() failed"); return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES, 0)
    glfw.window_hint(glfw.DEPTH_BITS, 0)

    window = glfw.create_window(
        1024, 768, "Grid Follow (ZenGL) — Orbit/Pan/Zoom", None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 夹具 ──
    h = TestHarness("Grid Follow (ZenGL)")
    h.set_window(window)
    h.init_engine()

    fbw, fbh = glfw.get_framebuffer_size(window)
    renderer = ZenGLRenderer.Create()
    h.set_renderer(renderer)
    h.patch_default_shader_440()
    print(f"[ZenGL] Renderer {renderer.viewport_width}×{renderer.viewport_height}")

    # ── 场景: 立方体 + 摄像机跟随网格 ──
    setup_default_scene(renderer, with_grid=True)

    # ── 摄像机 (TestEditorCamera, 与 outliner 统一) ──
    cam = h.create_test_camera()
    cam.distance = 10.0
    cam.yaw = math.pi * 0.7
    cam.pitch = 0.3
    h.inject_mock_camera(cam)

    # ── ★ 输入管线 + 主线预设 ──
    def update_title():
        t = cam.target
        d = cam.distance
        glfw.set_window_title(
            window,
            f"Grid Follow (ZenGL) — center=({t[0]:.1f},{t[1]:.1f},{t[2]:.1f}) "
            f"r={d:.1f}")

    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam, after_camera=update_title)
    pipeline.on_key = lambda k, sc, act, mods: (
        glfw.set_window_should_close(window, True)
        if act == glfw.PRESS and k == glfw.KEY_ESCAPE else None
    )
    update_title()

    # ── 主循环 (ZenGL: skip_cmd_queue) ──
    h.run_loop(cam, skip_cmd_queue=True)

    # ── 清理 ──
    Grid.unregister_from(renderer)
    h.shutdown()
    print("[ZenGL] Done")


if __name__ == "__main__":
    main()
