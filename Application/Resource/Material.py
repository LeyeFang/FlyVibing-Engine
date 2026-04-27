import numpy as np

from dataclasses import dataclass


@dataclass
class Material:

    shader_id: str
    texture_list: str
    uniforms: dict

    def __init__(
        self,
        shader_id: int,
        texture_list: list[int]
    ) -> None:
        self.shader_id = shader_id
        self.texture_list = texture_list


@dataclass
class Shader:

    vs_src: str
    fs_src: str
    uniforms: dict
    special_uniforms: dict

    def __init__(
        self,
        vs_src: str,
        fs_src: str,
        uniforms: dict = {},
        special_uniforms: dict = {}
    ) -> None:
        self.vs_src = vs_src
        self.fs_src = fs_src
        self.uniforms = uniforms
        self.special_uniforms = special_uniforms


@dataclass
class Texture:
    ...
