"""
Test: Camera Gizmo (ZenGL) — 场景摄像机 entity 的 frustum 可视化
═══════════════════════════════════════════════════════════════

验证:
  1. 场景中存在 Camera component 的 entity 自动显示 frustum gizmo
  2. 透视摄像机 → 四棱锥线框 (8 条线段)，始终覆盖实体+outliner
  3. 选中/未选中摄像机显示不同颜色 (浅蓝/灰)
  4. 移动摄像机 entity 时 gizmo 跟随更新
  5. 空格键可临时切换到测试摄像机视角 (再按切回)

操作:
  中键拖拽     = 轨道旋转
  中键+Shift   = 平移注视点
  滚轮         = 缩放
  F1           = 选中/取消选中摄像机 entity
  SPACE        = 切换编辑器摄像机 / 测试摄像机视角
  WASD         = 移动选中的摄像机 entity (世界坐标)
  Q / E        = 升降选中的摄像机 entity
  F4           = 切换 2D/3D 视图
  ESC          = 退出

运行: python Test/Application/Editor/test_camera_gizmo_zengl.py
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math
import numpy as np
import pyrr
import esper
import glfw

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer
from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Scene.GizmoQuery import GizmoQuery
from Application.Core.Scene.BasicComponents import Camera
from Application.Core.Math.Transform import calculate_entity_model
from Application.Editor.Gizmos.CameraFrustum import CameraFrustum
from Application.Core.Renderer.RenderCommand import (
    OverlayRegistrationCommand,
    OverlayUnregistrationCommand,
    SetViewProjectionCommand,
)

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene


# ═══════════════════════════════════════════════════════════════
# Camera Gizmo 刷新
# ═══════════════════════════════════════════════════════════════

class CameraGizmoRunner:
    """管理 camera gizmo overlay 的注册/注销/刷新。"""

    def __init__(self, renderer):
        self._renderer = renderer
        self._registered_keys: set[str] = set()

    def refresh(self, selected_ids: set[int] | None = None) -> None:
        """遍历 ECS 中所有 Camera entity，更新 gizmo overlay。"""
        for key in list(self._registered_keys):
            self._renderer.enqueue(OverlayUnregistrationCommand(key))
        self._registered_keys.clear()

        if selected_ids is None:
            selected_ids = set()

        try:
            cam_list = GizmoQuery.get_camera_gizmos(selected_ids=selected_ids)
        except Exception:
            return

        for cam_data in cam_list:
            # 椎体 (仅透视)
            if cam_data.is_perspective:
                overlay = CameraFrustum.build_overlay(cam_data)
                self._renderer.enqueue(OverlayRegistrationCommand(overlay))
                self._registered_keys.add(overlay.key)

    def cleanup(self) -> None:
        for key in list(self._registered_keys):
            self._renderer.enqueue(OverlayUnregistrationCommand(key))
        self._registered_keys.clear()


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
        1024, 768, "Camera Gizmo (ZenGL) — F1 select, WASD move, F4 2D/3D, ESC exit",
        None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 夹具 ──
    h = TestHarness("Camera Gizmo (ZenGL)")
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
    print(f"[ZenGL] Renderer {renderer.viewport_width}x{renderer.viewport_height}")

    # ── 场景: 3 个立方体 ──
    setup_default_scene(renderer, with_grid=True)

    # ── 测试摄像机: entity 1, 放置到 (5,3,8) 看向原点 ──
    #     引擎约定 M = T @ R (先位移后旋转), world_pos = position @ R
    #     要到达 world_pos=(5,3,8) 且看向原点, 需解 position @ R = (5,3,8)
    #     → position = (5,3,8) @ R^T = (0, 0, √98) ≈ (0, 0, 9.899)
    cam_eid = SceneManager.main_camera_id
    dx, dy, dz = -5.0, -3.0, -8.0   # 摄像机 → 原点方向
    _len = math.sqrt(dx*dx + dy*dy + dz*dz)
    rx = math.atan2(-dy, -dz)        # pitch 绕 X
    ry = math.asin(dx / _len)        # yaw   绕 Y
    rz = 0.0                         # roll  绕 Z
    # 预旋转 position: 使得 world_pos = position @ R = (5,3,8)
    world_target = np.array([5.0, 3.0, 8.0])
    # 构建 R^T (= R 的逆)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    R_T = np.array([
        [cy,           0.0,         -sy],
        [sy*sx,        cx,          cy*sx],
        [sy*cx,       -sx,          cy*cx],
    ])
    pre_pos = world_target @ R_T
    SceneManager.SetEntityTransform(
        cam_eid,
        position_xyz=(float(pre_pos[0]), float(pre_pos[1]), float(pre_pos[2])),
        rotation_xyz=(rx, ry, rz),
    )
    print(f"[Scene] Test camera entity={cam_eid} world_pos=(5,3,8) looking at origin")

    # ── 视图摄像机 (TestEditorCamera, 用于轨道操作) ──
    cam = h.create_test_camera()
    cam.distance = 15.0
    cam.yaw = math.pi * 0.7
    cam.pitch = 0.4
    h.inject_mock_camera(cam)

    # ── Camera Gizmo Runner ──
    selected_eid: int | None = None
    is_2d_mode = False
    use_test_cam_view = False
    gizmo_runner = CameraGizmoRunner(renderer)

    def refresh_gizmos():
        nonlocal selected_eid
        sel_set = {selected_eid} if selected_eid is not None else set()
        gizmo_runner.refresh(selected_ids=sel_set)

    refresh_gizmos()

    # ── 输入管线 ──
    def update_title():
        sel = f"sel={selected_eid}" if selected_eid is not None else "no sel"
        mode = "2D" if is_2d_mode else "3D"
        view = "[TEST CAM]" if use_test_cam_view else "[EDITOR]"
        glfw.set_window_title(
            window, f"Camera Gizmo (ZenGL) — {view} {mode} {sel}")

    pipeline = h.create_input_pipeline()
    pipeline.setup_editor_camera(cam, after_camera=update_title)

    def on_key(key, scancode, action, mods):
        nonlocal selected_eid, is_2d_mode, use_test_cam_view
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_F1:
            selected_eid = cam_eid if selected_eid is None else None
            print(f"[Select] {'entity ' + str(cam_eid) if selected_eid is not None else 'cleared'}")
            refresh_gizmos()
            update_title()
        elif key == glfw.KEY_SPACE:
            use_test_cam_view = not use_test_cam_view
            mode_str = "TEST CAM" if use_test_cam_view else "EDITOR CAM"
            print(f"[View] Switched to {mode_str}")
            update_title()
        elif key == glfw.KEY_F4:
            mode = cam.toggle_2d_3d()
            is_2d_mode = (mode == '2d')
            print(f"[View] Switched to {mode.upper()}")
            update_title()
        elif key in (glfw.KEY_W, glfw.KEY_A, glfw.KEY_S, glfw.KEY_D, glfw.KEY_Q, glfw.KEY_E):
            if selected_eid is None:
                return
            step = 0.5
            dx = -step if key == glfw.KEY_A else step if key == glfw.KEY_D else 0.0
            dy =  step if key == glfw.KEY_E else -step if key == glfw.KEY_Q else 0.0
            dz = -step if key == glfw.KEY_W else step if key == glfw.KEY_S else 0.0
            t = SceneManager.GetEntityTransform(selected_eid)
            SceneManager.SetEntityTransform(
                selected_eid,
                position_xyz=(t.position_x + dx, t.position_y + dy, t.position_z + dz),
            )
            refresh_gizmos()
            update_title()

    pipeline.on_key = on_key
    update_title()

    # ── 主循环 ──
    while not glfw.window_should_close(window):
        glfw.poll_events()
        aspect = fbw / fbh if fbh else 1.0

        if use_test_cam_view:
            # ── 从测试摄像机 entity 的 Transform 计算 view 矩阵 ──
            t = SceneManager.GetEntityTransform(cam_eid)
            model = calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )
            view = np.linalg.inv(model)
            # ── 从 Camera 组件获取投影参数 ──
            cam_comp = esper.component_for_entity(cam_eid, Camera)
            proj = pyrr.matrix44.create_perspective_projection(
                cam_comp.fov,
                aspect,
                cam_comp.near_plane,
                cam_comp.far_plane,
            )
            renderer.enqueue(SetViewProjectionCommand(
                view=view,
                proj=proj,
                orbit_target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
                orbit_distance=float(np.linalg.norm([t.position_x, t.position_y, t.position_z])),
            ))
        else:
            renderer.enqueue(SetViewProjectionCommand(
                view=cam.get_view_matrix(),
                proj=cam.get_projection_matrix(aspect),
                orbit_target=cam.target,
                orbit_distance=cam.distance,
            ))

        renderer.StartFrame()
        renderer.EndFrame()
        glfw.swap_buffers(window)

    gizmo_runner.cleanup()
    renderer.Shutdown()
    glfw.destroy_window(window)
    glfw.terminate()
    print("[ZenGL] Done")


if __name__ == '__main__':
    main()
