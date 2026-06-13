"""
Camera unified interface — minimal protocol for editor and scene cameras.

Defines the two methods renderer needs:
  - get_view_matrix()        → view matrix (world → camera space)
  - get_projection_matrix()  → projection matrix (camera → clip space)

All camera types (EditorCamera / SceneCamera / future CinematicCamera)
implement this interface to be usable by the renderer.

MATRIX CONVENTION:
  Camera matrices are pyrr-style (row-vector convention internally).
  For OpenGL upload: use glUniformMatrix4fv(..., GL_FALSE, ...).
  See Application/Core/Math/__init__.py for complete documentation.
"""

from abc import ABC, abstractmethod

import numpy as np


class CameraBase(ABC):
    """相机统一抽象接口。

    Renderer 不关心具体是编辑器相机还是场景相机，
    只通过此接口获取 view/proj 矩阵。
    """

    @abstractmethod
    def get_view_matrix(self) -> np.ndarray:
        """Return 4x4 view matrix (world space → camera/eye space).

        Returns:
            np.ndarray: shape (4, 4), dtype float32, pyrr row-vector convention.
            Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
        """
        ...

    @abstractmethod
    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """Return 4x4 projection matrix (camera space → clip space).

        Args:
            aspect_ratio: Viewport aspect ratio (width / height)

        Returns:
            np.ndarray: shape (4, 4), dtype float32, pyrr row-vector convention.
            Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
        """
        ...
