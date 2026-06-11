"""
Editor 事件定义 — 编辑器交互层专用事件。

事件命名约定:
  - *Event  : 编辑器领域事件 (选择、变换、编辑模式等)

所有事件继承 Application.Core.Events.Event.Event, 通过 Pack/UnPack 模式
在主线程与渲染线程之间传递状态变更。
"""

from Application.Core.Events.Event import Event


# ═══════════════════════════════════════════════════════════════
# 实体选择事件 / Entity Selection Events
# ═══════════════════════════════════════════════════════════════

class SelecteEntityEvent(Event):
    """实体被选中事件 — 由编辑器拾取系统触发。

    Pack 参数:
        entity_id   : 被选中的 ECS 实体 ID
        entity_name : (可选) 实体名称, 用于日志显示
    UnPack 返回:
        (entity_id, entity_name)
    """

    entity_id: int = None
    entity_name: str = ''
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        entity_id: int,
        entity_name: str = ''
    ):
        cls.entity_id = entity_id
        cls.entity_name = entity_name
        cls.log_info = (
            f"Entity '{entity_name or entity_id}' (ID={entity_id}) selected"
        )
        super().Pack()

    @classmethod
    def UnPack(cls):
        return cls.entity_id, cls.entity_name


class DeselectEntityEvent(Event):
    """实体取消选中事件。

    Pack 参数:
        entity_id   : 被取消选中的 ECS 实体 ID
    UnPack 返回:
        entity_id
    """

    entity_id: int = None
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        entity_id: int
    ):
        cls.entity_id = entity_id
        cls.log_info = f"Entity '{entity_id}' deselected"
        super().Pack()

    @classmethod
    def UnPack(cls):
        return cls.entity_id


class ClearSelectionEvent(Event):
    """清除所有选中事件。

    通常由 Escape 键或点击空白区域触发。
    """

    log_info: str = ''

    @classmethod
    def Pack(cls):
        cls.log_info = "Selection cleared"
        super().Pack()

    @classmethod
    def UnPack(cls):
        pass


# ═══════════════════════════════════════════════════════════════
# 视图立方体交互事件 / ViewGizmo Interaction Events
# ═══════════════════════════════════════════════════════════════

class ViewGizmoFaceClickEvent(Event):
    """视图立方体面点击事件 — 用户点击了视图立方体的某个面。

    Pack 参数:
        face_name : 被点击的面名称
                    ('front' / 'back' / 'left' / 'right' / 'top' / 'bottom')
    UnPack 返回:
        face_name : str
    """

    face_name: str = ''

    @classmethod
    def Pack(cls, face_name: str):
        cls.face_name = face_name
        cls.log_info = f"ViewGizmo face clicked: [{face_name}]"
        super().Pack()

    @classmethod
    def UnPack(cls) -> str:
        return cls.face_name
