import os
from os.path import join
from dataclasses import dataclass, field

import trimesh
import numpy as np

from Application.Resource._resource_utils import parse_shader_file
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import *


DEFAULT_MODEL_NAME = [
    'Square',
    'Cube'
]
DEFAULT_MODEL_FILE = [
    'Square.obj',
    'Cube.obj'
]
DEFAULT_SHADER_NAME = [
    'Basic',
    'SSVEP'
]
DEFAULT_SHADER_FILE = [
    'Basic.shader',
    'SSVEP.shader'
]


class ResourceManager:

    loaded_mesh: dict[dict] = {}
    loaded_shader: dict[dict] = {}
    loaded_texture: dict[dict] = {}
    loaded_material: dict[dict] = {}
    mesh_count: int = 0
    shader_count: int = 0
    texture_count: int = 0
    material_count: int = 0

    @classmethod
    def Init(
        cls,
        app
    ) -> int:
        cls.app = app
        cls.__load_default_mesh()
        cls.__load_default_shader()
        cls.__load_default_texture()


    # User Interface
    # ==============================================================
    @classmethod
    def LoadAssets(
        cls,
        assets_path: str
    ) -> int:
        base = os.path.basename(assets_path)
        stem, suffix = os.path.splitext(base)  # 分割
        if suffix == '.shader':
            vs_src, fs_src, uniforms_name_type = parse_shader_file(assets_path)
            cls.shader_count += 1
            _id = cls.shader_count
            cls.loaded_shader[f'{_id}'] = {}
            cls.loaded_shader[f'{_id}']['name'] = stem
            cls.loaded_shader[f'{_id}']['data'] = Shader(vs_src, fs_src, uniforms_name_type)
            return _id
        if suffix == '.obj':
            pass

    @classmethod
    def GetDefaultMesh(
        cls,
        mesh_name: list[str]
    ) -> dict:
        if mesh_name in DEFAULT_MODEL_NAME:
            for id, model in cls.loaded_mesh.items():
                if model['name'] == mesh_name:
                    return int(id)
        else:
            raise_info = f"""
                There is no model named '{mesh_name}',
                Available Models: {DEFAULT_MODEL_NAME}
            """
            raise raise_info

    @classmethod
    def GetDefaultShader(
        cls,
        shader_name: list[str]
    ) -> dict:
        if shader_name in DEFAULT_SHADER_NAME:
            for id, shader in cls.loaded_shader.items():
                if shader['name'] == shader_name:
                    return int(id)
        else:
            raise_info = f"""
                There is no shader named '{shader_name}',
                Available Shaders: {DEFAULT_SHADER_NAME}
            """
            raise BaseException(raise_info)

    @classmethod
    def GetMesh(
        cls,
        mesh_id: int
    ) -> Mesh:
        return cls.loaded_mesh[f"{mesh_id}"]['data']

    @classmethod
    def GetShader(
        cls,
        shader_id: int
    ) -> Shader:
        return cls.loaded_shader[f"{shader_id}"]['data']

    @classmethod
    def GetTexture(
        cls,
        texture_id: int
    ) -> Texture:
        return cls.loaded_texture[f"{texture_id}"]['data']

    @classmethod
    def GetMaterial(
        cls,
        material_id: int
    ) -> Material:
        return cls.loaded_material[f"{material_id}"]

    @classmethod
    def NewMaterial(
        cls
    ) -> int:
        cls.material_count += 1
        current_material_id = cls.material_count
        shader: Shader = cls.loaded_shader[f'{1}']['data']
        uniforms_name_type = shader.uniforms_name_type
        cls.loaded_material[f"{current_material_id}"] = Material(1, uniforms_name_type)
        return current_material_id


    # Functions that only used in this class
    # ==============================================================
    @classmethod
    def __load_default_mesh(
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
        for shader_name, file_name in zip(DEFAULT_SHADER_NAME, DEFAULT_SHADER_FILE):
            # Create Shader
            shader_file_path = join(default_shader_dir, file_name)
            vs_src, fs_src, uniforms_info = parse_shader_file(shader_file_path)
            save_shader = Shader(vs_src, fs_src, uniforms_info)
            # Save
            cls.shader_count += 1
            current_shader_id = cls.shader_count
            cls.loaded_shader[f'{current_shader_id}'] = {}
            cls.loaded_shader[f'{current_shader_id}']['data'] = save_shader
            cls.loaded_shader[f'{current_shader_id}']['name'] = shader_name

    @classmethod
    def __load_default_texture(
        cls
    ) -> None:
        pass
