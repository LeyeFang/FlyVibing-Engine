# ── 标准库 ──
import ctypes
import os
import time

# ── 第三方库 ──
from imgui_bundle import imgui

# ── 应用层: 核心 ──
from Application.Editor.EditorHost import EditorHost
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import *
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.WindowEvent import WindowResizeEvent
from Application.Core.Renderer.RenderCommand import SetViewProjectionCommand, EntityRegistrationCommand
from Application.Core.Events.Enum.InputEnum import (
    MouseButtonCode, 
    MouseActionCode,
    KeyButtonCode,
    KeyActionCode,)
from Application.Core.Input.InputState import IsShiftPressed, IsKeyDown
from Application.Core.Layers.Layer import Layer

# ── 应用层: 编辑器 ──
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.Gizmos.Grid import Grid
from Application.Editor.Gizmos.OutlinerID import OutlinerID
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
from Application.Editor.Gizmos.ViewGizmo import ViewGizmo
from Application.Editor.Gizmos.CameraFrustum import CameraFrustum
from Application.Editor.Gizmos.Camera2DBoundary import Camera2DBoundary
from Application.Editor.Gizmos.CameraIconGizmo import CameraIconGizmo
from Application.Editor.UI.UIManager import UIManager

# ★ 先导入 Controller（触发 auto-register 到 ControllerRegistry），再导入 Panel
from Application.Editor.UI.controllers.SimulationController import SimulationController  # noqa: F401
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController  # noqa: F401
from Application.Editor.UI.controllers.ViewportController import ViewportController  # noqa: F401
from Application.Editor.UI.controllers.SelectionController import SelectionController  # noqa: F401
from Application.Editor.UI.panels import ScenePanel, NodeEditorPanel, ResourcePanel


import numpy as np


class EditorLayer(Layer):

    # ── 渲染器引用（OnAttach 中赋值，OnEvent 可能在 OnAttach 之前被调用）──
    renderer = None

    # ── 字体配置 ────────────────────────────────────────────────
    FONT_SIZE: float = 17
    FONT_CANDIDATES: list[str] = [
        "Resource/Fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    # ════════════════════════════════════════════════════════════
    # 生命周期 (Layer 接口)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        """编辑器层初始化 — 创建 ImGui 上下文、注册 3D 渲染资源和 UI 面板。"""
        imgui.create_context()
        cls._config_dir = os.path.join(os.path.dirname(__file__), "Config")
        os.makedirs(cls._config_dir, exist_ok=True)
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable
        io.set_ini_filename("")   # 不保存/读取 imgui.ini，每次启动用默认布局
        cls._load_fonts()
        editor_window = EditorHost.get_editor_window()
        window_address = ctypes.cast(editor_window.glfw_window, ctypes.c_void_p).value
        imgui.backends.glfw_init_for_opengl(window_address, True)
        imgui.backends.opengl3_init("#version 440 core")
        io = imgui.get_io()
        w, h = editor_window.GetSize()
        io.display_size = (float(w), float(h))
        cls._init_ui_panels()
        # ── 渲染器: 注册 Grid/ViewGizmo/Outliner overlay + 推送初始相机矩阵 ──
        cls.renderer = EditorHost.get_editor_renderer()
        cam = EditorCamera.get_instance()
        # ── 注册启动前创建的 MeshRenderer 实体（如 DefaultCube）──
        cls._register_existing_mesh_entities()
        # 相机矩阵由逻辑线程计算后通过 SetViewProjectionCommand 推送
        cls._sync_camera_to_renderer()
        Grid.register_to(cls.renderer)
        ViewGizmo.register_to(cls.renderer)
        OutlinerID.register_to(cls.renderer)
        TransformGizmo.register_to(cls.renderer)
        # ── 摄像机 entity gizmo (frustum / 2D boundary) ──
        cls._refresh_camera_gizmos()

    @classmethod
    def OnDetach(cls):
        if cls.renderer is not None:
            cls._unregister_all_camera_gizmos()
            TransformGizmo.unregister_from(cls.renderer)
            OutlinerID.unregister_from(cls.renderer)
            ViewGizmo.unregister_from(cls.renderer)
            Grid.unregister_from(cls.renderer)
        # ── 关闭 ImGui 后端 (需在 GL 上下文有效时调用) ──
        imgui.backends.opengl3_shutdown()
        imgui.backends.glfw_shutdown()
        imgui.destroy_context()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        # ── 防御: 渲染线程已退出时 ImGui 上下文已被销毁 ──
        if imgui.get_current_context() is None:
            return
        # ── MouseMoveEvent: 始终更新拾取鼠标位置 (主线程安全, 零 GL 调用) ──
        if isinstance(event, MouseMoveEvent):
            if cls.renderer is not None:
                cls.renderer.update_pick_mouse(event.pos_x, event.pos_y)
            return
        # ── SceneCameraUpdateEvent: 始终处理 (ViewportController / DebugLayer 触发) ──
        if isinstance(event, SceneCameraUpdateEvent):
            cls._sync_camera_to_renderer()
            cls._camera_gizmo_state_hash = -1  # 模式切换 → 强制刷新 gizmo
            return
        # ── 窗口 resize 始终处理，不受面板鼠标拦截影响 ──
        if isinstance(event, WindowResizeEvent):
            w, h = event.unpack()
            io = imgui.get_io()
            io.display_size = (float(w), float(h))
            # 投影矩阵依赖 aspect_ratio，resize 后需重新推送
            cls._sync_camera_to_renderer()
            return
        # ── 键盘事件: ImGui 捕获键盘时跳过 (如正在文本框输入) ──
        if isinstance(event, KeyboardButtonEvent):
            io = imgui.get_io()
            if not io.want_capture_keyboard:
                if (event.key == KeyButtonCode.Space
                        and event.action == KeyActionCode.Press):
                    cls._toggle_preview_camera()
            return
        if cls._mouse_in_any_panel():
            return
        if cls.renderer is None:
            return
        cam = EditorCamera.get_instance()
        if isinstance(event, ScrollerEvent):
            _, y_offset = event.unpack()
            cam.on_scroll(y_offset)
            cls._sync_camera_to_renderer()
        elif isinstance(event, MouseGragEvent):
            bt, offset_x, offset_y = event.unpack()
            if bt == MouseButtonCode.Left:
                # ── 左键拖动: gizmo 拖拽优先 ──
                if TransformGizmo.is_dragging():
                    cls._handle_gizmo_drag(event.pos_x, event.pos_y)
                    return
                return  # 非 gizmo 左键拖动不操作视图，仅用于点选
            cam.on_mouse_drag(bt, offset_x, offset_y, IsShiftPressed())
            cls._sync_camera_to_renderer()
        elif isinstance(event, MouseButtonEvent):
            if event.button != MouseButtonCode.Left:
                return
            if event.action == MouseActionCode.Press:
                cls._handle_left_press(event.pos_x, event.pos_y, cam)
            else:  # Release
                cls._handle_left_release(event.pos_x, event.pos_y, cam)

    # ════════════════════════════════════════════════════════════
    # Camera Gizmo — ECS Camera entity 可视化
    # ════════════════════════════════════════════════════════════

    _camera_gizmo_keys: set[str] = set()
    """当前已注册的 camera gizmo overlay key 集合。"""
    _camera_gizmo_state_hash: int = -1
    """上次刷新时的状态哈希 (entity_id + world_pos + rotation + type + selected)，
    用于检测 transform 变化而不仅仅是 entity 增删。"""
    _preview_entity_id: int | None = None
    """SPACE 预览模式: 非 None 时使用该 entity 的摄像机, None 时用 EditorCamera。"""

    @classmethod
    def _toggle_preview_camera(cls) -> None:
        """SPACE: 切换编辑器摄像机 / entity 摄像机预览。"""
        from Application.Editor.UI.controllers.ViewportController import ViewportController
        from Application.Core.Scene.SceneManager import SceneManager
        if cls._preview_entity_id is not None:
            cls._preview_entity_id = None
            print("[EditorLayer] Preview: OFF (editor camera)")
        else:
            is_2d = ViewportController.is_2d()
            cls._preview_entity_id = (
                EditorHost.scene.get_main_camera_2d_id() if is_2d else EditorHost.scene.get_main_camera_id()
            )
            print(f"[EditorLayer] Preview: ON (entity {cls._preview_entity_id})")
        cls._camera_gizmo_state_hash = -1  # 强制刷新 gizmo (隐藏预览自身)
        cls._sync_camera_to_renderer()

    @classmethod
    def _refresh_camera_gizmos(cls) -> None:
        """遍历 ECS 中所有 Camera entity，注册/更新对应的 gizmo overlay。

        仅在 entity 增删、position/rotation 变化或选中状态变化时重建 GPU 资源。
        """
        if cls.renderer is None:
            return

        from Application.Core.Scene.GizmoQuery import GizmoQuery
        from Application.Core.Math.Transform import calculate_entity_model
        from Application.Editor.UI.controllers.SelectionController import SelectionController
        from Application.Core.Renderer.RenderCommand import (
            OverlayRegistrationCommand, OverlayUnregistrationCommand)

        try:
            selected_id = SelectionController.get_selected()
            selected_ids = {selected_id} if selected_id is not None else set()
        except Exception:
            selected_ids = set()

        try:
            cam_list = GizmoQuery.get_camera_gizmos(selected_ids=selected_ids)
        except Exception:
            return

        # ── 状态哈希: entity_id + world_pos + rotation + camera params + type + selected ──
        state_parts: list[tuple] = []
        for cd in cam_list:
            model = calculate_entity_model(
                position=cd.position, rotation=cd.rotation, scale=cd.scale)
            world_pos = (round(float(model[3, 0]), 4),
                         round(float(model[3, 1]), 4),
                         round(float(model[3, 2]), 4))
            rot = tuple(round(r, 4) for r in cd.rotation)
            state_parts.append((cd.entity_id, world_pos, rot,
                                cd.is_perspective, cd.is_selected,
                                round(cd.aspect_ratio, 4),
                                round(cd.fov, 2),
                                round(cd.ortho_size, 2)))
        new_hash = hash(frozenset(state_parts))

        if new_hash == cls._camera_gizmo_state_hash:
            return
        cls._camera_gizmo_state_hash = new_hash

        # ── 有变化 → 注销旧 + 注册新 ──
        from Application.Editor.UI.controllers.ViewportController import ViewportController
        is_2d = ViewportController.is_2d()
        preview_eid = cls._preview_entity_id
        cls._unregister_all_camera_gizmos()
        for cam_data in cam_list:
            # 预览模式: 隐藏预览自身的 gizmo
            if preview_eid is not None and cam_data.entity_id == preview_eid:
                continue
            # 模式过滤: 2D 模式只显示正交摄像机, 3D 模式只显示透视摄像机
            if is_2d and cam_data.is_perspective:
                continue
            if not is_2d and not cam_data.is_perspective:
                continue

            if cam_data.is_perspective:
                # 3D: 椎体线框 + 原点图标
                overlay = CameraFrustum.build_overlay(cam_data)
                cls.renderer.enqueue(OverlayRegistrationCommand(overlay))
                cls._camera_gizmo_keys.add(overlay.key)

                model = calculate_entity_model(
                    position=cam_data.position, rotation=cam_data.rotation,
                    scale=cam_data.scale)
                world_pos = (float(model[3, 0]), float(model[3, 1]), float(model[3, 2]))
                icon = CameraIconGizmo.build_icon_overlay(
                    cam_data.entity_id, world_pos)
                cls.renderer.enqueue(OverlayRegistrationCommand(icon))
                cls._camera_gizmo_keys.add(icon.key)
            else:
                # 2D: 正交边界框
                overlay = Camera2DBoundary.build_overlay(cam_data)
                cls.renderer.enqueue(OverlayRegistrationCommand(overlay))
                cls._camera_gizmo_keys.add(overlay.key)

    @classmethod
    def _unregister_all_camera_gizmos(cls) -> None:
        """注销所有已注册的 camera gizmo overlay。"""
        from Application.Core.Renderer.RenderCommand import OverlayUnregistrationCommand
        for key in list(cls._camera_gizmo_keys):
            cls.renderer.enqueue(OverlayUnregistrationCommand(key))
        cls._camera_gizmo_keys.clear()

    @classmethod
    def _register_existing_mesh_entities(cls) -> None:
        """将渲染器创建前已存在的 MeshRenderer 实体注册到 GPU。

        解决启动时默认实体（如 DefaultCube）在渲染器就绪前创建，
        EntityRegistrationCommand 未能入队的问题。
        """
        if cls.renderer is None:
            return
        import esper
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Scene.BasicComponents import MeshRenderer
        try:
            st = SceneManager._state()
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
    # Gizmo 拖拽 + 拾取辅助
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

        # 获取实体 WORLD 位置 (GL 坐标, 非 pre-rotation)
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Math.Transform import calculate_entity_model
        try:
            t = EditorHost.scene.GetEntityTransform(selected)
            model = calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )
            entity_pos = np.array(
                [float(model[3, 0]), float(model[3, 1]), float(model[3, 2])], dtype=np.float32)
        except Exception:
            return

        # 计算射线
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
        """处理 gizmo 拖拽: 计算新位置并更新实体 + gizmo。

        Args:
            mx, my: 当前鼠标屏幕坐标 (来自 MouseGragEvent.pos_x/pos_y)
        """
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

        # ── 写入实体 Transform: world pos → pre-rotation pos ──
        selected = SelectionController.get_selected()
        if selected is not None:
            from Application.Core.Scene.SceneManager import SceneManager
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
        # ── gizmo 拖拽结束 ──
        if TransformGizmo.is_dragging():
            TransformGizmo.end_drag()
            cls._camera_gizmo_state_hash = -1  # 强制下次刷新
            cls._refresh_camera_gizmos()
            return

        # ── 现有 pick 逻辑 ──
        t0 = time.perf_counter()
        pick_type, pick_value = cls.renderer.pick_at(mx, my)
        dt = (time.perf_counter() - t0) * 1000
        if pick_type == 'entity':
            # print(f"[EditorLayer] Click → Entity#{pick_value}  ({dt:.3f}ms)")
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
                    print(f"[EditorLayer] ViewGizmo → {face_name}  ({dt:.3f}ms)")
            else:
                print(f"[EditorLayer] Click → Overlay '{pick_value}'  ({dt:.3f}ms)")
        else:
            print(f"[EditorLayer] Click → nothing  ({dt:.3f}ms)")
            SelectionController.clear()

    @classmethod
    def OnUpdate(cls):
        # ── 消费延迟的 PIE 启动/停止请求 (主线程执行 GLFW 窗口操作) ──
        from Application.Editor.UI.controllers.SimulationController import SimulationController
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

        # ── 刷新 camera gizmo (Camera entity 增删 / Transform 变化 / 选中变化) ──
        cls._refresh_camera_gizmos()

    @classmethod
    def OnRender(cls):
        # ── 处理待处理的轮廓请求 (render thread, GL 调用) ──
        OutlinerID._sync()
        # ── ImGui ──
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        UIManager.draw_all()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())

    # ════════════════════════════════════════════════════════════
    # 初始化辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _load_fonts(cls) -> None:
        """加载 UI 字体并合并 Font Awesome 6 图标字体。

        hello_imgui.load_font_ttf_with_font_awesome_icons 需要字体文件位于
        assets 目录内，因此我们统一使用 Resource/Fonts/ 下的字体副本。
        """
        from imgui_bundle import hello_imgui as _hi

        # hello_imgui 的资源目录指向 Resource/，字体相对路径为 Fonts/xxx.ttf
        _resource_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Resource"))
        _hi.set_assets_folder(_resource_dir)

        io = imgui.get_io()
        font_loaded = False

        # 候选字体（相对于 Resource/ 的路径）
        _font_candidates = [
            "Fonts/Inter-Regular.ttf",
            "Fonts/segoeui.ttf",
            "Fonts/arial.ttf",
        ]
        for rel_path in _font_candidates:
            if _hi.asset_exists(rel_path):
                _hi.load_font_ttf_with_font_awesome_icons(
                    rel_path, cls.FONT_SIZE)
                print(f"[Font] Loaded + FA6: {rel_path} ({cls.FONT_SIZE}px)")
                font_loaded = True
                break

        if not font_loaded:
            io.fonts.add_font_default()
            print(
                "[Font] No bundled font found. Using ImGui default.\n"
                "       Place a .ttf in Resource/Fonts/, e.g. Inter-Regular.ttf"
            )

    @classmethod
    def _init_ui_panels(cls):
        """注册编辑器 UI 面板 (幂等, 仅首次调用生效)。

        默认隐藏 Scene / Node Editor / Resources 面板 — 用户通过 View 菜单打开。
        """
        if not hasattr(cls, '_panels_registered'):
            scene_panel = UIManager.register(ScenePanel())
            node_panel = UIManager.register(NodeEditorPanel())
            res_panel = UIManager.register(ResourcePanel())
            # 默认可见 — dock builder 需要在首帧找到这些窗口才能正确分配布局
            cls._panels_registered = True

    # ════════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _mouse_in_any_panel(cls) -> bool:
        """检查鼠标是否悬停在任意 ImGui 面板区域内。"""
        io = imgui.get_io()
        mx, my = io.mouse_pos
        for x, y, w, h in UIManager._panel_rects:
            if x <= mx <= x + w and y <= my <= y + h:
                return True
        return False

    @classmethod
    def _sync_camera_to_renderer(cls) -> None:
        """推送 view/proj 矩阵到渲染器。预览模式下使用 entity 摄像机。"""
        if cls.renderer is None:
            return

        if cls._preview_entity_id is not None:
            # ── 预览模式: 使用 entity 的摄像机 ──
            import numpy as np
            from Application.Core.Scene.SceneManager import SceneManager
            from Application.Core.Math.Transform import calculate_entity_model
            from Application.Core.Scene.BasicComponents import Camera
            from Application.Core.Scene.SceneManager import SceneManager
            try:
                t = EditorHost.scene.GetEntityTransform(cls._preview_entity_id)
                model = calculate_entity_model(
                    position=(t.position_x, t.position_y, t.position_z),
                    rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                    scale=(t.scale_x, t.scale_y, t.scale_z),
                )
                view = np.linalg.inv(model)
                cam_comp = EditorHost.scene.GetComponent(cls._preview_entity_id, Camera)
                if cam_comp.projection_type.value == 'orthographic':
                    aspect = cls.renderer.aspect_ratio
                    half_h = cam_comp.ortho_size
                    half_w = half_h * aspect
                    from pyrr import matrix44
                    proj = matrix44.create_orthogonal_projection(
                        -half_w, half_w, -half_h, half_h,
                        cam_comp.near_plane, cam_comp.far_plane,
                    ).astype(np.float32)
                else:
                    from pyrr import matrix44
                    proj = matrix44.create_perspective_projection(
                        cam_comp.fov, cls.renderer.aspect_ratio,
                        cam_comp.near_plane, cam_comp.far_plane,
                    ).astype(np.float32)
                cls.renderer.enqueue(SetViewProjectionCommand(
                    view=view, proj=proj,
                    orbit_target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
                    orbit_distance=float(np.linalg.norm(
                        [t.position_x, t.position_y, t.position_z])),
                ))
                return
            except Exception:
                cls._preview_entity_id = None  # 出错则回退

        cam = EditorCamera.get_instance()
        cls.renderer.enqueue(SetViewProjectionCommand(
            view=cam.get_view_matrix(),
            proj=cam.get_projection_matrix(cls.renderer.aspect_ratio),
            orbit_target=cam.orbit_target,
            orbit_distance=cam.orbit_distance,
            is_orthographic=cam.is_orthographic,
            ortho_size=cam.ortho_size,
        ))
