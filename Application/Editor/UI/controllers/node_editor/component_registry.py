"""
节点编辑器 — Component Property Registry。

定义每个 Component 类型的可编辑属性列表，
供 ComponentAdd / ComponentSet 节点动态生成 Pin 和内联控件。

新增组件类型时只需在此文件中扩充 _COMPONENT_PROPERTIES 即可。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class PropertyDescriptor:
    """组件属性的 UI 描述符 — 驱动动态 Pin 生成和内联控件渲染。

    Attributes:
        name: 属性名（也是 Pin 名），如 "Position"
        label: UI 标签，如 "Position"
        data_type: Pin 数据类型 — "float" | "int" | "bool" | "vec3" | "string" | "entity_ref"
        default: 默认值
        widget: 内联控件类型 — "drag_float3" | "drag_float" | "checkbox" | "combo" | "input_int"
        widget_config: 控件参数，如 {"speed": 0.1, "format": "%.2f"}
        pin_only: True 表示该属性只有 Pin（不显示内联控件），适用于 combo/资源选择器等复杂控件
    """
    name: str
    label: str
    data_type: str = "float"
    default: Any = 0.0
    widget: str = "drag_float"
    widget_config: dict = field(default_factory=dict)
    pin_only: bool = False
    attr_name: str = ""  # 实际组件属性名，空则使用 name

    def __post_init__(self):
        if not self.attr_name:
            self.attr_name = self.name


# ═══════════════════════════════════════════════════════════════
# Component → Property 注册表
# ═══════════════════════════════════════════════════════════════

_COMPONENT_PROPERTIES: dict[str, list[PropertyDescriptor]] = {
    "Transform": [
        PropertyDescriptor(
            "Position", "Position", "vec3", (0.0, 0.0, 0.0),
            widget="drag_float3",
            widget_config={"speed": 0.1, "format": "%.2f"},
        ),
        PropertyDescriptor(
            "Rotation", "Rotation", "vec3", (0.0, 0.0, 0.0),
            widget="drag_float3",
            widget_config={"speed": 1.0, "format": "%.1f"},
        ),
        PropertyDescriptor(
            "Scale", "Scale", "vec3", (1.0, 1.0, 1.0),
            widget="drag_float3",
            widget_config={"speed": 0.05, "format": "%.2f"},
        ),
    ],
    "MeshRenderer": [
        PropertyDescriptor(
            "MeshID", "Mesh ID", "int", 0,
            widget="input_int",
            attr_name="mesh_id",
        ),
        PropertyDescriptor(
            "MaterialID", "Material ID", "int", 0,
            widget="input_int",
            attr_name="material_id",
        ),
        PropertyDescriptor(
            "Visible", "Visible", "bool", True,
            widget="checkbox",
            attr_name="visible",
        ),
    ],
    # Camera —
}


# ═══════════════════════════════════════════════════════════════
# 查询接口
# ═══════════════════════════════════════════════════════════════

def get_properties(component_name: str) -> list[PropertyDescriptor]:
    """获取指定组件类型的属性描述符列表。"""
    return _COMPONENT_PROPERTIES.get(component_name, [])


def get_registered_component_names() -> list[str]:
    """获取所有已注册属性表的组件名（用于下拉菜单）。"""
    return sorted(_COMPONENT_PROPERTIES.keys(), key=lambda n: n.lower())
