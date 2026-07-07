"""
Test: Camera-Following Grid — 摄像机跟随网格 + 圆形淡化边缘
═══════════════════════════════════════════════════════════════

验证新的 Grid 功能:
  1. 网格中心跟随摄像机注视点 (orbit_target)
  2. 网格半径 = 摄像机距离 (orbit_distance)
  3. 0.8r ~ 1r 边缘逐渐虚化到透明
  4. 红色 X 轴 + 绿色 Y 轴始终可见 (无淡化)

操作:
  中键拖拽  = 轨道旋转 (观察网格跟随)
  中键+Shift 拖拽 = 平移注视点 (移动网格中心)
  滚轮      = 缩放 (改变网格淡化半径)
  ESC       = 退出

运行: python Test/Application/Editor/test_grid_camera_follow_opengl.py
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math
import numpy as np
import glfw

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 夹具: 窗口 / 引擎 / 渲染器 / 摄像机 ──
    h = TestHarness("Camera-Following Grid — Orbit/Pan/Zoom to test")
    h.create_window()
    h.init_engine()
    renderer = h.create_renderer()
    cam = h.create_default_camera()

    # ── 场景: 三个白色立方体 + 摄像机跟随网格 ──
    setup_default_scene(renderer, with_grid=True)

    # ── 摄像机初始参数 ──
    cam.orbit_target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    cam.orbit_distance = 10.0
    cam.yaw = math.pi * 0.7
    cam.pitch = 0.3
    cam._update_position()

    def update_title():
        t = cam.orbit_target
        d = cam.orbit_distance
        glfw.set_window_title(
            h.window,
            f"Grid Follow — center=({t[0]:.1f},{t[1]:.1f},{t[2]:.1f}) "
            f"r={d:.1f}  Drag:Left=Orbit Middle=Pan Scroll=Zoom",
        )

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam, after_camera=update_title)
    pipeline.on_key = lambda k, sc, act, mods: (
        glfw.set_window_should_close(h.window, True)
        if act == glfw.PRESS and k == glfw.KEY_ESCAPE else None
    )

    update_title()

    # ── 主循环 (不变) ──
    h.run_loop(cam)

    # ── 清理 ──
    from Application.Editor.Gizmos.Grid import Grid
    Grid.unregister_from(renderer)
    h.shutdown()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
