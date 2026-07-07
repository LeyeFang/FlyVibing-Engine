"""
Test: ViewGizmo (ZenGL) — 2D 正交俯视 / 3D 透视切换 + 面点击视角切换
═══════════════════════════════════════════════════════════════

ZenGL 渲染后端版本。

功能:
  ★ TAB 键一键切换 2D 正交俯视 ↔ 3D 透视
  ★ 点击 ViewGizmo 六面 → 摄像机切换至该方向视角
  ★ 实体拾取选中 + X-Ray 轮廓 + 清除选中

操作: 中键拖拽=轨道旋转(主线一致) 左键点击=拾取面/实体 滚轮=缩放 TAB=2D/3D ESC=退出
运行: python Test/Application/Editor/test_view_gizmo_zengl.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math, numpy as np, glfw

from Application.Editor.Gizmos.ViewGizmo import ViewGizmo

from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer
from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
from Application.Core.Renderer.CommandQueue import CommandQueue

from Test._test_harness import TestHarness
from Test._test_scene import (
    setup_default_scene,
    unregister_view_gizmo,
)

# ═══════════════════════════════════════════════════════════════
# 面名称 → GL 方向向量 (纯数据)
# ═══════════════════════════════════════════════════════════════

FACE_LOOK_DIRECTIONS: dict[str, np.ndarray] = {
    'front':    np.array([ 0.0,  0.0,  1.0], dtype=np.float32),
    'back':     np.array([ 0.0,  0.0, -1.0], dtype=np.float32),
    'right':    np.array([ 1.0,  0.0,  0.0], dtype=np.float32),
    'left':     np.array([-1.0,  0.0,  0.0], dtype=np.float32),
    'top':      np.array([ 0.0,  1.0,  0.0], dtype=np.float32),
    'bottom':   np.array([ 0.0, -1.0,  0.0], dtype=np.float32),
}

_FACE_CN: dict[str, str] = {
    'front': '前 (Front)', 'back': '后 (Back)',
    'left': '左 (Left)', 'right': '右 (Right)',
    'top': '顶 (Top)', 'bottom': '底 (Bottom)',
}


def _print_camera_state(cam, tag: str = ""):
    proj_type = "ORTHO" if cam.is_orthographic else "PERSP"
    print(
        f"[CAM {tag}] {proj_type}"
        f"  yaw={cam.yaw:.4f} ({math.degrees(cam.yaw):.1f}°)"
        f"  pitch={cam.pitch:.4f} ({math.degrees(cam.pitch):.1f}°)"
        f"  dist={cam.distance:.2f}")


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
        1024, 768, "ViewGizmo (ZenGL) — TAB: 2D/3D Toggle", None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 夹具 ──
    h = TestHarness("ViewGizmo (ZenGL)")
    h.set_window(window)
    h.init_engine()

    fbw, fbh = glfw.get_framebuffer_size(window)
    renderer = ZenGLRenderer
    renderer.viewport_width = fbw
    renderer.viewport_height = fbh
    renderer.aspect_ratio = fbw / fbh if fbh else 1.0
    ZenGLCore.init_core((fbw, fbh))
    ZenGLRenderer._command_queue = CommandQueue()
    h.set_renderer(renderer)
    h.patch_default_shader_440()
    print(f"[ZenGL] Renderer {renderer.viewport_width}×{renderer.viewport_height}")

    # ── 场景 ──
    setup_default_scene(renderer, with_grid=True, with_gizmo=True)

    # ── 摄像机 ──
    cam = h.create_test_camera()
    cam.distance = 15.0
    h.inject_mock_camera(cam)

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam)

    def on_key(key, sc, act, mods):
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_TAB:
            result = cam.toggle_2d_3d()
            mode = "2D ORTHO" if result == '2d' else "3D PERSP"
            print(f"[MODE] {mode}")
            _print_camera_state(cam, "TOGGLE")

    def on_mouse_button(button, action, mods, x, y):
        if button != glfw.MOUSE_BUTTON_LEFT: return
        if action != glfw.RELEASE: return
        if not pipeline.click_detected(x, y):
            return  # 拖拽, 非点击
        try:
            pick_type, pick_value = renderer.pick_at(x, y)
        except Exception:
            pick_type, pick_value = None, None
        if pick_type == 'overlay' and pick_value:
            prefix = ViewGizmo.OVERLAY_KEY_PREFIX
            if pick_value.startswith(prefix):
                face_name = pick_value.rsplit('_', 1)[-1]
                direction = FACE_LOOK_DIRECTIONS.get(face_name)
                if direction is not None:
                    if cam.is_orthographic:
                        cam.set_3d_perspective_view()
                    cam.look_from_direction(direction)
                    cn = _FACE_CN.get(face_name, face_name)
                    print(f"[CAM] {cn}  yaw={cam.yaw:.3f} pitch={cam.pitch:.3f}")
                else:
                    print(f"[CAM] Unknown face: '{face_name}'")
            else:
                print(f"[PICK OVERLAY] key='{pick_value}'")
        elif pick_type == 'entity':
            print(f"[PICK ENTITY] entity_id={pick_value}")
        else:
            print(f"[PICK] nothing at ({x:.0f},{y:.0f})")

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button

    # ── 主循环 (ZenGL: skip_cmd_queue) ──
    print("[ZenGL ViewGizmo] Ready. TAB=2D/3D toggle.")
    _print_camera_state(cam, "INIT")
    h.run_loop(cam, skip_cmd_queue=True)

    # ── 清理 ──
    unregister_view_gizmo(renderer)
    h.shutdown()
    print("[ZenGL] Done")


if __name__ == "__main__":
    main()
