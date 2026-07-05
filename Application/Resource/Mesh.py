import numpy as np

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Application.Core.Renderer.VertexLayout import VertexLayout


@dataclass
class Mesh:

    vertices: np.ndarray = None
    indices: np.ndarray = None
    uvs: np.ndarray = None
    normals: np.ndarray = None
    layout: 'VertexLayout' = None  # ★ 顶点格式描述符 (跨渲染后端), 取代旧 vao_config

    def __init__(
        self,
        vertices: np.ndarray,
        normals: np.ndarray,
        uvs: np.ndarray,
        indices: np.ndarray
    ) -> int:
        self.vertices = np.array(vertices, dtype=np.float32)
        self.indices = np.array(indices, dtype=np.uint32)
        self.uvs = np.array(uvs, dtype=np.float32)
        self.normals = np.array(normals, dtype=np.float32)

    def GetVertices(self):
        return self.vertices

    def GetIndices(self):
        return self.indices

    def GetNormals(self):
        return self.normals

    def GetUVs(self):
        return self.uvs
