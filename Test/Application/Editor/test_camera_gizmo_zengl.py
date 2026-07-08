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
  左键拖拽     = TransformGizmo 轴/面拖动
  左键点击     = 拾取 entity / gizmo 手柄
  中键拖拽     = 轨道旋转
  中键+Shift   = 平移注视点
  滚轮         = 缩放
  G            = 选中/取消选中摄像机 entity
  SPACE        = 切换编辑器摄像机 / 测试摄像机视角
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
import _path_setup  # noqa: E402  # pyright: ignore[reportUnusedImport]

import math
import numpy as np
import pyrr  # type: ignore[import-untyped]
import esper
import glfw  # type: ignore[import-untyped]

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer
from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Scene.GizmoQuery import CameraGizmoData, GizmoQuery
from Application.Core.Scene.BasicComponents import Camera, ProjectionType
from Application.Core.Math.Transform import calculate_entity_model
from Application.Editor.Gizmos.CameraFrustum import CameraFrustum
from Application.Editor.Gizmos.Camera2DBoundary import Camera2DBoundary
from Application.Editor.Gizmos.CameraIconGizmo import CameraIconGizmo
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
from Application.Core.Renderer.RenderCommand import (
    OverlayRegistrationCommand,
    OverlayUnregistrationCommand,
    SetViewProjectionCommand,
)

from Test._test_harness import TestHarness
from Test._test_scene import setup_default_scene  # type: ignore[reportUnknownVariableType]


# ═══════════════════════════════════════════════════════════════
# Camera Gizmo 刷新
# ═══════════════════════════════════════════════════════════════

class CameraGizmoRunner:
    """管理 camera gizmo overlay 的注册/注销/刷新 (椎体线框 + 原点图标)。"""

    def __init__(self, renderer: type[ZenGLRenderer]) -> None:
        self._renderer = renderer
        self._registered_keys: set[str] = set()

    @staticmethod
    def _compute_world_position(cam_data: CameraGizmoData) -> tuple[float, float, float]:
        """根据 T@R 约定计算 entity 原点在 world space 中的实际位置。"""
        model = calculate_entity_model(
            position=cam_data.position,
            rotation=cam_data.rotation,
            scale=cam_data.scale,
        )
        return (float(model[3, 0]), float(model[3, 1]), float(model[3, 2]))

    def refresh(self, selected_ids: set[int] | None = None,
                exclude_ids: set[int] | None = None) -> None:
        """遍历 ECS 中所有 Camera entity，更新 gizmo overlay。

        Args:
            selected_ids: 当前选中的 entity ID 集合。
            exclude_ids: 排除的 entity ID 集合 (不同模式的摄像机 + 预览自身)。
        """
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
            if exclude_ids and cam_data.entity_id in exclude_ids:
                continue  # 不同模式 / 预览自身 → 跳过

            if cam_data.is_perspective:
                # ── 3D: 椎体线框 + 原点图标 ──
                overlay = CameraFrustum.build_overlay(cam_data)
                self._renderer.enqueue(OverlayRegistrationCommand(overlay))
                self._registered_keys.add(overlay.key)

                world_pos = self._compute_world_position(cam_data)
                icon_overlay = CameraIconGizmo.build_icon_overlay(
                    cam_data.entity_id, world_pos,
                )
                self._renderer.enqueue(OverlayRegistrationCommand(icon_overlay))
                self._registered_keys.add(icon_overlay.key)
            else:
                # ── 2D: 正交边界框 (无图标、无椎体) ──
                overlay = Camera2DBoundary.build_overlay(cam_data)
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
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)  # type: ignore[reportUnknownMemberType]
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)  # type: ignore[reportUnknownMemberType]
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)  # type: ignore[reportUnknownMemberType]
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)  # type: ignore[reportUnknownMemberType]
    glfw.window_hint(glfw.SAMPLES, 0)  # type: ignore[reportUnknownMemberType]
    glfw.window_hint(glfw.DEPTH_BITS, 0)  # type: ignore[reportUnknownMemberType]

    window = glfw.create_window(  # type: ignore[reportUnknownMemberType]
        1024, 768, "Camera Gizmo (ZenGL) — F1 select, WASD move, F4 2D/3D, ESC exit",
        None, None)
    if not window: glfw.terminate(); return
    glfw.make_context_current(window)  # type: ignore[reportUnknownMemberType]
    glfw.swap_interval(1)  # type: ignore[reportUnknownMemberType]

    # ── 夹具 ──
    h = TestHarness("Camera Gizmo (ZenGL)")
    h.set_window(window)  # type: ignore[reportUnknownMemberType]
    h.init_engine()

    fbw, fbh = glfw.get_framebuffer_size(window)  # type: ignore[reportUnknownMemberType]
    renderer = ZenGLRenderer
    renderer.viewport_width = fbw
    renderer.viewport_height = fbh
    renderer.aspect_ratio = fbw / fbh if fbh else 1.0
    ZenGLCore.init_core((fbw, fbh))
    ZenGLRenderer._command_queue = CommandQueue()  # pyright: ignore[reportPrivateUsage]
    h.set_renderer(renderer)  # type: ignore[reportUnknownMemberType]
    h.patch_default_shader_440()
    print(f"[ZenGL] Renderer {renderer.viewport_width}x{renderer.viewport_height}")

    # ── 场景: 3 个立方体 ──
    setup_default_scene(renderer, with_grid=True)  # type: ignore[reportUnknownArgumentType]

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
    SceneManager.SetEntityTransform(  # type: ignore[reportUnknownMemberType]
        cam_eid,
        position_xyz=(float(pre_pos[0]), float(pre_pos[1]), float(pre_pos[2])),
        rotation_xyz=(rx, ry, rz),
    )
    print(f"[Scene] Test camera entity={cam_eid} world_pos=(5,3,8) looking at origin")

    # ── 2D 摄像机: entity N, 正交俯视 GL XZ 平面 (编辑器 XY) ──
    #     GL 视线方向 (0,-1,0) — 摄像机在 GL +Y 高处看向下方
    cam_2d_eid = SceneManager.AddEntity()
    SceneManager.SetEntityName(cam_2d_eid, "Camera2D")
    # 预旋转 position: 使得 world_pos = position @ R = (0, 10, 0) GL
    # R = Rx(π/2): 旋转后 local -Z → world (0,-1,0) 即俯视
    cam_2d_rx = math.pi / 2.0
    cam_2d_pre = np.array([0.0, 0.0, 10.0])  # position @ R 后 → (0,10,0)
    SceneManager.SetEntityTransform(
        cam_2d_eid,
        position_xyz=(float(cam_2d_pre[0]), float(cam_2d_pre[1]), float(cam_2d_pre[2])),
        rotation_xyz=(cam_2d_rx, 0.0, 0.0),
    )
    cam_2d_comp = Camera(is_primary=False)
    cam_2d_comp.projection_type = ProjectionType.ORTHOGRAPHIC
    cam_2d_comp.ortho_size = 10.0
    cam_2d_comp.near_plane = 0.1
    cam_2d_comp.far_plane = 100.0
    esper.add_component(cam_2d_eid, cam_2d_comp)
    print(f"[Scene] 2D camera entity={cam_2d_eid} ortho top-down, ortho_size=10")

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

    def refresh_gizmos() -> None:
        nonlocal selected_eid, is_2d_mode, use_test_cam_view
        sel_set: set[int] = {selected_eid} if selected_eid is not None else set()
        # 当前模式不匹配的摄像机 gizmo 应隐藏
        exclude: set[int] = set()
        if is_2d_mode:
            exclude.add(cam_eid)       # 2D 模式: 隐藏 3D frustum + icon
        else:
            exclude.add(cam_2d_eid)    # 3D 模式: 隐藏 2D boundary
        if use_test_cam_view:
            # 预览自身不显示 gizmo
            preview_eid = cam_2d_eid if is_2d_mode else cam_eid
            exclude.add(preview_eid)
        gizmo_runner.refresh(selected_ids=sel_set, exclude_ids=exclude)

    def update_gizmo_position() -> None:
        """同步 TransformGizmo 位置到选中 entity。"""
        if selected_eid is not None:
            try:
                t = SceneManager.GetEntityTransform(selected_eid)  # type: ignore[reportUnknownMemberType]
                TransformGizmo.set_target_position(
                    (t.position_x, t.position_y, t.position_z))
            except Exception:
                pass

    def select_entity(eid: int | None) -> None:
        """选中/取消选中 entity，同步 gizmo 显示。"""
        nonlocal selected_eid
        if selected_eid is not None:
            TransformGizmo.hide()
        selected_eid = eid
        if eid is not None:
            TransformGizmo.show(renderer, eid)
            update_gizmo_position()
        refresh_gizmos()
        update_title()

    refresh_gizmos()

    # ── 输入管线 ──
    def update_title() -> None:
        sel = f"sel={selected_eid}" if selected_eid is not None else "no sel"
        mode = "2D" if is_2d_mode else "3D"
        view = "[TEST CAM]" if use_test_cam_view else "[EDITOR]"
        glfw.set_window_title(  # type: ignore[reportUnknownMemberType]
            window, f"Camera Gizmo (ZenGL) — {view} {mode} {sel}")

    pipeline = h.create_input_pipeline()  # type: ignore[reportUnknownMemberType]
    pipeline.setup_editor_camera(cam, after_camera=update_title)  # type: ignore[reportUnknownMemberType]
    _orig_drag = pipeline.on_drag

    def on_key(key: int, scancode: int, action: int, mods: int) -> None:
        nonlocal is_2d_mode, use_test_cam_view
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(window, True)  # type: ignore[reportUnknownMemberType]
        elif key == glfw.KEY_G:
            new_sel = cam_eid if selected_eid != cam_eid else None
            select_entity(new_sel)
            print(f"[Select] {'entity ' + str(cam_eid) if new_sel is not None else 'cleared'}")
        elif key == glfw.KEY_SPACE:
            use_test_cam_view = not use_test_cam_view
            mode_str = "TEST CAM" if use_test_cam_view else "EDITOR CAM"
            print(f"[View] Switched to {mode_str}")
            refresh_gizmos()
            update_title()
        elif key == glfw.KEY_F4:
            mode = cam.toggle_2d_3d()
            is_2d_mode = (mode == '2d')
            print(f"[View] Switched to {mode.upper()}")
            refresh_gizmos()
            update_title()

    # ── 鼠标拾取 + Gizmo 拖拽 ──
    def on_mouse_button(button: int, action: int, mods: int, x: float, y: float) -> None:
        nonlocal selected_eid
        if button != glfw.MOUSE_BUTTON_LEFT:
            return

        vp_w = renderer.viewport_width
        vp_h = renderer.viewport_height

        if action == glfw.PRESS:
            pick_type, pick_value = renderer.pick_at(x, y)

            gizmo_info = None
            if pick_type == 'overlay' and pick_value:
                gizmo_info = TransformGizmo.parse_pick_key(pick_value)

            if gizmo_info and selected_eid is not None:
                t = SceneManager.GetEntityTransform(selected_eid)  # type: ignore[reportUnknownMemberType]
                entity_pos = np.array(
                    [t.position_x, t.position_y, t.position_z], dtype=np.float32)
                aspect = vp_w / max(vp_h, 1)
                view_mat = cam.get_view_matrix()
                proj_mat = cam.get_projection_matrix(aspect)
                ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                    x, y, vp_w, vp_h, view_mat, proj_mat)

                if gizmo_info['kind'] == 'axis':
                    TransformGizmo.begin_axis_drag(
                        entity_pos, gizmo_info['gl_dir'], cam.position, ray_o, ray_d)
                    print(f"[DRAG AXIS] {gizmo_info['name']}, entity={selected_eid}")
                elif gizmo_info['kind'] == 'plane':
                    d1, d2 = gizmo_info['gl_dirs']
                    TransformGizmo.begin_plane_drag(
                        entity_pos, d1, d2, ray_o, ray_d)
                    print(f"[DRAG PLANE] {gizmo_info['name']}, entity={selected_eid}")
                return

        else:  # RELEASE
            if TransformGizmo.is_dragging():
                TransformGizmo.end_drag()
                refresh_gizmos()
                return

            if abs(x - pipeline._press_mx) < 4 and abs(y - pipeline._press_my) < 4:
                pick_type, pick_value = renderer.pick_at(x, y)

                if pick_type == 'entity':
                    print(f"[PICK ENTITY] entity_id={pick_value}")
                    select_entity(pick_value)
                elif pick_type == 'overlay' and pick_value:
                    gi = TransformGizmo.parse_pick_key(pick_value)
                    if gi:
                        print(f"[GIZMO CLICK] {gi['kind']}={gi['name']}")
                        return
                else:
                    if selected_eid is not None:
                        print(f"[PICK] cleared selection")
                        select_entity(None)

    def on_drag(button: int, dx: float, dy: float, x: float, y: float) -> None:
        if TransformGizmo.is_dragging():
            vp_w = renderer.viewport_width
            vp_h = renderer.viewport_height
            aspect = vp_w / max(vp_h, 1)
            view_mat = cam.get_view_matrix()
            proj_mat = cam.get_projection_matrix(aspect)
            ray_o, ray_d = TransformGizmo.screen_to_world_ray(
                x, y, vp_w, vp_h, view_mat, proj_mat)

            new_pos = TransformGizmo.update_drag(ray_o, ray_d)
            if new_pos is not None and selected_eid is not None:
                SceneManager.SetEntityTransform(  # type: ignore[reportUnknownMemberType]
                    selected_eid,
                    position_xyz=(float(new_pos[0]), float(new_pos[1]), float(new_pos[2])))
                TransformGizmo.set_target_position(new_pos)
            return

        _orig_drag(button, dx, dy, x, y)

    pipeline.on_key = on_key
    pipeline.on_mouse_button = on_mouse_button
    pipeline.on_drag = on_drag
    update_title()

    # ── 主循环 ──
    while not glfw.window_should_close(window):  # type: ignore[reportUnknownMemberType]
        glfw.poll_events()  # type: ignore[reportUnknownMemberType]
        aspect = fbw / fbh if fbh else 1.0

        if use_test_cam_view:
            # ── 根据当前 2D/3D 模式选择对应的 entity 摄像机 ──
            preview_eid = cam_2d_eid if is_2d_mode else cam_eid
            t = SceneManager.GetEntityTransform(preview_eid)  # type: ignore[reportUnknownMemberType]
            model = calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )
            view = np.linalg.inv(model)
            cam_comp = esper.component_for_entity(preview_eid, Camera)
            if cam_comp.projection_type == ProjectionType.ORTHOGRAPHIC:
                half_h = cam_comp.ortho_size
                half_w = half_h * aspect
                proj = pyrr.matrix44.create_orthogonal_projection(  # type: ignore[reportUnknownMemberType]
                    -half_w, half_w, -half_h, half_h,
                    cam_comp.near_plane, cam_comp.far_plane,
                )
            else:
                proj = pyrr.matrix44.create_perspective_projection(  # type: ignore[reportUnknownMemberType]
                    cam_comp.fov, aspect,
                    cam_comp.near_plane, cam_comp.far_plane,
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
        glfw.swap_buffers(window)  # type: ignore[reportUnknownMemberType]

    gizmo_runner.cleanup()
    TransformGizmo.hide()
    TransformGizmo.unregister_from(renderer)
    renderer.Shutdown()
    glfw.destroy_window(window)  # type: ignore[reportUnknownMemberType]
    glfw.terminate()  # type: ignore[reportUnknownMemberType]
    print("[ZenGL] Done")


if __name__ == '__main__':
    main()
