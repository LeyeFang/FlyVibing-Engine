import numpy as np
from pyrr import matrix44, vector3, vector4
from pyrr import Matrix44, Vector3
from Application.Scene.BasicComponents import *
#
# Math
# ======================================================================================
import math


def Calculate_Entity_Model(
    transform: Transform
) -> Matrix44:
    # 1. 创建缩放矩阵
    scale_mat = Matrix44.from_scale(Vector3(
        [transform.scale_x, transform.scale_y, transform.scale_z]
    ), dtype=float)
    # 2. 从欧拉角创建旋转矩阵 (相当于 R = Rz * Ry * Rx)
    rot_mat = Matrix44.from_eulers(Vector3(
        [transform.rotation_x, transform.rotation_y, transform.rotation_z]
    ), dtype=float)
    # 3. 创建平移矩阵
    trans_mat = Matrix44.from_translation(Vector3(
        [transform.position_x, transform.position_y, transform.position_z]
    ), dtype=float)
    # 4. 按照 TRS 顺序相乘: Model = T * R * S
    return trans_mat * rot_mat * scale_mat


def Calculate_Camera_View(
    camera: Camera,
    transform: Transform
) -> Matrix44:
    """根据摄像机的辅助参数和实体的变换组件计算视图矩阵"""
    pos = Vector3([transform.position_x, transform.position_y, transform.position_z])
    # 构建旋转矩阵（欧拉角顺序 ZYX，弧度）
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,   # pitch (X)
        transform.rotation_y,   # yaw   (Y)
        transform.rotation_z    # roll  (Z)
    ])
    # 世界前向 = 旋转矩阵 * 局部前向（齐次向量 w=0）
    local_forward = Vector3(camera.local_forward)
    local_forward = vector4.create_from_vector3(local_forward)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward)
    world_forward = vector3.create_from_vector4(world_forward_vec4)
    world_forward = world_forward[0]
    target = pos + world_forward
    up = Vector3(camera.up_vector)
    return matrix44.create_look_at(pos, target, up)


def Calculate_Camera_Proj(
    camera: Camera,
    aspect_ratio: float
) -> Matrix44:
    """根据摄像机投影参数计算投影矩阵"""
    near = camera.near_plane
    far = camera.far_plane
    fov = camera.fov
    if camera.projection_type == ProjectionType.PERSPECTIVE:
        return matrix44.create_perspective_projection(
            fov,
            aspect_ratio,
            near,
            far
        )
    else:
        half_h = camera.ortho_size
        half_w = half_h * aspect_ratio
        return matrix44.create_orthogonal_projection(
            -half_w, half_w,   # left, right
            -half_h, half_h,   # bottom, top
            near, far
        )
