import numpy as np

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
            elif u_type == 'float':
                self.uniforms_data[u_name] = np.float32(0)
            elif u_type == 'double':
                self.uniforms_data[u_name] = np.float64(0)
            


@dataclass
class Shader:

    vs_src: str
    fs_src: str
    uniforms_name_type: dict


@dataclass
class Texture:
    ...
