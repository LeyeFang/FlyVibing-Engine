import numpy as np
import json
import os

from dataclasses import dataclass, field


@dataclass
class Material:

    shader_id: int = 1
    texture_id_list: list = field(default_factory=list)
    uniforms_data: dict[str, np.ndarray] = field(default_factory=dict)
    name: str = ""
    _is_saved: bool = False        # 是否已保存到磁盘
    _file_path: str = ""           # 关联的 .mat 文件路径

    def __init__(
        self,
        shader_id: int,
        uniforms_name_type: dict
    ) -> None:
        self.texture_id_list = []
        self.uniforms_data = {}
        self.shader_id = shader_id
        self.name = "*Untitled"
        self._is_saved = False
        self._file_path = ""
        for u_name, u_type in uniforms_name_type.items():
            if u_type == 'mat4':
                self.uniforms_data[u_name] = np.zeros((4, 4), dtype=np.float32)
            elif u_type == 'vec4':
                self.uniforms_data[u_name] = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
            elif u_type == 'vec3':
                self.uniforms_data[u_name] = np.array([1.0, 1.0, 1.0], dtype=np.float32)
            elif u_type == 'float':
                self.uniforms_data[u_name] = np.float32(0)
            elif u_type == 'double':
                self.uniforms_data[u_name] = np.float64(0)

    def set_new_shader(
            self,
            shader_id: int,
            uniforms_name_type: dict
        ) -> None: 
        self.uniforms_data = {}
        self.shader_id = shader_id
        for u_name, u_type in uniforms_name_type.items():
            if u_type == 'mat4':
                self.uniforms_data[u_name] = np.zeros((4, 4), dtype=np.float32)
            elif u_type == 'vec4':
                self.uniforms_data[u_name] = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
            elif u_type == 'vec3':
                self.uniforms_data[u_name] = np.array([1.0, 1.0, 1.0], dtype=np.float32)
            elif u_type == 'float':
                self.uniforms_data[u_name] = np.float32(0)
            elif u_type == 'double':
                self.uniforms_data[u_name] = np.float64(0)

    @property
    def display_name(self) -> str:
        """用于 UI 显示的材质名（未保存时前加 *）。"""
        if self._is_saved:
            return self.name
        # 不重复加 *
        nn = self.name
        if nn.startswith("*"):
            return nn
        return f"*{nn}"

    def mark_modified(self) -> None:
        """标记材质已被修改，保存按钮变为可用。"""
        self._is_saved = False

    def mark_saved(self, file_path: str = "") -> None:
        """标记材质已保存。"""
        self._is_saved = True
        if file_path:
            self._file_path = file_path

    def to_dict(self) -> dict:
        """序列化为 .mat JSON 格式。"""
        uniforms_serializable = {}
        for k, v in self.uniforms_data.items():
            if hasattr(v, 'tolist'):
                uniforms_serializable[k] = v.tolist()
            else:
                uniforms_serializable[k] = v
        return {
            "version": "0.1.0",
            "name": self.name,
            "shader_id": self.shader_id,
            "texture_ids": list(self.texture_id_list),
            "uniforms": uniforms_serializable,
        }

    @classmethod
    def from_dict(cls, data: dict,
                  uniforms_name_type: dict | None = None) -> 'Material':
        """从 .mat JSON dict 恢复 Material。"""
        uniforms_data = {}
        for k, v in data.get("uniforms", {}).items():
            uniforms_data[k] = np.array(v, dtype=np.float32)
        mat = cls.__new__(cls)
        mat.shader_id = data.get("shader_id", 1)
        mat.texture_id_list = data.get("texture_ids", [])
        mat.uniforms_data = uniforms_data
        mat.name = data.get("name", "Untitled")
        mat._is_saved = True
        mat._file_path = ""
        return mat

    def save_to_file(self, file_path: str) -> None:
        """保存材质到 .mat 文件。"""
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        self.mark_saved(file_path)

    @classmethod
    def load_from_file(cls, file_path: str,
                       shader_uniforms: dict | None = None) -> 'Material':
        """从 .mat 文件加载材质。"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mat = cls.from_dict(data)
        mat._file_path = file_path
        mat._is_saved = True
        return mat


@dataclass
class Shader:
    """着色器资源 — 同时持有 GLSL 源码 (OpenGL) 和 SPIR-V 二进制 (Vulkan)。"""
    vs_src: str = ""          # GLSL vertex shader 源码
    fs_src: str = ""          # GLSL fragment shader 源码
    vs_spv: bytes = b""       # SPIR-V vertex shader 二进制
    fs_spv: bytes = b""       # SPIR-V fragment shader 二进制
    uniforms_name_type: dict = field(default_factory=dict)


@dataclass
class Texture:
    """CPU 侧的纹理数据（类比 Mesh — Mesh 存顶点，Texture 存像素）
    Attributes:
        image_data: 像素数据，形状 (H, W, C)，dtype uint8
        width:      图像宽度（像素）
        height:     图像高度（像素）
        channels:   通道数（1=灰度, 3=RGB, 4=RGBA）
        file_path:  源文件路径（程序化生成的纹理为空）
    """
    image_data: np.ndarray = None
    width: int = 0
    height: int = 0
    channels: int = 0
    file_path: str = ""

    def __init__(
        self,
        image_data: np.ndarray = None,
        width: int = 0,
        height: int = 0,
        channels: int = 0,
        file_path: str = "",
    ) -> None:
        self.image_data = image_data
        self.width = width
        self.height = height
        self.channels = channels
        self.file_path = file_path

    @staticmethod
    def CreateWhiteTexture() -> 'Texture':
        """创建 1×1 白色纹理，作为默认/占位纹理"""
        return Texture(
            image_data=np.array([[[255, 255, 255, 255]]], dtype=np.uint8),
            width=1, height=1, channels=4,
        )

    @staticmethod
    def CreateCheckerboard(
        size: int = 64,
        grid_size: int = 8,
        color1: tuple = (200, 200, 200, 255),
        color2: tuple = (50, 50, 50, 255),
    ) -> 'Texture':
        """棋盘格纹理，便于调试 UV 映射"""
        data = np.zeros((size, size, 4), dtype=np.uint8)
        block = size // grid_size
        for y in range(size):
            for x in range(size):
                cx, cy = x // block, y // block
                data[y, x] = color1 if (cx + cy) % 2 == 0 else color2
        return Texture(image_data=data, width=size, height=size, channels=4)

    @staticmethod
    def CreateColored(
        color: tuple = (255, 0, 0, 255),
        width: int = 1,
        height: int = 1,
    ) -> 'Texture':
        """纯色纹理"""
        channels = len(color)
        data = np.full((height, width, channels), color, dtype=np.uint8)
        return Texture(
            image_data=data, width=width, height=height, channels=channels,
        )