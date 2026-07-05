"""场景浏览器 — 实体列表选择 & 检视逻辑"""

from dataclasses import dataclass
from typing import Optional

from Application.Core.Scene.SceneManager import SceneManager


@dataclass
class EntitySummary:
    entity_id: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
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
            t = SceneManager.GetEntityTransformEditor(entity_id)
            summary = EntitySummary(
                entity_id=entity_id,
                position=t['position'],
                rotation=t['rotation'],
                scale=t['scale'],
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

    # ── 实体属性编辑 ────────────────────────────────────────

    @classmethod
    def set_position(cls, entity_id: int, position: tuple[float, float, float]) -> None:
        """设置实体位置（编辑器坐标系）。"""
        SceneManager.SetEntityTransformEditor(entity_id, position_xyz=position)

    @classmethod
    def set_rotation(cls, entity_id: int, rotation: tuple[float, float, float]) -> None:
        """设置实体旋转（欧拉角）。"""
        SceneManager.SetEntityTransformEditor(entity_id, rotation_xyz=rotation)

    @classmethod
    def set_scale(cls, entity_id: int, scale: tuple[float, float, float]) -> None:
        """设置实体缩放。"""
        SceneManager.SetEntityTransformEditor(entity_id, scale_xyz=scale)


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SCENE_BROWSER
register(NAME_SCENE_BROWSER, SceneBrowserController)
