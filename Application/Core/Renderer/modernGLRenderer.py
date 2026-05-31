"""
ModernGL 渲染器后端 — 基于 moderngl 的现代 OpenGL 渲染实现。

特性:
  - 使用 moderngl 直接管理 GL 对象 (无状态机，类型安全)
  - 相机矩阵缓存机制 (仅在 SceneCameraUpdateEvent 时重算)
  - 延迟 resize 处理 (GL 调用隔离到渲染线程)
  - 引用计数 GPU 资源管理

架构:
  modernGLRenderer 同时继承 Renderer (生命周期) 和 RenderResourceManger (资源管理)。
  所有方法均为 @classmethod，以单例模式运作。
"""

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
    calculate_entity_model
)
from Application.Editor.EditorCamera import EditorCamera

import numpy as np
import moderngl as mgl
from dataclasses import dataclass


class modernGLRenderer(Renderer, RenderResourceManger):
    """ModernGL 渲染器 — 基于 moderngl 库的 GPU 渲染后端。

    Class-level 状态:
        ctx              : moderngl 上下文，所有 GL 操作的入口
        _cached_view     : 缓存的视图矩阵 (避免每帧重算)
        _cached_proj     : 缓存的投影矩阵 (窗口 resize 时更新)
        _pending_resize  : 延迟的窗口尺寸变更 (渲染线程安全)
    """

    ctx: mgl.Context = None

    # ── 相机矩阵缓存 ──
    # 仅在 SceneCameraUpdateEvent 时重算，避免每帧不必要的矩阵运算
    _cached_view: np.ndarray = None   # 4x4 视图矩阵 (float32)
    _cached_proj: np.ndarray = None   # 4x4 投影矩阵 (float32)

    # ── 延迟 resize ──
    # GL 调用只能在渲染线程进行，OnEvent 在主线程收到 resize 后存入此变量，
    # StartFrame 中再真正调用 ctx.viewport
    _pending_resize: tuple = None     # (width, height) or None

    # ════════════════════════════════════════════════════════════
    # GPU 资源数据结构 (覆盖基类，使用 ModernGL 类型)
    # ════════════════════════════════════════════════════════════

    @dataclass
    class entity_data_struct:
        """ModernGL 实体资源记录。

        Attributes:
            shader_id   : 着色器资源 ID
            texture_id  : 纹理资源 ID (0 表示无纹理)
            mesh_id     : 网格资源 ID
            material_id : 材质资源 ID
            vao         : mgl.VertexArray — 该实体专属的 VAO (已绑定 VBO + IBO + Shader)
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
            elements_count : 索引数量 (三角形数 * 3)
            ref_count      : 引用计数 (多个 entity 可共享同一 mesh)
        """
        vbo: object = None
        ibo: object = None
        elements_count: int = 0
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        """ModernGL 着色器资源记录。

        Attributes:
            program   : mgl.Program — 已编译链接的着色器程序
            ref_count : 引用计数 (多个 entity 可共享同一 shader)
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
        gl_handle: any = None
        texture_unit: int = -1

    # ════════════════════════════════════════════════════════════
    # 资源注册表 (key 为资源 ID)
    # ════════════════════════════════════════════════════════════

    registered_entities: dict[str, entity_data_struct] = {}
    registered_meshes: dict[str, mesh_data_struct] = {}
    registered_shaders: dict[str, shader_data_struct] = {}
    registered_textures: dict[str, texture_data_struct] = {}

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls,
        app: Application
    ) -> modernGLRenderer:
        """初始化 ModernGL 渲染器。

        在渲染线程调用，此时 GLFW 上下文已通过 MakeContextCurrent 绑定。
        完成以下初始化:
          1. 创建 moderngl 上下文
          2. 打印 GPU 信息 (厂商/型号/GL版本)
          3. 设置视口和深度测试
          4. 从 SceneManager 获取主摄像机并缓存初始 view/proj 矩阵

        Args:
            app: Application 单例引用

        Returns:
            modernGLRenderer: 自身 (classmethod 返回类型标注用)
        """
        cls.ctx = mgl.create_context()
        print(f"[ModernGL] GPU Vendor : {cls.ctx.info['GL_VENDOR']}")
        print(f"[ModernGL] GPU Renderer: {cls.ctx.info['GL_RENDERER']}")
        print(f"[ModernGL] GL Version  : {cls.ctx.info['GL_VERSION']}")
        window_size = app.window.GetSize()
        cls.ctx.viewport = (0, 0, window_size[0], window_size[1])
        cls.aspect_ratio = window_size[0] / window_size[1]
        cls.ctx.enable(mgl.DEPTH_TEST)
        # 初始化相机矩阵缓存 (编辑器模式: 使用 EditorCamera)
        cam = EditorCamera.get_instance()
        cls._cached_view = cam.get_view_matrix()
        cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)
        return cls

    @classmethod
    def StartFrame(cls) -> None:
        """开始一帧渲染 — 清屏并绘制所有可渲染实体。

        执行流程:
          1. 处理延迟的窗口 resize (如有)
          2. 用深灰色清屏 (0.2, 0.2, 0.2)
          3. 遍历 SceneManager 返回的可渲染实体列表
          4. 对每个实体: 上传 model/view/proj 矩阵 → 绑定纹理 → 上传材质参数 → 绘制
        """
        # 处理延迟的 resize (GL 调用隔离到渲染线程)
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
            # ① 计算并上传 MVP 矩阵 (model → view → projection)
            model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))
            program['model'].write(np.ascontiguousarray(model.astype('float32')).tobytes())
            program['view'].write(np.ascontiguousarray(view.astype('float32')).tobytes())
            program['projection'].write(np.ascontiguousarray(proj.astype('float32')).tobytes())
            # ② 绑定纹理 (仅当 entity 有有效纹理时)
            if entity.texture_id and entity.texture_id > 0:
                tex_data = cls.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle is not None:
                    tex_data.gl_handle.use(location=0)
                    try:
                        program['uTexture'] = 0
                    except KeyError:
                        pass  # shader 中没有 sampler2D，跳过
            # ③ 上传材质的自定义 uniform (跳过已传的 model/view/projection)
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
                    pass  # uniform 被 shader 编译器优化掉了，跳过
            # ④ 提交绘制命令 (三角形图元)
            entity.vao.render(mgl.TRIANGLES)

    @classmethod
    def EndFrame(cls) -> None:
        """结束当前帧渲染。

        ModernGL 无需额外操作 (swap_buffers 由 Application.render_loop 处理)。
        """
        pass

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        """处理引擎事件 (主线程调用)。

        注意: 此方法在主线程执行，不可直接调用 GL 函数。
        GL 相关操作通过缓存变量延迟到 StartFrame 中处理。

        处理的事件:
          - WindowResizeEvent        : 记录待处理的窗口尺寸变更
          - NewComponentEvent        : 新的 MeshRenderer → 注册实体
          - ComponentModifiedEvent   : 组件修改 → 更新注册状态
          - SceneCameraUpdateEvent   : 重算 view/proj 矩阵
        """
        if event is WindowResizeEvent:
            width, height = event.UnPack()
            cls._pending_resize = (width, height)
            cls.aspect_ratio = width / height
            cam = EditorCamera.get_instance()
            cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)

        if any([event is NewComponentEvent, event is ComponentModifiedEvent]):
            entity_id, comp = event.UnPack()
            if isinstance(comp, MeshRenderer):
                if comp.visible:
                    cls.register_entity(entity_id)
                else:
                    cls.unregister_entity(entity_id)

        if event is SceneCameraUpdateEvent:
            cls._camera_update_callback(event)

    # ════════════════════════════════════════════════════════════
    # 事件回调
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _camera_update_callback(
        cls,
        event: SceneCameraUpdateEvent
    ):
        """相机更新回调 — 从 EditorCamera 获取最新的 view/proj 矩阵。

        不触碰任何 GL 调用，仅更新 NumPy 矩阵缓存。
        """
        cam = EditorCamera.get_instance()
        cls._cached_view = cam.get_view_matrix()
        cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)

    # ════════════════════════════════════════════════════════════
    # 资源注册
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_entity(
        cls,
        entity_id: int
    ) -> None:
        """注册可渲染实体到 GPU。

        自动级联注册关联的 Mesh、Shader、Texture，然后创建 VAO。
        顶点布局: aPos(3f) + aTexCoord(2f) + aNormal(3f)，交错排列。

        Args:
            entity_id: 实体 ID (SceneManager 分配)
        """
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)
        # 级联注册依赖资源 (若已注册则仅增加引用计数)
        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)
        mesh_data = cls.registered_meshes[mesh_id]
        shader_data = cls.registered_shaders[shader_id]
        # 注册纹理 (取 material 的第一张纹理作为 diffuse)
        if material.texture_id_list:
            tex_id = material.texture_id_list[0]
            texture = ResourceManager.GetTexture(tex_id)
            cls.register_texture(texture, tex_id)
        else:
            tex_id = 0
        program = shader_data.program
        # 创建 VAO: 绑定 VBO (交错顶点) + IBO (索引) + Shader
        # skip_errors=True: 自动跳过 shader 中不存在的 attribute (如被优化掉的 aNormal)
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
        """上传网格数据到 GPU。

        若网格已注册，仅增加引用计数 (+1)。
        否则创建 VBO (交错顶点) 和 IBO (索引)。

        交错顶点格式 (每顶点 8 个 float):
          [px, py, pz,  u, v,  nx, ny, nz]
           └─位置──┘  └UV┘  └──法线───┘

        Args:
            mesh    : CPU 端 Mesh 资源 (vertices[Nx3], uvs[Nx2], normals[Nx3], indices[M])
            mesh_id : 网格资源 ID
        """
        if mesh_id in cls.registered_meshes:
            cls.registered_meshes[mesh_id].ref_count += 1
            return
        vertices = mesh.vertices   # (N, 3) float32 — 顶点位置
        uvs = mesh.uvs             # (N, 2) float32 — 纹理坐标
        normals = mesh.normals     # (N, 3) float32 — 法线向量
        indices = mesh.indices     # (M,) uint32   — 三角形索引
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
        """编译并链接着色器程序。

        若着色器已注册，仅增加引用计数 (+1)。
        ModernGL 一行完成编译+链接，自动检测错误。

        Args:
            shader    : CPU 端 Shader 资源 (vs_src + fs_src 源码)
            shader_id : 着色器资源 ID

        Raises:
            RuntimeError: 着色器编译/链接失败
        """
        if shader_id in cls.registered_shaders:
            cls.registered_shaders[shader_id].ref_count += 1
            return
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
        """上传纹理数据到 GPU。

        若纹理已注册，仅增加引用计数 (+1)。
        自动根据通道数选择内部格式 (R8/RGB8/RGBA8)，
        生成 mipmap 并设置线性过滤。

        Args:
            texture    : CPU 端 Texture 资源 (image_data + width/height/channels)
            texture_id : 纹理资源 ID

        Raises:
            ValueError: 不支持的通道数
        """
        if texture_id in cls.registered_textures:
            cls.registered_textures[texture_id].ref_count += 1
            return
        # 根据通道数确定 GPU 内部格式
        if texture.channels == 1:
            fmt = 'R8'
        elif texture.channels == 3:
            fmt = 'RGB8'
        elif texture.channels == 4:
            fmt = 'RGBA8'
        else:
            raise ValueError(f"不支持的纹理通道数: {texture.channels}")
        # 创建 ModernGL 纹理对象
        mgl_tex = cls.ctx.texture(
            (texture.width, texture.height),
            texture.channels,
            texture.image_data.tobytes(),
            dtype='f1',  # 8-bit unsigned normalized (0-255 → 0.0-1.0)
        )
        mgl_tex.filter = (mgl.LINEAR_MIPMAP_LINEAR, mgl.LINEAR)  # 三线性 mipmap
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
    def unregister_entity(
        cls,
        entity_id: int
    ) -> None:
        """从 GPU 卸载实体。

        释放 VAO，递减关联资源引用计数，从注册表中删除。

        Args:
            entity_id: 要卸载的实体 ID
        """
        if entity_id not in cls.registered_entities:
            return
        entity = cls.registered_entities[entity_id]
        # 释放 ModernGL VAO
        if entity.vao is not None:
            entity.vao.release()
        # 递减关联资源引用计数 (mesh / shader / texture)
        cls._decref_mesh(entity.mesh_id)
        cls._decref_shader(entity.shader_id)
        cls._decref_texture(entity.texture_id)
        del cls.registered_entities[entity_id]

    @classmethod
    def unregister_mesh(
        cls,
        mesh_id: int
    ) -> None:
        """递减网格引用计数，归零时释放 GPU 资源。

        Args:
            mesh_id: 网格资源 ID
        """
        cls._decref_mesh(mesh_id)

    @classmethod
    def unregister_shader(
        cls,
        shader_id: int
    ) -> None:
        """递减着色器引用计数，归零时释放 GPU 资源。

        Args:
            shader_id: 着色器资源 ID
        """
        cls._decref_shader(shader_id)

    @classmethod
    def unregister_texture(
        cls,
        texture_id: int
    ) -> None:
        """递减纹理引用计数，归零时释放 GPU 资源。

        Args:
            texture_id: 纹理资源 ID
        """
        cls._decref_texture(texture_id)

    # ════════════════════════════════════════════════════════════
    # 引用计数辅助 (内部方法)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _decref_mesh(
        cls,
        mesh_id: int
    ) -> None:
        """递减网格引用计数。

        归零时释放 VBO + IBO 并从注册表删除。
        不会抛异常 (幂等: 若 mesh_id 不存在则直接返回)。

        Args:
            mesh_id: 网格资源 ID
        """
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
        """递减着色器引用计数。

        归零时释放 mgl.Program 并从注册表删除。

        Args:
            shader_id: 着色器资源 ID
        """
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
        """递减纹理引用计数。

        归零时释放 mgl.Texture 并从注册表删除。

        Args:
            texture_id: 纹理资源 ID
        """
        if texture_id not in cls.registered_textures:
            return
        data = cls.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.gl_handle is not None:
                data.gl_handle.release()
            del cls.registered_textures[texture_id]
