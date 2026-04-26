import trimesh
import numpy as np

from Application.Resource._resource_utils import parse_shader_file
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material

from os.path import join
import re


DEFAULT_MODEL_NAME = [
    'Square'
]
DEFAULT_MODEL_FILE = [
    'Square.obj'
]
DEFAULT_SHADER_NAME = [
    'Basic'
]
DEFAULT_SHADER_FILE = [
    'Basic.shader'
]


class ResourceManager:

    loaded_mesh: dict[dict] = {}
    loaded_material: dict[dict] = {}
    mesh_count: int = 0
    material_count: int = 0

    @classmethod
    def Init(
        cls,
        app
    ) -> int:
        cls.app = app
        cls.__load_default_model()
        cls.__load_default_shader()


    # User Interface
    # ==============================================================
    @classmethod
    def LoadModel(
        cls,
        assets_path: str
    ) -> int:
        return cls.mesh_count

    @classmethod
    def GetModel(
        cls,
        asset_id: int
    ) -> dict:
        return cls.loaded_mesh[f'{asset_id}']

    @classmethod
    def GetDefaultModel(
        cls,
        model_name: list[str]
    ) -> dict:
        if model_name in DEFAULT_MODEL_NAME:
            for id, model in cls.loaded_mesh.items():
                if model['name'] == model_name:
                    return int(id)
        else:
            raise_info = f"""
                There is no model named '{model_name}',
                Available Models: {DEFAULT_MODEL_NAME}
            """
            raise raise_info

    @classmethod
    def GetMesh(
        cls,
        mesh_id: int
    ) -> Mesh:
        return cls.loaded_mesh[f"{mesh_id}"]['data']

    @classmethod
    def GetMaterial(
        cls,
        material_id: int
    ) -> Material:
        return cls.loaded_material[f"{material_id}"]['data']



    # Functions that only used in this class
    # ==============================================================
    @classmethod
    def __load_default_model(
        cls
    ) -> None:
        default_model_dir = 'Resource/DefaultObjects'
        for mesh_name, file_name in zip(DEFAULT_MODEL_NAME, DEFAULT_MODEL_FILE):
            # Create Mesh
            model_file_path = join(default_model_dir, file_name)
            load_mesh = trimesh.load(model_file_path)
            vertices = load_mesh.vertices
            normals = load_mesh.vertex_normals
            uvs = load_mesh.visual.uv
            faces = load_mesh.faces
            save_mesh = Mesh(vertices, normals, uvs, faces)
            # Registe
            cls.mesh_count += 1
            current_mesh_id = cls.mesh_count
            cls.loaded_mesh[f'{current_mesh_id}'] = {}
            cls.loaded_mesh[f'{current_mesh_id}']['name'] = mesh_name
            cls.loaded_mesh[f'{current_mesh_id}']['data'] = save_mesh

    @classmethod
    def __load_default_shader(
        cls
    ) -> None:
        default_shader_dir = 'Resource/DefaultShaders'
        for material_name, file_name in zip(DEFAULT_SHADER_NAME, DEFAULT_SHADER_FILE):
            # Create Shader
            shader_file_path = join(default_shader_dir, file_name)
            vs_src, fs_src, uniforms = parse_shader_file(shader_file_path)
            save_material = Material(vs_src, fs_src, uniforms)
            # Save
            cls.material_count += 1
            current_shader_id = cls.material_count
            cls.loaded_material[f'{current_shader_id}'] = {}
            cls.loaded_material[f'{current_shader_id}']['data'] = save_material
            cls.loaded_material[f'{current_shader_id}']['name'] = material_name
