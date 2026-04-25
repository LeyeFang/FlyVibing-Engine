import trimesh
import numpy as np

from Application.Resource.Mesh import Mesh

from os.path import join


DEFAULT_OBJ_FILE = [
    'Square.obj'
]


class ResourceManager:

    mesh_data: dict = {}

    @classmethod
    def Init(
        cls
    ) -> int:
        cls.__load_default_obj()
        cls.__load_default_shader()

    @classmethod
    def LoadAssets(
        assets_path: str
    ) -> int:
        return

    @classmethod
    def __load_default_obj(
        cls
    ) -> None:
        default_obj_dir = 'Resource/DefaultObjects'
        for file_name in DEFAULT_OBJ_FILE:
            obj_file_path = join(default_obj_dir, file_name)
            load_mesh = trimesh.load(obj_file_path)
            vertices = load_mesh.vertices
            normals = load_mesh.vertex_normals
            uvs = load_mesh.visual.uv
            faces = load_mesh.faces
            save_mesh = Mesh(vertices, normals, uvs, faces)
            current_mesh_id = len(cls.mesh_data)+1
            cls.mesh_data[f'{current_mesh_id}'] = save_mesh


    def __load_default_shader() -> None:
        pass
