"""
SceneManager — 场景数据管理器（每 Engine 独立状态 + 独立 ECS 世界）。

架构:
  - _registry: dict[engine_name, SceneManager] — 每个 Engine 持有自己的 SceneManager 实例
  - _active_name: str — 当前活跃的 Engine 名称 (Init 时设置)
  - 每个 SceneManager 实例拥有独立的 esper 世界 (通过 switch_world 隔离)

esper 世界命名规则:
  - "default"      — esper 默认世界 (保留不用)
  - "scene_EditorHost"  — 编辑器场景
  - "scene_GameRuntime" — 运行时场景
  - "scene_MockApp"     — 测试场景

生命周期:
  EditorHost.Init() → SceneManager.Init(EditorHost)     → 创建 scene_EditorHost 世界
  GameRuntime.Init() → SceneManager.Init(GameRuntime)   → 创建 scene_GameRuntime 世界
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
    """场景管理器 — 每 Engine 一个实例，持有独立的 esper 世界。

    实例化: SceneManager("EditorHost", app) — 每个 Engine 创建自己的实例。
    线程安全: set_thread_active() 绑定线程到 engine (过渡期)。
    向后兼容: 保留 classmethod facade，委托到当前线程对应的实例。
    """

    # ── 类级注册表 ─────────────────────────────────────────
    _registry: dict[str, 'SceneManager'] = {}        # engine_name → SceneManager 实例
    _active_name: str = ""                          # 全局默认
    _thread_active: dict[int, str] = {}             # thread_id → engine_name
    _thread_lock = threading.Lock()
    _component_registry: dict[str, type] = {}       # 全局共享
    _world_counter: dict[str, int] = {}             # engine_name → 世界序号 (非 Editor 每次 Init 递增)

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
        self._entity_names: dict[int, str] = {}
        self._entity_parent: dict[int, int] = {}
        self._editor_visible: set[int] = set()    # ★ 编辑器中可见的实体 ID (默认全可见, 空 set = 全部可见)
        self.world_name: str = f"scene_{engine_name}"
        self.game_type = GameType.GAME_3D

        # ★ 组合子管理器
        self.entity_mgr = EntityManager(self)
        self.sync_mgr = SceneSync(self)
        self.comp_mgr = ComponentRegistry(self)
        self.xform_mgr = TransformAccessor(self)
        self.cam_mgr = CameraManager(self)
        self.editor_mgr = EditorState(self)

    # 向后兼容别名: _SceneState 已被吸收，返回 SceneManager 自身
    _SceneState = None  # type: ignore

    def _switch_world(self) -> None:
        """切换到本实例的 esper 世界。"""
        esper.switch_world(self.world_name)

    @classmethod
    def set_thread_active(cls, engine_name: str) -> None:
        """将当前线程绑定到指定 Engine 的场景。

        应在以下位置调用:
          - EditorHost 启动后 (主线程 → "EditorHost")
          - Engine._render_loop() 入口 (渲染线程 → Engine 名称)
          - Engine._logic_loop() 入口 (逻辑线程 → Engine 名称)
        """
        with cls._thread_lock:
            cls._thread_active[threading.get_ident()] = engine_name

    @classmethod
    def _get_active_name(cls) -> str:
        """获取当前线程的活跃 Engine 名称。线程本地优先，回落全局。"""
        tid = threading.get_ident()
        with cls._thread_lock:
            return cls._thread_active.get(tid, cls._active_name)

    @classmethod
    def _state(cls) -> 'SceneManager':
        """返回当前线程对应的 SceneManager 实例，并切换 esper 世界。"""
        name = cls._get_active_name()
        if name not in cls._registry:
            raise RuntimeError(
                f"SceneManager: no instance for engine '{name}'. "
                f"Call SceneManager.Init(engine) first."
            )
        inst = cls._registry[name]
        esper.switch_world(inst.world_name)
        return inst

    @classmethod
    def _state_for(cls, engine_name: str) -> 'SceneManager':
        """返回指定 Engine 的 SceneManager 实例（跨 Engine 操作，不切换世界）。"""
        return cls._registry[engine_name]

    # ============================================================
    # 生命周期 / Lifecycle
    # ============================================================

    @classmethod
    def Init(cls, app) -> None:
        """初始化场景 — 创建 SceneManager 实例并注册。

        EditorHost: 幂等，始终复用同一世界 (scene_EditorHost)。
        GameRuntime: 每次 Init 创建新世界 (scene_GameRuntime_1, _2, ...)，
                     旧世界自动废弃，无需手动清理。
        """
        engine_name = getattr(app, '__name__', type(app).__name__)
        if not cls._active_name:
            cls._active_name = engine_name

        if engine_name in cls._registry:
            inst = cls._registry[engine_name]
            inst.app = app
            # ── EditorHost 幂等: 复用已有世界 ──
            if engine_name == "EditorHost":
                return
            # ── 非 Editor: 递增序号，创建全新世界 ──
            cls._world_counter[engine_name] = cls._world_counter.get(engine_name, 0) + 1
            inst.world_name = f"scene_{engine_name}_{cls._world_counter[engine_name]}"
            inst._reset_state()
        else:
            inst = SceneManager(engine_name, app)
            cls._registry[engine_name] = inst

        # ── 切换到本 Engine 的 ECS 世界（esper 自动创建）──
        esper.switch_world(inst.world_name)
        inst.cam_mgr.create_defaults(inst)
        cls._create_default_cube(inst)

        # ── 首次 Init 时自动注册内置 Component ──
        if not cls._component_registry:
            cls.RegisterComponent("Camera", Camera)
            cls.RegisterComponent("MeshRenderer", MeshRenderer)
            cls.RegisterComponent("Transform", Transform)

    @classmethod
    def _create_default_cameras(cls, inst: 'SceneManager') -> None:
        """委托到 CameraManager。"""
        inst.cam_mgr.create_defaults(inst)

    @classmethod
    def _create_default_cube(cls, inst: 'SceneManager') -> None:
        """在 inst 的当前 esper 世界中创建一个默认 Cube 实体（调试用）。"""
        from Application.Resource.ResourceManager import ResourceManager
        cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')

        cube_id = esper.create_entity(
            Transform(),
            MeshRenderer(mesh_id=cube_mesh_id),
        )
        inst.entities[f'{cube_id}'] = 1
        inst._entity_names[cube_id] = "DefaultCube"
        inst._editor_visible.add(cube_id)
        # 注: GPU 注册延迟到 EditorLayer.OnAttach（渲染器就绪后）

    def _reset_state(self) -> None:
        """重置实例的追踪数据（为新世界做准备）。"""
        self.entities.clear()
        self._entity_names.clear()
        self._entity_parent.clear()
        self._editor_visible.clear()
        self.scene_camera = None
        self.scene_camera_id = None

    @classmethod
    def CreateScene(cls, new_scene_name: str) -> None:
        st = cls._state()
        st.scene[new_scene_name] = new_scene_name

    # ============================================================
    # GameType
    # ============================================================
    # GameType → CameraManager
    # ============================================================

    @classmethod
    def SetGameType(cls, game_type) -> None:
        cls._state().cam_mgr.set_game_type(game_type)

    @classmethod
    def GetGameType(cls):
        return cls._state().cam_mgr.get_game_type()

    # ============================================================
    # 父子关系 → EntityManager
    # ============================================================

    @classmethod
    def SetEntityParent(cls, child_id: int, parent_id: int) -> None:
        cls._state().entity_mgr.set_parent(child_id, parent_id)

    @classmethod
    def GetEntityParent(cls, entity_id: int) -> int | None:
        return cls._state().entity_mgr.get_parent(entity_id)

    @classmethod
    def GetEntityChildren(cls, entity_id: int) -> list[int]:
        return cls._state().entity_mgr.get_children(entity_id)

    @classmethod
    def GetRootEntities(cls) -> list[int]:
        return cls._state().entity_mgr.get_roots()

    # ============================================================
    # 编辑器可见性 → EditorState
    # ============================================================

    @classmethod
    def SetEditorVisible(cls, entity_id: int, visible: bool) -> None:
        cls._state().editor_mgr.set_visible(entity_id, visible)

    @classmethod
    def IsEditorVisible(cls, entity_id: int) -> bool:
        return cls._state().editor_mgr.is_visible(entity_id)

    # ============================================================
    # 渲染可见性 → TransformAccessor
    # ============================================================

    @classmethod
    def SetEntityRenderVisible(cls, entity_id: int, visible: bool) -> None:
        cls._state().xform_mgr.set_render_visible(entity_id, visible)

    @classmethod
    def IsEntityRenderVisible(cls, entity_id: int) -> bool:
        return cls._state().xform_mgr.is_render_visible(entity_id)

    # ============================================================
    # 实体管理 → EntityManager
    # ============================================================

    @classmethod
    def AddEntity(cls, name: str = "") -> int:
        return cls._state().entity_mgr.add(name)

    @classmethod
    def DeleteEntity(cls, entity_id: int) -> bool:
        return cls._state().entity_mgr.delete(entity_id)

    # ============================================================
    # 命名 → EntityManager
    # ============================================================

    @classmethod
    def SetEntityName(cls, entity_id: int, name: str) -> None:
        cls._state().entity_mgr.set_name(entity_id, name)

    @classmethod
    def GetEntityName(cls, entity_id: int) -> str:
        return cls._state().entity_mgr.get_name(entity_id)

    # ============================================================
    # 组件注册表 → ComponentRegistry
    # ============================================================

    @classmethod
    def RegisterComponent(cls, name: str, component_cls: type) -> None:
        cls._state().comp_mgr.register(name, component_cls)

    @classmethod
    def GetRegisteredComponents(cls) -> dict[str, type]:
        return cls._state().comp_mgr.get_all()

    @classmethod
    def AddComponentToEntityByName(cls, entity_id: int, component_name: str) -> bool:
        return cls._state().comp_mgr.add_by_name(entity_id, component_name)

    @classmethod
    def AddComponentToEntity(cls, entity_id: int, component_instance) -> None:
        cls._state().entity_mgr.add_component(entity_id, component_instance)

    # ============================================================
    # Scene ↔ ECS 同步 → SceneSync
    # ============================================================

    @classmethod
    def SyncToScene(cls, scene: object) -> None:
        cls._state().sync_mgr.sync_to_scene(scene)

    @classmethod
    def SyncFromScene(cls, scene: object, clear_existing: bool = True) -> None:
        cls._state().sync_mgr.sync_from_scene(scene, clear_existing)

    # ============================================================
    # 查询接口 → EntityManager
    # ============================================================

    @classmethod
    def GetAllEntityInfos(cls) -> list[dict]:
        return cls._state().entity_mgr.get_all_infos()

    @classmethod
    def GetAllEntitiesWithComponent(cls, component_type: type) -> list[tuple[int, object]]:
        return cls._state().entity_mgr.get_all_with_component(component_type)

    @classmethod
    def EntityExists(cls, entity_id: int) -> bool:
        return cls._state().entity_mgr.exists(entity_id)

    @classmethod
    def HasComponent(cls, entity_id: int, component_cls: type) -> bool:
        cls._state()
        return esper.has_component(entity_id, component_cls)

    @classmethod
    def GetComponent(cls, entity_id: int, component_type: type):
        return cls._state().entity_mgr.get_component(entity_id, component_type)

    @classmethod
    def RemoveComponent(cls, entity_id: int, component_cls: type) -> bool:
        cls._state()
        try:
            esper.remove_component(entity_id, component_cls)
            return True
        except KeyError:
            return False

    @classmethod
    def GetRenderableEntities(cls) -> list:
        cls._state()
        return [eid for eid, rend in esper.get_component(MeshRenderer) if rend.visible]

    # ============================================================
    # 变换 + Mesh/Material/Camera → TransformAccessor
    # ============================================================

    @classmethod
    def GetEntityTransform(cls, entity_id) -> Transform:
        return cls._state().xform_mgr.get_transform(entity_id)

    @classmethod
    def GetEntityModelMatrix(cls, entity_id: int) -> 'np.ndarray':
        return cls._state().xform_mgr.get_model_matrix(entity_id)

    @classmethod
    def GetEntityMesh(cls, entity_id: int) -> int:
        return cls._state().xform_mgr.get_mesh(entity_id)

    @classmethod
    def GetEntityMaterial(cls, entity_id: int) -> int:
        return cls._state().xform_mgr.get_material(entity_id)

    @classmethod
    def SetEntityTransform(cls, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        cls._state().xform_mgr.set_transform(entity_id, position_xyz=position_xyz, rotation_xyz=rotation_xyz, scale_xyz=scale_xyz)

    @classmethod
    def SetEntityMeshRenderer(cls, entity_id=None, *, mesh_id=None, material_id=None, visible=None) -> None:
        cls._state().xform_mgr.set_mesh_renderer(entity_id, mesh_id=mesh_id, material_id=material_id, visible=visible)

    @classmethod
    def SetEntityMaterial(cls, entity_id: int, material_id: int) -> None:
        cls._state().xform_mgr.set_mesh_renderer(entity_id, material_id=material_id)

    @classmethod
    def SetEntityTexture(cls, entity_id: int, texture_id: int, slot: int = 0) -> None:
        st = cls._state()
        from Application.Resource.ResourceManager import ResourceManager
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mr.material_id)
        while len(material.texture_id_list) <= slot:
            material.texture_id_list.append(0)
        material.texture_id_list[slot] = texture_id
        ComponentModifiedEvent.Pack(entity_id, mr, engine=st.app)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    @classmethod
    def SetEntityShader(cls, entity_id: int, shader_id: int) -> None:
        st = cls._state()
        from Application.Resource.ResourceManager import ResourceManager
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mr.material_id)
        uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
        material.set_new_shader(shader_id, uniforms_name_type)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        ComponentModifiedEvent.Pack(entity_id, mr, engine=st.app)

    @classmethod
    def SetMaterialParams(cls, entity_id: int, params: dict) -> None:
        cls._state().xform_mgr.set_material_params(entity_id, params)

    @classmethod
    def SetCameraProperties(cls, entity_id: int, **kwargs) -> None:
        cls._state().xform_mgr.set_camera_properties(entity_id, **kwargs)

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

    @classmethod
    def GetEntityTransformEditor(cls, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': cls.gl_to_editor_position(t.position_x, t.position_y, t.position_z),
            'rotation': (t.rotation_x, t.rotation_y, t.rotation_z),
            'scale': cls.gl_to_editor_scale(t.scale_x, t.scale_y, t.scale_z),
        }

    @classmethod
    def SetEntityTransformEditor(cls, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        cls._state().xform_mgr.set_transform_editor(entity_id, position_xyz=position_xyz, rotation_xyz=rotation_xyz, scale_xyz=scale_xyz)

    @classmethod
    def GetEntityLocalTransformEditor(cls, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': cls.gl_to_editor_position(t.local_pos_x, t.local_pos_y, t.local_pos_z),
            'rotation': (t.local_rot_x, t.local_rot_y, t.local_rot_z),
            'scale': cls.gl_to_editor_scale(t.local_scl_x, t.local_scl_y, t.local_scl_z),
        }

    @classmethod
    def SetEntityLocalTransformEditor(cls, entity_id=None, *, position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        st = cls._state()
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        transform = esper.component_for_entity(entity_id, Transform)
        if position_xyz is not None:
            gl_x, gl_y, gl_z = cls.editor_to_gl_position(*position_xyz)
            transform.local_pos_x, transform.local_pos_y, transform.local_pos_z = gl_x, gl_y, gl_z
            transform.position_x, transform.position_y, transform.position_z = gl_x, gl_y, gl_z
        if rotation_xyz is not None:
            transform.local_rot_x, transform.local_rot_y, transform.local_rot_z = rotation_xyz
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
        if scale_xyz is not None:
            gl_sx, gl_sy, gl_sz = cls.editor_to_gl_scale(*scale_xyz)
            transform.local_scl_x, transform.local_scl_y, transform.local_scl_z = gl_sx, gl_sy, gl_sz
            transform.scale_x, transform.scale_y, transform.scale_z = gl_sx, gl_sy, gl_sz
        ComponentModifiedEvent.Pack(entity_id, transform, engine=st.app)

    # ============================================================
    # 摄像机管理 → CameraManager
    # ============================================================

    @classmethod
    def get_main_camera_id(cls) -> int | None:
        return cls._state().cam_mgr.get_main_id()

    @classmethod
    def get_main_camera_2d_id(cls) -> int | None:
        return cls._state().cam_mgr.get_main_2d_id()
