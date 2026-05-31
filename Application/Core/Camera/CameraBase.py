"""
相机统一接口 — 编辑器相机和场景相机的最小公共协议。

只定义 renderer 需要的两个方法：
  - get_view_matrix()        → 视图矩阵 (world → camera space)
  - get_projection_matrix()  → 投影矩阵 (camera → clip space)

所有相机类型 (EditorCamera / SceneCamera / 未来可能的 CinematicCamera)
都实现此接口即可被渲染器使用。
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
        """返回 4x4 视图矩阵 (world space → camera/eye space)。

        Returns:
            np.ndarray: shape (4, 4), dtype float32, column-major
        """
        ...

    @abstractmethod
    def get_projection_matrix(self, aspect_ratio: float) -> np.ndarray:
        """返回 4x4 投影矩阵 (camera space → clip space)。

        Args:
            aspect_ratio: 视口宽高比 (width / height)

        Returns:
            np.ndarray: shape (4, 4), dtype float32, column-major
        """
        ...
