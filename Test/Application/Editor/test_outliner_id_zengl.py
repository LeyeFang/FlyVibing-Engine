"""
Test: OutlinerID (ID Buffer) with ZenGL Renderer
═══════════════════════════════════════════════════════════════════════════════

纯 ZenGL 版本的 Blender 风格 ID buffer + 屏幕空间边缘检测轮廓高亮。
不使用任何 PyOpenGL（除 window 管理）。

验证:
  1. ZenGL MRT 渲染 (color + entity ID via r32uint image)
  2. ZenGL Roberts cross 边缘检测
  3. ZenGL Composite → resolve → blit
  4. 点击实体选中 + X-Ray 切换

操作:
  中键拖拽  = 轨道旋转 (与主线一致)
  左键点击  = 选中/取消选中实体
  滚轮      = 缩放
  X 键      = 切换 X-Ray
  空格      = 清除选中
  ESC       = 退出

运行: python Test/Application/Core/Renderer/zengl/test_outliner_id_zengl.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math, numpy as np, glfw

from Application.Editor.EditorEvent import (
    SelecteEntityEvent, DeselectEntityEvent, ClearSelectionEvent)
from Application.Editor.Gizmos.OutlinerID import OutlinerID

from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene, unregister_view_gizmo, unregister_outliner_id


def main():
    # ── GLFW 窗口 (ZenGL: SAMPLES=0, DEPTH_BITS=0) ──
    if not glfw.init():
        print("glfw.init() failed"); return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES, 0)
    glfw.window_hint(glfw.DEPTH_BITS, 0)

    window = glfw.create_window(
        1024, 768, "ZenGL ID Outliner — click cubes to select", None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 夹具: 引擎初始化 ──
    h = TestHarness("ZenGL ID Outliner")
    h.set_window(window)
    h.init_engine()

    # ── ZenGL 渲染器 ──
    fbw, fbh = glfw.get_framebuffer_size(window)
    renderer = ZenGLRenderer.Create()
    h.set_renderer(renderer)
    h.patch_default_shader_440()
    print(f"[ZenGL] Renderer {renderer.viewport_width}×{renderer.viewport_height}")

    # ── 场景: 3 个立方体 ──
    entity_ids = setup_default_scene(renderer, with_grid=True, with_gizmo=True, with_outliner=True)

    # ── 摄像机 (TestEditorCamera, 注入为 EditorCamera) ──
    cam = h.create_test_camera()
    h.inject_mock_camera(cam)

    # ── 交互状态 (仅保留业务状态, 拖拽由 InputPipeline 管理) ──
    selected: set[int] = set()
    xray: bool = True

    def sync():
        OutlinerID.set_selected_entities(selected)
        OutlinerID.configure(xray=xray)

    def update_title():
        s = ",".join(str(i) for i in sorted(selected)) or "none"
        glfw.set_window_title(
            window,
            f"ZenGL ID Outliner — [{'XRAY' if xray else 'NORMAL'}] sel=[{s}]")

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam)

    def on_key(key, sc, act, mods):
        nonlocal selected, xray
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                sync(); print(f"  Cleared: {sorted(old)}")
            update_title()
        elif key == glfw.KEY_X:
            xray = not xray; sync(); update_title()
            print(f"X-Ray: {'ON' if xray else 'OFF'}")

    def on_mouse_button(button, action, mods, x, y):
        nonlocal selected
        if button != glfw.MOUSE_BUTTON_LEFT: return
        if action != glfw.RELEASE: return
        if not pipeline.click_detected(x, y):
            return  # 拖拽, 非点击
        try:
            pick_type, pick_value = renderer.pick_at(x, y)
        except Exception:
            pick_type, pick_value = None, None
        if pick_type == 'entity' and pick_value is not None:
            if pick_value in selected:
                selected.discard(pick_value)
                DeselectEntityEvent.Pack(pick_value)
                print(f"[DESELECT] entity {pick_value}")
            else:
                SelecteEntityEvent.Pack(pick_value)
                selected.add(pick_value)
                print(f"[SELECT] entity {pick_value}")
        else:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                print(f"[CLEAR] deselect all {sorted(old)}")
        sync(); update_title()

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    sync(); update_title()
    print("[ZenGL] Ready — click to select, X for X-Ray.")

    # ── 主循环 (ZenGL: skip_cmd_queue=True) ──
    h.run_loop(cam, skip_cmd_queue=True)

    # ── 清理 ──
    unregister_view_gizmo(renderer)
    unregister_outliner_id(renderer)
    h.shutdown()
    print("[ZenGL] Done")


if __name__ == "__main__":
    main()
