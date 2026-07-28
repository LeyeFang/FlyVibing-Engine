"""
Test: TransformGizmo — 三种变换模式 (G/R/S 键切换)
══════════════════════════════════════════════════════

功能:
  ★ G 键 → GRAB 模式 (position): 三轴箭头 + 三平面手柄
  ★ R 键 → ROTATE 模式: 三色旋转环 + θ=0 处圆点手柄
  ★ S 键 → SCALE 模式: 三轴圆 + 均匀缩放圆 (始终面朝摄像机)

选取逻辑 (对齐主线):
  ★ 鼠标点击实体          → 选中 + 轮廓高亮 (不显示 gizmo)
  ★ G/R/S 键              → 切换模式 + 在已选中实体上显示 gizmo
  ★ 点击空白处             → 取消选中 + 隐藏 gizmo
  ★ 点击 gizmo 手柄并拖动  → 变换实体

操作:
  中键拖拽  = 轨道旋转
  滚轮      = 缩放
  TAB 键    = 2D/3D 切换
  X 键      = X-Ray 轮廓
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
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo, GizmoMode
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
    gizmo_shown: bool = False

    def sync():
        """同步选中集合到 OutlinerID (轮廓高亮)。"""
        OutlinerID.set_selected_entities(selected)

    def update_gizmo_position():
        if selected:
            eid = next(iter(selected))
            try:
                t = SceneManager._current().GetEntityTransform(eid)
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
        nonlocal selected, gizmo_shown
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            if gizmo_shown:
                TransformGizmo.hide(); gizmo_shown = False
            else:
                glfw.set_window_should_close(h.window, True)
            return
        elif key in (glfw.KEY_G, glfw.KEY_R, glfw.KEY_S):
            if key == glfw.KEY_G:
                TransformGizmo.set_mode(GizmoMode.GRAB)
                mode_name = "GRAB"
            elif key == glfw.KEY_R:
                TransformGizmo.set_mode(GizmoMode.ROTATE)
                mode_name = "ROTATE"
            else:
                TransformGizmo.set_mode(GizmoMode.SCALE)
                mode_name = "SCALE"
            # ★ G/R/S 仅切换模式; 若已选中实体则刷新 gizmo
            if selected:
                eid = next(iter(selected))
                if gizmo_shown:
                    TransformGizmo.hide()
                TransformGizmo.show(renderer, eid)
                gizmo_shown = True
                update_gizmo_position()
                sync()
                t = SceneManager._current().GetEntityTransform(eid)
                print(f"[GIZMO] mode={mode_name} entity={eid} "
                      f"pos=({t.position_x:.2f},{t.position_y:.2f},{t.position_z:.2f}) "
                      f"rot=({t.rotation_x:.2f},{t.rotation_y:.2f},{t.rotation_z:.2f}) "
                      f"scl=({t.scale_x:.2f},{t.scale_y:.2f},{t.scale_z:.2f})")
            else:
                print(f"[GIZMO] mode={mode_name} (no entity selected)")
            return
        elif key == glfw.KEY_TAB:
            result = cam.toggle_2d_3d()
            print(f"[MODE] Switched to {'2D ORTHO' if result == '2d' else '3D PERSP'}")
            return
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected); selected.clear()
                for eid in old:
                    DeselectEntityEvent.Pack(eid)
                if gizmo_shown:
                    TransformGizmo.hide(); gizmo_shown = False
                sync(); update_gizmo_position()
                print(f"[CLEAR] deselected {sorted(old)}")
            return

    def on_mouse_button(button, action, mods, x, y):
        nonlocal selected, gizmo_shown

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
                t = SceneManager._current().GetEntityTransform(eid)
                entity_pos = np.array(
                    [t.position_x, t.position_y, t.position_z], dtype=np.float32)

                view_mat = cam.get_view_matrix()
                proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
                ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                    x, y, vp_w, vp_h, view_mat, proj_mat)

                kind = gizmo_info['kind']
                if kind == 'axis':
                    TransformGizmo.begin_axis_drag(
                        entity_pos, gizmo_info['gl_dir'], cam.position, ray_o, ray_d)
                    print(f"[DRAG AXIS] axis={gizmo_info['name']}, entity={eid}")
                elif kind == 'plane':
                    d1, d2 = gizmo_info['gl_dirs']
                    TransformGizmo.begin_plane_drag(
                        entity_pos, d1, d2, ray_o, ray_d)
                    print(f"[DRAG PLANE] plane={gizmo_info['name']}, entity={eid}")
                elif kind == 'ring':
                    TransformGizmo.begin_ring_drag(
                        entity_pos, gizmo_info['gl_dir'], cam.position, ray_o, ray_d)
                    print(f"[DRAG RING] axis={gizmo_info['name']}, entity={eid}")
                elif kind in ('scale_axis', 'scale_uniform'):
                    gl_dir = gizmo_info.get('gl_dir') if kind == 'scale_axis' else None
                    t_scl = SceneManager._current().GetEntityTransform(eid)
                    current_scale = (t_scl.scale_x, t_scl.scale_y, t_scl.scale_z)
                    TransformGizmo.begin_scale_drag(
                        entity_pos, gl_dir, ray_o, ray_d, current_scale)
                    print(f"[DRAG SCALE] {gizmo_info['name']}, entity={eid}")
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
                    old_sel = set(selected)
                    selected = {pid}
                    if pid not in old_sel:
                        SelecteEntityEvent.Pack(pid)
                    update_gizmo_position()
                    # ★ G/R/S 按住点击 → 选中 + gizmo
                    if glfw.get_key(h.window, glfw.KEY_G) == glfw.PRESS:
                        TransformGizmo.set_mode(GizmoMode.GRAB)
                    elif glfw.get_key(h.window, glfw.KEY_R) == glfw.PRESS:
                        TransformGizmo.set_mode(GizmoMode.ROTATE)
                    elif glfw.get_key(h.window, glfw.KEY_S) == glfw.PRESS:
                        TransformGizmo.set_mode(GizmoMode.SCALE)
                    else:
                        # 纯点击: 仅选中, 不显示 gizmo
                        t = SceneManager._current().GetEntityTransform(pid)
                        print(f"[SELECT] entity={pid} "
                              f"pos=({t.position_x:.2f},{t.position_y:.2f},{t.position_z:.2f}) "
                              f"rot=({t.rotation_x:.2f},{t.rotation_y:.2f},{t.rotation_z:.2f}) "
                              f"scl=({t.scale_x:.2f},{t.scale_y:.2f},{t.scale_z:.2f}) "
                              f"(gizmo=off)")
                        sync()
                        return
                    # G/R/S held: 显示 gizmo
                    if gizmo_shown:
                        TransformGizmo.hide()
                    TransformGizmo.show(renderer, pid)
                    gizmo_shown = True
                    sync()
                    t = SceneManager._current().GetEntityTransform(pid)
                    print(f"[SELECT+GIZMO] entity={pid} "
                          f"pos=({t.position_x:.2f},{t.position_y:.2f},{t.position_z:.2f}) "
                          f"rot=({t.rotation_x:.2f},{t.rotation_y:.2f},{t.rotation_z:.2f}) "
                          f"scl=({t.scale_x:.2f},{t.scale_y:.2f},{t.scale_z:.2f})")
                else:
                    if selected:
                        old = set(selected); selected.clear()
                        for eid in old:
                            DeselectEntityEvent.Pack(eid)
                        if gizmo_shown:
                            TransformGizmo.hide(); gizmo_shown = False
                        update_gizmo_position()
                        print(f"[DESELECT] cleared {sorted(old)}")
                sync()

    _drag_frame: int = 0

    def on_drag(button, dx, dy, x, y):
        nonlocal _drag_frame
        if TransformGizmo.is_dragging():
            vp_w = renderer.viewport_width
            vp_h = renderer.viewport_height
            view_mat = cam.get_view_matrix()
            proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
            ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                x, y, vp_w, vp_h, view_mat, proj_mat)

            result = TransformGizmo.update_drag(ray_o, ray_d)
            if result is None:
                return

            selected_id = next(iter(selected)) if selected else None
            if selected_id is None:
                return

            mode = TransformGizmo.get_mode()
            if mode == GizmoMode.GRAB:
                new_pos = np.asarray(result, dtype=np.float32)
                SceneManager._current().SetEntityTransform(
                    selected_id,
                    position_xyz=(float(new_pos[0]), float(new_pos[1]), float(new_pos[2])))
                TransformGizmo.set_target_position(new_pos)
                if _drag_frame % 30 == 0:
                    t = SceneManager._current().GetEntityTransform(selected_id)
                    print(f"[DRAG-GRAB] frame={_drag_frame} pos=({t.position_x:.2f},{t.position_y:.2f},{t.position_z:.2f})")
            elif mode == GizmoMode.ROTATE:
                delta_euler = np.asarray(result, dtype=np.float32)
                t = SceneManager._current().GetEntityTransform(selected_id)
                new_rot = (
                    t.rotation_x + float(delta_euler[0]),
                    t.rotation_y + float(delta_euler[1]),
                    t.rotation_z + float(delta_euler[2]),
                )
                SceneManager._current().SetEntityTransform(selected_id, rotation_xyz=new_rot)
                if _drag_frame % 30 == 0:
                    t2 = SceneManager._current().GetEntityTransform(selected_id)
                    print(f"[DRAG-ROT] frame={_drag_frame} "
                          f"pos=({t2.position_x:.3f},{t2.position_y:.3f},{t2.position_z:.3f}) "
                          f"rot=({t2.rotation_x:.3f},{t2.rotation_y:.3f},{t2.rotation_z:.3f})")
            elif mode == GizmoMode.SCALE:
                SceneManager._current().SetEntityTransform(
                    selected_id,
                    scale_xyz=(float(result[0]), float(result[1]), float(result[2])))
                if _drag_frame % 30 == 0:
                    t2 = SceneManager._current().GetEntityTransform(selected_id)
                    print(f"[DRAG-SCALE] frame={_drag_frame} scl=({t2.scale_x:.3f},{t2.scale_y:.3f},{t2.scale_z:.3f})")
            _drag_frame += 1
            return

        _drag_frame = 0
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
    print("[TEST] Ready. G=Grab R=Rotate S=Scale | Click entity → gizmo appears. Drag handles.")
    h.run_loop(cam)

    # ── 清理 ──
    TransformGizmo.unregister_from(renderer)
    unregister_view_gizmo(renderer)
    unregister_outliner_id(renderer)
    h.shutdown()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
