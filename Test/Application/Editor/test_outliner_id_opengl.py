"""
Test: OutlinerID (ID Buffer) with Mainline OpenGL Renderer
═══════════════════════════════════════════════════════════════════════════════

Blender 风格 ID buffer + Roberts cross 边缘检测轮廓高亮。
使用主线 openGLRenderer。

操作: 中键拖拽=轨道旋转(主线一致) 左键点击=选中/取消 滚轮=缩放 X=X-Ray 空格=清除 ESC=退出
运行: python Test/Application/Editor/test_outliner_id_opengl.py
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

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene, unregister_view_gizmo, unregister_outliner_id


def main():
    # ── 夹具: 窗口 / 引擎 / 渲染器 ──
    h = TestHarness("OpenGL ID Outliner — Click to Select")
    h.create_window()
    h.init_engine()
    h.patch_default_shader_440()
    renderer = h.create_renderer()

    # ── 场景: 3 个立方体 + ViewGizmo + OutlinerID ──
    entity_ids = setup_default_scene(renderer, with_grid=True, with_gizmo=True, with_outliner=True)

    # ── 摄像机 (TestEditorCamera, 注入为 EditorCamera) ──
    cam = h.create_test_camera()
    h.inject_mock_camera(cam)

    # ── 交互状态 (仅保留业务状态, 拖拽由 InputPipeline 管理) ──
    selected: set[int] = set()
    xray: bool = True

    def sync():
        OutlinerID.set_selected_entities(selected)
        OutlinerID.configure(xray=xray, outline_width=3)

    def title():
        s = ",".join(str(i) for i in sorted(selected)) or "none"
        glfw.set_window_title(
            h.window,
            f"ID Outliner [{'XRAY' if xray else 'NORMAL'}] sel=[{s}]")

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam)

    def on_key(key, sc, act, mods):
        nonlocal selected, xray
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(h.window, True)
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                sync(); print(f" Cleared: {sorted(old)}")
            title()
        elif key == glfw.KEY_X:
            xray = not xray; sync(); title()
            print(f"X-Ray: {'ON' if xray else 'OFF'}")

    def on_mouse_button(button, action, mods, x, y):
        nonlocal selected
        if button != glfw.MOUSE_BUTTON_LEFT: return
        if action != glfw.RELEASE: return
        if not pipeline.click_detected(x, y):
            return  # 拖拽, 非点击
        try:
            pt, pv = renderer.pick_at(x, y)
        except Exception:
            pt, pv = None, None
        print(f"[DEBUG] pick_at({x:.0f},{y:.0f}) → type={pt} value={pv}")
        if pt == 'entity' and pv is not None:
            if pv not in selected:
                old = set(selected)
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                selected.clear()
                SelecteEntityEvent.Pack(pv)
                selected.add(pv)
                print(f"[SELECT] entity {pv} (deselected {sorted(old)})")
            else:
                print(f"[CLICK] entity {pv} already selected — no change")
        else:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                print(f"[CLEAR] {sorted(old)}")
        sync(); title()

    def on_move(x, y):
        renderer.update_pick_mouse(x, y)

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    pipeline.on_move = on_move
    sync(); title()
    print("[OpenGL] Ready.")

    # ── 主循环 ──
    h.run_loop(cam)

    # ── 清理 ──
    unregister_view_gizmo(renderer)
    unregister_outliner_id(renderer)
    h.shutdown()
    print("[OpenGL] Done")


if __name__ == "__main__":
    main()
