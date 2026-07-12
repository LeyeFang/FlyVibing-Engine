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
    # ── 世界空间 (World / Global) ──
    position_x: float = 0
    position_y: float = 0
    position_z: float = 0
    rotation_x: float = 0
    rotation_y: float = 0
    rotation_z: float = 0
    scale_x: float = 1
    scale_y: float = 1
    scale_z: float = 1

    # ── 本地空间 (Local, 相对于父实体) ──
    local_pos_x: float = 0
    local_pos_y: float = 0
    local_pos_z: float = 0
    local_rot_x: float = 0
    local_rot_y: float = 0
    local_rot_z: float = 0
    local_scl_x: float = 1
    local_scl_y: float = 1
    local_scl_z: float = 1

    def __post_init__(self) -> None:
        """dataclass 生成 __init__ 后自动调用 — 同步 local = world（根实体默认）。"""
        if self.local_pos_x == 0 and self.local_pos_y == 0 and self.local_pos_z == 0:
            self.local_pos_x = self.position_x
            self.local_pos_y = self.position_y
            self.local_pos_z = self.position_z
            self.local_rot_x = self.rotation_x
            self.local_rot_y = self.rotation_y
            self.local_rot_z = self.rotation_z
            self.local_scl_x = self.scale_x
            self.local_scl_y = self.scale_y
            self.local_scl_z = self.scale_z



@component
class MeshRenderer:
    mesh_id: int = 1
    material_id: int = 0
    visible: bool = True

    def __post_init__(self) -> None:
        """dataclass 生成 __init__ 后自动调用 — 创建默认 Material。"""
        if self.material_id == 0:
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
    far_plane: float = 1000.0
    # 视图辅助参数（用于计算视图矩阵，但实际位置/旋转来自 Transform）
    # 默认观察方向：局部坐标系中的前方（通常为 +Z 或 -Z，这里按 OpenGL 习惯设 -Z）
    local_forward: tuple = (0.0, 0.0, -1.0)
    up_vector: tuple = (0.0, 1.0, 0.0)
    # 可选：是否为主摄像机（若场景中有多个摄像机，用于标识默认）
    is_primary: bool = False
