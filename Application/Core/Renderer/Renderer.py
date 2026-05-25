from abc import ABC, abstractmethod
from dataclasses import dataclass

from Application.Core.Events.Event import Event


class Renderer(ABC):

    app = None
    viewport_width: int
    viewport_height: int
    aspect_ratio: float
    camera_id: int

    @classmethod
    @abstractmethod
    def Create(cls):
        ...

    @classmethod
    @abstractmethod
    def StartFrame(cls):
        ...

    @classmethod
    @abstractmethod
    def EndFrame(cls):
        ...

    @classmethod
    @abstractmethod
    def OnEvent(
        cls,
        event: Event
    ):
        ...


class RenderResourceManger(ABC):

    view_matrix = None
    proj_matrix = None

    @dataclass
    class entity_data_struct:
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int

    @dataclass
    class mesh_data_struct:
        vbo: int
        vao: int
        ebo: int
        elements_count: int
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        program: int
        uniforms_type: list[str]
        uniforms_loc: dict[str, int]
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        ref_count: int = 0


    registered_entities: dict[entity_data_struct] = {}
    registered_meshes: dict[mesh_data_struct] = {}
    registered_shaders: dict[shader_data_struct] = {}
    registered_textures: dict = {}

    @classmethod
    @abstractmethod
    def register_entity(cls):
        ...

    @classmethod
    @abstractmethod
    def register_mesh(cls):
        ...

    @classmethod
    @abstractmethod
    def register_texture(cls):
        ...

    @classmethod
    def register_shader(cls):
        ...

    @classmethod
    @abstractmethod
    def unregister_entity(cls):
        ...

    @classmethod
    @abstractmethod
    def unregister_mesh(cls):
        ...

    @classmethod
    @abstractmethod
    def unregister_texture(cls):
        ...

    @classmethod
    def unregister_shader(cls):
        ...
