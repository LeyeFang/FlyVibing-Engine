from Application.Layers.Layer import Layer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import MeshRenderer
from Application.Timer.Timer import GetRunTime


class DebugLayer(Layer):
    @classmethod
    def OnAttach(
        cls
    ):
        square_mesh_id = ResourceManager.GetDefaultMesh("Square")
        cube_mesh_id = ResourceManager.GetDefaultMesh("Cube")
        ssvep_shader_id = ResourceManager.LoadAssets("Resource/DefaultShaders/SSVEP.shader")
        print(ssvep_shader_id)
        # Entity 1
        cls.entity_id_1 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_1,
            component_instance=MeshRenderer(mesh_id=cube_mesh_id))
        SceneManager.SetEntityTransfrom(
            cls.entity_id_1,
            position_xyz=(-10, 0, -50),
            scale_xyz=(8, 8, 8))
        # Entity 2
        cls.entity_id_2 = SceneManager.AddEntity()
        SceneManager.AddComponentToEntity(
            entity_id=cls.entity_id_2,
            component_instance=MeshRenderer(mesh_id=square_mesh_id))
        SceneManager.SetEntityTransfrom(
            cls.entity_id_2,
            position_xyz=(10, 0, -50),
            scale_xyz=(5, 5, 5))
        SceneManager.SetEntityShader(
            cls.entity_id_2,
            ssvep_shader_id
        )
        SceneManager.SetEntityShaderUniforms(
            cls.entity_id_2,
            {"freq": 40}
        )
        # Camera
        SceneManager.SetMainCameraTransfrom(
            position_xyz=(-3, 0, 0))

    @classmethod
    def OnEvent(
        cls,
        event
    ):
        print(f"Time: {GetRunTime():.4f}, Event: {event}")
        pass

    @classmethod
    def OnUpdate(
        cls
    ):
        
        run_time = GetRunTime()
        SceneManager.SetEntityShaderUniforms(
            cls.entity_id_2,
            {'time': run_time})
