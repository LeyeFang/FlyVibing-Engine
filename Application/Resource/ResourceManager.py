import os
from os.path import join
from dataclasses import dataclass, field

import trimesh
import numpy as np
from PIL import Image

from Application.Resource._resource_utils import parse_shader_files, parse_shader_file
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import *


# ── 支持的资源格式 ─────────────────────────────────────────────
MESH_EXTENSIONS = {'.obj', '.gltf', '.glb', '.stl', '.ply', '.off', '.fbx', '.dae', '.3ds'}
TEXTURE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.tiff', '.tif', '.hdr', '.exr'}

DEFAULT_MODEL_NAME = [
    'Square',
    'Cube'
]
DEFAULT_MODEL_FILE = [
    '2D/Square.obj',
    '3D/Cube.obj'
]
DEFAULT_SHADER_NAME = [
    'Basic',
    'SSVEP'
]
DEFAULT_SHADER_FILE = [
    ('Basic.vert', 'Basic.frag'),
    ('SSVEP.vert', 'SSVEP.frag'),
]
DEFAULT_TEXTURE_NAME = [
    'Default',
    'Checkerboard',
]

# ── 预设调色板 ─────────────────────────────────────────────
COLOR_PRESETS = {
    'White':   (1.0, 1.0, 1.0, 1.0),
    'Red':     (1.0, 0.0, 0.0, 1.0),
    'Green':   (0.0, 1.0, 0.0, 1.0),
    'Blue':    (0.0, 0.0, 1.0, 1.0),
    'Yellow':  (1.0, 1.0, 0.0, 1.0),
    'Cyan':    (0.0, 1.0, 1.0, 1.0),
    'Magenta': (1.0, 0.0, 1.0, 1.0),
    'Black':   (0.0, 0.0, 0.0, 1.0),
    'Gray':    (0.5, 0.5, 0.5, 1.0),
    'Orange':  (1.0, 0.5, 0.0, 1.0),
}


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
        cls.__load_default_material()


    # ==============================================================
    # 资源导入 / Asset Import
    # ==============================================================
    @classmethod
    def LoadAssets(
        cls,
        assets_path: str,
        resource_name: str = None
    ) -> int:
        """统一资源导入入口 — 根据后缀自动分发到对应的加载器。

        Args:
            assets_path  : 资源文件路径
            resource_name: 自定义资源名称 (默认取文件名 stem)

        Returns:
            int: 资源 ID (mesh_id / shader_id / texture_id)

        Raises:
            FileNotFoundError: 文件不存在
            ValueError       : 不支持的文件格式
        """
        if not os.path.exists(assets_path):
            raise FileNotFoundError(f"资源文件不存在: {assets_path}")

        base = os.path.basename(assets_path)
        stem, suffix = os.path.splitext(base)
        suffix_lower = suffix.lower()
        name = resource_name or stem

        # ── 着色器 / Shader ──
        if suffix_lower == '.vert':
            return cls.__load_shader_from_vert(assets_path, name)
        if suffix_lower == '.shader':
            return cls.__load_shader_from_single_file(assets_path, name)

        # ── 网格 / Mesh ──
        if suffix_lower in MESH_EXTENSIONS:
            return cls.__load_mesh_from_file(assets_path, name)

        # ── 纹理 / Texture ──
        if suffix_lower in TEXTURE_EXTENSIONS:
            return cls.__load_texture_from_file(assets_path, name)

        raise ValueError(
            f"不支持的资源格式 '{suffix}'，"
            f"支持的网格格式: {MESH_EXTENSIONS}，"
            f"支持的纹理格式: {TEXTURE_EXTENSIONS}"
        )

    @classmethod
    def ImportMesh(
        cls,
        file_path: str,
        mesh_name: str = None
    ) -> int:
        """便捷方法: 导入网格文件。等同于 LoadAssets(file_path, mesh_name)。"""
        return cls.LoadAssets(file_path, mesh_name)

    @classmethod
    def ImportTexture(
        cls,
        file_path: str,
        texture_name: str = None
    ) -> int:
        """便捷方法: 导入纹理文件。等同于 LoadAssets(file_path, texture_name)。"""
        return cls.LoadAssets(file_path, texture_name)

    # ==============================================================
    # 着色器加载 (内部)
    # ==============================================================
    @classmethod
    def __load_shader_from_vert(
        cls,
        vert_path: str,
        name: str
    ) -> int:
        """从 .vert 文件加载着色器 (自动查找配套 .frag + .spv)"""
        frag_path = vert_path.replace('.vert', '.frag')
        spv_v = vert_path + '.spv'
        spv_f = frag_path + '.spv'
        vs_src, fs_src, vs_spv, fs_spv, uniforms = parse_shader_files(
            vert_path, frag_path, spv_v, spv_f
        )
        cls.shader_count += 1
        cls.loaded_shader[f'{cls.shader_count}'] = {
            'name': name,
            'data': Shader(vs_src=vs_src, fs_src=fs_src,
                           vs_spv=vs_spv, fs_spv=fs_spv,
                           uniforms_name_type=uniforms),
            'path': vert_path,
        }
        return cls.shader_count

    @classmethod
    def __load_shader_from_single_file(
        cls,
        file_path: str,
        name: str
    ) -> int:
        """从 .shader 单文件加载着色器 (旧版兼容)"""
        vs_src, fs_src, uniforms = parse_shader_file(file_path)
        cls.shader_count += 1
        cls.loaded_shader[f'{cls.shader_count}'] = {
            'name': name,
            'data': Shader(vs_src=vs_src, fs_src=fs_src, uniforms_name_type=uniforms),
            'path': file_path,
        }
        return cls.shader_count

    # ==============================================================
    # 网格加载 (内部)
    # ==============================================================
    @classmethod
    def __load_mesh_from_file(
        cls,
        file_path: str,
        name: str
    ) -> int:
        """使用 trimesh 加载网格文件 (OBJ / glTF / STL / PLY / FBX 等)。

        自动处理:
          - 单网格文件 (Trimesh): 直接提取顶点数据
          - 场景文件 (Scene, 如 glTF): 合并所有子网格为一个 Mesh
          - 缺失 UV / 法线: 自动补零
        """
        try:
            loaded = trimesh.load(file_path, force='mesh')
        except Exception as e:
            raise RuntimeError(f"trimesh 无法加载 '{file_path}': {e}")

        # ── 场景类型 (glTF / GLB / FBX): 合并所有几何体 ──
        if isinstance(loaded, trimesh.Scene):
            all_vertices = []
            all_normals = []
            all_uvs = []
            all_faces = []
            vertex_offset = 0

            for geo_name, geom in loaded.geometry.items():
                if not isinstance(geom, trimesh.Trimesh):
                    continue

                v = np.array(geom.vertices, dtype=np.float32)
                all_vertices.append(v)

                # 法线: 若缺失则计算
                n = geom.vertex_normals
                if n is not None:
                    all_normals.append(np.array(n, dtype=np.float32))
                else:
                    all_normals.append(np.zeros_like(v, dtype=np.float32))

                # UV: 若缺失则补零
                uv = getattr(geom.visual, 'uv', None)
                if uv is not None:
                    all_uvs.append(np.array(uv, dtype=np.float32))
                else:
                    all_uvs.append(np.zeros((len(v), 2), dtype=np.float32))

                # 索引
                f = geom.faces
                if f is not None and len(f) > 0:
                    all_faces.append(np.array(f, dtype=np.uint32) + vertex_offset)
                vertex_offset += len(v)

            if not all_vertices:
                raise RuntimeError(f"文件中没有可提取的几何体: {file_path}")

            vertices = np.vstack(all_vertices)
            normals = np.vstack(all_normals)
            uvs = np.vstack(all_uvs)
            indices = np.vstack(all_faces) if all_faces else np.array([], dtype=np.uint32)

        # ── 单网格类型 (OBJ / STL / PLY) ──
        else:
            vertices = np.array(loaded.vertices, dtype=np.float32)
            n = loaded.vertex_normals
            normals = np.array(n, dtype=np.float32) if n is not None else np.zeros_like(vertices, dtype=np.float32)
            uv = getattr(loaded.visual, 'uv', None)
            uvs = np.array(uv, dtype=np.float32) if uv is not None else np.zeros((len(vertices), 2), dtype=np.float32)
            f = loaded.faces
            indices = np.array(f, dtype=np.uint32) if f is not None else np.array([], dtype=np.uint32)

        # ── 注册 ──
        mesh = Mesh(vertices, normals, uvs, indices)
        cls.mesh_count += 1
        current_id = cls.mesh_count
        cls.loaded_mesh[f'{current_id}'] = {
            'name': name,
            'data': mesh,
            'path': file_path,
        }
        return current_id

    # ==============================================================
    # 纹理加载 (内部)
    # ==============================================================
    @classmethod
    def __load_texture_from_file(
        cls,
        file_path: str,
        name: str
    ) -> int:
        """使用 PIL 加载纹理文件 (PNG / JPG / BMP / TGA / HDR 等)。

        Returns:
            int: texture_id
        """
        try:
            img = Image.open(file_path)
            # 统一转为 RGBA 或 RGB
            if img.mode == 'RGBA':
                channels = 4
            elif img.mode == 'RGB':
                channels = 3
            elif img.mode == 'L':
                channels = 1
            else:
                img = img.convert('RGBA')
                channels = 4

            image_data = np.array(img, dtype=np.uint8)
            width, height = img.size

            texture = Texture(
                image_data=image_data,
                width=width,
                height=height,
                channels=channels,
                file_path=file_path,
            )
        except Exception as e:
            raise RuntimeError(f"无法加载纹理 '{file_path}': {e}")

        cls.texture_count += 1
        current_id = cls.texture_count
        cls.loaded_texture[f'{current_id}'] = {
            'name': name,
            'data': texture,
            'path': file_path,
        }
        return current_id

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
    def GetDefaultTexture(
        cls,
        texture_name: str
    ) -> int:
        if texture_name in DEFAULT_TEXTURE_NAME:
            for id_str, tex in cls.loaded_texture.items():
                if tex['name'] == texture_name:
                    return int(id_str)
        raise KeyError(
            f"没有名为 '{texture_name}' 的默认纹理，"
            f"可用: {DEFAULT_TEXTURE_NAME}"
        )

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
        material = Material(1, uniforms_name_type)
        # ★ 新建 material 自动绑定默认白色纹理，保证渲染始终有纹理可用
        material.texture_id_list = [cls.GetDefaultTexture('Default')]
        cls.loaded_material[f"{current_material_id}"] = material
        return current_material_id

    @classmethod
    def SetMaterialColor(
        cls,
        material_id: int,
        r: float, g: float, b: float, a: float = 1.0
    ) -> None:
        """设置材质的 uColor uniform（要求 shader 支持 vec4 uColor）。
        常用于颜色调色盘实时改色。
        """
        mat = cls.GetMaterial(material_id)
        mat.uniforms_data['uColor'] = np.array([r, g, b, a], dtype=np.float32)

    @classmethod
    def GetMaterialColor(
        cls,
        material_id: int
    ) -> tuple[float, float, float, float] | None:
        """获取材质的 uColor uniform 值。无 uColor 时返回 None。"""
        mat = cls.GetMaterial(material_id)
        c = mat.uniforms_data.get('uColor')
        if c is not None and hasattr(c, '__len__') and len(c) == 4:
            return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
        return None

    @classmethod
    def GetShaderName(
        cls,
        shader_id: int
    ) -> str:
        """获取 shader 的名称（如 'Basic', 'SSVEP'）。"""
        entry = cls.loaded_shader.get(str(shader_id))
        return entry['name'] if entry else 'Unknown'

    @classmethod
    def AddMaterialTexture(
        cls,
        material_id: int,
        texture_id: int
    ) -> None:
        """给材质追加一个纹理引用。"""
        mat = cls.GetMaterial(material_id)
        if texture_id not in mat.texture_id_list:
            mat.texture_id_list.append(texture_id)

    @classmethod
    def RemoveMaterialTexture(
        cls,
        material_id: int,
        slot_index: int
    ) -> None:
        """从材质中移除指定槽位的纹理。"""
        mat = cls.GetMaterial(material_id)
        if 0 <= slot_index < len(mat.texture_id_list):
            mat.texture_id_list.pop(slot_index)

    # ==============================================================
    # 资源删除 / Asset Deletion
    # ==============================================================

    @classmethod
    def DeleteMesh(cls, mesh_id: int) -> bool:
        """删除指定网格资源。返回是否成功。"""
        key = str(mesh_id)
        if key not in cls.loaded_mesh:
            return False
        del cls.loaded_mesh[key]
        return True

    @classmethod
    def DeleteShader(cls, shader_id: int) -> bool:
        """删除指定着色器资源。若被 Material 引用则拒绝删除。"""
        key = str(shader_id)
        if key not in cls.loaded_shader:
            return False
        # 检查是否被任何 Material 引用
        for mat_key, mat in cls.loaded_material.items():
            if getattr(mat, 'shader_id', None) == shader_id:
                raise RuntimeError(
                    f"Cannot delete Shader #{shader_id}: "
                    f"still referenced by Material #{mat_key}"
                )
        del cls.loaded_shader[key]
        return True

    @classmethod
    def DeleteTexture(cls, texture_id: int) -> bool:
        """删除指定纹理资源。若被 Material 引用则拒绝删除。"""
        key = str(texture_id)
        if key not in cls.loaded_texture:
            return False
        # 检查是否被任何 Material 引用
        for mat_key, mat in cls.loaded_material.items():
            tex_list = getattr(mat, 'texture_id_list', [])
            if texture_id in tex_list:
                raise RuntimeError(
                    f"Cannot delete Texture #{texture_id}: "
                    f"still referenced by Material #{mat_key}"
                )
        del cls.loaded_texture[key]
        return True

    @classmethod
    def DeleteMaterial(cls, material_id: int) -> bool:
        """删除指定材质资源。返回是否成功。"""
        key = str(material_id)
        if key not in cls.loaded_material:
            return False
        del cls.loaded_material[key]
        return True


    # Functions that only used in this class
    # ==============================================================
    @classmethod
    def __load_default_mesh(
        cls
    ) -> None:
        default_model_dir = 'Resource/Meshes/Builtin'
        for mesh_name, file_name in zip(DEFAULT_MODEL_NAME, DEFAULT_MODEL_FILE):
            model_file_path = join(default_model_dir, file_name)
            cls.__load_mesh_from_file(model_file_path, mesh_name)

    @classmethod
    def __load_default_shader(
        cls
    ) -> None:
        default_shader_dir = 'Resource/Shaders/Builtin'
        for shader_name, (vert_file, frag_file) in zip(DEFAULT_SHADER_NAME, DEFAULT_SHADER_FILE):
            vert_path = join(default_shader_dir, vert_file)
            frag_path = join(default_shader_dir, frag_file)
            vert_spv_path = join(default_shader_dir, vert_file + '.spv')
            frag_spv_path = join(default_shader_dir, frag_file + '.spv')

            vs_src, fs_src, vs_spv, fs_spv, uniforms_info = parse_shader_files(
                vert_path, frag_path, vert_spv_path, frag_spv_path
            )
            save_shader = Shader(
                vs_src=vs_src, fs_src=fs_src,
                vs_spv=vs_spv, fs_spv=fs_spv,
                uniforms_name_type=uniforms_info
            )
            cls.shader_count += 1
            current_shader_id = cls.shader_count
            cls.loaded_shader[f'{current_shader_id}'] = {}
            cls.loaded_shader[f'{current_shader_id}']['data'] = save_shader
            cls.loaded_shader[f'{current_shader_id}']['name'] = shader_name
            cls.loaded_shader[f'{current_shader_id}']['path'] = vert_path

    @classmethod
    def __load_default_texture(
        cls
    ) -> None:
        """加载默认纹理（程序化生成，无需外部文件）"""
        # --- 白色占位纹理 ---
        cls.texture_count += 1
        cls.loaded_texture[f'{cls.texture_count}'] = {
            'name': 'Default',
            'data': Texture.CreateWhiteTexture(),
        }
        # --- 棋盘格调试纹理 ---
        cls.texture_count += 1
        cls.loaded_texture[f'{cls.texture_count}'] = {
            'name': 'Checkerboard',
            'data': Texture.CreateCheckerboard(),
        }

    @classmethod
    def __load_default_material(cls) -> None:
        """创建默认材质（Basic shader + Default 纹理），所有新建实体共享。"""
        cls.material_count += 1
        current_id = cls.material_count
        shader: Shader = cls.loaded_shader[f'{1}']['data']
        material = Material(1, shader.uniforms_name_type)
        material.name = "Default"
        material.texture_id_list = [cls.GetDefaultTexture('Default')]
        material._is_saved = True
        cls.loaded_material[f"{current_id}"] = material

    @classmethod
    def GetDefaultMaterial(cls) -> int:
        """返回默认材质 ID（所有新建 MeshRenderer 共享）。"""
        for mid, mat in cls.loaded_material.items():
            if getattr(mat, 'name', '') == "Default":
                return int(mid)
        return cls.NewMaterial()  # fallback
