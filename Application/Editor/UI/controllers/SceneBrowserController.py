"""场景浏览器 — 实体列表选择 & 检视逻辑"""

import math
from dataclasses import dataclass
from typing import Optional

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import Camera
from Application.Editor.EditorHost import EditorHost

# ── 输入安全常量 ─────────────────────────────────────────
_SCALE_MIN: float = 0.0001          # Scale 下限 (防止零除/反转法线)
_POSITION_MAX: float = 1e6          # Position 绝对值上限 (世界单位)
_SCALE_MAX: float = 1e4             # Scale 绝对值上限
_ROTATION_MAX_DEG: float = 360.0    # Rotation 单轴最大值 (角度制, 超出后取模)


@dataclass
class EntitySummary:
    entity_id: int
    name: str = ""
    position: tuple[float, float, float] = (0, 0, 0)
    rotation: tuple[float, float, float] = (0, 0, 0)
    scale: tuple[float, float, float] = (1, 1, 1)
    mesh_id: Optional[int] = None
    material_id: Optional[int] = None
    has_camera: bool = False
    render_visible: bool = True           # ★ MeshRenderer.visible (渲染可见性)


class SceneBrowserController:
    """实体选择与检视 — 纯数据层，不 import imgui"""

    selected_entity_id: Optional[int] = None

    # ── Spawn 模板 ─────────────────────────────────────────
    ENTITY_TEMPLATES: dict[str, list[str]] = {
        "Empty":  ["Transform"],
        "Cube":   ["Transform", "MeshRenderer"],
        "Camera": ["Transform", "Camera"],
    }

    # ── 实体列表 ────────────────────────────────────────────

    @classmethod
    def get_renderable_entities(cls) -> list[int]:
        return EditorHost.scene.GetRenderableEntities()

    @classmethod
    def get_all_entity_infos(cls) -> list[dict]:
        """返回所有实体的摘要信息列表（含名称、组件标记）。"""
        return EditorHost.scene.GetAllEntityInfos()

    # ── 实体选择 ────────────────────────────────────────────

    @classmethod
    def select(cls, entity_id: int) -> None:
        cls.selected_entity_id = entity_id

    @classmethod
    def get_selected(cls) -> Optional[int]:
        return cls.selected_entity_id

    @classmethod
    def clear_selection(cls) -> None:
        cls.selected_entity_id = None

    # ── 实体检视 ────────────────────────────────────────────

    @classmethod
    def get_summary(cls, entity_id: int, use_local: bool = False) -> Optional[EntitySummary]:
        """获取实体组件摘要。use_local=True 时返回本地 Transform。"""
        try:
            if use_local:
                t = EditorHost.scene.GetEntityLocalTransformEditor(entity_id)
            else:
                t = EditorHost.scene.GetEntityTransformEditor(entity_id)
            # Transform 组件存储弧度为内部约定，UI 层转为角度显示
            rot_rad = t['rotation']
            rot_deg = tuple(math.degrees(r) for r in rot_rad)
            summary = EntitySummary(
                entity_id=entity_id,
                name=EditorHost.scene.GetEntityName(entity_id),
                position=t['position'],
                rotation=rot_deg,
                scale=t['scale'],
            )
            try:
                summary.mesh_id = EditorHost.scene.GetEntityMesh(entity_id)
            except Exception:
                pass
            try:
                summary.material_id = EditorHost.scene.GetEntityMaterial(entity_id)
            except Exception:
                pass
            try:
                summary.has_camera = EditorHost.scene.HasComponent(entity_id, Camera)
            except Exception:
                pass
            try:
                summary.render_visible = EditorHost.scene.IsEntityRenderVisible(entity_id)
            except Exception:
                pass
            return summary
        except Exception:
            return None

    # ── 实体属性编辑 ────────────────────────────────────────

    @classmethod
    def set_position(cls, entity_id: int, position: tuple[float, float, float],
                     use_local: bool = False) -> None:
        """设置实体位置（编辑器坐标系）。use_local=True 写本地坐标。"""
        # ── 安全检查: 拒绝 NaN/Inf, 钳制绝对值 ──
        px, py, pz = float(position[0]), float(position[1]), float(position[2])
        if not (math.isfinite(px) and math.isfinite(py) and math.isfinite(pz)):
            return
        px = max(-_POSITION_MAX, min(_POSITION_MAX, px))
        py = max(-_POSITION_MAX, min(_POSITION_MAX, py))
        pz = max(-_POSITION_MAX, min(_POSITION_MAX, pz))
        safe_pos = (px, py, pz)
        if use_local:
            EditorHost.scene.SetEntityLocalTransformEditor(entity_id, position_xyz=safe_pos)
        else:
            EditorHost.scene.SetEntityTransformEditor(entity_id, position_xyz=safe_pos)

    @classmethod
    def set_rotation(cls, entity_id: int, rotation: tuple[float, float, float],
                     use_local: bool = False) -> None:
        """设置实体旋转（欧拉角，角度制）。
        
        UI 层使用角度 (degrees)，内部存储为弧度 (radians)。
        """
        # ── 安全检查: 拒绝 NaN/Inf, 归一化到 [-360, 360] ──
        rx, ry, rz = float(rotation[0]), float(rotation[1]), float(rotation[2])
        if not (math.isfinite(rx) and math.isfinite(ry) and math.isfinite(rz)):
            return
        rx = rx % _ROTATION_MAX_DEG if rx >= 0 else -(-rx % _ROTATION_MAX_DEG)
        ry = ry % _ROTATION_MAX_DEG if ry >= 0 else -(-ry % _ROTATION_MAX_DEG)
        rz = rz % _ROTATION_MAX_DEG if rz >= 0 else -(-rz % _ROTATION_MAX_DEG)
        rot_rad = (math.radians(rx), math.radians(ry), math.radians(rz))
        if use_local:
            EditorHost.scene.SetEntityLocalTransformEditor(entity_id, rotation_xyz=rot_rad)
        else:
            EditorHost.scene.SetEntityTransformEditor(entity_id, rotation_xyz=rot_rad)

    @classmethod
    def set_scale(cls, entity_id: int, scale: tuple[float, float, float],
                  use_local: bool = False) -> None:
        """设置实体缩放（编辑器坐标系）。"""
        # ── 安全检查: 拒绝 NaN/Inf/≤0, 钳制范围 ──
        sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
        if not (math.isfinite(sx) and math.isfinite(sy) and math.isfinite(sz)):
            return
        sx = max(_SCALE_MIN, min(_SCALE_MAX, sx))
        sy = max(_SCALE_MIN, min(_SCALE_MAX, sy))
        sz = max(_SCALE_MIN, min(_SCALE_MAX, sz))
        safe_scale = (sx, sy, sz)
        if use_local:
            EditorHost.scene.SetEntityLocalTransformEditor(entity_id, scale_xyz=safe_scale)
        else:
            EditorHost.scene.SetEntityTransformEditor(entity_id, scale_xyz=safe_scale)

    @classmethod
    def set_name(cls, entity_id: int, name: str) -> None:
        """设置实体名称。"""
        EditorHost.scene.SetEntityName(entity_id, name)

    @classmethod
    def get_camera_info(cls, entity_id: int) -> Optional[dict]:
        """获取实体的 Camera 组件信息（用于检视面板）。"""
        try:
            cam = EditorHost.scene.GetComponent(entity_id, Camera)
            return {
                'projection': cam.projection_type.value
                    if hasattr(cam.projection_type, 'value') else str(cam.projection_type),
                'is_perspective': cam.projection_type.value == 'perspective'
                    if hasattr(cam.projection_type, 'value') else True,
                'fov': cam.fov,
                'ortho_size': cam.ortho_size,
                'aspect_ratio': cam.aspect_ratio,
                'near': cam.near_plane,
                'far': cam.far_plane,
                'is_primary': cam.is_primary,
            }
        except Exception:
            return None

    @classmethod
    def set_camera_fov(cls, entity_id: int, fov: float) -> None:
        cam = EditorHost.scene.GetComponent(entity_id, Camera)
        cam.fov = max(1.0, min(179.0, fov))

    @classmethod
    def set_camera_ortho_size(cls, entity_id: int, size: float) -> None:
        cam = EditorHost.scene.GetComponent(entity_id, Camera)
        cam.ortho_size = max(0.01, size)

    @classmethod
    def set_camera_clip(cls, entity_id: int, near: float, far: float) -> None:
        cam = EditorHost.scene.GetComponent(entity_id, Camera)
        cam.near_plane = max(0.001, near)
        cam.far_plane = max(cam.near_plane + 0.01, far)

    @classmethod
    def set_camera_projection(cls, entity_id: int, is_perspective: bool) -> None:
        from Application.Core.Scene.BasicComponents import ProjectionType
        cam = EditorHost.scene.GetComponent(entity_id, Camera)
        cam.projection_type = (
            ProjectionType.PERSPECTIVE if is_perspective else ProjectionType.ORTHOGRAPHIC)

    @classmethod
    def set_camera_aspect_ratio(cls, entity_id: int, ratio: float) -> None:
        cam = EditorHost.scene.GetComponent(entity_id, Camera)
        cam.aspect_ratio = max(0.1, min(10.0, ratio))

    @classmethod
    def get_game_type(cls) -> str:
        """返回 GameType 字符串 ('3d' / '2d' / 'overlay')。"""
        scene = EditorHost.scene
        gt = scene.game_type
        return gt.value if hasattr(gt, 'value') else str(gt)

    @classmethod
    def set_game_type(cls, game_type_str: str) -> None:
        """设置 GameType 并切换默认摄像机。"""
        from Application.Core.Scene.Scene import GameType
        gt = GameType(game_type_str)
        scene = EditorHost.scene
        if scene.game_type == gt:
            return
        scene.game_type = gt
        # 切换默认摄像机
        from Application.Core.Scene.BasicComponents import Camera
        is_default = (scene.scene_camera_id == scene.main_camera_id
                      or scene.scene_camera_id == scene.main_camera_2d_id)
        if is_default:
            if gt == GameType.GAME_2D and scene.main_camera_2d_id is not None:
                scene.scene_camera_id = scene.main_camera_2d_id
            else:
                scene.scene_camera_id = scene.main_camera_id
            if scene.scene_camera_id is not None:
                try:
                    scene.scene_camera = EditorHost.scene.GetComponent(scene.scene_camera_id, Camera)
                except Exception:
                    scene.scene_camera = None

    # ── Scene CRUD ───────────────────────────────────────────

    @classmethod
    def get_scene_names(cls) -> list[str]:
        """返回所有已创建场景的名称列表。"""
        from Application.Editor.EditorHost import EditorHost
        return EditorHost.list_scenes()

    @classmethod
    def get_active_scene_name(cls) -> str:
        """返回当前活跃场景的名称。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is not None:
            return getattr(scene, 'name', 'Untitled')
        return "default"

    @classmethod
    def switch_scene(cls, name: str) -> bool:
        """切换到指定场景。返回是否成功。"""
        from Application.Editor.EditorHost import EditorHost
        return EditorHost.switch_scene(name)

    @classmethod
    def create_scene(cls, name: str) -> str:
        """创建新场景并设为活跃。返回场景名称。"""
        from Application.Editor.EditorHost import EditorHost
        EditorHost.create_scene(name)
        return name

    # ── 实体层级 / Entity Hierarchy ───────────────────────────

    @classmethod
    def get_root_entities(cls) -> list[int]:
        """获取所有根实体（无父实体的）。"""
        return EditorHost.scene.GetRootEntities()

    @classmethod
    def get_entity_children(cls, entity_id: int) -> list[int]:
        """获取实体的直接子实体 ID 列表。"""
        return EditorHost.scene.GetEntityChildren(entity_id)

    @classmethod
    def get_entity_parent(cls, entity_id: int) -> int | None:
        """获取实体的父实体 ID。"""
        return EditorHost.scene.GetEntityParent(entity_id)

    @classmethod
    def set_entity_parent(cls, child_id: int, parent_id: int) -> None:
        """设置父子关系。"""
        EditorHost.scene.SetEntityParent(child_id, parent_id)

    @classmethod
    def get_entity_info(cls, entity_id: int) -> dict | None:
        """获取单个实体的摘要信息。"""
        infos = EditorHost.scene.GetAllEntityInfos()
        for info in infos:
            if info['entity_id'] == entity_id:
                return info
        return None

    # ── 编辑器可见性 ──────────────────────────────────────────

    @classmethod
    def is_editor_visible(cls, entity_id: int) -> bool:
        """查询实体在编辑器视口中是否可见（眼图标状态）。"""
        return EditorHost.scene.IsEditorVisible(entity_id)

    @classmethod
    def set_editor_visible(cls, entity_id: int, visible: bool) -> None:
        """设置实体在编辑器视口中的可见性。"""
        EditorHost.scene.SetEditorVisible(entity_id, visible)

    # ── 渲染可见性 ──────────────────────────────────────────

    @classmethod
    def set_entity_render_visible(cls, entity_id: int, visible: bool) -> None:
        """设置实体的渲染可见性 (MeshRenderer.visible)。"""
        EditorHost.scene.SetEntityRenderVisible(entity_id, visible)

    # ── Entity CRUD ───────────────────────────────────────────

    @classmethod
    def add_entity(cls, name: str = "") -> int:
        """创建新实体（仅 Transform），返回 entity_id。"""
        eid = EditorHost.scene.AddEntity(name=name or "Entity")
        if cls.selected_entity_id is not None:
            EditorHost.scene.SetEntityParent(eid, cls.selected_entity_id)
        return eid

    @classmethod
    def delete_entity(cls, entity_id: int) -> bool:
        """删除实体及其子实体。若删除的是当前选中实体，则清除选中。"""
        if cls.selected_entity_id == entity_id:
            cls.selected_entity_id = None
        return EditorHost.scene.DeleteEntity(entity_id)

    @classmethod
    def delete_selected(cls) -> bool:
        """删除当前选中的实体。"""
        if cls.selected_entity_id is None:
            return False
        return cls.delete_entity(cls.selected_entity_id)

    # ── Component 管理 ────────────────────────────────────────

    @classmethod
    def get_available_components(cls) -> dict[str, type]:
        """获取所有已注册的可用 Component 类型。"""
        return EditorHost.scene.GetRegisteredComponents()

    @classmethod
    def add_component(cls, entity_id: int, component_name: str) -> bool:
        """给实体添加指定名称的 Component。"""
        return EditorHost.scene.AddComponentToEntityByName(entity_id, component_name)

    @classmethod
    def get_entity_components(cls, entity_id: int) -> list[str]:
        """获取实体当前拥有的 Component 名称列表。"""
        comps = cls.get_available_components()
        result = []
        for name, comp_cls in comps.items():
            try:
                if EditorHost.scene.HasComponent(entity_id, comp_cls):
                    result.append(name)
            except Exception:
                pass
        return result

    # ── MeshRenderer 编辑 ─────────────────────────────────────

    @classmethod
    def get_entity_mesh_id(cls, entity_id: int) -> int | None:
        try:
            return EditorHost.scene.GetEntityMesh(entity_id)
        except Exception:
            return None

    @classmethod
    def get_entity_material_id(cls, entity_id: int) -> int | None:
        try:
            return EditorHost.scene.GetEntityMaterial(entity_id)
        except Exception:
            return None

    @classmethod
    def set_entity_mesh(cls, entity_id: int, mesh_id: int) -> None:
        EditorHost.scene.SetEntityMeshRenderer(entity_id, mesh_id=mesh_id)

    @classmethod
    def set_entity_material(cls, entity_id: int, material_id: int) -> None:
        EditorHost.scene.SetEntityMaterial(entity_id, material_id)

    @classmethod
    def get_entity_material_info(cls, entity_id: int) -> dict | None:
        """获取实体当前 material 的详细信息（含 meta）。"""
        try:
            mid = EditorHost.scene.GetEntityMaterial(entity_id)
            from Application.Resource.ResourceManager import ResourceManager
            mat = ResourceManager.GetMaterial(mid)
            return {
                'material_id': mid,
                'material_name': mat.name,
                'display_name': mat.display_name,
                'is_saved': mat._is_saved,
                'file_path': mat._file_path,
                'shader_id': mat.shader_id,
                'shader_name': ResourceManager.GetShaderName(mat.shader_id),
                'texture_ids': list(mat.texture_id_list),
                'uniforms': dict(mat.uniforms_data),
            }
        except Exception:
            return None

    @classmethod
    def set_material_name(cls, entity_id: int, new_name: str) -> None:
        """设置 material 名称并标记为已修改。"""
        try:
            mid = EditorHost.scene.GetEntityMaterial(entity_id)
            from Application.Resource.ResourceManager import ResourceManager
            mat = ResourceManager.GetMaterial(mid)
            if mat.name != new_name:
                mat.name = new_name
                mat.mark_modified()
        except Exception:
            pass

    @classmethod
    def set_material_shader(cls, entity_id: int, shader_id: int) -> None:
        """切换 material 的 shader 并标记修改。"""
        try:
            mid = EditorHost.scene.GetEntityMaterial(entity_id)
            from Application.Resource.ResourceManager import ResourceManager
            mat = ResourceManager.GetMaterial(mid)
            shader = ResourceManager.GetShader(shader_id)
            mat.set_new_shader(shader_id, shader.uniforms_name_type)
            mat.mark_modified()
            EditorHost.scene.SetEntityMaterial(entity_id, mid)
        except Exception:
            pass

    @classmethod
    def save_material_to_file(cls, entity_id: int, file_path: str) -> bool:
        """保存 entity 的 material 到 .mat 文件。"""
        try:
            mid = EditorHost.scene.GetEntityMaterial(entity_id)
            from Application.Resource.ResourceManager import ResourceManager
            mat = ResourceManager.GetMaterial(mid)
            mat.save_to_file(file_path)
            return True
        except Exception as e:
            print(f"[SceneBrowser] save_material failed: {e}")
            return False

    @classmethod
    def load_material_from_file(cls, entity_id: int, file_path: str) -> bool:
        """从 .mat 文件加载 material 并绑定到 entity。"""
        try:
            from Application.Resource.Material import Material
            mat = Material.load_from_file(file_path)
            from Application.Resource.ResourceManager import ResourceManager
            new_mid = ResourceManager.material_count + 1
            ResourceManager.material_count = new_mid
            ResourceManager.loaded_material[str(new_mid)] = mat
            EditorHost.scene.SetEntityMaterial(entity_id, new_mid)
            return True
        except Exception as e:
            print(f"[SceneBrowser] load_material failed: {e}")
            return False

    @classmethod
    def set_material_uniform(cls, entity_id: int, name: str, value) -> None:
        """设置 entity material 的单个 uniform 参数。"""
        EditorHost.scene.SetMaterialParams(entity_id, {name: value})

    @classmethod
    def create_material_for_entity(cls, entity_id: int) -> int | None:
        """为实体创建默认材质（Basic shader + Default 纹理）并绑定。返回 material_id。"""
        from Application.Resource.ResourceManager import ResourceManager
        mid = ResourceManager.NewMaterial()
        EditorHost.scene.SetEntityMaterial(entity_id, mid)
        return mid

    @classmethod
    def remove_material_texture(cls, entity_id: int, slot_index: int) -> None:
        """移除实体材质指定槽位的纹理（含渲染器同步）。"""
        from Application.Resource.ResourceManager import ResourceManager
        mid = EditorHost.scene.GetEntityMaterial(entity_id)
        ResourceManager.RemoveMaterialTexture(mid, slot_index)
        if slot_index == 0:
            mat = ResourceManager.GetMaterial(mid)
            new_tex = mat.texture_id_list[0] if mat.texture_id_list else 0
            EditorHost.scene.SetEntityTexture(entity_id, new_tex, slot=0)

    @classmethod
    def add_material_texture(cls, entity_id: int, texture_id: int) -> None:
        """给实体材质追加一个纹理。"""
        from Application.Resource.ResourceManager import ResourceManager
        mid = EditorHost.scene.GetEntityMaterial(entity_id)
        ResourceManager.AddMaterialTexture(mid, texture_id)
# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SCENE_BROWSER
register(NAME_SCENE_BROWSER, SceneBrowserController)
