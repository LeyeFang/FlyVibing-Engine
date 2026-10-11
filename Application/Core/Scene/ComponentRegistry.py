"""
ComponentRegistry — 组件类型注册表。

职责:
  - 组件类型注册 / 查询
  - 按名称给实体添加组件

组合模式:
  ComponentRegistry 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import esper

from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Camera, MediaPlayer, Light, TextDisplay
from Application.Core.Renderer.RenderCommand import (
    EntityRegistrationCommand, EntityRenderVisibleCommand, EntityVisibilityCommand,
)
from Application.Core.Events.SceneEvent import NewComponentEvent

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


# ═══════════════════════════════════════════════════════════════
# 组件字段数值范围 (单一权威 — Inspector / MCP / 脚本写入共用)
# ═══════════════════════════════════════════════════════════════
# 值: (min, max); None = 该侧不限制; tuple/list 字段逐元素钳制。
# 写入口径: SceneBrowserController.set_component_field / LiveCommandServer component.set。
FIELD_CLAMPS: dict = {
    # ── Transform (world 分量; 与 SceneBrowserController 安全钳制同源) ──
    ("Transform", "position_x"): (-100000.0, 100000.0),
    ("Transform", "position_y"): (-100000.0, 100000.0),
    ("Transform", "position_z"): (-100000.0, 100000.0),
    ("Transform", "rotation_x"): (-3600.0, 3600.0),
    ("Transform", "rotation_y"): (-3600.0, 3600.0),
    ("Transform", "rotation_z"): (-3600.0, 3600.0),
    ("Transform", "scale_x"): (-10000.0, 10000.0),
    ("Transform", "scale_y"): (-10000.0, 10000.0),
    ("Transform", "scale_z"): (-10000.0, 10000.0),
    # ── Camera ──
    ("Camera", "fov"): (1.0, 179.0),
    ("Camera", "ortho_size"): (0.01, 10000.0),
    ("Camera", "near_plane"): (0.0001, 100.0),
    ("Camera", "far_plane"): (0.01, 1000000.0),
    # ── MeshRenderer (资源 id) ──
    ("MeshRenderer", "mesh_id"): (-1, 100000),
    ("MeshRenderer", "material_id"): (-1, 100000),
    # ── Light ──
    ("Light", "color_r"): (0.0, 1.0),
    ("Light", "color_g"): (0.0, 1.0),
    ("Light", "color_b"): (0.0, 1.0),
    ("Light", "intensity"): (0.0, 10.0),
    ("Light", "range"): (0.01, 1000.0),
    # ── MediaPlayer ──
    ("MediaPlayer", "speed"): (0.0, 10.0),
    # ── TextDisplay ──
    ("TextDisplay", "size"): (4, 512),
    ("TextDisplay", "line_spacing"): (0.1, 5.0),
    ("TextDisplay", "padding"): (0, 256),
    ("TextDisplay", "wrap_width"): (0, 8192),
    ("TextDisplay", "world_height"): (0.01, 100.0),
    ("TextDisplay", "color"): (0.0, 1.0),      # tuple: 逐元素
    ("TextDisplay", "bg_color"): (0.0, 1.0),   # tuple: 逐元素
}


def clamp_component_field(component_name: str, field_name: str, value):
    """按 FIELD_CLAMPS 钳制组件字段值。

    - 无规则 / bool / 非数值 → 原样返回;
    - tuple/list 值 → 逐元素钳制并保持 tuple;
    - int 值保持 int。
    """
    rule = FIELD_CLAMPS.get((component_name, field_name))
    if rule is None:
        return value
    lo, hi = rule

    def _clamp_one(v):
        if isinstance(v, bool):
            return v
        try:
            if isinstance(v, int):
                out = v
                if lo is not None:
                    out = max(int(lo), out)
                if hi is not None:
                    out = min(int(hi), out)
                return out
            out = float(v)
            if lo is not None:
                out = max(float(lo), out)
            if hi is not None:
                out = min(float(hi), out)
            return out
        except (TypeError, ValueError):
            return v

    if isinstance(value, (tuple, list)):
        return tuple(_clamp_one(v) for v in value)
    return _clamp_one(value)


# ═══════════════════════════════════════════════════════════════
# 组件字段选择集 (受控枚举 — Inspector 应渲染下拉而非自由文本)
# ═══════════════════════════════════════════════════════════════
# 值: [(存储值, 显示标签), ...]; 仅登记**已实现且测试过**的枚举值 —
# 不得登记未实现的未来选项 (假自由度; GUI 自由度规范见 Doc/Dev/ui_protocol.md §11)。
FIELD_CHOICES: dict = {
    # ── Light ──
    ("Light", "light_type"): [("directional", "Directional (平面光)"),
                              ("point", "Point (点光)")],
    # ── TextDisplay ──
    ("TextDisplay", "align"): [("left", "Left 左"),
                                ("center", "Center 中"),
                                ("right", "Right 右")],
}


def get_field_choices(component_name: str, field_name: str):
    """返回字段选择集 [(value, label)]; 无登记 → None。

    消费者: SceneBrowserController.get_component_fields → ScenePanel 通用检视
    (受控枚举字段渲染 Combo — 详见 ui_protocol.md §11 自由度分级)。
    """
    return FIELD_CHOICES.get((component_name, field_name))


class ComponentRegistry:
    """组件类型注册与管理。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    def register(self, name: str, component_cls: type) -> None:
        """注册一个可用的 Component 类型。"""
        self._mgr._component_registry[name] = component_cls

    def get_all(self) -> dict[str, type]:
        """获取所有已注册的 Component 类型。"""
        return dict(self._mgr._component_registry)

    def add_by_name(self, entity_id: int, component_name: str) -> bool:
        """按名称给实体添加 Component。线程安全。"""
        comp_cls = self._mgr._component_registry.get(component_name)
        if comp_cls is None:
            return False
        if esper.has_component(entity_id, comp_cls):
            return False
        instance = comp_cls()
        # ★ MeshRenderer 默认 mesh 设为 Cube 而非 Square
        if isinstance(instance, MeshRenderer):
            from Application.Resource.ResourceManager import ResourceManager
            try:
                instance.mesh_id = ResourceManager.GetDefaultMesh('Cube')
            except Exception:
                pass  # fallback to default mesh_id=1
        self._mgr.entity_mgr.add_component(entity_id, instance)
        return True

    def ensure_defaults(self) -> None:
        """确保内置组件已注册。"""
        reg = self._mgr._component_registry
        if "Camera" not in reg:
            reg["Camera"] = Camera
        if "MeshRenderer" not in reg:
            reg["MeshRenderer"] = MeshRenderer
        if "Transform" not in reg:
            reg["Transform"] = Transform
        if "MediaPlayer" not in reg:
            reg["MediaPlayer"] = MediaPlayer
        if "Light" not in reg:
            reg["Light"] = Light
        if "TextDisplay" not in reg:
            reg["TextDisplay"] = TextDisplay
