"""
ModernGLResourceManager — ModernGL GPU 资源管理器 (Mesh / Shader / Texture / Entity)。

职责:
  - GPU 资源数据结构 (entity / mesh / shader / texture)
  - 资源注册表 (引用计数管理)
  - register_* : CPU 数据 → GPU 资源上传
  - unregister_* : GPU 资源降引用与销毁

依赖:
  - ModernGLCore : 提供 moderngl.Context
  - ResourceManager (CPU 端): 提供资源数据
  - SceneManager: 提供实体→资源映射

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import numpy as np
import moderngl as mgl
from dataclasses import dataclass

from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.ModernGL.ModernGLCore import ModernGLCore


class ModernGLResourceManager:
    """ModernGL GPU 资源管理器 — Mesh/Shader/Texture/Entity 的注册与生命周期。"""

    # ════════════════════════════════════════════════════════════
    # GPU 资源数据结构
    # ════════════════════════════════════════════════════════════

    @dataclass
    class entity_data_struct:
        """ModernGL 实体资源记录。

        Attributes:
            shader_id   : 着色器资源 ID
            texture_id  : 纹理资源 ID (0 表示无纹理)
            mesh_id     : 网格资源 ID
            material_id : 材质资源 ID
            vao         : mgl.VertexArray (绑定了 VBO + IBO + Shader)
        """
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int
        vao: object = None

    @dataclass
    class mesh_data_struct:
        """ModernGL 网格资源记录。

        Attributes:
            vbo            : mgl.Buffer — 顶点缓冲 (交错: pos+uv+normal)
            ibo            : mgl.Buffer — 索引缓冲
            elements_count : 索引数量 (三角形数 × 3)
            ref_count      : 引用计数
        """
        vbo: object = None
        ibo: object = None
        elements_count: int = 0
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        """ModernGL 着色器资源记录。

        Attributes:
            program   : mgl.Program — 编译链接的着色器程序
            ref_count : 引用计数
        """
        program: object = None
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        """ModernGL 纹理资源记录。

        Attributes:
            ref_count    : 引用计数
            gl_handle    : mgl.Texture — GPU 纹理对象
            texture_unit : 分配的纹理单元编号 (-1 表示未分配)
        """
        ref_count: int = 0
        gl_handle: object = None
        texture_unit: int = -1

    # ════════════════════════════════════════════════════════════
    # 资源注册表 (key 为资源 ID)
    # ════════════════════════════════════════════════════════════

    registered_entities: dict[str, entity_data_struct] = {}
    registered_meshes: dict[str, mesh_data_struct] = {}
    registered_shaders: dict[str, shader_data_struct] = {}
    registered_textures: dict[str, texture_data_struct] = {}

    # ════════════════════════════════════════════════════════════
    # 资源注册
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_entity(cls, entity_id: int) -> None:
        """注册可渲染实体到 GPU — 级联注册 Mesh/Shader/Texture，创建 VAO。

        Args:
            entity_id: 实体 ID
        """
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)

        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)

        if material.texture_id_list:
            tex_id = material.texture_id_list[0]
            texture = ResourceManager.GetTexture(tex_id)
            cls.register_texture(texture, tex_id)
        else:
            tex_id = 0

        program = cls.registered_shaders[shader_id].program
        mesh_data = cls.registered_meshes[mesh_id]

        vao = ModernGLCore.ctx.vertex_array(
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
        """上传网格数据到 GPU — 创建 VBO (交错顶点) + IBO (索引)。

        交错顶点格式 (每顶点 8 个 float):
          [px, py, pz,  u, v,  nx, ny, nz]

        Args:
            mesh    : CPU 端 Mesh 资源
            mesh_id : 网格资源 ID
        """
        if mesh_id in cls.registered_meshes:
            cls.registered_meshes[mesh_id].ref_count += 1
            return

        ver_uv_nor = np.hstack((
            mesh.vertices, mesh.uvs, mesh.normals
        )).astype('float32')
        indices = mesh.indices.astype('uint32')

        vbo = ModernGLCore.ctx.buffer(ver_uv_nor.tobytes())
        ibo = ModernGLCore.ctx.buffer(indices.tobytes())

        cls.registered_meshes[mesh_id] = cls.mesh_data_struct(
            vbo=vbo,
            ibo=ibo,
            elements_count=int(indices.size),
            ref_count=1,
        )

    @classmethod
    def register_shader(cls, shader: Shader, shader_id: int) -> None:
        """编译并链接着色器程序。

        Args:
            shader    : CPU 端 Shader 资源
            shader_id : 着色器资源 ID

        Raises:
            RuntimeError: 编译/链接失败
        """
        if shader_id in cls.registered_shaders:
            cls.registered_shaders[shader_id].ref_count += 1
            return

        try:
            program = ModernGLCore.ctx.program(
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
    def register_texture(cls, texture: Texture, texture_id: int) -> None:
        """上传纹理数据到 GPU。

        Args:
            texture    : CPU 端 Texture 资源
            texture_id : 纹理资源 ID

        Raises:
            ValueError: 不支持的通道数
        """
        if texture_id in cls.registered_textures:
            cls.registered_textures[texture_id].ref_count += 1
            return

        _CHANNEL_FORMAT = {1: 'R8', 3: 'RGB8', 4: 'RGBA8'}
        if texture.channels not in _CHANNEL_FORMAT:
            raise ValueError(f"不支持的纹理通道数: {texture.channels}")

        mgl_tex = ModernGLCore.ctx.texture(
            (texture.width, texture.height),
            texture.channels,
            texture.image_data.tobytes(),
            dtype='f1',
        )
        mgl_tex.filter = (mgl.LINEAR_MIPMAP_LINEAR, mgl.LINEAR)
        mgl_tex.build_mipmaps()

        cls.registered_textures[texture_id] = cls.texture_data_struct(
            ref_count=1,
            gl_handle=mgl_tex,
            texture_unit=-1,
        )

    # ════════════════════════════════════════════════════════════
    # 资源卸载
    # ════════════════════════════════════════════════════════════

    @classmethod
    def unregister_entity(cls, entity_id: int) -> None:
        """从 GPU 卸载实体。"""
        if entity_id not in cls.registered_entities:
            return
        entity = cls.registered_entities[entity_id]
        if entity.vao is not None:
            entity.vao.release()
        cls._decref_mesh(entity.mesh_id)
        cls._decref_shader(entity.shader_id)
        cls._decref_texture(entity.texture_id)
        del cls.registered_entities[entity_id]

    @classmethod
    def unregister_mesh(cls, mesh_id: int) -> None:
        cls._decref_mesh(mesh_id)

    @classmethod
    def unregister_shader(cls, shader_id: int) -> None:
        cls._decref_shader(shader_id)

    @classmethod
    def unregister_texture(cls, texture_id: int) -> None:
        cls._decref_texture(texture_id)

    # ════════════════════════════════════════════════════════════
    # 引用计数辅助
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _decref_mesh(cls, mesh_id: int) -> None:
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
    def _decref_shader(cls, shader_id: int) -> None:
        if shader_id not in cls.registered_shaders:
            return
        data = cls.registered_shaders[shader_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.program is not None:
                data.program.release()
            del cls.registered_shaders[shader_id]

    @classmethod
    def _decref_texture(cls, texture_id: int) -> None:
        if texture_id not in cls.registered_textures:
            return
        data = cls.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.gl_handle is not None:
                data.gl_handle.release()
            del cls.registered_textures[texture_id]
