import numpy as np
from OpenGL.GL import *

# Event
from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowResizeEvent
from Application.Events.SceneEvent import NewComponentEvent, ComponentModifiedEvent
# Resource
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture
# Scene
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import *
# Renderer
from Application.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Renderer._renderer_math_utils import (
    Calculate_Camera_Proj,
    Calculate_Camera_View,
    Calculate_Entity_Model
)


class openglRenderer(Renderer, RenderResourceManger):

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
            cls.register_entity(entity_id)
            #
            # Get Mesh Info
            entity: RenderResourceManger.entity_data_struct = cls.registered_entities[f'{entity_id}']
            entity_mesh_id = entity.mesh_id
            entity_mesh: RenderResourceManger.mesh_data_struct = cls.registered_meshes[f'{entity_mesh_id}']
            current_vao = entity_mesh.vao
            current_counts = entity_mesh.elements_count
            #
            # Update Shader Program
            cls.update_uniform(
                entity_id=entity_id,
                view=view,
                proj=proj)
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
            if isinstance(comp, MeshRenderer):
                if comp.visible:
                    cls.register_entity(entity_id)
                else:
                    cls.unregister_entity(entity_id)

    @classmethod
    def update_uniform(
        cls,
        entity_id: int,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        model = Calculate_Entity_Model(SceneManager.GetEntityTransform(entity_id))
        entity: RenderResourceManger.entity_data_struct = cls.registered_entities[f"{entity_id}"]
        entity_material_id = entity.material_id
        material = ResourceManager.GetMaterial(entity_material_id)
        uniforms_data = material.uniforms_data
        entity_shader_id = entity.shader_id
        entity_shader: RenderResourceManger.shader_data_struct = cls.registered_shaders[f'{entity_shader_id}']
        glUseProgram(entity_shader.program)
        for (u_name, u_value), u_type in zip(uniforms_data.items(), entity_shader.uniforms_type):
            loc = entity_shader.uniforms_loc[u_name]
            if u_name == 'model':
                glUniformMatrix4fv(loc, 1, GL_FALSE, model.astype('float32'))
            elif u_name == 'view':
                glUniformMatrix4fv(loc, 1, GL_FALSE, view.astype('float32'))
            elif u_name == 'projection':
                glUniformMatrix4fv(loc, 1, GL_FALSE, proj.astype('float32'))
            else:
                if u_type == 'mat4':
                    glUniformMatrix4fv(loc, 1, GL_FALSE, u_value)
                if u_type == 'float':
                    glUniform1f(loc, u_value)
                if u_type == 'double':
                    glUniform1d(loc, u_value)

    #
    # Renderer Resource Manage
    # ================================================================================================
    @classmethod
    def register_entity(
        cls,
        entity_id: int
    ) -> None:
        #
        # Get mesh and material resource
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)
        # texture_id_list = material.texture_id_list
        # texture = ResourceManager.GetTexture(texture_id_list)
        #
        # Record mesh and material id that prosibly used by entity
        cls.registered_entities[f'{entity_id}'] = cls.entity_data_struct(
            shader_id=shader_id,
            texture_id=0,
            mesh_id=mesh_id,
            material_id=material_id)
        #
        # Upload mesh and material to Graphic-Device like GPU
        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)

    @classmethod
    def register_mesh(
        cls,
        mesh: Mesh,
        mesh_id: int
    ):
        if f"{mesh_id}" in cls.registered_meshes.keys():
            cls.registered_meshes[f"{mesh_id}"].ref_count += 1
            return
        vertices: np.ndarray = mesh.vertices
        uvs: np.ndarray = mesh.uvs
        normals: np.ndarray = mesh.normals
        ver_uv_nor = np.hstack((vertices, uvs, normals))
        indices: np.ndarray = mesh.indices
        # VBO
        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, ver_uv_nor.nbytes, ver_uv_nor, GL_STATIC_DRAW)
        # VAO
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)
        stride = (3+2+3) * sizeof(GLfloat)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))  # 顶点位置属性 (location = 0)
        glEnableVertexAttribArray(0)
        tex_offset = 3 * sizeof(GLfloat)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(tex_offset))  # 纹理坐标属性 (location = 1)
        glEnableVertexAttribArray(1)
        normal_offset = (3 + 2) * sizeof(GLfloat)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(normal_offset))  # 法线属性 (location = 2)
        glEnableVertexAttribArray(2)
        # EBO
        ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        # New Mesh
        cls.registered_meshes[f'{mesh_id}'] = cls.mesh_data_struct(
            vbo,
            vao,
            ebo,
            indices.size
        )

    @classmethod
    def register_shader(
        cls,
        shader: Shader,
        shader_id: int
    ) -> None:
        if f"{shader_id}" in cls.registered_shaders.keys():
            cls.registered_shaders[f"{shader_id}"].ref_count += 1
            return
        # 编译顶点着色器
        vs_src = shader.vs_src
        fs_src = shader.fs_src
        uniforms_name_type = shader.uniforms_name_type
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
        u_type_list = []
        u_loc_dict = {}
        for u_name, u_type in uniforms_name_type.items():
            u_type_list.append(u_type)
            loc = glGetUniformLocation(program, u_name)
            if loc != -1:
                u_loc_dict[u_name] = loc
        cls.registered_shaders[f'{shader_id}'] = cls.shader_data_struct(
            program,
            u_type_list,
            u_loc_dict
        )

    @classmethod
    def unregister_entity(
        cls,
        entity_id: int
    ) -> None:
        target_entity: dict = cls.registered_entities[f"entity_id"]
        target_entity["mesh_id"]["ref_count"] -= 1
        target_entity["shader_id"]["ref_count"] -= 1
        target_entity["texture_id"]["ref_count"] -= 1
        cls.unregister_mesh(target_entity["mesh_id"])
        cls.unregister_shader(target_entity["shader_id"])
        cls.unregister_texture(target_entity["texture_id"])
        del cls.registered_entities[f"{entity_id}"]

    @classmethod
    def unregister_mesh(
        cls,
        mesh_id: int
    ) -> None:
        target_mesh: RenderResourceManger.mesh_data_struct = cls.registered_meshes[f"{mesh_id}"]
        if target_mesh.ref_count == 0:
            glDeleteVertexArrays(1, [target_mesh.vao])
            glDeleteBuffers(1, [target_mesh.vbo])
            glDeleteBuffers(1, [target_mesh.ebo])
            del cls.registered_meshes[f"{mesh_id}"]
        else:
            pass

    @classmethod
    def unregister_shader(
        cls,
        shader_id: int
    ) -> None:
        if cls.registered_shaders[f"{shader_id}"]["ref_count"] == 0:
            del cls.registered_shaders[f"{shader_id}"]
        else:
            pass

    @classmethod
    def unregister_texture(
        cls,
        texture_id: int
    ) -> None:
        if cls.registered_textures[f"{texture_id}"]["ref_count"] == 0:
            del cls.registered_textures[f"{texture_id}"]
        else:
            pass
