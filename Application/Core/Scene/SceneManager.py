"""
SceneManager — 场景数据管理器（每 Engine 独立状态 + 独立 ECS 世界）。

架构:
  - _registry: dict[engine_name, SceneState] — 每个 Engine 子类拥有独立的场景数据
  - _active_name: str — 当前活跃的 Engine 名称 (Init 时设置)
  - 每个 _SceneState 拥有独立的 esper 世界 (通过 switch_world 隔离)

esper 世界命名规则:
  - "default"      — esper 默认世界 (保留不用)
  - "scene_EditorHost"  — 编辑器场景
  - "scene_GameRuntime" — 运行时场景
  - "scene_MockApp"     — 测试场景

生命周期:
  EditorHost.Init() → SceneManager.Init(EditorHost)     → 创建 scene_EditorHost 世界
  GameRuntime.Init() → SceneManager.Init(GameRuntime)   → 创建 scene_GameRuntime 世界
  GameRuntime.Stop() → SceneManager.Shutdown(GameRuntime) → 删除 scene_GameRuntime 世界
"""

import esper
import math
import numpy as np
import threading

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand


# ═══════════════════════════════════════════════════════════════
# Per-Engine 场景状态
# ═══════════════════════════════════════════════════════════════

class _SceneState:
    """单个 Engine 的场景数据容器。"""
    __slots__ = (
        'app', 'scene', 'entities',
        'scene_camera', 'scene_camera_id',
        'main_camera_id', 'main_camera_2d_id',
        '_entity_names', '_entity_parent',
        'world_name',
    )

    def __init__(self):
        self.app = None
        self.scene: dict = {}
        self.entities: dict = {}
        self.scene_camera: Camera | None = None
        self.scene_camera_id: int | None = None
        self.main_camera_id: int | None = None
        self.main_camera_2d_id: int | None = None
        self._entity_names: dict[int, str] = {}
        self._entity_parent: dict[int, int] = {}
        self.world_name: str = ""


class SceneManager:
    """场景管理器 — 每 Engine 独立的场景数据 + ECS 世界。

    线程安全: 每个线程通过 set_thread_active() 绑定到特定 Engine。
    同一 Engine 的多个线程共享同一个场景数据（但 ECS 世界切换是线程安全的关键）。
    """

    # ── 类级注册表 ─────────────────────────────────────────
    _registry: dict[str, _SceneState] = {}
    _active_name: str = ""                          # 全局默认 (线程本地未设置时的回落)
    _thread_active: dict[int, str] = {}             # thread_id → engine_name
    _thread_lock = threading.Lock()
    _component_registry: dict[str, type] = {}       # 组件注册表: name → Component class

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
    def _state(cls) -> _SceneState:
        """返回当前线程对应 Engine 的场景状态，并切换到对应的 esper 世界。"""
        name = cls._get_active_name()
        if name not in cls._registry:
            raise RuntimeError(
                f"SceneManager: no scene for engine '{name}'. "
                f"Call SceneManager.Init(engine) first."
            )
        st = cls._registry[name]
        esper.switch_world(st.world_name)
        return st

    @classmethod
    def _state_for(cls, engine_name: str) -> _SceneState:
        """返回指定 Engine 的场景状态（用于跨 Engine 操作）。"""
        return cls._registry[engine_name]

    # ============================================================
    # 生命周期 / Lifecycle
    # ============================================================

    @classmethod
    def Init(cls, app) -> None:
        """初始化场景 — 为当前 Engine 创建独立的场景状态 + ECS 世界。

        幂等：同一 Engine 多次调用不重复初始化。
        app 可以是 Engine 子类 (如 EditorHost) 或实例 (如 MockApp)。

        注意: Init() 不自动绑定线程 —— 调用方需通过 set_thread_active()
        将当前线程绑定到对应 Engine，确保多线程环境下 ECS 世界不串扰。
        """
        engine_name = getattr(app, '__name__', type(app).__name__)
        # 设置全局默认 (仅在没有线程本地时回落使用)
        if not cls._active_name:
            cls._active_name = engine_name

        if engine_name in cls._registry:
            cls._state().app = app
            return

        st = _SceneState()
        st.app = app
        st.scene["default"] = "default"
        st.world_name = f"scene_{engine_name}"
        cls._registry[engine_name] = st

        # ── 切换到本 Engine 的 ECS 世界（esper 自动创建）──
        esper.switch_world(st.world_name)

        # ── 3D 透视摄像机 ──
        st.main_camera_id = esper.create_entity(Transform(), Camera(True))
        st.scene_camera_id = st.main_camera_id
        st.scene_camera = esper.component_for_entity(st.scene_camera_id, Camera)
        st.entities[f'{st.main_camera_id}'] = 1
        st._entity_names[st.main_camera_id] = "Camera"

        # ── 2D 正交俯视摄像机 ──
        st.main_camera_2d_id = esper.create_entity(
            Transform(
                position_x=0.0, position_y=0.0, position_z=10.0,
                rotation_x=math.pi / 2.0,
            ),
            Camera(is_primary=False),
        )
        cam_2d = esper.component_for_entity(st.main_camera_2d_id, Camera)
        cam_2d.projection_type = ProjectionType.ORTHOGRAPHIC
        cam_2d.ortho_size = 10.0
        cam_2d.near_plane = 0.1
        cam_2d.far_plane = 100.0
        st.entities[f'{st.main_camera_2d_id}'] = 1
        st._entity_names[st.main_camera_2d_id] = "Camera2D"

        # ── 首次 Init 时自动注册内置 Component ──
        if not cls._component_registry:
            cls.RegisterComponent("Camera", Camera)
            cls.RegisterComponent("MeshRenderer", MeshRenderer)
            cls.RegisterComponent("Transform", Transform)

    @classmethod
    def Shutdown(cls, engine_name: str) -> None:
        """清理指定 Engine 的场景数据和 ECS 世界。"""
        if engine_name not in cls._registry:
            return
        st = cls._registry.pop(engine_name)
        st.entities.clear()
        st._entity_names.clear()
        st._entity_parent.clear()

        # ── 删除 ECS 世界 ──
        #     esper.delete_world() 不允许删除当前活跃的世界，
        #     先切回默认世界再删除
        world_to_delete = st.world_name
        try:
            esper.switch_world("default")
            esper.delete_world(world_to_delete)
        except Exception:
            pass  # 世界可能已被删除或不存在

    @classmethod
    def CreateScene(cls, new_scene_name: str) -> None:
        st = cls._state()
        st.scene[new_scene_name] = new_scene_name

    # ============================================================
    # 父子关系 / Parent-Child Hierarchy
    # ============================================================

    @classmethod
    def SetEntityParent(cls, child_id: int, parent_id: int) -> None:
        st = cls._state()
        if parent_id and parent_id != 0:
            st._entity_parent[child_id] = parent_id
        else:
            st._entity_parent.pop(child_id, None)

    @classmethod
    def GetEntityParent(cls, entity_id: int) -> int | None:
        return cls._state()._entity_parent.get(entity_id)

    @classmethod
    def GetEntityChildren(cls, entity_id: int) -> list[int]:
        st = cls._state()
        return [cid for cid, pid in st._entity_parent.items() if pid == entity_id]

    @classmethod
    def GetRootEntities(cls) -> list[int]:
        st = cls._state()
        all_ids = list(st.entities.keys())
        return [int(eid) for eid in all_ids if int(eid) not in st._entity_parent]

    # ============================================================
    # 实体管理 / Entity Management
    # ============================================================

    @classmethod
    def AddEntity(cls, name: str = "") -> int:
        st = cls._state()
        entity_id = esper.create_entity(Transform())
        st.entities[f'{entity_id}'] = 1
        if name:
            st._entity_names[entity_id] = name
        return entity_id

    @classmethod
    def DeleteEntity(cls, entity_id: int) -> bool:
        """删除实体及其所有子实体。

        从 ECS 世界、entities 注册表、名称表、父子关系表中移除。
        返回是否成功删除。
        """
        st = cls._state()
        if f'{entity_id}' not in st.entities:
            return False

        # ── 递归删除子实体 ──
        children = cls.GetEntityChildren(entity_id)
        for child_id in children:
            cls.DeleteEntity(child_id)

        # ── 从父实体解除关系 ──
        parent_id = st._entity_parent.pop(entity_id, None)
        # 不需要通知父实体，esper 会自动处理组件关联

        # ── 清理追踪数据 ──
        st.entities.pop(f'{entity_id}', None)
        st._entity_names.pop(entity_id, None)

        # ── 通知渲染器注销 GPU 资源 ──
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=False))

        # ── 从 ECS 世界删除 (esper 自动清理所有关联 Component) ──
        try:
            esper.delete_entity(entity_id)
        except KeyError:
            pass

        return True

    # ============================================================
    # 组件注册表 / Component Registry
    # ============================================================

    @classmethod
    def RegisterComponent(cls, name: str, component_cls: type) -> None:
        """注册一个可用的 Component 类型（供编辑器 UI 列出可选组件）。"""
        cls._component_registry[name] = component_cls

    @classmethod
    def GetRegisteredComponents(cls) -> dict[str, type]:
        """获取所有已注册的 Component 类型。"""
        return dict(cls._component_registry)

    @classmethod
    def AddComponentToEntityByName(cls, entity_id: int, component_name: str) -> bool:
        """按名称给实体添加 Component（通过注册表查找）。"""
        comp_cls = cls._component_registry.get(component_name)
        if comp_cls is None:
            return False
        if esper.has_component(entity_id, comp_cls):
            return False  # 已存在，不重复添加
        instance = comp_cls()
        cls.AddComponentToEntity(entity_id, instance)
        return True

    @classmethod
    def SetEntityName(cls, entity_id: int, name: str) -> None:
        st = cls._state()
        if name.strip():
            st._entity_names[entity_id] = name.strip()
        else:
            st._entity_names.pop(entity_id, None)

    @classmethod
    def GetEntityName(cls, entity_id: int) -> str:
        return cls._state()._entity_names.get(entity_id, "")

    @classmethod
    def GetAllEntityInfos(cls) -> list[dict]:
        st = cls._state()
        result = []
        all_ids = [int(k) for k in st.entities.keys()]
        for entity_id in all_ids:
            info = {
                'entity_id': entity_id,
                'name': cls.GetEntityName(entity_id),
                'has_mesh': esper.has_component(entity_id, MeshRenderer),
                'has_camera': esper.has_component(entity_id, Camera),
            }
            result.append(info)
        return result

    @classmethod
    def AddComponentToEntity(
        cls, entity_id: int, component_instance: Component
    ) -> None:
        st = cls._state()
        esper.add_component(entity_id, component_instance)
        NewComponentEvent.Pack(entity_id, component_instance, engine=st.app)
        if isinstance(component_instance, MeshRenderer):
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    # ============================================================
    # 查询接口 / Query Interface
    # ============================================================

    @classmethod
    def GetSceneCamera(cls) -> tuple[Camera, Transform]:
        st = cls._state()
        camera = esper.component_for_entity(st.scene_camera_id, Camera)
        transform = esper.component_for_entity(st.scene_camera_id, Transform)
        return camera, transform

    @classmethod
    def GetRenderableEntities(cls) -> list:
        entity_id_list = []
        for entity_id, rend in esper.get_component(MeshRenderer):
            if rend.visible:
                entity_id_list.append(entity_id)
        return entity_id_list

    @classmethod
    def GetEntityTransform(cls, entity_id) -> Transform:
        return esper.component_for_entity(entity_id, Transform)

    @classmethod
    def GetEntityModelMatrix(cls, entity_id: int) -> 'np.ndarray':
        from Application.Core.Math.Transform import calculate_entity_model
        t = cls.GetEntityTransform(entity_id)
        return calculate_entity_model(
            position=(t.position_x, t.position_y, t.position_z),
            rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
            scale=(t.scale_x, t.scale_y, t.scale_z),
        )

    @classmethod
    def GetEntityMesh(cls, entity_id: int) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        return mesh_rend.mesh_id

    @classmethod
    def GetEntityMaterial(cls, entity_id: int) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        return mesh_rend.material_id

    @classmethod
    def GetEntityTexture(cls, entity_id: int, slot: int = 0) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mesh_rend.material_id)
        if slot < len(material.texture_id_list):
            return material.texture_id_list[slot]
        return 0

    # ============================================================
    # 修改接口 / Modification Interface
    # ============================================================

    @classmethod
    def SetEntityTransform(
        cls, entity_id: int = None,
        position_xyz: tuple = None, rotation_xyz: tuple = None, scale_xyz: tuple = None,
    ) -> None:
        st = cls._state()
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        transform = esper.component_for_entity(entity_id, Transform)
        if position_xyz is not None:
            transform.position_x, transform.position_y, transform.position_z = position_xyz
        if rotation_xyz is not None:
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
        if scale_xyz is not None:
            transform.scale_x, transform.scale_y, transform.scale_z = scale_xyz
        ComponentModifiedEvent.Pack(entity_id, transform, engine=st.app)

    @classmethod
    def SetMainCameraTransform(
        cls,
        position_x: float = None, position_y: float = None, position_z: float = None,
        rotation_x: float = None, rotation_y: float = None, rotation_z: float = None,
    ) -> None:
        st = cls._state()
        transform = esper.component_for_entity(st.main_camera_id, Transform)
        if position_x is not None: transform.position_x = position_x
        if position_y is not None: transform.position_y = position_y
        if position_z is not None: transform.position_z = position_z
        if rotation_x is not None: transform.rotation_x = rotation_x
        if rotation_y is not None: transform.rotation_y = rotation_y
        if rotation_z is not None: transform.rotation_z = rotation_z

    @classmethod
    def SetEntityMeshRenderer(
        cls, entity_id: int,
        visible: bool = None, mesh_id: int = None, material_id: int = None,
    ) -> None:
        st = cls._state()
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        changed = False
        if visible is not None:
            mesh_rend.visible = visible
            changed = True
        if mesh_id is not None:
            mesh_rend.mesh_id = mesh_id
            changed = True
        if material_id is not None:
            if material_id == 0:
                # ── 兜底: material=0 时自动创建新材质，避免渲染崩溃 ──
                material_id = ResourceManager.NewMaterial()
            mesh_rend.material_id = material_id
            changed = True
        if changed:
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        if visible is not None:
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=visible))
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=st.app)

    @classmethod
    def NewEntityMaterial(cls, entity_id: int, shader_id: int = None) -> int:
        if shader_id is not None:
            new_material_id = ResourceManager.NewMaterial()
            material = ResourceManager.GetMaterial(new_material_id)
            uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
            material.set_new_shader(shader_id, uniforms_name_type)
        else:
            new_material_id = ResourceManager.NewMaterial()
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        mesh_rend.material_id = new_material_id
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls._state().app)
        return new_material_id

    @classmethod
    def SetEntityMaterial(cls, entity_id: int, material_id: int) -> None:
        st = cls._state()
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        if material_id == 0:
            material_id = ResourceManager.NewMaterial()
        mesh_rend.material_id = material_id
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=st.app)
        # ★ 通知渲染器重新注册 (刷新缓存的 material_id / shader_id / texture_id)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    @classmethod
    def SetEntityTexture(cls, entity_id: int, texture_id: int, slot: int = 0) -> None:
        st = cls._state()
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mesh_rend.material_id)
        while len(material.texture_id_list) <= slot:
            material.texture_id_list.append(0)
        material.texture_id_list[slot] = texture_id
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=st.app)
        # ★ 通知渲染器重新注册 (刷新缓存的 texture_id)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    @classmethod
    def SetEntityShader(cls, entity_id: int, shader_id: int) -> None:
        st = cls._state()
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        entity_material = ResourceManager.GetMaterial(mesh_rend.material_id)
        uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
        entity_material.set_new_shader(shader_id, uniforms_name_type)
        # ★ 通知渲染器重新注册 (刷新缓存的 shader_id)
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls._state().app)

    @classmethod
    def SetMaterialParams(cls, entity_id: int, params: dict) -> None:
        """批量设置 entity 材质的着色器参数（uniform）。

        跳过材质中不存在的参数名，不再抛出异常。
        """
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        try:
            mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
            material_id = mesh_rend.material_id
            material = ResourceManager.GetMaterial(material_id)
            for u_name, u_value in params.items():
                if u_name in material.uniforms_data:
                    material.uniforms_data[u_name] = u_value
        except KeyError:
            raise ValueError(f"Entity '{entity_id}' do not have mesh renderer")

    # ============================================================
    # 坐标系转换 / Coordinate Conversion
    # ============================================================

    @staticmethod
    def gl_to_editor_position(gl_x: float, gl_y: float, gl_z: float) -> tuple[float, float, float]:
        return (gl_x, -gl_z, gl_y)

    @staticmethod
    def editor_to_gl_position(editor_x: float, editor_y: float, editor_z: float) -> tuple[float, float, float]:
        return (editor_x, editor_z, -editor_y)

    @staticmethod
    def gl_to_editor_scale(gl_sx: float, gl_sy: float, gl_sz: float) -> tuple[float, float, float]:
        """GL 轴缩放 → 编辑器轴缩放: 交换 Y↔Z, 无需符号翻转 (scale 是大小量)。"""
        return (gl_sx, gl_sz, gl_sy)

    @staticmethod
    def editor_to_gl_scale(editor_sx: float, editor_sy: float, editor_sz: float) -> tuple[float, float, float]:
        """编辑器轴缩放 → GL 轴缩放: 交换 Y↔Z。"""
        return (editor_sx, editor_sz, editor_sy)

    @classmethod
    def GetEntityTransformEditor(cls, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': cls.gl_to_editor_position(t.position_x, t.position_y, t.position_z),
            'rotation': (t.rotation_x, t.rotation_y, t.rotation_z),
            'scale': cls.gl_to_editor_scale(t.scale_x, t.scale_y, t.scale_z),
        }

    @classmethod
    def SetEntityTransformEditor(
        cls, entity_id: int = None,
        position_xyz: tuple = None, rotation_xyz: tuple = None, scale_xyz: tuple = None,
    ) -> None:
        st = cls._state()
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        transform = esper.component_for_entity(entity_id, Transform)
        modified = False
        if position_xyz is not None:
            gl_x, gl_y, gl_z = cls.editor_to_gl_position(*position_xyz)
            transform.position_x, transform.position_y, transform.position_z = gl_x, gl_y, gl_z
            modified = True
        if rotation_xyz is not None:
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
            modified = True
        if scale_xyz is not None:
            gl_sx, gl_sy, gl_sz = cls.editor_to_gl_scale(*scale_xyz)
            transform.scale_x, transform.scale_y, transform.scale_z = gl_sx, gl_sy, gl_sz
            modified = True
        if modified:
            ComponentModifiedEvent.Pack(entity_id, transform, engine=st.app)

    @classmethod
    def GetEntityLocalTransformEditor(cls, entity_id: int) -> dict:
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': cls.gl_to_editor_position(t.local_pos_x, t.local_pos_y, t.local_pos_z),
            'rotation': (t.local_rot_x, t.local_rot_y, t.local_rot_z),
            'scale': cls.gl_to_editor_scale(t.local_scl_x, t.local_scl_y, t.local_scl_z),
        }

    @classmethod
    def SetEntityLocalTransformEditor(
        cls, entity_id: int,
        position_xyz: tuple = None, rotation_xyz: tuple = None, scale_xyz: tuple = None,
    ) -> None:
        st = cls._state()
        if entity_id is None:
            raise ValueError("Must specify entity ID")
        transform = esper.component_for_entity(entity_id, Transform)
        modified = False
        if position_xyz is not None:
            gl_x, gl_y, gl_z = cls.editor_to_gl_position(*position_xyz)
            transform.local_pos_x, transform.local_pos_y, transform.local_pos_z = gl_x, gl_y, gl_z
            transform.position_x, transform.position_y, transform.position_z = gl_x, gl_y, gl_z
            modified = True
        if rotation_xyz is not None:
            transform.local_rot_x, transform.local_rot_y, transform.local_rot_z = rotation_xyz
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
            modified = True
        if scale_xyz is not None:
            gl_sx, gl_sy, gl_sz = cls.editor_to_gl_scale(*scale_xyz)
            transform.local_scl_x, transform.local_scl_y, transform.local_scl_z = gl_sx, gl_sy, gl_sz
            transform.scale_x, transform.scale_y, transform.scale_z = gl_sx, gl_sy, gl_sz
            modified = True
        if modified:
            ComponentModifiedEvent.Pack(entity_id, transform, engine=st.app)

    # ============================================================
    # 跨 Engine 场景操作
    # ============================================================

    @classmethod
    def get_engine_name(cls) -> str:
        """返回当前活跃的 Engine 名称。"""
        return cls._active_name

    @classmethod
    def get_active_app(cls):
        """返回当前活跃 Engine 的 app 引用。"""
        return cls._state().app

    # ── 便捷访问器 (兼容旧代码直接引用 main_camera_id 等) ──

    @classmethod
    def get_main_camera_id(cls) -> int | None:
        return cls._state().main_camera_id

    @classmethod
    def get_main_camera_2d_id(cls) -> int | None:
        return cls._state().main_camera_2d_id

    @classmethod
    def get_scene_camera_id(cls) -> int | None:
        return cls._state().scene_camera_id

    @classmethod
    def get_scene_camera(cls) -> Camera | None:
        return cls._state().scene_camera
