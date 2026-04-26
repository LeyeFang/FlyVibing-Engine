from Application.Scene.BasicComponents import Component
from Application.Events.Event import Event


#
# Scene Event
# =========================================
class NewSceneEvent(Event):
    pass


#
# Component Event
# =========================================
class ComponentModifiedEvent(Event):

    entity_id: int = None
    modified_comp: Component = None
    args_dict: dict = {}
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        entity_id: int,
        comp: Component
    ):
        cls.entity_id = entity_id
        cls.modified_comp = comp
        cls.log_info: str = f"Modified component '{cls.modified_comp.__class__.__name__}' for entity '{entity_id}'"
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ):
        super().UnPack()
        return cls.entity_id, cls.modified_comp


class NewComponentEvent(Event):

    entity_id: int = None
    new_comp: Component = None
    log_info: str = ''

    @classmethod
    def Pack(
        cls,
        entity_id: int,
        comp: Component
    ):
        cls.entity_id = entity_id
        cls.new_comp = comp
        cls.log_info: str = f"New component '{cls.new_comp.__class__.__name__}' for entity '{entity_id}'"
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> tuple:
        return cls.entity_id, cls.new_comp
