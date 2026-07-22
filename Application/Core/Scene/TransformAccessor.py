"""
TransformAccessor — 实体变换 + Mesh/Material 读写。

职责:
  - Get/Set 实体 Transform (world + editor 坐标转换)
  - 实体 Model 矩阵计算
  - Mesh/Material ID 读写
  - 渲染可见性控制

组合模式:
  TransformAccessor 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np
import esper

from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Camera
from Application.Core.Events.SceneEvent import ComponentModifiedEvent
from Application.Core.Renderer.RenderCommand import (
    EntityRegistrationCommand, EntityRenderVisibleCommand, EntityVisibilityCommand,
)
from Application.Core.Math.CoordinateSystem import (
    editor_to_gl_position, gl_to_editor_position,
    editor_to_gl_scale, gl_to_editor_scale,
)
from Application.Core.Math.Transform import (
    calculate_entity_model,
    local_to_world_position, world_to_local_position,
    local_to_world_rotation, world_to_local_rotation,
    local_to_world_scale, world_to_local_scale,
)

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class TransformAccessor:
    """实体变换 + 材质 Mesh 读写。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    # ════════════════════════════════════════════════════════════
    # Transform 读写
    # ════════════════════════════════════════════════════════════

    def get_transform(self, entity_id: int) -> Transform:
        """获取实体 Transform 组件（返回引用，可修改）。"""
        try:
            return esper.component_for_entity(entity_id, Transform)
        except KeyError:
            return Transform()

    def get_world_position(self, entity_id: int) -> tuple[float, float, float]:
        """计算实体的世界位置 (local → world 沿父链推导)。"""
        t = self.get_transform(entity_id)
        parent_id = self._mgr._entity_parent.get(entity_id)
        if parent_id is not None and parent_id != entity_id:
            p_pos = self.get_world_position(parent_id)
            return local_to_world_position(
                (t.local_pos_x, t.local_pos_y, t.local_pos_z), p_pos)
        return (t.local_pos_x, t.local_pos_y, t.local_pos_z)

    def get_world_rotation(self, entity_id: int) -> tuple[float, float, float]:
        """计算实体的世界旋转 (local → world 沿父链推导, Euler 分量累加)。"""
        t = self.get_transform(entity_id)
        parent_id = self._mgr._entity_parent.get(entity_id)
        if parent_id is not None and parent_id != entity_id:
            p_rot = self.get_world_rotation(parent_id)
            return local_to_world_rotation(
                (t.local_rot_x, t.local_rot_y, t.local_rot_z), p_rot)
        return (t.local_rot_x, t.local_rot_y, t.local_rot_z)

    def get_world_scale(self, entity_id: int) -> tuple[float, float, float]:
        """计算实体的世界缩放 (local → world 沿父链推导, component-wise 乘法)。"""
        t = self.get_transform(entity_id)
        parent_id = self._mgr._entity_parent.get(entity_id)
        if parent_id is not None and parent_id != entity_id:
            p_scl = self.get_world_scale(parent_id)
            return local_to_world_scale(
                (t.local_scl_x, t.local_scl_y, t.local_scl_z), p_scl)
        return (t.local_scl_x, t.local_scl_y, t.local_scl_z)

    def set_transform(self, entity_id: int, *,
                      position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        """设置实体 Transform（GL 坐标系）。线程安全。

        若 entity 有父实体，从 world 值反推 local 值以保持一致性。
        """
        st = self._mgr
        try:
            t = esper.component_for_entity(entity_id, Transform)
        except KeyError:
            return
        parent_id = st._entity_parent.get(entity_id)
        changed = False

        if position_xyz is not None:
            t.position_x, t.position_y, t.position_z = position_xyz
            if parent_id is not None and parent_id != entity_id:
                try:
                    parent_t = esper.component_for_entity(parent_id, Transform)
                    p_pos = (parent_t.position_x, parent_t.position_y, parent_t.position_z)
                    lx, ly, lz = world_to_local_position(position_xyz, p_pos)
                    t.local_pos_x, t.local_pos_y, t.local_pos_z = lx, ly, lz
                except KeyError:
                    t.local_pos_x, t.local_pos_y, t.local_pos_z = position_xyz
            else:
                t.local_pos_x, t.local_pos_y, t.local_pos_z = position_xyz
            changed = True

        if rotation_xyz is not None:
            t.rotation_x, t.rotation_y, t.rotation_z = rotation_xyz
            if parent_id is not None and parent_id != entity_id:
                try:
                    parent_t = esper.component_for_entity(parent_id, Transform)
                    p_rot = (parent_t.rotation_x, parent_t.rotation_y, parent_t.rotation_z)
                    lx, ly, lz = world_to_local_rotation(rotation_xyz, p_rot)
                    t.local_rot_x, t.local_rot_y, t.local_rot_z = lx, ly, lz
                except KeyError:
                    t.local_rot_x, t.local_rot_y, t.local_rot_z = rotation_xyz
            else:
                t.local_rot_x, t.local_rot_y, t.local_rot_z = rotation_xyz
            changed = True

        if scale_xyz is not None:
            t.scale_x, t.scale_y, t.scale_z = scale_xyz
            if parent_id is not None and parent_id != entity_id:
                try:
                    parent_t = esper.component_for_entity(parent_id, Transform)
                    p_scl = (parent_t.scale_x, parent_t.scale_y, parent_t.scale_z)
                    lx, ly, lz = world_to_local_scale(scale_xyz, p_scl)
                    t.local_scl_x, t.local_scl_y, t.local_scl_z = lx, ly, lz
                except KeyError:
                    pass
            else:
                t.local_scl_x, t.local_scl_y, t.local_scl_z = scale_xyz
            changed = True

        if changed:
            ComponentModifiedEvent.Pack(entity_id, t, engine=st.app)

    def set_transform_editor(self, entity_id: int, *,
                             position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        """设置实体 Transform（编辑器坐标系 → 自动转换到 GL）。

        Position: editor (right, forward, up) → GL (right, up, backward)
        Rotation: 同 Position 映射（Y↔Z 交换 + Y 符号翻转）
        Scale:    Y↔Z 交换（无符号翻转）
        """
        gl_pos = None
        gl_rot = None
        gl_scale = None
        if position_xyz is not None:
            gl_pos = editor_to_gl_position(*position_xyz)
        if rotation_xyz is not None:
            gl_rot = editor_to_gl_position(*rotation_xyz)
        if scale_xyz is not None:
            gl_scale = editor_to_gl_scale(*scale_xyz)
        self.set_transform(entity_id, position_xyz=gl_pos, rotation_xyz=gl_rot,
                           scale_xyz=gl_scale)

    def get_model_matrix(self, entity_id: int) -> np.ndarray:
        """计算实体的 4×4 model 矩阵（世界变换）。

        有父实体时: world = local_matrix @ parent_world_matrix
        无父实体时: world = world_matrix (position_xyz / rotation_xyz / scale_xyz)
        """
        t = self.get_transform(entity_id)
        parent_id = self._mgr._entity_parent.get(entity_id)

        if parent_id is not None and parent_id != entity_id:
            # ★ 有父实体 → 用 local 变换结合父世界矩阵
            local_model = calculate_entity_model(
                position=(t.local_pos_x, t.local_pos_y, t.local_pos_z),
                rotation=(t.local_rot_x, t.local_rot_y, t.local_rot_z),
                scale=(t.local_scl_x, t.local_scl_y, t.local_scl_z),
            )
            parent_model = self.get_model_matrix(parent_id)
            # row-vector 约定: v' = v × local × parent = v × (local @ parent)
            return local_model @ parent_model
        else:
            # 根实体 → 直接用世界坐标
            return calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )

    # ════════════════════════════════════════════════════════════
    # Mesh / Material 读写
    # ════════════════════════════════════════════════════════════

    def get_mesh(self, entity_id: int) -> int:
        """获取实体的 mesh_id。线程安全。"""
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        return mr.mesh_id

    def get_material(self, entity_id: int) -> int:
        """获取实体的 material_id。线程安全。"""
        mr = esper.component_for_entity(entity_id, MeshRenderer)
        return mr.material_id

    def set_mesh_renderer(self, entity_id: int, *, mesh_id=None, material_id=None,
                          visible=None) -> None:
        """修改实体 MeshRenderer 属性。线程安全。"""
        st = self._mgr
        try:
            mr = esper.component_for_entity(entity_id, MeshRenderer)
        except KeyError:
            return
        needs_reregister = False
        if mesh_id is not None:
            mr.mesh_id = mesh_id
            needs_reregister = True
        if material_id is not None:
            mr.material_id = material_id
            needs_reregister = True
        if visible is not None:
            mr.visible = visible
        if needs_reregister or visible is not None:
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                if needs_reregister:
                    _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
                else:
                    _renderer.enqueue(EntityRenderVisibleCommand(entity_id, visible=visible))
        if needs_reregister:
            ComponentModifiedEvent.Pack(entity_id, mr, engine=st.app)

    # ════════════════════════════════════════════════════════════
    # Camera 属性
    # ════════════════════════════════════════════════════════════

    def set_camera_properties(self, entity_id: int, **kwargs) -> None:
        """设置 Camera 组件属性（含 clamp）。线程安全。"""
        st = self._mgr
        try:
            cam = esper.component_for_entity(entity_id, Camera)
        except KeyError:
            return
        changed = False
        for key, value in kwargs.items():
            if hasattr(cam, key):
                # Clamp 合理范围
                if key == 'fov' and value is not None:
                    value = max(1.0, min(179.0, float(value)))
                elif key == 'near_plane' and value is not None:
                    value = max(0.001, float(value))
                elif key == 'far_plane' and value is not None:
                    value = max(0.01, float(value))
                setattr(cam, key, value)
                changed = True
        if changed:
            ComponentModifiedEvent.Pack(entity_id, cam, engine=st.app)

    def set_material_params(self, entity_id: int, params: dict) -> None:
        """设置实体材质的 uniform 参数。"""
        st = self._mgr
        try:
            mr = esper.component_for_entity(entity_id, MeshRenderer)
        except KeyError:
            return
        from Application.Resource.ResourceManager import ResourceManager
        mat = ResourceManager.GetMaterial(mr.material_id)
        if mat is not None:
            for key, value in params.items():
                if key in mat.uniforms_data:
                    mat.uniforms_data[key] = value

    # ════════════════════════════════════════════════════════════
    # 渲染可见性
    # ════════════════════════════════════════════════════════════

    def set_render_visible(self, entity_id: int, visible: bool) -> None:
        self.set_mesh_renderer(entity_id, visible=visible)

    def is_render_visible(self, entity_id: int) -> bool:
        """查询实体渲染可见性。"""
        try:
            mr = esper.component_for_entity(entity_id, MeshRenderer)
            return mr.visible
        except KeyError:
            return False
