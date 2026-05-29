"""场景浏览器 — 实体列表选择 & 检视逻辑"""

from dataclasses import dataclass
from typing import Optional

from Application.Core.Scene.SceneManager import SceneManager


@dataclass
class EntitySummary:
    entity_id: int
    position: tuple[float, float, float]
    mesh_id: Optional[int] = None
    material_id: Optional[int] = None


class SceneBrowserController:
    """实体选择与检视 — 纯数据层，不 import imgui"""

    selected_entity_id: Optional[int] = None

    # ── 实体列表 ────────────────────────────────────────────

    @classmethod
    def get_renderable_entities(cls) -> list[int]:
        return SceneManager.GetRenderableEntities()

    # ── 实体选择 ────────────────────────────────────────────

    @classmethod
    def select(cls, entity_id: int) -> None:
        cls.selected_entity_id = entity_id

    @classmethod
    def get_selected(cls) -> Optional[int]:
        return cls.selected_entity_id

    @classmethod
    def clear_selection(cls) -> None:
        cls.selected_entity_id = None

    # ── 实体检视 ────────────────────────────────────────────

    @classmethod
    def get_summary(cls, entity_id: int) -> Optional[EntitySummary]:
        try:
            t = SceneManager.GetEntityTransform(entity_id)
            summary = EntitySummary(
                entity_id=entity_id,
                position=(t.position_x, t.position_y, t.position_z),
            )
            try:
                summary.mesh_id = SceneManager.GetEntityMesh(entity_id)
            except Exception:
                pass
            try:
                summary.material_id = SceneManager.GetEntityMaterial(entity_id)
            except Exception:
                pass
            return summary
        except Exception:
            return None
