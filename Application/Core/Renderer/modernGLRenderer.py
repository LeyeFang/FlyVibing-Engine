from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application

from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.SceneEvent import *
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Math.RendererMath import (
    calculate_view_matrix,
    calculate_projection_matrix,
    calculate_entity_model
)

import numpy as np
import moderngl as mgl
from dataclasses import dataclass


class modernGLRenderer(Renderer, RenderResourceManger):

    ctx: mgl.Context = None

    # Cached camera matrices (only recalculated on SceneCameraUpdateEvent)
    _cached_view: np.ndarray = None
    _cached_proj: np.ndarray = None

    # Deferred resize (GL calls only in render thread via StartFrame)
    _pending_resize: tuple = None  # (width, height) or None

    # ============================================================
    # 独立的资源注册表（不与 openglRenderer 共享）
    # ============================================================
    @dataclass
    class entity_data_struct:
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int
        vao: object = None       # mgl.VertexArray — 该 entity 专属的 VAO

    @dataclass
    class mesh_data_struct:
        vbo: object = None       # mgl.Buffer — 顶点缓冲
        ibo: object = None       # mgl.Buffer — 索引缓冲
        elements_count: int = 0
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        program: object = None   # mgl.Program
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        ref_count: int = 0
        # 子类 upload 后填充:
        #   modernGL → mgl.Texture 对象
        #   opengl   → GL uint (纹理 ID)
        gl_handle: any = None
        texture_unit: int = -1   # 分配的纹理单元

    registered_entities: dict[str, entity_data_struct] = {}
    registered_meshes: dict[str, mesh_data_struct] = {}
    registered_shaders: dict[str, shader_data_struct] = {}
    registered_textures: dict[str, texture_data_struct] = {}

    # ============================================================
    # Lifecycle
    # ============================================================
    @classmethod
    def Create(
        cls,
        app: Application
    ) -> modernGLRenderer:
        """在渲染线程调用，GLFW 上下文已 current"""
        cls.ctx = mgl.create_context()
        print(f"[ModernGL] GPU Vendor : {cls.ctx.info['GL_VENDOR']}")
        print(f"[ModernGL] GPU Renderer: {cls.ctx.info['GL_RENDERER']}")
        print(f"[ModernGL] GL Version  : {cls.ctx.info['GL_VERSION']}")
        window_size = app.window.GetSize()
        cls.ctx.viewport = (0, 0, window_size[0], window_size[1])
        cls.aspect_ratio = window_size[0] / window_size[1]
        cls.ctx.enable(mgl.DEPTH_TEST)
        # 初始化相机矩阵缓存
        camera, transform = SceneManager.GetSceneCamera()
        cls._cached_view = calculate_view_matrix(camera, transform)
        cls._cached_proj = calculate_projection_matrix(camera, cls.aspect_ratio)
        return cls

    @classmethod
    def StartFrame(cls) -> None:
        # 处理延迟的 resize（确保在主线程的 GL 调用不会发生）
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            cls.ctx.viewport = (0, 0, w, h)
            cls._pending_resize = None
        cls.ctx.clear(0.2, 0.2, 0.2, 1.0)
        view = cls._cached_view
        proj = cls._cached_proj
        renderable_entities = SceneManager.GetRenderableEntities()
        for entity_id in renderable_entities:
            entity = cls.registered_entities[entity_id]
            entity_shader = cls.registered_shaders[entity.shader_id]
            program = entity_shader.program
            # 1. 先算并上传模型矩阵
            model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))
            program['model'].write(np.ascontiguousarray(model.astype('float32')).tobytes())
            program['view'].write(np.ascontiguousarray(view.astype('float32')).tobytes())
            program['projection'].write(np.ascontiguousarray(proj.astype('float32')).tobytes())
            # --- 绑定纹理 ---
            if entity.texture_id and entity.texture_id > 0:
                tex_data = cls.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle is not None:
                    tex_data.gl_handle.use(location=0)
                    try:
                        program['uTexture'] = 0
                    except KeyError:
                        pass  # shader 里没有 sampler2D
            # 2. 上传材料的其他 uniform，跳过已经传过的三个矩阵
            material = ResourceManager.GetMaterial(entity.material_id)
            for u_name, u_value in material.uniforms_data.items():
                if u_name in ('model', 'view', 'projection'):
                    continue
                try:
                    if isinstance(u_value, np.ndarray) and u_value.ndim == 2:
                        program[u_name].write(
                            np.ascontiguousarray(u_value.astype('float32')).tobytes()
                        )
                    else:
                        program[u_name] = u_value
                except KeyError:
                    pass  # uniform 被 shader 编译器优化掉了
            entity.vao.render(mgl.TRIANGLES)

    @classmethod
    def EndFrame(cls) -> None:
        pass

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        # 注意：OnEvent 在主线程执行，不可直接调用 GL 函数
        if event is WindowResizeEvent:
            width, height = event.UnPack()
            cls._pending_resize = (width, height)
            cls.aspect_ratio = width / height
            camera, transform = SceneManager.GetSceneCamera()
            cls._cached_proj = calculate_projection_matrix(camera, cls.aspect_ratio)

        if any([event is NewComponentEvent, event is ComponentModifiedEvent]):
            entity_id, comp = event.UnPack()
            if isinstance(comp, MeshRenderer):
                if comp.visible:
                    cls.register_entity(entity_id)
                else:
                    cls.unregister_entity(entity_id)

        if event is SceneCameraUpdateEvent:
            cls._camera_update_callback(event)

    # ============================================================
    # Event callback
    # ============================================================
    @classmethod
    def _camera_update_callback(
        cls,
        event: SceneCameraUpdateEvent
    ):
        """仅缓存矩阵，不碰任何 GL 调用（GL 上下文在渲染线程）"""
        camera, transform = SceneManager.GetSceneCamera()
        cls._cached_view = calculate_view_matrix(camera, transform)
        cls._cached_proj = calculate_projection_matrix(camera, cls.aspect_ratio)

    # ============================================================
    # 资源注册
    # ============================================================
    @classmethod
    def register_entity(
        cls,
        entity_id: int
    ) -> None:
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)
        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)
        mesh_data = cls.registered_meshes[mesh_id]
        shader_data = cls.registered_shaders[shader_id]
        # --- 注册纹理 ---
        if material.texture_id_list:
            tex_id = material.texture_id_list[0]  # 取第一张作为 diffuse
            texture = ResourceManager.GetTexture(tex_id)
            cls.register_texture(texture, tex_id)
        else:
            tex_id = 0
        program = shader_data.program
        # skip_errors=True: 自动跳过 shader 中不存在的 attribute（如被优化掉的 aNormal）
        vao = cls.ctx.vertex_array(
            program,
            [(mesh_data.vbo, '3f 2f 3f', 'aPos', 'aTexCoord', 'aNormal')],
            mesh_data.ibo,
            skip_errors=True,
        )
        cls.registered_entities[entity_id] = cls.entity_data_struct(
            shader_id=shader_id,
            texture_id=tex_id,
            mesh_id=mesh_id,
            material_id=material_id,
            vao=vao,
        )

    @classmethod
    def register_mesh(cls, mesh: Mesh, mesh_id: int) -> None:
        if mesh_id in cls.registered_meshes:
            cls.registered_meshes[mesh_id].ref_count += 1
            return
        vertices = mesh.vertices   # (N, 3) float32
        uvs = mesh.uvs             # (N, 2) float32
        normals = mesh.normals     # (N, 3) float32
        indices = mesh.indices     # (M,) uint32
        # 交错排列: pos(3) + uv(2) + normal(3) = 8 floats per vertex
        ver_uv_nor = np.hstack((vertices, uvs, normals)).astype('float32')
        vbo = cls.ctx.buffer(ver_uv_nor.tobytes())
        ibo = cls.ctx.buffer(indices.astype('uint32').tobytes())
        cls.registered_meshes[mesh_id] = cls.mesh_data_struct(
            vbo=vbo,
            ibo=ibo,
            elements_count=indices.size,
            ref_count=1,
        )

    @classmethod
    def register_shader(cls, shader: Shader, shader_id: int) -> None:
        if shader_id in cls.registered_shaders:
            cls.registered_shaders[shader_id].ref_count += 1
            return
        # ModernGL 一行编译+链接，自动检测编译错误
        try:
            program = cls.ctx.program(
                vertex_shader=shader.vs_src,
                fragment_shader=shader.fs_src,
            )
        except mgl.Error as e:
            raise RuntimeError(f"Shader compilation failed (id={shader_id}):\n{e}")
        cls.registered_shaders[shader_id] = cls.shader_data_struct(
            program=program,
            ref_count=1,
        )

    @classmethod
    def register_texture(
        cls,
        texture: Texture,
        texture_id: int
    ) -> None:
        """将 CPU 纹理上传到 GPU（ModernGL）"""
        if texture_id in cls.registered_textures:
            cls.registered_textures[texture_id].ref_count += 1
            return
        # 确定内部格式和数据类型
        if texture.channels == 1:
            fmt = 'R8'
        elif texture.channels == 3:
            fmt = 'RGB8'
        elif texture.channels == 4:
            fmt = 'RGBA8'
        else:
            raise ValueError(f"不支持的纹理通道数: {texture.channels}")
        # 创建 ModernGL 纹理
        mgl_tex = cls.ctx.texture(
            (texture.width, texture.height),
            texture.channels,
            texture.image_data.tobytes(),
            dtype='f1',  # 8-bit unsigned normalized
        )
        mgl_tex.filter = (mgl.LINEAR_MIPMAP_LINEAR, mgl.LINEAR)
        mgl_tex.build_mipmaps()
        cls.registered_textures[texture_id] = cls.texture_data_struct(
            ref_count=1,
            gl_handle=mgl_tex,
            texture_unit=-1,
        )

    @classmethod
    def unregister_entity(
        cls,
        entity_id: int
    ) -> None:
        if entity_id not in cls.registered_entities:
            return
        entity = cls.registered_entities[entity_id]
        # 释放 VAO
        if entity.vao is not None:
            entity.vao.release()
        # 减少引用计数
        cls._decref_mesh(entity.mesh_id)
        cls._decref_shader(entity.shader_id)
        cls._decref_texture(entity.texture_id)
        del cls.registered_entities[entity_id]

    @classmethod
    def unregister_mesh(
        cls,
        mesh_id: int
    ) -> None:
        cls._decref_mesh(mesh_id)

    @classmethod
    def unregister_shader(
        cls,
        shader_id: int
    ) -> None:
        cls._decref_shader(shader_id)

    @classmethod
    def unregister_texture(
        cls,
        texture_id: int
    ) -> None:
        cls._decref_texture(texture_id)

    # ============================================================
    # 引用计数辅助
    # ============================================================
    @classmethod
    def _decref_mesh(
        cls,
        mesh_id: int
    ) -> None:
        if mesh_id not in cls.registered_meshes:
            return
        data = cls.registered_meshes[mesh_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.vbo is not None:
                data.vbo.release()
            if data.ibo is not None:
                data.ibo.release()
            del cls.registered_meshes[mesh_id]

    @classmethod
    def _decref_shader(
        cls,
        shader_id: int
    ) -> None:
        if shader_id not in cls.registered_shaders:
            return
        data = cls.registered_shaders[shader_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.program is not None:
                data.program.release()
            del cls.registered_shaders[shader_id]

    @classmethod
    def _decref_texture(
        cls,
        texture_id: int
    ) -> None:
        if texture_id not in cls.registered_textures:
            return
        data = cls.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.gl_handle is not None:
                data.gl_handle.release()
            del cls.registered_textures[texture_id]
