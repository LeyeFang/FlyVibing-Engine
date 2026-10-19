"""显示名翻译（节点/组件/Add 菜单分组）— 编辑器层中立模块。

键空间（键规范要求全小写，CamelCase 类型名转 snake_case）：
  - `node.<snake_type>`  → 节点卡片标题 / Add 菜单叶子
  - `comp.<snake_type>`  → 检查器组件标题 / Add Component 菜单
  - `menu.node_group.<snake>` → Add 菜单分类/分组标题

缺失词条时回退注册表自带的英文 label —— 扩展新增节点即使没有语言包也能正常显示。
"""

from __future__ import annotations

import re

from Application.Editor.I18n import t_optional


def _snake(name: str) -> str:
    """CamelCase → snake_case（InitFBCSP → init_fbcsp）。"""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name or ""))
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def node_key(type_name: str) -> str:
    return f"node.{_snake(type_name)}"


def component_key(comp_name: str) -> str:
    return f"comp.{_snake(comp_name)}"


def group_key(title: str) -> str:
    return f"menu.node_group.{_snake(title)}"


def node_label(type_name: str, fallback: str) -> str:
    """节点显示名（`node.<snake>` 缺失 → fallback）。"""
    return t_optional(node_key(type_name), fallback)


def component_label(comp_name: str, fallback: str | None = None) -> str:
    """组件显示名（`comp.<snake>` 缺失 → fallback 或原名）。"""
    return t_optional(component_key(comp_name), fallback or comp_name)


def group_label(title: str, fallback: str | None = None) -> str:
    """Add 菜单分类/分组标题（`menu.node_group.<snake>` 缺失 → fallback）。"""
    return t_optional(group_key(title), fallback or title)
