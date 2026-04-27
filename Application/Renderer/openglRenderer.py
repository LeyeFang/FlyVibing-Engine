import numpy as np
from OpenGL.GL import *

# Event
from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowResizeEvent
from Application.Events.SceneEvent import NewComponentEvent, ComponentModifiedEvent
# Resource
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material
# Scene
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import *
# Renderer
from Application.Renderer.Renderer import Renderer
from Application.Renderer._renderer_math_utils import (
    Calculate_Camera_Proj,
    Calculate_Camera_View,
    Calculate_Entity_Model
)


class openglRenderer(Renderer):

    aspect_ratio: float = 4/3
    registered_entities: dict[dict] = {}
    registered_mesh: dict[dict] = {}
    registered_material: dict[dict] = {}

    @classmethod
    def Create(
        cls,
        app
    ):
        window_size = app.window.GetSize()
        glViewport(0, 0, window_size[0], window_size[1])
        cls.aspect_ratio = window_size[0] / window_size[1]
        return cls


    @classmethod
    def StartFrame(
        cls
    ) -> None:
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glEnable(GL_DEPTH_TEST)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        # About Camera
        camera, transform = SceneManager.GetSceneCamera()
        view = Calculate_Camera_View(camera, transform)
        proj = Calculate_Camera_Proj(camera, cls.aspect_ratio)
        # About Mesh and Shader
        renderable_entities = SceneManager.GetRenderableEntities()
        for entity_id in renderable_entities:
            #
            # Try Register Entity
            cls._register_entity(entity_id)
            #
            # Get Mesh Info
            entity_mesh_id = cls.registered_entities[f'{entity_id}']['mesh_id']
            entity_mesh = cls.registered_mesh[f'{entity_mesh_id}']
            current_vao = entity_mesh['vao']
            current_counts = entity_mesh['counts']
            #
            # Update Shader Program
            model = Calculate_Entity_Model(SceneManager.GetEntityTransform(entity_id))
            entity_material_id = cls.registered_entities[f'{entity_id}']['material_id']
            entity_material = cls.registered_material[f'{entity_material_id}']
            glUseProgram(entity_material['program'])
            uniform_locs = entity_material['uniform_locs']
            if 'model' in uniform_locs:
                glUniformMatrix4fv(uniform_locs['model'], 1, GL_FALSE, model.astype('float32'))
            if 'view' in uniform_locs:
                glUniformMatrix4fv(uniform_locs['view'], 1, GL_FALSE, view.astype('float32'))
            if 'projection' in uniform_locs:
                glUniformMatrix4fv(uniform_locs['projection'], 1, GL_FALSE, proj.astype('float32'))
            #
            # Draw
            glBindVertexArray(current_vao)
            glDrawElements(GL_TRIANGLES, current_counts, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)

    @classmethod
    def EndFrame(
        cls
    ) -> None:
        for entity_info in cls.registered_entities.values():
            pass

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ):
        if event is WindowResizeEvent:
            width, height = event.UnPack()
            glViewport(0, 0, width, height)
            cls.aspect_ratio = width / height
        if any([
            event is NewComponentEvent,
            event is ComponentModifiedEvent
        ]):
            entity_id, comp = event.UnPack()
            if comp is MeshRenderer:
                if comp.visible:
                    cls._register_entity(entity_id)
                else:
                    cls._unregister_entity(entity_id)


    #
    # Renderer Resource Manage
    # ================================================================================================
    @classmethod
    def _register_entity(
        cls,
        entity_id: int
    ) -> None:
        if f"{entity_id}" in cls.registered_entities.keys():
            return
        #
        # Get mesh and material resource
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material = ResourceManager.GetMaterial(material_id)
        #
        # Upload mesh and material to Graphic-Device like GPU
        cls._register_mesh(mesh, mesh_id)
        cls._register_material(material, material_id)
        #
        # Record mesh and material id that prosibly used by entity
        cls.registered_entities[f'{entity_id}'] = {'mesh_id': mesh_id, 'material_id': material_id}

    @classmethod
    def _register_mesh(
        cls,
        mesh: Mesh,
        mesh_id: int
    ):
        if f"{mesh_id}" in cls.registered_mesh.keys():
            return
        cls.registered_mesh[f'{mesh_id}'] = {}
        current_mesh = cls.registered_mesh[f'{mesh_id}']
        vertices: np.ndarray = mesh.vertices
        uvs: np.ndarray = mesh.uvs
        normals: np.ndarray = mesh.normals
        ver_uv_nor = np.hstack((vertices, uvs, normals))
        indices: np.ndarray = mesh.indices
        # VBO
        # ---------------------
        current_mesh['vbo'] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, current_mesh['vbo'])
        glBufferData(GL_ARRAY_BUFFER, ver_uv_nor.nbytes, ver_uv_nor, GL_STATIC_DRAW)
        # VAO
        # ---------------------
        current_mesh['vao'] = glGenVertexArrays(1)
        glBindVertexArray(current_mesh['vao'])
        stride = (3+2+3) * sizeof(GLfloat)
        # 顶点位置属性 (location = 0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # 纹理坐标属性 (location = 1)
        tex_offset = 3 * sizeof(GLfloat)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(tex_offset))
        glEnableVertexAttribArray(1)
        # 法线属性 (location = 2)
        normal_offset = (3 + 2) * sizeof(GLfloat)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(normal_offset))
        glEnableVertexAttribArray(2)
        # EBO
        # ---------------------
        current_mesh['ebo'] = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, current_mesh['ebo'])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        # Counts
        current_mesh['counts'] = indices.size
        # print(current_mesh['counts'])

    @classmethod
    def _register_material(
        cls,
        material: Material,
        material_id: int
    ) -> None:
        if f"{material_id}" in cls.registered_material.keys():
            return
        # 编译顶点着色器
        vs_src = material.vs_src
        fs_src = material.fs_src
        uniforms = material.uniforms
        vertex_shader = glCreateShader(GL_VERTEX_SHADER)
        glShaderSource(vertex_shader, vs_src)
        glCompileShader(vertex_shader)
        # 检查编译状态
        success = glGetShaderiv(vertex_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(vertex_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            raise RuntimeError(f"Vertex shader compilation failed:\n{log}")
        # 编译片段着色器
        fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
        glShaderSource(fragment_shader, fs_src)
        glCompileShader(fragment_shader)
        success = glGetShaderiv(fragment_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(fragment_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Fragment shader compilation failed:\n{log}")
        # 创建着色器程序并链接
        program = glCreateProgram()
        glAttachShader(program, vertex_shader)
        glAttachShader(program, fragment_shader)
        glLinkProgram(program)
        # 检查链接状态
        success = glGetProgramiv(program, GL_LINK_STATUS)
        if not success:
            log = glGetProgramInfoLog(program).decode('utf-8')
            glDeleteProgram(program)
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Shader program linking failed:\n{log}")
        # 着色器对象已链接到程序，可以删除
        glDeleteShader(vertex_shader)
        glDeleteShader(fragment_shader)
        # 获取所有 uniform 的位置 (location)
        uniform_locs = {}
        for name, typ in uniforms.items():
            loc = glGetUniformLocation(program, name)
            if loc != -1:
                uniform_locs[name] = loc
        cls.registered_material[f'{material_id}'] = {
            'program': program,
            'uniforms': uniforms,        # 保留类型信息以备扩展
            'uniform_locs': uniform_locs
        }

    @classmethod
    def _unregister_entity(
        cls,
        entity_id: int
    ) -> None:
        del cls.registered_entities[f"{entity_id}"]

    @classmethod
    def _unregister_mesh(
        cls,
        mesh_id: int
    ) -> None:
        del cls.registered_mesh[f"{mesh_id}"]

    @classmethod
    def _unregister_material(
        cls,
        material_id: int
    ) -> None:
        del cls.registered_material[f"{material_id}"]
