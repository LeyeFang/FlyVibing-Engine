"""
Test: TransformGizmo — 三轴箭头 + 三平面平移手柄
══════════════════════════════════════════════════════

功能:
  ★ TransformGizmo 注册: 3 轴箭头 + 3 平面手柄
  ★ 点击实体 → 选中 + gizmo 定位到实体位置
  ★ 点击 gizmo 轴 → 开始沿轴拖动平移
  ★ 点击 gizmo 平面 → 开始平面内拖动平移
  ★ 空格清除选中 (gizmo 定位到原点)

操作:
  中键拖拽  = 轨道旋转 (与主线一致)
  左键点击  = 拾取: 实体选中 / gizmo 轴拖动 / 空白清除选中
  滚轮      = 缩放
  G 键      = 显示/隐藏 TransformGizmo
  TAB 键    = 2D 正交俯视 / 3D 透视切换
  X 键      = 切换 X-Ray 轮廓
  空格      = 清除选中
  ESC       = 退出

运行: python Test/Application/Editor/test_transform_gizmo_opengl.py
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

from Test._test_harness import TestHarness
from Test._test_scene import (
    setup_default_scene,
    unregister_view_gizmo, unregister_outliner_id,
)


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 夹具 ──
    h = TestHarness("TransformGizmo — Axis/Plane Drag Test")
    h.create_window()
    h.init_engine()
    h.patch_default_shader_440()
    renderer = h.create_renderer()

    # ── 场景: 立方体 + Grid + ViewGizmo + OutlinerID ──
    entity_ids = setup_default_scene(
        renderer, with_grid=True, with_gizmo=True, with_outliner=True)

    # ── TransformGizmo: 默认隐藏, 按 G 键在选中实体位置显示 ──

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
    _orig_drag = pipeline.on_drag  # 保存预设的 on_drag (中键=orbit)

    def on_key(key, sc, act, mods):
        nonlocal selected, xray, gizmo_shown
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            if gizmo_shown:
                TransformGizmo.hide(); gizmo_shown = False
            else:
                glfw.set_window_should_close(h.window, True)
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
            print(f"[MODE] Switched to {'2D ORTHO' if result == '2d' else '3D PERSP'}")
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
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
            print(f"  [DBG-TEST] PRESS pick: type={pick_type} value={pick_value} at ({x},{y})")
            gizmo_info = None
            if pick_type == 'overlay' and pick_value:
                gizmo_info = TransformGizmo.parse_pick_key(pick_value)

            if gizmo_info and selected:
                print(f"  [DBG-TEST] gizmo hit: kind={gizmo_info['kind']} name={gizmo_info['name']}")
                eid = next(iter(selected))
                t = SceneManager.GetEntityTransform(eid)
                entity_pos = np.array(
                    [t.position_x, t.position_y, t.position_z], dtype=np.float32)
                print(f"  [DBG-TEST] entity_pos=({entity_pos[0]:.2f},{entity_pos[1]:.2f},{entity_pos[2]:.2f})")
                print(f"  [DBG-TEST] cam_pos=({cam.position[0]:.2f},{cam.position[1]:.2f},{cam.position[2]:.2f})")
                print(f"  [DBG-TEST] vp={vp_w}x{vp_h}")
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
                    print(f"[DRAG AXIS] axis={gizmo_info['name']}, entity={eid}")
                elif gizmo_info['kind'] == 'plane':
                    d1, d2 = gizmo_info['gl_dirs']
                    TransformGizmo.begin_plane_drag(
                        entity_pos, d1, d2, ray_o, ray_d)
                    print(f"[DRAG PLANE] plane={gizmo_info['name']}, entity={eid}")
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

                    gizmo_info = TransformGizmo.parse_pick_key(pick_value)
                    if gizmo_info:
                        print(f"[GIZMO CLICK] {gizmo_info['kind']}={gizmo_info['name']} (no drag)")
                        return

                    print(f"[PICK OVERLAY] key='{pick_value}'")
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
                        for eid in old:
                            DeselectEntityEvent.Pack(eid)
                        update_gizmo_position()
                        print(f"[PICK] cleared {sorted(old)}")
                sync()

    def on_drag(button, dx, dy, x, y):
        if TransformGizmo.is_dragging():
            print(f"  [DBG-TEST] on_drag: gizmo dragging at ({x},{y}) dx={dx:.1f} dy={dy:.1f}")
            vp_w = renderer.viewport_width
            vp_h = renderer.viewport_height
            view_mat = cam.get_view_matrix()
            proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
            ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                x, y, vp_w, vp_h, view_mat, proj_mat)

            new_pos = TransformGizmo.update_drag(ray_o, ray_d)
            if new_pos is not None:
                print(f"  [DBG-TEST] on_drag: applying pos=({new_pos[0]:.2f},{new_pos[1]:.2f},{new_pos[2]:.2f})")
                selected_id = next(iter(selected)) if selected else None
                if selected_id is not None:
                    SceneManager.SetEntityTransform(
                        selected_id,
                        position_xyz=(float(new_pos[0]), float(new_pos[1]), float(new_pos[2])))
                    TransformGizmo.set_target_position(new_pos)
            else:
                print(f"  [DBG-TEST] on_drag: update_drag returned None")
            return

        # 非 gizmo 拖拽 → 交给主线预设 (中键=orbit/pan)
        _orig_drag(button, dx, dy, x, y)

    def on_move(x, y):
        renderer.update_pick_mouse(x, y)

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    pipeline.on_drag = on_drag
    pipeline.on_move = on_move
    sync()
    update_gizmo_position()

    # ── 主循环 ──
    print("[TEST] Ready. Click entity → gizmo appears. Drag axis/plane to translate.")
    h.run_loop(cam)

    # ── 清理 ──
    TransformGizmo.unregister_from(renderer)
    unregister_view_gizmo(renderer)
    unregister_outliner_id(renderer)
    h.shutdown()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
