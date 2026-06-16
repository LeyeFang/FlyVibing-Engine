from Application.Core.Scene.BasicComponents import *
from Application.Core.Events.Event import Event


#
# Scene Event
# =========================================
class NewSceneEvent(Event):
    """新场景创建信号 — 无数据负载。"""

    @classmethod
    def Pack(cls) -> None:
        super().Pack()


#
# Component Event
# =========================================
class ComponentModifiedEvent(Event):
    """组件修改通知 — 携带 entity_id + 被修改的组件实例。"""

    def __init__(self, entity_id: int, comp: Component) -> None:
        super().__init__()
        self.entity_id: int = entity_id
        self.modified_comp: Component = comp

    @property
    def log_info(self) -> str:
        return f"Modified component '{self.modified_comp.__class__.__name__}' for entity '{self.entity_id}'"

    @classmethod
    def Pack(cls, entity_id: int, comp: Component) -> None:
        super().Pack(entity_id, comp)

    def unpack(self) -> tuple:
        return self.entity_id, self.modified_comp


class NewComponentEvent(Event):
    """新组件添加通知 — 携带 entity_id + 新组件实例。"""

    def __init__(self, entity_id: int, comp: Component) -> None:
        super().__init__()
        self.entity_id: int = entity_id
        self.new_comp: Component = comp

    @property
    def log_info(self) -> str:
        return f"New component '{self.new_comp.__class__.__name__}' for entity '{self.entity_id}'"

    @classmethod
    def Pack(cls, entity_id: int, comp: Component) -> None:
        super().Pack(entity_id, comp)

    def unpack(self) -> tuple:
        return self.entity_id, self.new_comp


class UpdateShaderUniformsEvent(Event):
    """Shader Uniform 更新通知 — 携带 entity_id + uniform 字典。"""

    def __init__(self, entity_id: int, uniforms: dict) -> None:
        super().__init__()
        self.entity_id: int = entity_id
        self.uniforms: dict = uniforms

    @classmethod
    def Pack(cls, entity_id: int, uniforms: dict) -> None:
        super().Pack(entity_id, uniforms)

    def unpack(self) -> tuple:
        return self.entity_id, self.uniforms


class SceneCameraUpdateEvent(Event):
    """场景摄像机更新信号 — 通知 Renderer 刷新 view/proj 缓存 (无数据负载)。"""

    @classmethod
    def Pack(cls) -> None:
        super().Pack()

