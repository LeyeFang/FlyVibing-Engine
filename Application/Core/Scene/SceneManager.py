"""
SceneManager — 场景数据管理器（单 esper 世界 + ID 分段隔离 Editor/Runtime）。

架构:
  - 单 esper 世界，不切换，不加锁
  - Editor 实体和 Runtime 实体共存于同一世界
  - _runtime_entities: set[int] 追踪 PIE 动态实体，stop_pie() 精确清理

esper 世界命名:
  - "scene" — 唯一世界（替代旧的 scene_EditorHost / scene_GameRuntime 多世界方案）

生命周期:
  EditorHost.Init() → SceneManager.Init(EditorHost)     → 创建默认实体 (cameras + cube)
  GameRuntime.Init() → SceneManager.Init(GameRuntime)   → 仅注册实例，不创建默认实体
"""

import esper
import math
import numpy as np
import threading

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand, EntityVisibilityCommand, EntityRenderVisibleCommand

# ── 子管理器 (组合模式) ──
from Application.Core.Scene.EntityManager import EntityManager
from Application.Core.Scene.SceneSync import SceneSync
from Application.Core.Scene.ComponentRegistry import ComponentRegistry
from Application.Core.Scene.TransformAccessor import TransformAccessor
from Application.Core.Scene.CameraManager import CameraManager
from Application.Core.Scene.EditorState import EditorState


class SceneManager:
    """场景管理器 — 单实例，单 esper 世界。

    实例化: SceneManager("EditorHost", app) — 创建唯一实例。
    """

    # ── 类级注册表 ─────────────────────────────────────────
    _registry: dict[str, 'SceneManager'] = {}        # engine_name → SceneManager 实例
    _component_registry: dict[str, type] = {}         # 全局共享

    def __init__(self, engine_name: str, app=None) -> None:
        from Application.Core.Scene.Scene import GameType
        self.engine_name = engine_name
        self.app = app
        self.scene: dict = {}      # 场景名注册表（EditorHost 是权威来源）
        self.entities: dict = {}
        self.scene_camera: Camera | None = None
        self.scene_camera_id: int | None = None
        self.main_camera_id: int | None = None
        self.main_camera_2d_id: int | None = None
        self.main_camera_overlay_id: int | None = None
        self._entity_names: dict[int, str] = {}
        self._entity_parent: dict[int, int] = {}
        self._editor_visible: set[int] = set()
        self._sid_map: dict[int, int] = {}     # scene-local sid → esper eid
        self._eid_to_sid: dict[int, int] = {}  # esper eid → scene-local sid
        self.game_type = GameType.GAME_3D
        # ── 场景环境光 (RGB 0..1) — 渲染器每帧注入 uAmbient ──
        #    默认 0.5 (50% 全局光; 业内常用软光基调 — 保证未直照面带也能看清)
        self.ambient_color: tuple = (0.5, 0.5, 0.5)
        # ── 无灯回退: 场景无任何方向光时满亮 (避免"未配置光照=全黑"; shader_protocol §7.3) ──
        self.lighting_fallback: bool = True

        # ★ 组合子管理器
        self.entity_mgr = EntityManager(self)
        self.sync_mgr = SceneSync(self)
        self.comp_mgr = ComponentRegistry(self)
        self.xform_mgr = TransformAccessor(self)
        self.cam_mgr = CameraManager(self)
        self.editor_mgr = EditorState(self)

    # ============================================================
    # 生命周期 / Lifecycle
    # ============================================================

    @classmethod
    def Init(cls, app) -> None:
        """初始化场景 — 为每个 Engine 创建独立的 SceneManager 实例。

        所有实例共享同一个 esper 世界（单 world），但各自维护 entities / _entity_names 等元数据。
        EditorHost: 首次 Init 创建默认实体 (cameras + cube)。
        GameRuntime: 不复用 EditorHost 实例，创建自己的空实例。
        """
        engine_name = getattr(app, '__name__', type(app).__name__)

        if engine_name in cls._registry:
            inst = cls._registry[engine_name]
            inst.app = app
        else:
            inst = SceneManager(engine_name, app)
            cls._registry[engine_name] = inst

        # ── EditorHost 首次: 创建默认实体 ──
        if engine_name == "EditorHost" and not inst.entities:
            inst.cam_mgr.create_defaults(inst)
            cls._create_default_cube(inst)
            cls._create_default_light(inst)

        # ── 自动注册内置 Component ──
        # ★ 必须经由本引擎自己的 inst 注册（独立播放器无 EditorHost 实例,
        #   走 cls.RegisterComponent → _current() 会拿到 None → 崩溃;
        #   注册结果写入全局 _component_registry, 两种途径等价）
        # ★ 单一注册源: ComponentRegistry.ensure_defaults() — 新增内置组件只改一处
        inst.comp_mgr.ensure_defaults()

    @classmethod
    def _current(cls) -> 'SceneManager':
        """返回 EditorHost 的 SceneManager 实例（向后兼容 classmethod 调用）。"""
        return cls._registry.get("EditorHost") or cls._registry.get("MockApp")

    @classmethod
    def _state_for(cls, engine_name: str) -> 'SceneManager':
        """返回指定 Engine 的 SceneManager 实例。"""
        return cls._registry[engine_name]

    @classmethod
    def _create_default_cube(cls, inst: 'SceneManager') -> None:
        """在 inst 的当前 esper 世界中创建默认 Cube 实体（通过 Prefab 实例化）。"""
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.PrefabManager import PrefabManager

        for pid_str, pdata in ResourceManager.loaded_prefab.items():
            if pdata.get('name') == 'DefaultCube' and pdata.get('prefab_data') is not None:
                created = PrefabManager.instantiate_to_scene(pdata['prefab_data'], inst)
                # ★ 默认 Cube 挂 Lighting 材质 (让默认光源可见; 用户实体仍用默认 "Default" 材质)
                if created:
                    try:
                        lit_id = ResourceManager.GetBuiltinMaterial('DefaultLit')
                        inst.SetEntityMaterial(created[0], lit_id)
                    except Exception:
                        pass
                return

    @classmethod
    def _create_default_light(cls, inst: 'SceneManager') -> None:
        """创建默认 Sun (方向光, DefaultLight.prefab) — 默认场景即带光照。"""
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.PrefabManager import PrefabManager

        for pid_str, pdata in ResourceManager.loaded_prefab.items():
            if pdata.get('name') == 'DefaultLight' and pdata.get('prefab_data') is not None:
                PrefabManager.instantiate_to_scene(pdata['prefab_data'], inst)
                return

    def _reset_state(self) -> None:
        """重置实例的追踪数据（为新世界做准备）。"""
        self.entities.clear()
        self._entity_names.clear()
        self._entity_parent.clear()
        self._editor_visible.clear()
        self.scene_camera = None
        self.scene_camera_id = None

    def CreateScene(self, new_scene_name: str) -> None:
        st = self
        st.scene[new_scene_name] = new_scene_name

    # ============================================================
    # 环境光 (场景级光照设置 — 渲染器每帧读取)
    # ============================================================

    def SetAmbientColor(self, r: float, g: float, b: float) -> None:
        """设置场景环境光 (RGB 0..1) — 下一帧生效。"""
        self.ambient_color = (float(r), float(g), float(b))

    def GetAmbientColor(self) -> tuple:
        """返回场景环境光 (RGB)。"""
        return tuple(self.ambient_color)

    def SetLightingFallback(self, enabled: bool) -> None:
        """设置"无灯满亮回退"开关 (无方向光时环境光强制 1.0)。"""
        self.lighting_fallback = bool(enabled)

    def GetLightingFallback(self) -> bool:
        return bool(self.lighting_fallback)

    # ============================================================
    # GameType
    # ============================================================
    # GameType → CameraManager
    # ============================================================

    def SetGameType(self, game_type) -> None:
        self.cam_mgr.set_game_type(game_type)

    def GetGameType(self):
        return self.cam_mgr.get_game_type()

    # ============================================================
    # 父子关系 → EntityManager
    # ============================================================

    def SetEntityParent(self, child_id: int, parent_id: int) -> None:
        self.entity_mgr.set_parent(child_id, parent_id)

    def GetEntityParent(self, entity_id: int) -> int | None:
        return self.entity_mgr.get_parent(entity_id)

    def GetEntityChildren(self, entity_id: int) -> list[int]:
        return self.entity_mgr.get_children(entity_id)

    def GetRootEntities(self) -> list[int]:
        return self.entity_mgr.get_roots()

    # ============================================================
    # 编辑器可见性 → EditorState
    # ============================================================

    def SetEditorVisible(self, entity_id: int, visible: bool) -> None:
        self.editor_mgr.set_visible(entity_id, visible)

    def IsEditorVisible(self, entity_id: int) -> bool:
        return self.editor_mgr.is_visible(entity_id)

    # ============================================================
    # 渲染可见性 → TransformAccessor
    # ============================================================

    def SetEntityRenderVisible(self, entity_id: int, visible: bool) -> None:
        self.xform_mgr.set_render_visible(entity_id, visible)

    def IsEntityRenderVisible(self, entity_id: int) -> bool:
        return self.xform_mgr.is_render_visible(entity_id)

    def SetEntitiesRenderVisible(self, entity_ids, visible: bool) -> int:
        """批量设置多个实体的渲染可见性 — 单批命令 (同一帧全部生效)。

        用于多部件组合体 (cue 箭把+箭头等) 的原子显隐: 命令经 enqueue_many
        一次入队, 渲染帧边界不会把该组切成两半 (见 CommandQueue 原子批)。

        Returns:
            实际应用到的实体数量
        """
        cmds = []
        seen: set[int] = set()
        for eid in entity_ids:
            eid = int(eid)
            if eid in seen:
                continue
            seen.add(eid)
            try:
                mr = esper.component_for_entity(eid, MeshRenderer)
            except KeyError:
                continue
            mr.visible = visible
            cmds.append(EntityRenderVisibleCommand(eid, visible=visible))
        if cmds:
            _renderer = getattr(self.app, 'renderer', None)
            if _renderer is not None:
                if hasattr(_renderer, 'enqueue_many'):
                    _renderer.enqueue_many(cmds)
                else:
                    for c in cmds:
                        _renderer.enqueue(c)
        return len(cmds)

    # ============================================================
    # 实体管理 → EntityManager (实例方法 — 各自引擎独立)
    # ============================================================

    def AddEntity(self, name: str = "", *components) -> int:
        """在本实例上创建实体。Editor 调则入 Editor，Runtime 调则入 Runtime。"""
        return self.entity_mgr.add(name, *components)

    def DeleteEntity(self, entity_id: int) -> bool:
        return self.entity_mgr.delete(entity_id)

    # ============================================================
    # 命名 → EntityManager
    # ============================================================

    def SetEntityName(self, entity_id: int, name: str) -> None:
        self.entity_mgr.set_name(entity_id, name)

    def GetEntityName(self, entity_id: int) -> str:
        return self.entity_mgr.get_name(entity_id)

    def GetEntityByName(self, name: str) -> int:
        """按名称查找实体 ID。未找到返回 -1。"""
        return self.entity_mgr.get_id_by_name(name)

    # ============================================================
    # 组件注册表 → ComponentRegistry
    # ============================================================

    @classmethod
    def RegisterComponent(cls, name: str, component_cls: type) -> None:
        cls._current().comp_mgr.register(name, component_cls)

    @classmethod
    def GetRegisteredComponents(cls) -> dict[str, type]:
        return cls._current().comp_mgr.get_all()

    def AddComponentToEntityByName(self, entity_id: int, component_name: str) -> bool:
        return self.comp_mgr.add_by_name(entity_id, component_name)

    def AddComponentToEntity(self, entity_id: int, component_instance) -> None:
        self.entity_mgr.add_component(entity_id, component_instance)

    # ============================================================
    # Scene ↔ ECS 同步 → SceneSync
    # ============================================================

    def SyncToScene(self, scene: object) -> None:
        self.sync_mgr.sync_to_scene(scene)

    def SyncFromScene(self, scene: object, clear_existing: bool = True) -> None:
        self.sync_mgr.sync_from_scene(scene, clear_existing)

    # ============================================================
    # 查询接口 → EntityManager
    # ============================================================

    def GetAllEntityInfos(self) -> list[dict]:
        return self.entity_mgr.get_all_infos()

    def GetAllEntitiesWithComponent(self, component_type: type) -> list[tuple[int, object]]:
        return self.entity_mgr.get_all_with_component(component_type)

    def EntityExists(self, entity_id: int) -> bool:
        return self.entity_mgr.exists(entity_id)

    def HasComponent(self, entity_id: int, component_cls: type) -> bool:
        self
        return esper.has_component(entity_id, component_cls)

    def GetComponent(self, entity_id: int, component_type: type):
        return self.entity_mgr.get_component(entity_id, component_type)

    def RemoveComponent(self, entity_id: int, component_cls: type) -> bool:
        self
        try:
            esper.remove_component(entity_id, component_cls)
            return True
        except KeyError:
            return False

    def GetRenderableEntities(self) -> list:
        """返回当前实例中可见的 MeshRenderer 实体。"""
        result = []
        for eid, rend in esper.get_component(MeshRenderer):
            if not rend.visible:
                continue
            if str(eid) in self.entities:
                result.append(eid)
        return result

    # ============================================================
    # 变换 + Mesh/Material/Camera → TransformAccessor
    # ============================================================

    def GetEntityTransform(self, entity_id) -> Transform:
        return self.xform_mgr.get_transform(entity_id)

    def GetEntityModelMatrix(self, entity_id: int) -> 'np.ndarray':
        return self.xform_mgr.get_model_matrix(entity_id)

    def GetEntityMesh(self, entity_id: int) -> int:
        return self.xform_mgr.get_mesh(entity_id)

    def GetEntityMaterial(self, entity_id: int) -> int:
        return self.xform_mgr.get_material(entity_id)

    def SetEntityTransform(self, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        self.xform_mgr.set_transform(entity_id, position_xyz=position_xyz, rotation_xyz=rotation_xyz, scale_xyz=scale_xyz)

    def SetEntityMeshRenderer(self, entity_id=None, *, mesh_id=None, material_id=None, visible=None) -> None:
        self.xform_mgr.set_mesh_renderer(entity_id, mesh_id=mesh_id, material_id=material_id, visible=visible)

    def SetEntityMaterial(self, entity_id: int, material_id: int) -> None:
        self.xform_mgr.set_mesh_renderer(entity_id, material_id=material_id)

    @staticmethod
    def _ensure_unique_material(st: 'SceneManager', entity_id: int, mr) -> None:
        """确保修改 material 不污染其他 entity。

        两种情形先 clone 一份给本 entity 再改：
          1. 当前 material 被多个 entity 共享；
          2. 当前 material 是**内置材质模板**（builtin_name 非空，如 Default/
             DefaultLit）——即使当前只有本 entity 引用它也不得就地修改，
             否则会污染未来所有新建实体（live 演示逮到的真实 bug）。
        """
        from Application.Resource.ResourceManager import ResourceManager
        current_mid = mr.material_id
        is_builtin = False
        try:
            mat = ResourceManager.GetMaterial(current_mid)
            is_builtin = getattr(mat, 'builtin_name', None) is not None
        except Exception:
            pass
        if not is_builtin:
            # 统计使用该 material 的 entity 数量
            share_count = 0
            for eid, other_mr in esper.get_component(MeshRenderer):
                if other_mr.material_id == current_mid:
                    share_count += 1
                    if share_count > 1:
                        break
            if share_count <= 1:
                return  # 独占（非内置），无需 clone

        # 内置模板 / 多实体共享 → clone
        new_mid = ResourceManager.CloneMaterial(current_mid)
        mr.material_id = new_mid
        # 重新注册 GPU 资源（新 material 需要新 uniform buffer 等）
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    def SetEntityTexture(self, entity_id: int, texture_id: int, slot: int = 0) -> None:
        st = self
        from Application.Resource.ResourceManager import ResourceManager
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        SceneManager._ensure_unique_material(st, entity_id, mr)
        material = ResourceManager.GetMaterial(mr.material_id)
        while len(material.texture_id_list) <= slot:
            material.texture_id_list.append(0)
        material.texture_id_list[slot] = texture_id
        ComponentModifiedEvent.Pack(entity_id, mr, engine=st.app)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    def SetEntityShader(self, entity_id: int, shader_id: int) -> None:
        st = self
        from Application.Resource.ResourceManager import ResourceManager
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        SceneManager._ensure_unique_material(st, entity_id, mr)
        material = ResourceManager.GetMaterial(mr.material_id)
        uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
        material.set_new_shader(shader_id, uniforms_name_type)
        material.mark_modified()
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        ComponentModifiedEvent.Pack(entity_id, mr, engine=st.app)

    def SetMaterialParams(self, entity_id: int, params: dict) -> None:
        st = self
        from Application.Resource.ResourceManager import ResourceManager
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        SceneManager._ensure_unique_material(st, entity_id, mr)
        self.xform_mgr.set_material_params(entity_id, params)
        mat = ResourceManager.GetMaterial(mr.material_id)
        if mat is not None:
            mat.mark_modified()

    def SetCameraProperties(self, entity_id: int, **kwargs) -> None:
        self.xform_mgr.set_camera_properties(entity_id, **kwargs)

    # ============================================================
    # 坐标系转换 → Core/Math/CoordinateSystem
    # ============================================================

    @staticmethod
    def gl_to_editor_position(gl_x, gl_y, gl_z):
        from Application.Core.Math.CoordinateSystem import gl_to_editor_position as _fn
        return _fn(gl_x, gl_y, gl_z)

    @staticmethod
    def editor_to_gl_position(editor_x, editor_y, editor_z):
        from Application.Core.Math.CoordinateSystem import editor_to_gl_position as _fn
        return _fn(editor_x, editor_y, editor_z)

    @staticmethod
    def gl_to_editor_scale(gl_sx, gl_sy, gl_sz):
        from Application.Core.Math.CoordinateSystem import gl_to_editor_scale as _fn
        return _fn(gl_sx, gl_sy, gl_sz)

    @staticmethod
    def editor_to_gl_scale(editor_sx, editor_sy, editor_sz):
        from Application.Core.Math.CoordinateSystem import editor_to_gl_scale as _fn
        return _fn(editor_sx, editor_sy, editor_sz)

    def GetEntityTransformEditor(self, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': SceneManager.gl_to_editor_position(t.position_x, t.position_y, t.position_z),
            'rotation': SceneManager.gl_to_editor_position(t.rotation_x, t.rotation_y, t.rotation_z),
            'scale': SceneManager.gl_to_editor_scale(t.scale_x, t.scale_y, t.scale_z),
        }

    def SetEntityTransformEditor(self, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        self.xform_mgr.set_transform_editor(entity_id, position_xyz=position_xyz, rotation_xyz=rotation_xyz, scale_xyz=scale_xyz)

    def GetEntityLocalTransformEditor(self, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': SceneManager.gl_to_editor_position(t.local_pos_x, t.local_pos_y, t.local_pos_z),
            'rotation': SceneManager.gl_to_editor_position(t.local_rot_x, t.local_rot_y, t.local_rot_z),
            'scale': SceneManager.gl_to_editor_scale(t.local_scl_x, t.local_scl_y, t.local_scl_z),
        }

    def SetEntityLocalTransformEditor(self, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        st = self
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        transform = esper.component_for_entity(entity_id, Transform)
        parent_id = st._entity_parent.get(entity_id)

        if position_xyz is not None:
            gl_x, gl_y, gl_z = SceneManager.editor_to_gl_position(*position_xyz)
            transform.local_pos_x, transform.local_pos_y, transform.local_pos_z = gl_x, gl_y, gl_z
            # 有父实体时从 local + parent world 计算世界位置
            if parent_id is not None and parent_id != entity_id:
                world_pos = SceneManager._local_to_world_position(
                    st, (gl_x, gl_y, gl_z), parent_id,
                )
                transform.position_x, transform.position_y, transform.position_z = world_pos
            else:
                transform.position_x, transform.position_y, transform.position_z = gl_x, gl_y, gl_z

        if rotation_xyz is not None:
            gl_rx, gl_ry, gl_rz = SceneManager.editor_to_gl_position(*rotation_xyz)
            transform.local_rot_x, transform.local_rot_y, transform.local_rot_z = gl_rx, gl_ry, gl_rz
            # 有父实体时: world_rot = parent_world_rot + child_local_rot (Euler 累加)
            if parent_id is not None and parent_id != entity_id:
                from Application.Core.Math.Transform import local_to_world_rotation
                parent_t = esper.component_for_entity(parent_id, Transform)
                p_rot = (parent_t.rotation_x, parent_t.rotation_y, parent_t.rotation_z)
                wrx, wry, wrz = local_to_world_rotation((gl_rx, gl_ry, gl_rz), p_rot)
                transform.rotation_x, transform.rotation_y, transform.rotation_z = wrx, wry, wrz
            else:
                transform.rotation_x, transform.rotation_y, transform.rotation_z = gl_rx, gl_ry, gl_rz

        if scale_xyz is not None:
            gl_sx, gl_sy, gl_sz = SceneManager.editor_to_gl_scale(*scale_xyz)
            transform.local_scl_x, transform.local_scl_y, transform.local_scl_z = gl_sx, gl_sy, gl_sz
            # 有父实体时: world_scale = parent_world_scale × child_local_scale (分量乘)
            if parent_id is not None and parent_id != entity_id:
                parent_t = esper.component_for_entity(parent_id, Transform)
                transform.scale_x = parent_t.scale_x * gl_sx
                transform.scale_y = parent_t.scale_y * gl_sy
                transform.scale_z = parent_t.scale_z * gl_sz
            else:
                transform.scale_x, transform.scale_y, transform.scale_z = gl_sx, gl_sy, gl_sz

        ComponentModifiedEvent.Pack(entity_id, transform, engine=st.app)

    @staticmethod
    def _local_to_world_position(st, local_pos: tuple, parent_id: int) -> tuple:
        """将子实体的 local 位置转换为 world 位置（沿 parent chain 传播）。"""
        import numpy as np
        from Application.Core.Math.Transform import calculate_entity_model

        # ★ 从 parent 的 world Transform 直接构建模型矩阵（不递归以避免锁死锁）
        #   parent 的 world position/rotation/scale 已经是正确的世界值
        parent_t = esper.component_for_entity(parent_id, Transform)
        parent_model = calculate_entity_model(
            position=(parent_t.position_x, parent_t.position_y, parent_t.position_z),
            rotation=(parent_t.rotation_x, parent_t.rotation_y, parent_t.rotation_z),
            scale=(parent_t.scale_x, parent_t.scale_y, parent_t.scale_z),
        )
        local_vec = np.array([local_pos[0], local_pos[1], local_pos[2], 1.0], dtype=np.float64)
        world_vec = local_vec @ parent_model  # row-vector
        return (float(world_vec[0]), float(world_vec[1]), float(world_vec[2]))

    # ============================================================
    # 摄像机管理 → CameraManager
    # ============================================================

    def get_main_camera_id(self) -> int | None:
        return self.cam_mgr.get_main_id()

    def get_main_camera_2d_id(self) -> int | None:
        return self.cam_mgr.get_main_2d_id()

    def get_main_camera_overlay_id(self) -> int | None:
        return self.cam_mgr.get_main_overlay_id()
