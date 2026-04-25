import trimesh
import numpy as np

from Application.Resource.Mesh import Mesh

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

    loaded_models: dict[dict] = {}
    loaded_shaders: dict[dict] = {}
    model_count: int = 0
    shader_count: int = 0

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
        return cls.model_count

    @classmethod
    def GetModel(
        cls,
        asset_id: int
    ) -> dict:
        return cls.loaded_models[f'{asset_id}']

    @classmethod
    def GetDefaultModel(
        cls,
        model_name: list[str]
    ) -> dict:
        if model_name in DEFAULT_MODEL_NAME:
            for id, model in cls.loaded_models.items():
                if model['model_name'] == model_name:
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
        model_id: int
    ) -> Mesh:
        return cls.loaded_models[f"{model_id}"]['mesh_data']

    @classmethod
    def GetShader(
        cls,
        shader_id: int
    ) -> tuple[str]:
        vs: str = cls.loaded_shaders[f"{shader_id}"]['vertex_shader']
        fs: str = cls.loaded_shaders[f"{shader_id}"]['fragment_shader']
        return vs, fs

    # Functions that only used in this class
    # ==============================================================
    @classmethod
    def __load_default_model(
        cls
    ) -> None:
        default_model_dir = 'Resource/DefaultObjects'
        for model_name, file_name in zip(DEFAULT_MODEL_NAME, DEFAULT_MODEL_FILE):
            # Create Mesh
            model_file_path = join(default_model_dir, file_name)
            load_mesh = trimesh.load(model_file_path)
            vertices = load_mesh.vertices
            normals = load_mesh.vertex_normals
            uvs = load_mesh.visual.uv
            faces = load_mesh.faces
            save_mesh = Mesh(vertices, normals, uvs, faces)
            # Registe
            cls.model_count += 1
            current_model_id = cls.model_count
            cls.loaded_models[f'{current_model_id}'] = {}
            cls.loaded_models[f'{current_model_id}']['model_name'] = model_name
            cls.loaded_models[f'{current_model_id}']['file_name'] = file_name
            cls.loaded_models[f'{current_model_id}']['mesh_data'] = save_mesh

    @classmethod
    def __load_default_shader(
        cls
    ) -> None:
        default_shader_dir = 'Resource/DefaultShaders'
        for shader_name, file_name in zip(DEFAULT_SHADER_NAME, DEFAULT_SHADER_FILE):
            # Create Shader
            shader_file_path = join(default_shader_dir, file_name)
            vs, fs = parse_shader_file(shader_file_path)
            # Save
            cls.shader_count += 1
            current_shader_id = cls.shader_count
            cls.loaded_shaders[f'{current_shader_id}'] = {}
            cls.loaded_shaders[f'{current_shader_id}']['shader_name'] = shader_name
            cls.loaded_shaders[f'{current_shader_id}']['file_name'] = file_name
            cls.loaded_shaders[f'{current_shader_id}']['vertex_shader'] = vs
            cls.loaded_shaders[f'{current_shader_id}']['fragment_shader'] = fs


# Utile of this module
def parse_shader_file(
    filepath: str
) -> tuple[str]:
    """
    从 .shader 文件中读取内容，分离出顶点着色器和片段着色器的源代码。

    参数:
        filepath (str): .shader 文件的路径。

    返回:
        tuple: (vertex_src, fragment_src) 两个字符串，分别包含顶点和片段着色器的完整代码。
               如果缺少某一种类型，对应的值将为 None。

    异常:
        FileNotFoundError: 文件不存在。
        ValueError: 文件内容无法解析（例如没有找到任何有效着色器块，或无法确定类型）。
    """
    # 1. 读取文件内容
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"文件未找到: {filepath}")
    # 2. 按 #version 分割代码块（每个块是一个完整的着色器）
    #    正则含义：以 #version 开头，后面非贪婪匹配直到遇到下一个 #version 或文件结尾
    pattern = r'(#version\s+\d+\s+\w+.*?)(?=#version\s+\d+\s+\w+|\Z)'
    blocks = re.findall(pattern, content, re.DOTALL)
    if not blocks:
        raise ValueError("没有找到任何以 #version 开头的着色器代码块")
    vertex_src = None
    fragment_src = None
    # 3. 对每个块进行类型识别
    for block in blocks:
        block = block.strip()
        # 判断是否为片段着色器（常见特征：定义 out vec4 输出，或操作 FragColor）
        if re.search(r'\bout\s+vec4\s+\w+\s*;', block) or 'FragColor' in block:
            fragment_src = block
        # 判断是否为顶点着色器（必须设置 gl_Position）
        elif 'gl_Position' in block:
            vertex_src = block
        # 兜底规则：包含 layout(location=*) in vec3 的一般是顶点着色器
        elif re.search(r'layout\s*\(\s*location\s*=\s*\d+\s*\)\s+in\s+vec3', block):
            vertex_src = block
        # 如果上述都不匹配，可能是几何/曲面细分着色器，或格式错误
        else:
            # 这里可以选择跳过或抛出警告
            print(f"警告: 无法识别的着色器块，已忽略:\n{block[:100]}...")
    # 4. 可选：如果文件里只有一个块，并且两种特征都部分满足（罕见），可以再尝试精确匹配
    if vertex_src is None and fragment_src is None and len(blocks) == 1:
        raise ValueError("单个着色器块无法识别为顶点或片段着色器")
    return vertex_src, fragment_src
