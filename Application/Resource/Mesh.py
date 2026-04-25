import numpy as np
from OpenGL.GL import *


class Mesh:

    vertices: np.ndarray = None
    indices: np.ndarray = None
    uvs: np.ndarray = None
    normals: np.ndarray = None

    def __init__(
        self,
        vertices: np.ndarray,
        normals: np.ndarray,
        uvs: np.ndarray,
        indices: np.ndarray
    ) -> int:
        self.vertices = vertices
        self.indices = indices
        self.uvs = uvs
        self.normals = normals

    def GetVertices(self):
        return self.vertices

    def GetIndices(self):
        return self.indices

    def GetNormals(self):
        return self.normals

    def GetUVs(self):
        return self.uvs
