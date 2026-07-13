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

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class TransformAccessor:
    """实体变换 + 材质 Mesh 读写。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    def _esper_op(self, operation, op_name="?"):
        """在 esper 锁保护下执行操作（世界切换 + 操作原子化 + 事后还原）。"""
        from Application.Core.Scene.SceneManager import SceneManager as _SM
        with _SM._esper_lock:
            old_world = esper.current_world
            esper.switch_world(self._mgr.world_name)
            try:
                return operation()
            finally:
                esper.switch_world(old_world)

    # ════════════════════════════════════════════════════════════
    # Transform 读写
    # ════════════════════════════════════════════════════════════

    def get_transform(self, entity_id: int) -> Transform:
        """获取实体 Transform。线程安全。"""
        try:
            return self._esper_op(lambda: esper.component_for_entity(entity_id, Transform), f"get_transform({entity_id})")
        except KeyError:
            return Transform()

    def set_transform(self, entity_id: int, *,
                      position_xyz=None, rotation_xyz=None, scale_xyz=None) -> None:
        """设置实体 Transform（GL 坐标系）。线程安全。

        若 entity 有父实体，从 world 值反推 local 值以保持一致性。
        """
        st = self._mgr
        try:
            t = self._esper_op(lambda: esper.component_for_entity(entity_id, Transform), f"set_transform({entity_id})")
        except KeyError:
            return
        parent_id = st._entity_parent.get(entity_id)
        changed = False

        if position_xyz is not None:
            t.position_x, t.position_y, t.position_z = position_xyz
            # 有父实体 → 从 world 反推 local
            if parent_id is not None and parent_id != entity_id:
                try:
                    parent_t = esper.component_for_entity(parent_id, Transform)
                    t.local_pos_x = position_xyz[0] - parent_t.position_x
                    t.local_pos_y = position_xyz[1] - parent_t.position_y
                    t.local_pos_z = position_xyz[2] - parent_t.position_z
                except KeyError:
                    pass
            else:
                t.local_pos_x, t.local_pos_y, t.local_pos_z = position_xyz
            changed = True

        if rotation_xyz is not None:
            t.rotation_x, t.rotation_y, t.rotation_z = rotation_xyz
            t.local_rot_x, t.local_rot_y, t.local_rot_z = rotation_xyz
            changed = True

        if scale_xyz is not None:
            t.scale_x, t.scale_y, t.scale_z = scale_xyz
            # 有父实体 → 从 world 反推 local (component-wise)
            if parent_id is not None and parent_id != entity_id:
                try:
                    parent_t = esper.component_for_entity(parent_id, Transform)
                    psx, psy, psz = parent_t.scale_x, parent_t.scale_y, parent_t.scale_z
                    t.local_scl_x = scale_xyz[0] / psx if psx != 0 else scale_xyz[0]
                    t.local_scl_y = scale_xyz[1] / psy if psy != 0 else scale_xyz[1]
                    t.local_scl_z = scale_xyz[2] / psz if psz != 0 else scale_xyz[2]
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
        from Application.Core.Math.Transform import calculate_entity_model
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
        mr = self._esper_op(lambda: esper.component_for_entity(entity_id, MeshRenderer), f"get_mesh({entity_id})")
        return mr.mesh_id

    def get_material(self, entity_id: int) -> int:
        """获取实体的 material_id。线程安全。"""
        mr = self._esper_op(lambda: esper.component_for_entity(entity_id, MeshRenderer), f"get_material({entity_id})")
        return mr.material_id

    def set_mesh_renderer(self, entity_id: int, *, mesh_id=None, material_id=None,
                          visible=None) -> None:
        """修改实体 MeshRenderer 属性。线程安全。"""
        st = self._mgr
        try:
            mr = self._esper_op(lambda: esper.component_for_entity(entity_id, MeshRenderer), f"set_mesh_renderer({entity_id})")
        except KeyError:
            return
        if mesh_id is not None:
            mr.mesh_id = mesh_id
        if material_id is not None:
            mr.material_id = material_id
        if visible is not None:
            mr.visible = visible
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRenderVisibleCommand(entity_id, visible=visible))

    # ════════════════════════════════════════════════════════════
    # Camera 属性
    # ════════════════════════════════════════════════════════════

    def set_camera_properties(self, entity_id: int, **kwargs) -> None:
        """设置 Camera 组件属性（含 clamp）。线程安全。"""
        st = self._mgr
        try:
            cam = self._esper_op(lambda: esper.component_for_entity(entity_id, Camera), f"set_camera_properties({entity_id})")
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
        """设置实体材质的 uniform 参数。线程安全。"""
        st = self._mgr
        try:
            mr = self._esper_op(lambda: esper.component_for_entity(entity_id, MeshRenderer))
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
        """查询实体渲染可见性。线程安全。"""
        try:
            mr = self._esper_op(lambda: esper.component_for_entity(entity_id, MeshRenderer))
            return mr.visible
        except KeyError:
            return False
