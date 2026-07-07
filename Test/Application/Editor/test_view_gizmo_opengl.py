"""
Test: ViewGizmo — 2D 正交俯视 / 3D 透视切换 + 面点击视角切换
═══════════════════════════════════════════════════════════════

功能:
  ★ TAB 键一键切换 2D 正交俯视 ↔ 3D 透视
    - 2D 模式: 摄像机 GL (0,-1,0) 方向俯视 GL XZ 平面 (编辑器 XY 平面)
    - 3D 模式: 恢复之前保存的透视视角
  ★ 点击 ViewGizmo 六面 → 摄像机切换至该方向视角
  ★ 实体拾取选中 + X-Ray 轮廓 + 清除选中

操作:
  中键拖拽  = 轨道旋转 (与主线一致)
  左键点击  = 拾取 ViewGizmo 面 → 切换视角 / 拾取实体 → 选中
  滚轮      = 缩放
  TAB 键    = ★ 切换 2D 正交俯视 / 3D 透视
  ESC       = 退出

运行: python Test/Application/Editor/test_view_gizmo_opengl.py
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

from Test._test_harness import TestHarness
from Test._test_scene import (
    setup_default_scene,
    unregister_view_gizmo,
)


# ═══════════════════════════════════════════════════════════════
# 面名称 → GL 方向向量 (纯数据)
# ═══════════════════════════════════════════════════════════════

FACE_LOOK_DIRECTIONS: dict[str, np.ndarray] = {
    'front':    np.array([ 0.0,  0.0,  1.0], dtype=np.float32),  # GL +Z
    'back':     np.array([ 0.0,  0.0, -1.0], dtype=np.float32),  # GL -Z
    'right':    np.array([ 1.0,  0.0,  0.0], dtype=np.float32),  # GL +X
    'left':     np.array([-1.0,  0.0,  0.0], dtype=np.float32),  # GL -X
    'top':      np.array([ 0.0,  1.0,  0.0], dtype=np.float32),  # GL +Y
    'bottom':   np.array([ 0.0, -1.0,  0.0], dtype=np.float32),  # GL -Y
}

_FACE_CN: dict[str, str] = {
    'front':  '前 (Front)',  'back':   '后 (Back)',
    'left':   '左 (Left)',   'right':  '右 (Right)',
    'top':    '顶 (Top)',    'bottom': '底 (Bottom)',
}


def _print_camera_state(cam, tag: str = ""):
    """打印当前摄像机完整状态 (调试用)。"""
    proj_type = "ORTHO" if cam.is_orthographic else "PERSP"
    print(
        f"[V8 CAM {tag}] {proj_type}"
        f"  yaw={cam.yaw:.4f} ({math.degrees(cam.yaw):.1f}°)"
        f"  pitch={cam.pitch:.4f} ({math.degrees(cam.pitch):.1f}°)"
        f"  dist={cam.distance:.2f}"
        f"  pos=({cam.position[0]:.2f},{cam.position[1]:.2f},{cam.position[2]:.2f})"
        f"  target=({cam.target[0]:.2f},{cam.target[1]:.2f},{cam.target[2]:.2f})"
        + (f"  ortho_size={cam._ortho_size:.2f}" if cam.is_orthographic else f"  fov={cam.fov:.1f}°")
    )


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 夹具 ──
    h = TestHarness("ViewGizmo — TAB: 2D/3D Toggle")
    h.create_window()
    h.init_engine()
    h.patch_default_shader_440()
    renderer = h.create_renderer()

    # ── 场景: 立方体 + Grid + ViewGizmo ──
    entity_ids = setup_default_scene(
        renderer, with_grid=True, with_gizmo=True)

    # ── 摄像机 ──
    cam = h.create_test_camera()
    cam.distance = 15.0  # ViewGizmo 测试用稍远距离
    h.inject_mock_camera(cam)

    # ── ★ 输入管线 + 主线预设 ──
    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam)

    def on_key(key, sc, act, mods):
        if act != glfw.PRESS: return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(h.window, True)
        elif key == glfw.KEY_TAB:
            result = cam.toggle_2d_3d()
            if result == '2d':
                print("╔══════════════════════════════════════════╗")
                print("║  ★ SWITCHED TO 2D ORTHO TOP-DOWN VIEW  ║")
                print("╚══════════════════════════════════════════╝")
            else:
                print("╔══════════════════════════════════════════╗")
                print("║  ★ SWITCHED TO 3D PERSPECTIVE VIEW     ║")
                print("╚══════════════════════════════════════════╝")
            _print_camera_state(cam, "TOGGLE")
        elif key == glfw.KEY_U:
            u_dir = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            cam.look_from_direction(u_dir)
            fwd = cam._forward
            print("╔══════════════════════════════════════════════╗")
            print("║  ★ [DEBUG] ViewGizmo U-Face (Top) Params  ║")
            print(f"║  Forward (tgt→cam) = ({fwd[0]:+.4f}, {fwd[1]:+.4f}, {fwd[2]:+.4f})  ║")
            print(f"║  yaw={cam.yaw:.6f}  pitch={cam.pitch:.6f}  dist={cam.distance:.4f}  ║")
            print("╚══════════════════════════════════════════════╝")

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
                    old_yaw, old_pitch = cam.yaw, cam.pitch
                    if cam.is_orthographic:
                        cam.set_3d_perspective_view()
                    cam.look_from_direction(direction)
                    cn = _FACE_CN.get(face_name, face_name)
                    print(
                        f"[V8 CAM] {cn}"
                        f"  yaw: {old_yaw:.3f}→{cam.yaw:.3f}"
                        f"  pitch: {old_pitch:.3f}→{cam.pitch:.3f}"
                        f"  dist: {cam.distance:.2f}")
                else:
                    print(f"[V8 CAM] Unknown face: '{face_name}'")
            else:
                print(f"[PICK OVERLAY] key='{pick_value}'")
        elif pick_type == 'entity':
            print(f"[PICK ENTITY] entity_id={pick_value}")
        else:
            print(f"[PICK] nothing at ({x:.0f},{y:.0f})")

    def on_move(x, y):
        renderer.update_pick_mouse(x, y)

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    pipeline.on_move = on_move

    # ── 主循环 ──
    print("[V8] Ready. Press TAB to toggle 2D ortho / 3D perspective.")
    _print_camera_state(cam, "INIT")
    h.run_loop(cam)

    # ── 清理 ──
    unregister_view_gizmo(renderer)
    h.shutdown()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
