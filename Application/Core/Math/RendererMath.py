import numpy as np
from pyrr import matrix44, Matrix44, vector4, vector3, Vector3
from Application.Core.Scene.BasicComponents import Camera, Transform, ProjectionType


def calculate_view_matrix(
    camera: Camera,
    transform: Transform,
    target: np.ndarray = None     # ← 轨道摄像头：指定 look-at 目标点
) -> np.ndarray:
    """根据摄像机和 Transform 计算视图矩阵

    当 target 不为 None 时，直接使用 target 作为 look-at 目标（轨道摄像头模式）。
    否则使用旋转矩阵 + local_forward 计算目标（自由摄像头模式）。
    """
    pos = Vector3([transform.position_x, transform.position_y, transform.position_z])
    up = Vector3(camera.up_vector)

    if target is not None:
        return matrix44.create_look_at(pos, Vector3(target), up)

    # 构建旋转矩阵
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,   # pitch
        transform.rotation_y,   # yaw
        transform.rotation_z    # roll
    ])
    # 将局部前向 (0,0,-1) 转换到世界空间
    local_forward = Vector3(camera.local_forward)
    local_forward_h = vector4.create_from_vector3(local_forward)  # w=0 (方向向量)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward_h)
    world_forward = vector3.create_from_vector4(world_forward_vec4)
    # ✅ 修复: 使用完整 3D 向量，而非只取 X 分量
    target_from_rot = pos + world_forward[0]
    return matrix44.create_look_at(pos, target_from_rot, up)


def calculate_projection_matrix(
    camera: Camera,
    aspect_ratio: float
) -> np.ndarray:
    """根据摄像机参数计算投影矩阵"""
    near = camera.near_plane
    far = camera.far_plane
    fov = camera.fov
    if camera.projection_type == ProjectionType.PERSPECTIVE:
        return matrix44.create_perspective_projection(
            fov, aspect_ratio, near, far
        )
    else:
        half_h = camera.ortho_size
        half_w = half_h * aspect_ratio
        return matrix44.create_orthogonal_projection(
            -half_w, half_w, -half_h, half_h, near, far
        )


def get_world_forward(
    camera: Camera,
    transform: Transform
) -> np.ndarray:
    """获取摄像机在世界空间中的前向单位向量 (3-element array)"""
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,
        transform.rotation_y,
        transform.rotation_z
    ])
    local_forward = Vector3(camera.local_forward)
    local_forward_h = vector4.create_from_vector3(local_forward)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward_h)
    world_forward = vector3.create_from_vector4(world_forward_vec4)[0]
    # 归一化确保单位向量
    fwd_len = np.linalg.norm(world_forward)
    if fwd_len > 0:
        world_forward = world_forward / fwd_len
    return world_forward


def calculate_entity_model(
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