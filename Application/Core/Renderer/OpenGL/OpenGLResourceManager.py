"""
OpenGLResourceManager — PyOpenGL GPU 资源管理器 (Mesh / Shader / Texture / Entity)。

职责:
  - GPU 资源数据结构 (entity / mesh / shader / texture)
  - 资源注册表 (引用计数管理)
  - register_* : CPU 数据 → GPU 资源上传
  - unregister_* : GPU 资源降引用与销毁

依赖:
  - OpenGLCore : 提供 GL 状态
  - ResourceManager (CPU 端): 提供资源数据
  - SceneManager: 提供实体→资源映射

GPU 资源句柄对应关系:
  - VBO / EBO       → GLuint
  - VAO              → GLuint
  - Shader Program   → GLuint
  - Texture          → GLuint

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import ctypes
import numpy as np
from dataclasses import dataclass, field
from typing import Callable
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils
from Application.Core.Renderer.VertexLayout import VertexLayout, STD_LAYOUT
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture
from Application.Core.Scene.SceneManager import SceneManager


class OpenGLResourceManager:
    """PyOpenGL GPU 资源管理器 — Mesh/Shader/Texture/Entity 的注册与生命周期。"""

    # ════════════════════════════════════════════════════════════
    # GPU 资源数据结构
    # ════════════════════════════════════════════════════════════

    @dataclass
    class entity_data_struct:
        """PyOpenGL 实体资源记录。

        Attributes:
            shader_id   : 着色器资源 ID
            texture_id  : 纹理资源 ID (0 表示无纹理)
            mesh_id     : 网格资源 ID
            material_id : 材质资源 ID
            vao         : GLuint — 顶点数组对象 (绑定 VBO/EBO + 顶点属性)
        """
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int
        vao: int = 0

    @dataclass
    class mesh_data_struct:
        """PyOpenGL 网格资源记录。

        Attributes:
            vbo            : GLuint — 顶点缓冲 (交错: pos+uv+normal)
            ebo            : GLuint — 索引缓冲
            elements_count : 索引数量 (三角形数 × 3)
            layout         : VertexLayout — 顶点格式描述符
            ref_count      : 引用计数
        """
        vbo: int = 0
        ebo: int = 0
        elements_count: int = 0
        layout: 'VertexLayout' = None
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        """PyOpenGL 着色器资源记录。

        Attributes:
            program       : GLuint — 编译链接的着色器程序
            uniforms_loc  : uniform 名称 → location 的缓存字典
            uniforms_type : uniform 名称 → GLSL 类型 ('float'/'mat4'/'int'/...) 的缓存字典
            ref_count     : 引用计数
        """
        program: int = 0
        uniforms_loc: dict = None
        uniforms_type: dict = None
        ref_count: int = 0

        def __post_init__(self):
            if self.uniforms_loc is None:
                self.uniforms_loc = {}
            if self.uniforms_type is None:
                self.uniforms_type = {}

    @dataclass
    class texture_data_struct:
        """PyOpenGL 纹理资源记录。

        Attributes:
            ref_count    : 引用计数
            gl_handle    : GLuint — GPU 纹理对象
            texture_unit : 分配的纹理单元编号 (-1 表示未分配)
        """
        ref_count: int = 0
        gl_handle: int = 0
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

        创建的 VAO 绑定 mesh 的 VBO/EBO 并配置顶点属性布局。
        后续渲染时只需: glBindVertexArray(vao) → glUseProgram(program) → glDrawElements(...)

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

        # ── 创建 VAO，绑定 VBO/EBO 并设置顶点属性 ──
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)

        # 绑定 VBO 并设置顶点属性
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, mesh_data.vbo)

        # ★ 顶点格式: 优先使用 mesh.layout, 回退到旧硬编码常量
        layout = getattr(mesh_data, 'layout', None) or STD_LAYOUT.ENTITY_POS_UV_NORMAL
        VertexLayout.check_shader_consistency(
            layout, shader.vs_src, f"entity shader '{shader_id}'")
        for loc, size, stride, offset in layout.to_gl_attribs():
            gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                     ctypes.c_void_p(offset))
            gl.glEnableVertexAttribArray(loc)

        # 绑定 EBO
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, mesh_data.ebo)

        # 解绑 VAO (可选，但推荐以避免误修改)
        gl.glBindVertexArray(0)

        cls.registered_entities[entity_id] = cls.entity_data_struct(
            shader_id=shader_id,
            texture_id=tex_id,
            mesh_id=mesh_id,
            material_id=material_id,
            vao=vao,
        )

    @classmethod
    def register_mesh(cls, mesh: Mesh, mesh_id: int) -> None:
        """上传网格数据到 GPU — 创建 VBO (交错顶点) + EBO (索引)。

        交错顶点格式 (每顶点 8 个 float):
          [px, py, pz,  u, v,  nx, ny, nz]

        Args:
            mesh    : CPU 端 Mesh 资源
            mesh_id : 网格资源 ID
        """
        if mesh_id in cls.registered_meshes:
            cls.registered_meshes[mesh_id].ref_count += 1
            return

        # ── 构建交错顶点数组 ──
        ver_uv_nor = np.hstack((
            mesh.vertices, mesh.uvs, mesh.normals
        )).astype('float32')
        indices = mesh.indices.astype('uint32')

        # ── VBO ──
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, ver_uv_nor.nbytes,
                        ver_uv_nor.tobytes(), gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

        # ── EBO ──
        ebo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                        indices.tobytes(), gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)

        cls.registered_meshes[mesh_id] = cls.mesh_data_struct(
            vbo=vbo,
            ebo=ebo,
            elements_count=int(indices.size),
            layout=mesh.layout or STD_LAYOUT.ENTITY_POS_UV_NORMAL,
            ref_count=1,
        )

    @classmethod
    def register_shader(cls, shader: Shader, shader_id: int) -> None:
        """编译并链接着色器程序。

        Args:
            shader    : CPU 端 Shader 资源 (含 vs_src / fs_src)
            shader_id : 着色器资源 ID

        Raises:
            RuntimeError: 编译/链接失败
        """
        if shader_id in cls.registered_shaders:
            cls.registered_shaders[shader_id].ref_count += 1
            return

        program = OpenGLUtils.compile_program(shader.vs_src, shader.fs_src)

        # ── 预查询所有 uniform location (PyOpenGL 兼容) ──
        uniforms_loc: dict[str, int] = {}
        num_uniforms = gl.glGetProgramiv(program, gl.GL_ACTIVE_UNIFORMS)
        for i in range(num_uniforms):
            try:
                # PyOpenGL 不同版本返回: (name, size, type) 或需传 bufSize
                result = gl.glGetActiveUniform(program, i, 256)
                if result and len(result) >= 1:
                    name = result[0] if isinstance(result, tuple) else result
                    if isinstance(name, bytes):
                        name = name.decode()
                    loc = gl.glGetUniformLocation(program, name)
                    if loc >= 0:
                        uniforms_loc[name] = loc
            except Exception:
                continue

        cls.registered_shaders[shader_id] = cls.shader_data_struct(
            program=program,
            uniforms_loc=uniforms_loc,
            uniforms_type=shader.uniforms_name_type.copy(),
            ref_count=1,
        )

    @classmethod
    def register_texture(cls, texture: Texture, texture_id: int) -> None:
        """上传纹理数据到 GPU。

        支持:
          - 灰度 (1 通道) → GL_R8
          - RGB  (3 通道) → GL_RGB8
          - RGBA (4 通道) → GL_RGBA8

        Args:
            texture    : CPU 端 Texture 资源
            texture_id : 纹理资源 ID

        Raises:
            ValueError: 不支持的通道数
        """
        if texture_id in cls.registered_textures:
            cls.registered_textures[texture_id].ref_count += 1
            return

        _CHANNEL_FORMAT = {
            1: (gl.GL_R8, gl.GL_RED),
            3: (gl.GL_RGB8, gl.GL_RGB),
            4: (gl.GL_RGBA8, gl.GL_RGBA),
        }
        if texture.channels not in _CHANNEL_FORMAT:
            raise ValueError(f"不支持的纹理通道数: {texture.channels}")

        internal_format, data_format = _CHANNEL_FORMAT[texture.channels]

        # ── 创建纹理 ──
        gl_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, gl_tex)

        # 上传像素数据
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, internal_format,
            texture.width, texture.height, 0,
            data_format, gl.GL_UNSIGNED_BYTE,
            texture.image_data.tobytes()
        )

        # 设置过滤 & mipmap
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        cls.registered_textures[texture_id] = cls.texture_data_struct(
            ref_count=1,
            gl_handle=gl_tex,
            texture_unit=-1,
        )

    # ════════════════════════════════════════════════════════════
    # Uniform 辅助 — 薄封装，委托到 OpenGLUtils
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_uniform_location(cls, shader_id: int, name: str) -> int:
        """获取 uniform location (带缓存，支持懒查询)。

        委托到 OpenGLUtils.get_uniform_location，传入 cls.registered_shaders。
        """
        return OpenGLUtils.get_uniform_location(cls.registered_shaders, shader_id, name)

    @classmethod
    def set_uniform_mat4(cls, shader_id: int, name: str, matrix: np.ndarray) -> None:
        """Set a mat4 uniform — 委托到 OpenGLUtils。"""
        OpenGLUtils.set_uniform_mat4(cls.registered_shaders, shader_id, name, matrix)

    @classmethod
    def set_uniform_float(cls, shader_id: int, name: str, value: float) -> None:
        """设置 float uniform — 委托到 OpenGLUtils。"""
        OpenGLUtils.set_uniform_float(cls.registered_shaders, shader_id, name, value)

    @classmethod
    def set_uniform_int(cls, shader_id: int, name: str, value: int) -> None:
        """设置 int / sampler2D uniform — 委托到 OpenGLUtils。"""
        OpenGLUtils.set_uniform_int(cls.registered_shaders, shader_id, name, value)

    @classmethod
    def set_uniform_value(cls, shader_id: int, name: str, value) -> None:
        """根据 GLSL 类型自动选择 glUniform* 调用 — 委托到 OpenGLUtils。"""
        OpenGLUtils.set_uniform_value(cls.registered_shaders, shader_id, name, value)

    # ════════════════════════════════════════════════════════════
    # 资源卸载
    # ════════════════════════════════════════════════════════════

    @classmethod
    def unregister_entity(cls, entity_id: int) -> None:
        """从 GPU 卸载实体。"""
        if entity_id not in cls.registered_entities:
            return
        entity = cls.registered_entities[entity_id]
        if entity.vao:
            gl.glDeleteVertexArrays(1, [entity.vao])
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
            if data.vbo:
                gl.glDeleteBuffers(1, [data.vbo])
            if data.ebo:
                gl.glDeleteBuffers(1, [data.ebo])
            del cls.registered_meshes[mesh_id]

    @classmethod
    def _decref_shader(cls, shader_id: int) -> None:
        if shader_id not in cls.registered_shaders:
            return
        data = cls.registered_shaders[shader_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.program:
                gl.glDeleteProgram(data.program)
            del cls.registered_shaders[shader_id]

    @classmethod
    def _decref_texture(cls, texture_id: int) -> None:
        if texture_id not in cls.registered_textures:
            return
        data = cls.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.gl_handle:
                gl.glDeleteTextures(1, [data.gl_handle])
            del cls.registered_textures[texture_id]

    # ════════════════════════════════════════════════════════════
    # 批量资源清理 (Shutdown 时调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _unregister_all_entities(cls) -> None:
        """卸载所有已注册实体的 GPU 资源 (VAO)，级联降引用 mesh/shader/texture。"""
        for entity_id in list(cls.registered_entities.keys()):
            cls.unregister_entity(entity_id)

    @classmethod
    def _unregister_all_overlays(cls) -> None:
        """卸载所有 overlay 的 GPU 资源 (VAO/VBO/EBO/program/texture)。"""
        for key in list(cls._overlay_gpu_resources.keys()):
            cls.unregister_overlay_drawable(key)

    # ════════════════════════════════════════════════════════════
    # Editor Overlay 资源管理 (GPU 端实现)
    # ════════════════════════════════════════════════════════════
    #
    # 与 entity 资源管理解耦: overlay 不经过 ResourceManager/SceneManager，
    # 由 Editor 层直接提供顶点数据和着色器源码，渲染器仅负责上传和绘制。
    #
    # 渲染器不知道 "Grid" 或 "Gizmo" 的存在 — 只看到带 key 的可绘制对象。

    @dataclass
    class overlay_gpu_data:
        """Overlay 在 GPU 端的资源记录 (OpenGL 专用)。"""
        vao: int = 0
        vbo: int = 0
        ebo: int = 0
        program: int = 0
        texture: int = 0
        elements_count: int = 0
        draw_mode: int = 0
        depth_test: bool = True
        blend: bool = False
        cull_face: bool = False
        line_width: float = 1.0
        uniforms_setup: Callable[[int], None] = field(default=lambda p: None)
        uniforms: dict = None  # 声明式 uniform (后端无关)
        layout: 'VertexLayout' = None  # ★ 顶点格式描述符
        render_layer: int = 0
        ignore_scene_matrices: bool = False
        model_matrix_cb: Callable[[int, int], 'np.ndarray'] = None
        texture_uniform: str = ''
        pick_type: int = 0
        pick_id: int = 0
        model_is_ndc: bool = False  # True=model_matrix_cb 返回完整 MVP (如 TransformGizmo)
    # GPU 端 overlay 注册表: key → overlay_gpu_data
    _overlay_gpu_resources: dict[str, 'overlay_gpu_data'] = {}
    _DRAW_MODE_MAP: dict[str, int] = {
        'lines': gl.GL_LINES,
        'triangles': gl.GL_TRIANGLES,
    }

    @classmethod
    def register_overlay_drawable(
        cls,
        overlay: 'RenderResourceManger.overlay_drawable_struct'
    ) -> None:
        """注册编辑器叠加层可绘制对象 — 编译 shader, 上传 VBO/EBO/纹理, 创建 VAO。
        Args:
            overlay: 来自 Editor 层的纯数据载体 (无 GL 依赖)
        """
        if overlay.key in cls._overlay_gpu_resources:
            return
        # ── 编译着色器 ──
        program = OpenGLUtils.compile_program(overlay.vs_src, overlay.fs_src)
        # ── VAO ──
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        # ── VBO (通用顶点布局) ──
        vbo = gl.glGenBuffers(1)
        verts = np.ascontiguousarray(overlay.vertices.astype('float32'))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(
            gl.GL_ARRAY_BUFFER,
            verts.nbytes,
            verts.tobytes(),
            gl.GL_STATIC_DRAW)

        # ★ 顶点格式: 优先使用 overlay.layout, 回退到 overlay.vertex_attrs
        ol_layout = overlay.layout
        if ol_layout is not None:
            VertexLayout.check_shader_consistency(
                ol_layout, overlay.vs_src, f"overlay '{overlay.key}'")
            for loc, size, stride, offset in ol_layout.to_gl_attribs():
                gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                         ctypes.c_void_p(offset))
                gl.glEnableVertexAttribArray(loc)
        else:
            for loc, size, offset in overlay.vertex_attrs:
                gl.glVertexAttribPointer(
                    loc, size, gl.GL_FLOAT, gl.GL_FALSE,
                    overlay.vertex_stride, ctypes.c_void_p(offset))
                gl.glEnableVertexAttribArray(loc)
        # ── EBO ──
        ebo = gl.glGenBuffers(1)
        indices = np.ascontiguousarray(overlay.indices.astype('uint32'))
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        gl.glBufferData(
            gl.GL_ELEMENT_ARRAY_BUFFER,
            indices.nbytes,
            indices.tobytes(),
            gl.GL_STATIC_DRAW)
        gl.glBindVertexArray(0)
        # ── 纹理 (可选) ──
        texture = 0
        if overlay.texture_pixels is not None and overlay.texture_pixels.size > 0:
            texture = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            pixels = np.ascontiguousarray(overlay.texture_pixels)
            h, w = pixels.shape[:2]
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D,
                0,
                gl.GL_RGBA,
                w, h,
                0,
                gl.GL_RGBA,
                gl.GL_UNSIGNED_BYTE,
                pixels)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        draw_mode_gl = cls._DRAW_MODE_MAP.get(overlay.draw_mode, gl.GL_LINES)
        # ★ 顶点格式: 优先 overlay.layout, 回退从 vertex_attrs 构造
        ol_layout = overlay.layout
        if ol_layout is None and overlay.vertex_attrs is not None:
            ol_layout = VertexLayout(
                attributes=tuple(overlay.vertex_attrs),
                stride=overlay.vertex_stride,
            )
        cls._overlay_gpu_resources[overlay.key] = cls.overlay_gpu_data(
            vao=vao, vbo=vbo, ebo=ebo, program=program,
            texture=texture,
            elements_count=int(indices.size),
            draw_mode=draw_mode_gl,
            depth_test=overlay.depth_test,
            line_width=overlay.line_width,
            blend=overlay.blend,
            cull_face=overlay.cull_face,
            uniforms_setup=overlay.uniforms_setup,
            uniforms=getattr(overlay, 'uniforms', None),
            layout=ol_layout,
            render_layer=getattr(overlay, 'render_layer', 0),
            ignore_scene_matrices=overlay.ignore_scene_matrices,
            model_matrix_cb=overlay.model_matrix_cb,
            texture_uniform=overlay.texture_uniform,
            pick_type=overlay.pick_type,
            pick_id=overlay.pick_id,
            model_is_ndc=getattr(overlay, 'model_is_ndc', False),
        )

    @classmethod
    def unregister_overlay_drawable(cls, key: str) -> None:
        """取消注册并释放 overlay 的 GPU 资源 (含纹理)。"""
        gpu = cls._overlay_gpu_resources.pop(key, None)
        if gpu is None:
            return
        if gpu.texture:
            gl.glDeleteTextures([gpu.texture])
        if gpu.vao:
            gl.glDeleteVertexArrays(1, [gpu.vao])
        if gpu.vbo:
            gl.glDeleteBuffers(1, [gpu.vbo])
        if gpu.ebo:
            gl.glDeleteBuffers(1, [gpu.ebo])
        if gpu.program:
            gl.glDeleteProgram(gpu.program)
