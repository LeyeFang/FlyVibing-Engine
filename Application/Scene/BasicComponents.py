from dataclasses import dataclass as component
from enum import Enum

from Application.Resource.ResourceManager import ResourceManager


@component
class Component:
    pass


@component
class ObjectInfo:
    name: str
    obj_id: int


@component
class Transform:
    position_x: float = 0
    position_y: float = 0
    position_z: float = 0
    rotation_x: float = 0
    rotation_y: float = 0
    rotation_z: float = 0
    scale_x: float = 1
    scale_y: float = 1
    scale_z: float = 1

    def __init__(
        self,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_x=0,
        rotation_y=0,
        rotation_z=0,
        scale_x=1,
        scale_y=1,
        scale_z=1,
    ):
        self.position_x = position_x
        self.position_y = position_y
        self.position_z = position_z
        self.rotation_x = rotation_x
        self.rotation_y = rotation_y
        self.rotation_z = rotation_z
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.scale_z = scale_z



@component
class MeshRenderer:
    mesh_id: int
    material_id: int
    visible: bool = True

    def __init__(
        self,
        mesh_id: int = 1
    ) -> None:
        self.mesh_id = mesh_id
        self.material_id = ResourceManager.NewMaterial()


class ProjectionType(Enum):
    PERSPECTIVE = "perspective"
    ORTHOGRAPHIC = "orthographic"


@component
class Camera:
    # 投影类型（默认透视投影）
    projection_type: ProjectionType = ProjectionType.PERSPECTIVE
    # 透视投影参数（角度制）
    fov: float = 45.0
    aspect_ratio: float = 16.0 / 9.0
    # 正交投影参数（世界单位半高）
    ortho_size: float = 5.0
    # 通用裁剪平面
    near_plane: float = 0.1
    far_plane: float = 100.0
    # 视图辅助参数（用于计算视图矩阵，但实际位置/旋转来自 Transform）
    # 默认观察方向：局部坐标系中的前方（通常为 +Z 或 -Z，这里按 OpenGL 习惯设 -Z）
    local_forward: tuple = (0.0, 0.0, -1.0)
    up_vector: tuple = (0.0, 1.0, 0.0)
    # 可选：是否为主摄像机（若场景中有多个摄像机，用于标识默认）
    is_primary: bool = False

    def __init__(
        self,
        is_primary=False
    ) -> None:
        self.is_primary = is_primary
