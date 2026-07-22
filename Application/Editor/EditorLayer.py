"""
EditorLayer — 编辑器核心层（视口 + 场景交互 + Gizmo 拾取拖拽）。

已拆分:
  - EditorImguiLayer  : ImGui 上下文 / 字体 / Backend / 面板渲染
  - EditorGizmoLayer  : Camera entity gizmo 可视化 / 预览切换
  - EditorInputLayer  : 输入事件路由 (鼠标/键盘/滚轮/窗口)
"""

from __future__ import annotations

import time
import numpy as np

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Renderer.RenderCommand import SetViewProjectionCommand, EntityRegistrationCommand
from Application.Core.Events.Enum.InputEnum import (
    KeyButtonCode,
)
from Application.Core.Input.InputState import IsKeyDown

from Application.Editor.EditorHost import EditorHost
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.EditorInputLayer import EditorInputLayer
from Application.Editor.EditorGizmoLayer import EditorGizmoLayer
from Application.Editor.Gizmos.Grid import Grid
from Application.Editor.Gizmos.OutlinerID import OutlinerID
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
from Application.Editor.Gizmos.ViewGizmo import ViewGizmo
from Application.Editor.UI.controllers.SelectionController import SelectionController


# ★ 先导入 Controller（触发 auto-register 到 ControllerRegistry），再导入 Panel
from Application.Editor.UI.controllers.SimulationController import SimulationController  # noqa: F401
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ViewportController import ViewportController  # noqa: F401


class EditorLayer(Layer):
    """编辑器核心层 — 视口渲染管线 + Gizmo 拾取拖拽 + 层间连线。"""

    renderer = None

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        """编辑器核心初始化 — 渲染器接入 + overlay 注册 + 层间连线。"""
        super().OnAttach()

        cls.renderer = EditorHost.get_editor_renderer()

        # ── 注册启动前创建的 MeshRenderer 实体 ──
        cls._register_existing_mesh_entities()

        # ── 推送初始相机矩阵 ──
        cls._sync_camera_to_renderer()

        # ── 注册视口 overlay (Grid / ViewGizmo / Outliner / TransformGizmo) ──
        Grid.register_to(cls.renderer)
        ViewGizmo.register_to(cls.renderer)
        OutlinerID.register_to(cls.renderer)
        TransformGizmo.register_to(cls.renderer)

        # ── 连线子层 (OnAttach 尚未执行, 提前注入引用) ──
        EditorInputLayer.renderer = cls.renderer
        EditorInputLayer._editor_layer = cls
        EditorGizmoLayer.renderer = cls.renderer
        EditorGizmoLayer._editor_layer = cls

    @classmethod
    def OnDetach(cls):
        """编辑器核心清理 — 仅注销视口 overlay。"""
        if cls.renderer is not None:
            TransformGizmo.unregister_from(cls.renderer)
            OutlinerID.unregister_from(cls.renderer)
            ViewGizmo.unregister_from(cls.renderer)
            Grid.unregister_from(cls.renderer)

    @classmethod
    def OnUpdate(cls):
        # ── 首次 OnUpdate: 主线程安全同步窗口标题 ──
        if not getattr(cls, '_title_synced', False):
            cls._title_synced = True
            from Application.Editor.ProjectManager import ProjectManager
            ProjectManager._update_window_title()

        # ── 消费延迟的 PIE 启动/停止请求 ──
        SimulationController._try_consume_start()
        SimulationController._try_consume_stop()

        # ── 检测 RuntimeWindow 关闭 (用户点 X) ──
        if SimulationController.is_running():
            from Application.Runtime.GameRuntime import GameRuntime
            import glfw as _glfw
            if (GameRuntime.window is not None
                    and GameRuntime.window.glfw_window is not None
                    and _glfw.window_should_close(GameRuntime.window.glfw_window)):
                SimulationController.stop()

    @classmethod
    def OnRender(cls):
        """非 ImGui 渲染 — 轮廓请求同步 (ImGui 渲染见 EditorImguiLayer)。"""
        OutlinerID._sync()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass  # 输入事件由 EditorInputLayer 处理

    # ════════════════════════════════════════════════════════════
    # 相机同步 (供 EditorInputLayer / EditorGizmoLayer 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _sync_camera_to_renderer(cls) -> None:
        """推送 view/proj 矩阵到渲染器。预览模式下使用 entity 摄像机。"""
        if cls.renderer is None:
            return

        # ★ 预览 entity ID 现在由 EditorGizmoLayer 持有
        preview_eid = EditorGizmoLayer._preview_entity_id

        if preview_eid is not None:
            # ── 预览模式: 使用 entity 的摄像机 ──
            from Application.Core.Math.Transform import calculate_entity_model
            from Application.Core.Scene.BasicComponents import Camera
            from Application.Core.Math.Camera import orthogonal_projection, perspective_projection
            try:
                t = EditorHost.scene.GetEntityTransform(preview_eid)
                model_np = calculate_entity_model(
                    position=(t.position_x, t.position_y, t.position_z),
                    rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                    scale=(t.scale_x, t.scale_y, t.scale_z),
                )
                view = np.linalg.inv(model_np)
                cam_comp = EditorHost.scene.GetComponent(preview_eid, Camera)
                if cam_comp.projection_type.value == 'orthographic':
                    aspect = cls.renderer.aspect_ratio
                    half_h = cam_comp.ortho_size
                    half_w = half_h * aspect
                    proj = orthogonal_projection(
                        -half_w, half_w, -half_h, half_h,
                        cam_comp.near_plane, cam_comp.far_plane,
                    )
                else:
                    proj = perspective_projection(
                        cam_comp.fov, cls.renderer.aspect_ratio,
                        cam_comp.near_plane, cam_comp.far_plane,
                    )
                cls.renderer.enqueue(SetViewProjectionCommand(
                    view=view, proj=proj,
                    orbit_target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
                    orbit_distance=float(np.linalg.norm(
                        [t.position_x, t.position_y, t.position_z])),
                ))
                return
            except Exception:
                EditorGizmoLayer._preview_entity_id = None  # 出错则回退

        # ── 编辑器摄像机 ──
        cam = EditorCamera.get_instance()
        cls.renderer.enqueue(SetViewProjectionCommand(
            view=cam.get_view_matrix(),
            proj=cam.get_projection_matrix(cls.renderer.aspect_ratio),
            orbit_target=cam.orbit_target,
            orbit_distance=cam.orbit_distance,
            is_orthographic=cam.is_orthographic,
            ortho_size=cam.ortho_size,
        ))

    # ════════════════════════════════════════════════════════════
    # 实体注册 (OnAttach 辅助)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _register_existing_mesh_entities(cls) -> None:
        """将渲染器创建前已存在的 MeshRenderer 实体注册到 GPU。"""
        if cls.renderer is None:
            return
        import esper
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Scene.BasicComponents import MeshRenderer
        try:
            st = SceneManager._current()
            for entity_id_str in st.entities:
                eid = int(entity_id_str)
                try:
                    if esper.has_component(eid, MeshRenderer):
                        cls.renderer.enqueue(
                            EntityRegistrationCommand(eid, register=True))
                except KeyError:
                    pass
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════
    # Gizmo 拖拽 + 拾取 (供 EditorInputLayer 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _handle_left_press(cls, mx: int, my: int, cam) -> None:
        """左键按下: 检测是否命中 gizmo，若是则开始拖拽。"""
        pick_type, pick_value = cls.renderer.pick_at(mx, my)
        if pick_type != 'overlay' or not pick_value:
            return

        gizmo_info = TransformGizmo.parse_pick_key(pick_value)
        if gizmo_info is None:
            return

        selected = SelectionController.get_selected()
        if selected is None:
            return

        from Application.Core.Math.Transform import calculate_entity_model
        try:
            t = EditorHost.scene.GetEntityTransform(selected)
            model_np = calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )
            entity_pos = np.array(
                [float(model_np[3, 0]), float(model_np[3, 1]), float(model_np[3, 2])],
                dtype=np.float32)
        except Exception:
            return

        vp_w = cls.renderer.viewport_width
        vp_h = cls.renderer.viewport_height
        view_mat = cam.get_view_matrix()
        proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
        ray_o, ray_d = TransformGizmo.screen_to_world_ray(
            mx, my, vp_w, vp_h, view_mat, proj_mat)

        if gizmo_info['kind'] == 'axis':
            TransformGizmo.begin_axis_drag(
                entity_pos, gizmo_info['gl_dir'], cam.position, ray_o, ray_d)
        elif gizmo_info['kind'] == 'plane':
            d1, d2 = gizmo_info['gl_dirs']
            TransformGizmo.begin_plane_drag(
                entity_pos, d1, d2, ray_o, ray_d)

    @classmethod
    def _handle_gizmo_drag(cls, mx: int, my: int) -> None:
        """处理 gizmo 拖拽: 计算新位置并更新实体 + gizmo。"""
        vp_w = cls.renderer.viewport_width
        vp_h = cls.renderer.viewport_height
        cam = EditorCamera.get_instance()
        view_mat = cam.get_view_matrix()
        proj_mat = cam.get_projection_matrix(vp_w / max(vp_h, 1))
        ray_o, ray_d = TransformGizmo.screen_to_world_ray(
            mx, my, vp_w, vp_h, view_mat, proj_mat)

        new_pos = TransformGizmo.update_drag(ray_o, ray_d)
        if new_pos is None:
            return

        selected = SelectionController.get_selected()
        if selected is not None:
            from Application.Core.Math.Transform import _build_R_T
            t = EditorHost.scene.GetEntityTransform(selected)
            R_T = _build_R_T(t.rotation_x, t.rotation_y, t.rotation_z)
            wp = np.array([float(new_pos[0]), float(new_pos[1]), float(new_pos[2])])
            pre_pos = wp @ R_T
            EditorHost.scene.SetEntityTransform(
                selected,
                position_xyz=(float(pre_pos[0]), float(pre_pos[1]), float(pre_pos[2])))
            TransformGizmo.set_target_position(new_pos)

    @classmethod
    def _handle_left_release(cls, mx: int, my: int, cam) -> None:
        """左键释放: gizmo 拖拽结束优先，否则走 entity/viewgizmo pick。"""
        if TransformGizmo.is_dragging():
            TransformGizmo.end_drag()
            EditorGizmoLayer.invalidate_camera_gizmos()
            EditorGizmoLayer._refresh_camera_gizmos()
            return

        t0 = time.perf_counter()
        pick_type, pick_value = cls.renderer.pick_at(mx, my)
        dt = (time.perf_counter() - t0) * 1000

        if pick_type == 'entity':
            if IsKeyDown(KeyButtonCode.G):
                SelectionController.select_with_gizmo(pick_value)
            else:
                SelectionController.select(pick_value)
        elif pick_type == 'overlay' and pick_value:
            prefix = ViewGizmo.OVERLAY_KEY_PREFIX
            if pick_value.startswith(prefix):
                face_name = pick_value.rsplit('_', 1)[-1]
                direction = ViewGizmo.FACE_LOOK_DIRECTIONS.get(face_name)
                if direction is not None:
                    cam.look_from_direction(direction)
                    cls._sync_camera_to_renderer()
                    print(f"[EditorLayer] ViewGizmo → {face_name}")
            else:
                print(f"[EditorLayer] Click → Overlay '{pick_value}'")
        else:
            SelectionController.clear()
