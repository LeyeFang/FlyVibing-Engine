import esper

import numpy as np

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand


class SceneManager:

    app = None
    scene: dict = {}
    entities: dict = {}
    scene_camera: Camera = None
    scene_camera_id: int = None
    main_camera_id: int = None

    # ============================================================
    # 生命周期 / Lifecycle
    # ============================================================
    @classmethod
    def Init(
        cls,
        app
    ) -> None:
        cls.app = app
        cls.scene["default"] = "default"
        cls.main_camera_id = esper.create_entity(Transform(), Camera(True))
        cls.scene_camera_id = cls.main_camera_id
        cls.scene_camera = esper.component_for_entity(cls.scene_camera_id, Camera)

    @classmethod
    def CreateScene(
        cls,
        new_scene_name: str
    ) -> None:
        cls.scene[new_scene_name] = new_scene_name

    # ============================================================
    # 实体管理 / Entity Management
    # ============================================================
    @classmethod
    def AddEntity(
        cls
    ) -> int:
        entity_id = esper.create_entity(Transform())
        cls.entities[f'{entity_id}'] = 1
        return entity_id

    @classmethod
    def AddComponentToEntity(
        cls,
        entity_id: int,
        component_instance: Component
    ) -> None:
        esper.add_component(entity_id, component_instance)
        NewComponentEvent.Pack(entity_id, component_instance, engine=cls.app)
        # ── 自动向渲染器注册/注销实体 GPU 资源 ──
        if isinstance(component_instance, MeshRenderer):
            _renderer = getattr(cls.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))

    # ============================================================
    # 查询接口 / Query Interface
    # ============================================================
    # --- 相机 / Camera ---
    @classmethod
    def GetSceneCamera(
        cls
    ) -> tuple[Camera, Transform]:
        """返回场景主摄像机的 Camera 组件和 Transform。

        编辑器模式下可能不使用此相机（改用 EditorCamera），
        运行/游戏模式下使用此相机渲染。
        """
        camera = esper.component_for_entity(cls.scene_camera_id, Camera)
        transform = esper.component_for_entity(cls.scene_camera_id, Transform)
        return camera, transform

    # --- 渲染 / Rendering ---
    @classmethod
    def GetRenderableEntities(
        cls
    ) -> list:
        entity_id_list = []
        for entity_id, rend in esper.get_component(MeshRenderer):
            if rend.visible:
                entity_id_list.append(entity_id)
        return entity_id_list

    # --- 组件查询 / Component Queries ---
    @classmethod
    def GetEntityTransform(
        cls,
        entity_id
    ) -> Transform:
        transform = esper.component_for_entity(entity_id, Transform)
        return transform

    @classmethod
    def GetEntityModelMatrix(
        cls,
        entity_id: int,
    ) -> 'np.ndarray':
        """Get the TRS model matrix for an entity (convenience wrapper).

        Extracts position/rotation/scale from the entity's Transform component
        and delegates to Core.Math.Transform.calculate_entity_model().

        Returns:
            numpy ndarray: 4×4 float32 model matrix (pyrr-style, row-vector).
            Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
        """
        from Application.Core.Math.Transform import calculate_entity_model
        t = cls.GetEntityTransform(entity_id)
        return calculate_entity_model(
            position=(t.position_x, t.position_y, t.position_z),
            rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
            scale=(t.scale_x, t.scale_y, t.scale_z),
        )

    @classmethod
    def GetEntityMesh(
        cls,
        entity_id: int
    ) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        mesh_id = mesh_rend.mesh_id
        return mesh_id

    @classmethod
    def GetEntityMaterial(
        cls,
        entity_id: int
    ) -> int:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material_id = mesh_rend.material_id
        return material_id

    @classmethod
    def GetEntityTexture(
        cls,
        entity_id: int,
        slot: int = 0
    ) -> int:
        """获取 entity 当前使用的纹理 ID"""
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mesh_rend.material_id)
        if slot < len(material.texture_id_list):
            return material.texture_id_list[slot]
        return 0

    # ============================================================
    # 修改接口 / Modification Interface
    # ============================================================
    # --- 变换 / Transform ---
    @classmethod
    def SetEntityTransform(
        cls,
        entity_id: int = None,
        position_xyz: tuple = None,
        rotation_xyz: tuple = None,
        scale_xyz: tuple = None
    ) -> None:
        if entity_id is None:
            raise ("Must specific entity ID")
        if position_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.position_x, transform.position_y, transform.position_z = position_xyz
        if rotation_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
        if scale_xyz is not None:
            transform = esper.component_for_entity(entity_id, Transform)
            transform.scale_x, transform.scale_y, transform.scale_z = scale_xyz
        ComponentModifiedEvent.Pack(entity_id, transform, engine=cls.app)

    @classmethod
    def SetMainCameraTransform(
        cls,
        position_x: float = None,
        position_y: float = None,
        position_z: float = None,
        rotation_x: float = None,
        rotation_y: float = None,
        rotation_z: float = None
    ) -> None:
        transform = esper.component_for_entity(cls.main_camera_id, Transform)
        if position_x is not None:
            transform.position_x = position_x
        if position_y is not None:
            transform.position_y = position_y
        if position_z is not None:
            transform.position_z = position_z
        if rotation_x is not None:
            transform.rotation_x = rotation_x
        if rotation_y is not None:
            transform.rotation_y = rotation_y
        if rotation_z is not None:
            transform.rotation_z = rotation_z

    # --- 网格渲染器 / Mesh Renderer ---
    @classmethod
    def SetEntityMeshRenderer(
        cls,
        entity_id: int,
        visible: bool = None,
        mesh_id: int = None,
        material_id: int = None
    ) -> None:
        if entity_id is None:
            raise ("Must specific entity ID")

        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        if visible is not None:
            mesh_rend.visible = visible
        if mesh_id is not None:
            mesh_rend.mesh_id = mesh_id
        if material_id is not None:
            mesh_rend.material_id = material_id
        # ── 可见性切换 → 自动向渲染器注册/注销 ──
        if visible is not None:
            _renderer = getattr(cls.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=visible))
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls.app)

    # --- 材质 / Material & Shader ---
    @classmethod
    def NewEntityMaterial(
        cls,
        entity_id: int,
        shader_id: int = None
    ) -> int:
        """为 entity 创建一个全新的独立 material，返回 material_id

        调用时机：当你希望某个 entity 拥有不和别人共享的材质时。
        之后可以 SetEntityTexture / SetMaterialParams 进一步定制。
        """
        if shader_id is not None:
            # 创建指定 shader 的 material
            new_material_id = ResourceManager.NewMaterial()
            material = ResourceManager.GetMaterial(new_material_id)
            uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
            material.set_new_shader(shader_id, uniforms_name_type)
        else:
            new_material_id = ResourceManager.NewMaterial()

        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        mesh_rend.material_id = new_material_id
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls.app)
        return new_material_id

    @classmethod
    def SetEntityMaterial(
        cls,
        entity_id: int,
        material_id: int
    ) -> None:
        """直接将 entity 的 material 切换为已有的 material_id

        适用场景：多个 entity 共享同一个材质（节省 GPU 资源）。
        """
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        mesh_rend.material_id = material_id
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls.app)

    @classmethod
    def SetEntityTexture(
        cls,
        entity_id: int,
        texture_id: int,
        slot: int = 0
    ) -> None:
        """为 entity 的 material 设置纹理

        Args:
            entity_id:  目标实体
            texture_id: 纹理资源 ID（通过 ResourceManager.GetDefaultTexture 或 LoadAssets 获得）
            slot:       纹理槽位，0=diffuse/albedo, 1=normal, 2=specular, ...
                        当前只用了 slot 0，预留多纹理支持
        """
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        material = ResourceManager.GetMaterial(mesh_rend.material_id)
        # 确保 texture_id_list 够长
        while len(material.texture_id_list) <= slot:
            material.texture_id_list.append(0)
        material.texture_id_list[slot] = texture_id
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls.app)

    @classmethod
    def SetEntityShader(
        cls,
        entity_id: int,
        shader_id: int
    ) -> None:
        mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
        entity_material = ResourceManager.GetMaterial(mesh_rend.material_id)
        uniforms_name_type = ResourceManager.GetShader(shader_id).uniforms_name_type
        entity_material.set_new_shader(shader_id, uniforms_name_type)
        ComponentModifiedEvent.Pack(entity_id, mesh_rend, engine=cls.app)

    @classmethod
    def SetMaterialParams(
        cls,
        entity_id: int,
        params: dict
    ):
        """批量设置 entity 材质的着色器参数（uniform）

        Args:
            entity_id:  目标实体
            params:     参数名 → 值的字典，如 {"freq": 60, "time": 0.5}
        """
        if entity_id is None:
            raise ("Must specific entity ID")

        try:
            mesh_rend = esper.component_for_entity(entity_id, MeshRenderer)
            material_id = mesh_rend.material_id
            uniforms_should_be: dict = ResourceManager.GetMaterial(material_id).uniforms_data
            material = ResourceManager.GetMaterial(material_id)
            for u_name, u_value in params.items():
                if u_name in uniforms_should_be.keys():
                    material.uniforms_data[u_name] = u_value
                else:
                    raise BaseException("Input params and material actual params not match !!")
        except KeyError:
            raise BaseException(f"Entity '{entity_id}' do not have mesh renderer")

    # ============================================================
    # 坐标系转换 / Coordinate Conversion
    # ============================================================
    # GL 标准坐标系 → 编辑器坐标系:
    #   编辑器 X = GL X
    #   编辑器 Y = -GL Z  (GL 的 Z 负半轴 → 编辑器 Y 正半轴)
    #   编辑器 Z = GL Y   (GL 的 Y 正半轴 → 编辑器 Z 正半轴)
    #
    # Transform 内部始终以 GL 坐标存储，编辑器通过以下方法读写。

    @staticmethod
    def gl_to_editor_position(
        gl_x: float, gl_y: float, gl_z: float
    ) -> tuple[float, float, float]:
        """GL 坐标 → 编辑器坐标"""
        return (gl_x, -gl_z, gl_y)

    @staticmethod
    def editor_to_gl_position(
        editor_x: float, editor_y: float, editor_z: float
    ) -> tuple[float, float, float]:
        """编辑器坐标 → GL 坐标"""
        return (editor_x, editor_z, -editor_y)

    # --- 编辑器坐标读写接口 ---

    @classmethod
    def GetEntityTransformEditor(
        cls,
        entity_id: int
    ) -> dict:
        """获取实体 Transform，位置以**编辑器坐标系**返回。

        Returns:
            dict 包含键:
              - 'position': (editor_x, editor_y, editor_z)
              - 'rotation': (rotation_x, rotation_y, rotation_z)  # 欧拉角, 沿用 GL 约定
              - 'scale':    (scale_x, scale_y, scale_z)
        """
        t = esper.component_for_entity(entity_id, Transform)
        return {
            'position': cls.gl_to_editor_position(
                t.position_x, t.position_y, t.position_z
            ),
            'rotation': (t.rotation_x, t.rotation_y, t.rotation_z),
            'scale': (t.scale_x, t.scale_y, t.scale_z),
        }

    @classmethod
    def SetEntityTransformEditor(
        cls,
        entity_id: int = None,
        position_xyz: tuple = None,
        rotation_xyz: tuple = None,
        scale_xyz: tuple = None
    ) -> None:
        """设置实体 Transform，位置以**编辑器坐标系**传入。

        内部自动转换为 GL 坐标后存储。
        """
        if entity_id is None:
            raise ValueError("Must specify entity ID")

        transform = esper.component_for_entity(entity_id, Transform)
        modified = False

        if position_xyz is not None:
            gl_x, gl_y, gl_z = cls.editor_to_gl_position(*position_xyz)
            transform.position_x = gl_x
            transform.position_y = gl_y
            transform.position_z = gl_z
            modified = True
        if rotation_xyz is not None:
            transform.rotation_x, transform.rotation_y, transform.rotation_z = rotation_xyz
            modified = True
        if scale_xyz is not None:
            transform.scale_x, transform.scale_y, transform.scale_z = scale_xyz
            modified = True

        if modified:
            ComponentModifiedEvent.Pack(entity_id, transform, engine=cls.app)