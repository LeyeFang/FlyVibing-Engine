from dataclasses import dataclass as component


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


@component
class MeshRenderer:
    mesh_handle: int
    shader_handle: int
