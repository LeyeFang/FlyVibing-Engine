"""
Component 节点 — ComponentAdd, ComponentRemove, SetComponent, GetComponent。
"""

from . import _reg, _gen_id, COMPONENT_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── ComponentAdd / SetComponent 共用属性 Pin (input) ──
_COMPONENT_PROPERTY_PINS: list = [
    PinDef(_gen_id(), "Position", "data", "input", "vec3"),
    PinDef(_gen_id(), "Rotation", "data", "input", "vec3"),
    PinDef(_gen_id(), "Scale", "data", "input", "vec3"),
    PinDef(_gen_id(), "MeshID", "data", "input", "int"),
    PinDef(_gen_id(), "MaterialID", "data", "input", "int"),
    PinDef(_gen_id(), "Visible", "data", "input", "bool"),
]

# ── GetComponent 属性 Pin (output) ──
_COMPONENT_PROPERTY_OUT_PINS: list = [
    PinDef(_gen_id(), "Position", "data", "output", "vec3"),
    PinDef(_gen_id(), "Rotation", "data", "output", "vec3"),
    PinDef(_gen_id(), "Scale", "data", "output", "vec3"),
    PinDef(_gen_id(), "MeshID", "data", "output", "int"),
    PinDef(_gen_id(), "MaterialID", "data", "output", "int"),
    PinDef(_gen_id(), "Visible", "data", "output", "bool"),
]

_reg(NodeTypeDef(
    "ComponentAdd", "Add Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add component to entity",
))

_reg(NodeTypeDef(
    "ComponentRemove", "Remove Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Remove component from entity",
))

_reg(NodeTypeDef(
    "SetComponent", "Set Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Modify existing component",
))

_reg(NodeTypeDef(
    "GetComponent", "Get Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_OUT_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Read component values",
))
