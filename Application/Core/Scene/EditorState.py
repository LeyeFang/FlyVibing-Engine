"""
EditorState — 编辑器状态管理。

职责:
  - 编辑器视口可见性 (眼图标)
  - 编辑器渲染可见性控制

组合模式:
  EditorState 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from Application.Core.Renderer.RenderCommand import EntityVisibilityCommand

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class EditorState:
    """编辑器可见性 + 状态。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    def set_visible(self, entity_id: int, visible: bool) -> None:
        """设置实体在编辑器视口中的可见性 (眼图标)。不影响 PIE 渲染。"""
        st = self._mgr
        if visible:
            st._editor_visible.add(entity_id)
        else:
            st._editor_visible.discard(entity_id)

        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityVisibilityCommand(entity_id, visible=visible))

    def is_visible(self, entity_id: int) -> bool:
        return entity_id in self._mgr._editor_visible

    def get_visible_entities(self) -> set[int]:
        """返回编辑器可见实体集合（无过滤时返回空 set 表示全部可见）。"""
        return set(self._mgr._editor_visible)
