import numpy as np

from dataclasses import dataclass


@dataclass
class Material:

    vs_src: str
    fs_src: str
    uniforms: dict

    def __init__(
        self,
        vs_src: str,
        fs_src: str,
        uniforms: dict = {}
    ) -> None:
        self.vs_src = vs_src
        self.fs_src = fs_src
        self.uniforms = uniforms
