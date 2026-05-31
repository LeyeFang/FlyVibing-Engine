"""
传统 OpenGL 渲染器后端 — 基于 PyOpenGL 的直接 GL 调用实现。

特性:
  - 手动着色器编译/链接 (glCompileShader / glLinkProgram)
  - 手动 VBO/VAO/EBO 管理 (glGenBuffers / glVertexAttribPointer)
  - 逐 uniform 上传 (glUniform*) — 无矩阵缓存
  - 引用计数 GPU 资源管理

与 modernGLRenderer 的区别:
  - 使用 GL 状态机模型 (bind → set → draw → unbind)
  - 每帧通过 update_uniform 重新上传所有矩阵
  - 更接近底层 OpenGL，适合学习和调试

架构:
  openglRenderer 同时继承 Renderer (生命周期) 和 RenderResourceManger (资源管理)。
  所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application

# ── 事件系统 ──
from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.SceneEvent import *

# ── 资源管理 ──
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture

# ── 场景管理 ──
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import *

# ── 渲染器基类 ──
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Math.RendererMath import (
    calculate_entity_model
)
from Application.Editor.EditorCamera import EditorCamera

import numpy as np
from OpenGL.GL import *


class openglRenderer(Renderer, RenderResourceManger):
    """传统 OpenGL 渲染器 — 基于 PyOpenGL 的直接 GL 调用。

    使用基类 RenderResourceManger 的数据结构 (entity/mesh/shader/texture_data_struct)，
    不覆盖 dataclass，直接使用基类的 int 类型句柄 (VBO/VAO/Program 等 GLuint)。

    Class-level 状态:
        viewport_width  : 视口像素宽度 (从基类继承)
        viewport_height : 视口像素高度 (从基类继承)
        aspect_ratio    : 宽高比 (从基类继承)
        view_matrix     : 视图矩阵缓存 (np.ndarray 4x4)
        proj_matrix     : 投影矩阵缓存 (np.ndarray 4x4)
    """

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls,
        app: Application
    ):
        """初始化 OpenGL 渲染器。

        在渲染线程调用，此时 GLFW 上下文已绑定。
        完成以下初始化:
          1. 打印 GPU 信息 (厂商/型号)
          2. 设置视口
          3. 启用深度测试
          4. 从 SceneManager 获取主摄像机并缓存初始 view/proj 矩阵

        Args:
            app: Application 单例引用
        """
        print(f"GPU Vendor: {glGetString(GL_VENDOR).decode()}")
        print(f"GPU Renderer: {glGetString(GL_RENDERER).decode()}")

        window_size = app.window.GetSize()
        glViewport(0, 0, window_size[0], window_size[1])
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]

        # 启用深度测试 (确保远距离物体被近处物体遮挡)
        glEnable(GL_DEPTH_TEST)

        # 初始化相机矩阵缓存 (编辑器模式: 使用 EditorCamera)
        cam = EditorCamera.get_instance()
        cls.view_matrix = cam.get_view_matrix()
        cls.proj_matrix = cam.get_projection_matrix(cls.aspect_ratio)
        return cls

    @classmethod
    def StartFrame(
        cls
    ) -> None:
        """开始一帧渲染 — 清屏并绘制所有可渲染实体。

        执行流程:
          1. 更新视口 (处理可能的窗口 resize)
          2. 用深灰色清屏 (0.2, 0.2, 0.2)
          3. 遍历可渲染实体列表
          4. 对每个实体: 绑定 VAO → 更新 uniform → glDrawElements → 解绑 VAO
        """
        glViewport(0, 0, cls.viewport_width, cls.viewport_height)
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        renderable_entities = SceneManager.GetRenderableEntities()
        for entity_id in renderable_entities:
            # ① 获取实体的 mesh 数据 (VAO + 索引数)
            entity: RenderResourceManger.entity_data_struct = (
                cls.registered_entities[f'{entity_id}']
            )
            entity_mesh_id = entity.mesh_id
            entity_mesh: RenderResourceManger.mesh_data_struct = (
                cls.registered_meshes[f'{entity_mesh_id}']
            )
            current_vao = entity_mesh.vao
            current_counts = entity_mesh.elements_count

            # ② 激活着色器程序并上传所有 uniform
            cls.update_uniform(entity_id=entity_id)

            # ③ 绑定 VAO 并绘制元素
            glBindVertexArray(current_vao)
            glDrawElements(GL_TRIANGLES, current_counts, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)  # 解绑

    @classmethod
    def EndFrame(
        cls
    ) -> None:
        """结束当前帧渲染。

        OpenGL 无需额外操作 (swap_buffers 由 Application.render_loop 处理)。
        """
        for entity_info in cls.registered_entities.values():
            pass

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ):
        """处理引擎事件。

        处理的事件:
          - WindowCloseEvent          : (预留) 窗口关闭
          - WindowResizeEvent         : 更新视口尺寸和宽高比
          - NewComponentEvent         : 新的 MeshRenderer → 注册实体
          - ComponentModifiedEvent    : 组件修改 → 更新注册状态
          - SceneCameraUpdateEvent    : 重算 view/proj 矩阵

        Args:
            event: 引擎事件实例
        """
        if event is WindowCloseEvent:
            pass
        if event is WindowResizeEvent:
            width, height = event.UnPack()
            cls.viewport_width = width
            cls.viewport_height = height
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
        if event is SceneCameraUpdateEvent:
            cls._camera_update_callback()

    # ════════════════════════════════════════════════════════════
    # Uniform 上传
    # ════════════════════════════════════════════════════════════

    @classmethod
    def update_uniform(
        cls,
        entity_id: int
    ) -> None:
        """激活着色器程序并上传该实体的所有 uniform。

        包括:
          - model      : 模型矩阵 (TRS → world space)
          - view       : 视图矩阵 (world → camera space)
          - projection : 投影矩阵 (camera → clip space)
          - 自定义     : 材质中定义的其他 uniform (float/mat4 等)

        根据 uniform 类型自动选择对应的 glUniform* 函数。

        Args:
            entity_id: 实体 ID
        """
        # 计算模型矩阵 (Transform → 4x4)
        model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))

        # 获取实体的材质和着色器信息
        entity: RenderResourceManger.entity_data_struct = (
            cls.registered_entities[f"{entity_id}"]
        )
        entity_material_id = entity.material_id
        material = ResourceManager.GetMaterial(entity_material_id)
        uniforms_data = material.uniforms_data
        entity_shader_id = entity.shader_id
        entity_shader: RenderResourceManger.shader_data_struct = (
            cls.registered_shaders[f'{entity_shader_id}']
        )

        # 激活着色器程序
        glUseProgram(entity_shader.program)

        # 遍历 uniform 并上传
        for (u_name, u_value), u_type in zip(
            uniforms_data.items(), entity_shader.uniforms_type
        ):
            loc = entity_shader.uniforms_loc[u_name]

            if u_name == 'model':
                # 模型矩阵 → 将物体从局部空间变换到世界空间
                glUniformMatrix4fv(loc, 1, GL_FALSE, model.astype('float32'))
            elif u_name == 'view':
                # 视图矩阵 → 将世界空间变换到摄像机空间
                glUniformMatrix4fv(loc, 1, GL_FALSE, cls.view_matrix.astype('float32'))
            elif u_name == 'projection':
                # 投影矩阵 → 将摄像机空间变换到裁剪空间
                glUniformMatrix4fv(loc, 1, GL_FALSE, cls.proj_matrix.astype('float32'))
            else:
                # 自定义 uniform (材质参数: 时间/频率/颜色等)
                if u_type == 'mat4':
                    glUniformMatrix4fv(loc, 1, GL_FALSE, u_value)
                if u_type == 'float':
                    glUniform1f(loc, u_value)
                if u_type == 'double':
                    glUniform1d(loc, u_value)

    # ════════════════════════════════════════════════════════════
    # 资源注册
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_entity(
        cls,
        entity_id: int
    ) -> None:
        """注册可渲染实体。

        从 SceneManager 获取实体的 Mesh/Material/Shader 信息，
        级联注册依赖资源，记录到 registered_entities。

        注意: OpenGL 后端的 VAO 存储在 mesh_data_struct 中 (而非 entity_data_struct)，
        因此多个 entity 共享同一 mesh 时共用同一个 VAO。

        Args:
            entity_id: 实体 ID
        """
        # 获取 mesh 和 material 资源 ID
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)

        # 记录实体引用的资源 ID (VAO 在 register_mesh 中创建并共享)
        cls.registered_entities[f'{entity_id}'] = cls.entity_data_struct(
            shader_id=shader_id,
            texture_id=0,
            mesh_id=mesh_id,
            material_id=material_id
        )

        # 级联注册依赖资源 (若已注册则仅增加引用计数)
        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)

    @classmethod
    def register_mesh(
        cls,
        mesh: Mesh,
        mesh_id: int
    ):
        """上传网格数据到 GPU。

        若网格已注册，仅增加引用计数 (+1)。
        否则创建 VBO (顶点+UV+法线)、VAO (属性布局)、EBO (索引)。

        顶点属性布局 (location):
          - location 0 : aPos      (vec3, offset 0)
          - location 1 : aTexCoord (vec2, offset 12 bytes)
          - location 2 : aNormal   (vec3, offset 20 bytes)

        交错顶点格式 (每顶点 8 个 float, 32 bytes):
          [px, py, pz,  u, v,  nx, ny, nz]

        Args:
            mesh    : CPU 端 Mesh 资源
            mesh_id : 网格资源 ID
        """
        if f"{mesh_id}" in cls.registered_meshes.keys():
            cls.registered_meshes[f"{mesh_id}"].ref_count += 1
            return

        vertices: np.ndarray = mesh.vertices   # (N, 3) float32
        uvs: np.ndarray = mesh.uvs             # (N, 2) float32
        normals: np.ndarray = mesh.normals     # (N, 3) float32
        ver_uv_nor = np.hstack((vertices, uvs, normals))  # 交错排列
        indices: np.ndarray = mesh.indices     # (M,) uint32

        # ── VBO (顶点缓冲对象) ──
        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, ver_uv_nor.nbytes, ver_uv_nor, GL_STATIC_DRAW)

        # ── VAO (顶点数组对象) ──
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)
        stride = (3 + 2 + 3) * sizeof(GLfloat)  # 每顶点 8 floats = 32 bytes

        # location=0: aPos (顶点位置, vec3)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)

        # location=1: aTexCoord (纹理坐标, vec2, offset = 3*4 = 12 bytes)
        tex_offset = 3 * sizeof(GLfloat)
        glVertexAttribPointer(
            1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(tex_offset)
        )
        glEnableVertexAttribArray(1)

        # location=2: aNormal (法线向量, vec3, offset = 5*4 = 20 bytes)
        normal_offset = (3 + 2) * sizeof(GLfloat)
        glVertexAttribPointer(
            2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(normal_offset)
        )
        glEnableVertexAttribArray(2)

        # ── EBO (索引缓冲对象) ──
        ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

        # 记录到注册表
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
        """编译顶点/片段着色器并链接为着色器程序。

        若着色器已注册，仅增加引用计数 (+1)。
        手动完成整个 GL 着色器编译管线:
          1. 分别编译 VS 和 FS (glCompileShader)
          2. 创建 Program 并 attach 两个 shader (glAttachShader)
          3. 链接程序 (glLinkProgram)
          4. 删除中间 shader 对象 (glDeleteShader)
          5. 查询所有 uniform location (glGetUniformLocation)

        Args:
            shader    : CPU 端 Shader 资源 (vs_src + fs_src + uniforms_name_type)
            shader_id : 着色器资源 ID

        Raises:
            RuntimeError: 顶点/片段着色器编译失败，或程序链接失败
        """
        if f"{shader_id}" in cls.registered_shaders.keys():
            cls.registered_shaders[f"{shader_id}"].ref_count += 1
            return

        vs_src = shader.vs_src
        fs_src = shader.fs_src
        uniforms_name_type = shader.uniforms_name_type

        # ── 编译顶点着色器 ──
        vertex_shader = glCreateShader(GL_VERTEX_SHADER)
        glShaderSource(vertex_shader, vs_src)
        glCompileShader(vertex_shader)
        success = glGetShaderiv(vertex_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(vertex_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            raise RuntimeError(f"Vertex shader compilation failed:\n{log}")

        # ── 编译片段着色器 ──
        fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
        glShaderSource(fragment_shader, fs_src)
        glCompileShader(fragment_shader)
        success = glGetShaderiv(fragment_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(fragment_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Fragment shader compilation failed:\n{log}")

        # ── 链接着色器程序 ──
        program = glCreateProgram()
        glAttachShader(program, vertex_shader)
        glAttachShader(program, fragment_shader)
        glLinkProgram(program)
        success = glGetProgramiv(program, GL_LINK_STATUS)
        if not success:
            log = glGetProgramInfoLog(program).decode('utf-8')
            glDeleteProgram(program)
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Shader program linking failed:\n{log}")

        # 着色器对象已链接到程序，可安全删除中间对象
        glDeleteShader(vertex_shader)
        glDeleteShader(fragment_shader)

        # ── 查询所有 uniform 的 location ──
        u_type_list = []
        u_loc_dict = {}
        for u_name, u_type in uniforms_name_type.items():
            u_type_list.append(u_type)
            loc = glGetUniformLocation(program, u_name)
            if loc != -1:                    # location -1 表示 uniform 被优化掉
                u_loc_dict[u_name] = loc

        # 记录到注册表
        cls.registered_shaders[f'{shader_id}'] = cls.shader_data_struct(
            program,
            u_type_list,
            u_loc_dict
        )

    # ════════════════════════════════════════════════════════════
    # 资源卸载
    # ════════════════════════════════════════════════════════════

    @classmethod
    def unregister_entity(
        cls,
        entity_id: int
    ) -> None:
        """从注册表卸载实体。

        递减关联资源的引用计数，级联清理归零资源。

        Args:
            entity_id: 要卸载的实体 ID
        """
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
        """递减网格引用计数，归零时释放 GPU 资源。

        释放 VAO、VBO、EBO 并从注册表删除。

        Args:
            mesh_id: 网格资源 ID
        """
        target_mesh: RenderResourceManger.mesh_data_struct = (
            cls.registered_meshes[f"{mesh_id}"]
        )
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
        """递减着色器引用计数，归零时从注册表删除。

        注意: 当前未调用 glDeleteProgram，需补充。

        Args:
            shader_id: 着色器资源 ID
        """
        if cls.registered_shaders[f"{shader_id}"]["ref_count"] == 0:
            del cls.registered_shaders[f"{shader_id}"]
        else:
            pass

    @classmethod
    def unregister_texture(
        cls,
        texture_id: int
    ) -> None:
        """递减纹理引用计数，归零时从注册表删除。

        注意: 当前未调用 glDeleteTextures，需补充。

        Args:
            texture_id: 纹理资源 ID
        """
        if cls.registered_textures[f"{texture_id}"]["ref_count"] == 0:
            del cls.registered_textures[f"{texture_id}"]
        else:
            pass

    # ════════════════════════════════════════════════════════════
    # 事件回调
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _camera_update_callback(
        cls
    ):
        """相机更新回调 — 从 EditorCamera 获取最新的 view/proj 矩阵。

        当用户旋转/平移/缩放轨道摄像机时触发。
        """
        cam = EditorCamera.get_instance()
        cls.view_matrix = cam.get_view_matrix()
        cls.proj_matrix = cam.get_projection_matrix(cls.aspect_ratio)
