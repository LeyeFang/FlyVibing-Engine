import numpy as np
import copy

from dataclasses import dataclass, field


@dataclass
class Material:

    shader_id: int = 1
    texture_id_list: list = field(default_factory=list)
    uniforms_data: dict[str, np.ndarray] = field(default_factory=dict)

    def __init__(
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
        # ── 材质元数据 ──
        self.name: str = "Untitled"
        self._is_saved: bool = False        # 是否已保存到文件
        self._file_path: str = ""           # 上次保存/加载的文件路径

    @property
    def display_name(self) -> str:
        """编辑器显示名：* 前缀表示未保存。"""
        prefix = "" if self._is_saved else "*"
        return f"{prefix}{self.name}"

    def mark_modified(self) -> None:
        """标记为已修改（未保存）。"""
        self._is_saved = False

    def save_to_file(self, file_path: str) -> None:
        """保存材质到 .mat 文件（JSON）。"""
        import json, os
        data = {
            "name": self.name,
            "shader_id": self.shader_id,
            "texture_ids": self.texture_id_list,
            "uniforms": {
                k: v.tolist() if hasattr(v, 'tolist') else v
                for k, v in self.uniforms_data.items()
            },
        }
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        self._is_saved = True
        self._file_path = file_path

    @staticmethod
    def load_from_file(file_path: str) -> "Material":
        """从 .mat 文件加载材质。"""
        import json
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # 需要 shader 信息来初始化 uniforms — 用空 dict 作为占位，后续 set_new_shader 会填充
        mat = Material(data.get("shader_id", 1), {})
        mat.name = data.get("name", "Untitled")
        mat.texture_id_list = data.get("texture_ids", [])
        for k, v in data.get("uniforms", {}).items():
            mat.uniforms_data[k] = np.array(v, dtype=np.float32)
        mat._is_saved = True
        mat._file_path = file_path
        return mat

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