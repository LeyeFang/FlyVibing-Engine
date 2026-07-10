"""
Test: TransformGizmo (ZenGL) — 三轴箭头 + 三平面平移手柄
══════════════════════════════════════════════════════

ZenGL 渲染后端版本。

功能:
  ★ TransformGizmo 注册: 3 轴箭头 + 3 平面手柄
  ★ 点击实体 → 选中 + gizmo 定位到实体位置
  ★ 点击 gizmo 轴 → 沿轴拖动平移
  ★ 点击 gizmo 平面 → 平面内拖动平移

操作: 左键拖拽=旋转 左键点击=拾取 滚轮=缩放 TAB=2D/3D X=X-Ray 空格=清除 ESC=退出
运行: python Test/Application/Editor/test_transform_gizmo_zengl.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math, numpy as np, glfw

from Application.Core.Scene.SceneManager import SceneManager
from Application.Editor.EditorEvent import (
    SelecteEntityEvent, DeselectEntityEvent, ClearSelectionEvent)
from Application.Editor.Gizmos.ViewGizmo import ViewGizmo
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
from Application.Editor.Gizmos.OutlinerID import OutlinerID

from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer

from Test._test_harness import TestHarness
from Test._test_scene import (
    setup_default_scene,
    unregister_view_gizmo, unregister_outliner_id,
)


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

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
        1024, 768, "TransformGizmo (ZenGL) — Axis/Plane Drag", None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    # ── 夹具 ──
    h = TestHarness("TransformGizmo (ZenGL)")
    h.set_window(window)
    h.init_engine()
    fbw, fbh = glfw.get_framebuffer_size(window)
    renderer = ZenGLRenderer.Create()
    h.set_renderer(renderer)
    h.patch_default_shader_440()
    print(f"[ZenGL] Renderer {renderer.viewport_width}×{renderer.viewport_height}")
    # ── 场景 ──
    setup_default_scene(renderer, with_grid=True, with_gizmo=True, with_outliner=True)
    # TransformGizmo: 默认隐藏, 按 G 键在选中实体位置显示
    # ── 摄像机 ──
    cam = h.create_test_camera()
    cam.distance = 15.0
    h.inject_mock_camera(cam)
    # ── 交互状态 ──
    selected: set[int] = set()
    xray: bool = True
    gizmo_shown: bool = False

    def sync():
        OutlinerID.set_selected_entities(selected)
        OutlinerID.configure(xray=xray, outline_width=3)

    def update_gizmo_position():
        if selected:
            eid = next(iter(selected))
            try:
                t = SceneManager.GetEntityTransform(eid)
                TransformGizmo.set_target_position(
                    (t.position_x, t.position_y, t.position_z))
                return
            except Exception:
                pass
        TransformGizmo.set_target_position((0.0, 0.0, 0.0))

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam)
    _orig_drag = pipeline.on_drag

    def on_key(key, sc, act, mods):
        nonlocal selected, xray, gizmo_shown
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            if gizmo_shown:
                TransformGizmo.hide(); gizmo_shown = False
            else:
                glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_G:
            if gizmo_shown:
                TransformGizmo.hide(); gizmo_shown = False
                print("[GIZMO] hidden")
            elif selected:
                eid = next(iter(selected))
                TransformGizmo.show(renderer, eid)
                gizmo_shown = True
                print(f"[GIZMO] shown at entity {eid}")
        elif key == glfw.KEY_TAB:
            result = cam.toggle_2d_3d()
            print(f"[MODE] {'2D ORTHO' if result == '2d' else '3D PERSP'}")
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected); selected.clear()
                for eid in old: DeselectEntityEvent.Pack(eid)
                sync(); update_gizmo_position()
                print(f"  (Cleared: {sorted(old)})")
        elif key == glfw.KEY_X:
            xray = not xray; sync()
            print(f"[MODE] X-Ray={'ON' if xray else 'OFF'}")

    def on_mouse_button(button, action, mods, x, y):
        nonlocal selected

        if button != glfw.MOUSE_BUTTON_LEFT: return
        vp_w = renderer.viewport_width
        vp_h = renderer.viewport_height

        if action == glfw.PRESS:
            pick_type, pick_value = renderer.pick_at(x, y)
            gizmo_info = None
            if pick_type == 'overlay' and pick_value:
                gizmo_info = TransformGizmo.parse_pick_key(pick_value)

            if gizmo_info and selected:
                eid = next(iter(selected))
                t = SceneManager.GetEntityTransform(eid)
                entity_pos = np.array(
                    [t.position_x, t.position_y, t.position_z], dtype=np.float32)

                view_mat = cam.get_view_matrix()
                proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
                ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                    x, y, vp_w, vp_h, view_mat, proj_mat)

                if gizmo_info['kind'] == 'axis':
                    TransformGizmo.begin_axis_drag(
                        entity_pos, gizmo_info['gl_dir'], cam.position, ray_o, ray_d)
                    print(f"[DRAG AXIS] {gizmo_info['name']}, entity={eid}")
                elif gizmo_info['kind'] == 'plane':
                    d1, d2 = gizmo_info['gl_dirs']
                    TransformGizmo.begin_plane_drag(
                        entity_pos, d1, d2, ray_o, ray_d)
                    print(f"[DRAG PLANE] {gizmo_info['name']}, entity={eid}")
                return

        else:  # RELEASE
            if TransformGizmo.is_dragging():
                TransformGizmo.end_drag()
                return

            if abs(x - pipeline._press_mx) < 4 and abs(y - pipeline._press_my) < 4:
                pick_type, pick_value = renderer.pick_at(x, y)

                if pick_type == 'overlay' and pick_value:
                    prefix = ViewGizmo.OVERLAY_KEY_PREFIX
                    if pick_value.startswith(prefix):
                        face_name = pick_value.rsplit('_', 1)[-1]
                        direction = ViewGizmo.FACE_LOOK_DIRECTIONS.get(face_name)
                        if direction is not None:
                            if cam.is_orthographic:
                                cam.set_3d_perspective_view()
                            cam.look_from_direction(direction)
                            print(f"[VIEWGIZMO] face={face_name}")
                        return
                    gi = TransformGizmo.parse_pick_key(pick_value)
                    if gi:
                        print(f"[GIZMO CLICK] {gi['kind']}={gi['name']}")
                        return
                    return

                elif pick_type == 'entity':
                    pid = pick_value
                    print(f"[PICK ENTITY] entity_id={pid}")
                    SelecteEntityEvent.Pack(pid)
                    selected = {pid}
                    update_gizmo_position()
                else:
                    if selected:
                        old = set(selected); selected.clear()
                        for eid in old: DeselectEntityEvent.Pack(eid)
                        update_gizmo_position()
                        print(f"[PICK] cleared {sorted(old)}")
                sync()

    def on_drag(button, dx, dy, x, y):
        if TransformGizmo.is_dragging():
            vp_w = renderer.viewport_width
            vp_h = renderer.viewport_height
            view_mat = cam.get_view_matrix()
            proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
            ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                x, y, vp_w, vp_h, view_mat, proj_mat)

            new_pos = TransformGizmo.update_drag(ray_o, ray_d)
            if new_pos is not None:
                selected_id = next(iter(selected)) if selected else None
                if selected_id is not None:
                    SceneManager.SetEntityTransform(
                        selected_id,
                        position_xyz=(float(new_pos[0]), float(new_pos[1]), float(new_pos[2])))
                    TransformGizmo.set_target_position(new_pos)
            return

        # 非 gizmo 拖拽 → 交给主线预设 (中键=orbit/pan)
        _orig_drag(button, dx, dy, x, y)

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    pipeline.on_drag = on_drag
    sync()
    update_gizmo_position()

    # ── 主循环 (ZenGL: skip_cmd_queue) ──
    print("[ZenGL TransformGizmo] Ready. Click entity → gizmo appears.")
    h.run_loop(cam, skip_cmd_queue=True)

    # ── 清理 ──
    TransformGizmo.unregister_from(renderer)
    unregister_view_gizmo(renderer)
    unregister_outliner_id(renderer)
    h.shutdown()
    print("[ZenGL] Done")


if __name__ == "__main__":
    main()
