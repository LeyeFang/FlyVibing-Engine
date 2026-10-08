"""
Entity 节点 — 实体生命周期 (Spawn, Destroy, Get, AddMesh, AddCamera, SetRenderVisible)。
"""

from . import _reg, _gen_id, ENTITY_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── v2: 类型安全 EntityRef ──

_reg(NodeTypeDef(
    "EntitySpawn", "Spawn Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Entity", "data", "output", "entity_ref"),
    ],
    "Instantiate from Scene template",
))

_reg(NodeTypeDef(
    "EntityDestroy", "Destroy Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Remove entity instance",
))

_reg(NodeTypeDef(
    "EntityGet", "Get Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "Entity", "data", "output", "entity_ref"),
    ],
    "Find entity by name",
))

# ── v1 兼容节点 (菜单中不出现 — 由 Component 节点覆盖) ──
#    EntityAddMesh / EntityAddCamera: Add Component / Set Component
#    的组件下拉已覆盖同样功能, 仅保留供旧图加载执行。

_reg(NodeTypeDef(
    "EntityAddMesh", "Add Mesh Component", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "MeshID", "data", "input", "int"),
        PinDef(_gen_id(), "MaterialID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add visible mesh",
))

_reg(NodeTypeDef(
    "EntityAddCamera", "Add Camera Component", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add camera component to entity",
))

# ── v1 但菜单保留 (Scene ▸ Entity): MI 实验图在用, 暂无 v2 替代 ──

_reg(NodeTypeDef(
    "EntitySetRenderVisible", "Set Render Visible", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "Visible", "data", "input", "bool"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show or hide entity (MeshRenderer.visible)",
))

_reg(NodeTypeDef(
    "EntityGroupSetVisible", "Set Group Visible", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity1", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Entity2", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Entity3", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Entity4", "data", "input", "entity_ref", optional=True),
        PinDef(_gen_id(), "Visible", "data", "input", "bool"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show/hide up to 4 entities as one atomic batch (same frame)",
))
