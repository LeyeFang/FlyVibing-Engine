import numpy as np
from OpenGL.GL import *

from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowResizeEvent
from Application.Renderer.Renderer import Renderer
from Application.Resource.Mesh import Mesh
from Application.Resource.ResourceManager import ResourceManager


class openglRenderer(Renderer):

    registed_mesh: dict[dict] = {}
    registed_shader: dict = {}

    @classmethod
    def Create(
        cls,
        app
    ):
        window_size = app.window.GetSize()
        glViewport(0, 0, window_size[0], window_size[1])
        return cls

    @classmethod
    def CreateMesh(
        cls,
        mesh: Mesh,
        mesh_id: int,
    ):
        vertices: np.ndarray = mesh.vertices
        indices: np.ndarray = mesh.indices
        cls.registed_mesh[f'{mesh_id}'] = {}
        current_mesh = cls.registed_mesh[f'{mesh_id}']
        current_mesh['mesh'] = mesh
        # VBO
        current_mesh['vbo'] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, current_mesh['vbo'])
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        # VAO
        current_mesh['vao'] = glGenVertexArrays(1)
        glBindVertexArray(current_mesh['vao'])
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(GLfloat), ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # EBO
        current_mesh['ebo'] = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, current_mesh['ebo'])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        # Counts
        current_mesh['counts'] = len(indices)
        return mesh_id

    @classmethod
    def StartFrame(cls):
        for current_mesh in cls.registed_mesh.values():
            pass

    @classmethod
    def EndFrame(cls):
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        for current_mesh in cls.registed_mesh.values():
            current_vao = current_mesh['vao']
            current_counts = current_mesh['counts']
            glBindVertexArray(current_vao)
            glDrawElements(GL_TRIANGLES, current_counts, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ):
        if event is WindowResizeEvent:
            width, height = event.Unpack()
            glViewport(0, 0, width, height)
