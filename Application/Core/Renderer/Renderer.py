"""
渲染器抽象基类 — 定义所有渲染后端的统一接口。

架构说明:
  - Renderer       : 渲染生命周期接口 (Create / StartFrame / EndFrame / OnEvent)
  - RenderResourceManger : GPU 资源注册/卸载接口 (Mesh / Shader / Texture / Entity)

子类实现:
  - modernGLRenderer  : ModernGL/ — 基于 moderngl 的现代 OpenGL 后端
  - vulkanRenderer    : Vulkan/   — Vulkan 低级图形 API 后端
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import numpy as np

from Application.Core.Events.Event import Event


class Renderer(ABC):
    """渲染器抽象基类 — 定义帧循环和事件处理接口。

    Class-level 属性 (所有方法均为 @classmethod，单例模式):
        app             : Application 实例引用
        viewport_width  : 视口像素宽度
        viewport_height : 视口像素高度
        aspect_ratio    : 宽高比 (width / height)
        camera_id       : 当前激活的摄像机实体 ID
    """

    app = None
    viewport_width: int
    viewport_height: int
    aspect_ratio: float
    camera_id: int

    @classmethod
    @abstractmethod
    def Create(cls):
        """初始化渲染器。

        在渲染线程调用，此时 GL 上下文已绑定。
        应完成: GPU 上下文创建、默认状态设置、初始资源加载。
        """
        ...

    @classmethod
    @abstractmethod
    def StartFrame(cls):
        """开始新一帧的渲染。

        每帧调用一次，在 Layer.OnRender() 之前执行。
        应完成: 清屏、视口设置、遍历可渲染实体并提交绘制命令。
        """
        ...

    @classmethod
    @abstractmethod
    def EndFrame(cls):
        """结束当前帧的渲染。

        每帧调用一次，在 Layer.OnRender() 之后执行。
        可用于: GUI 叠加层绘制、后处理、帧同步。
        """
        ...

    @classmethod
    @abstractmethod
    def OnEvent(
        cls,
        event: Event
    ):
        """处理引擎事件。

        在主线程调用 (不可直接调用 GL 函数)。
        应延迟到 StartFrame 中通过缓存变量处理 GL 操作。

        Args:
            event: 引擎事件实例 (WindowResizeEvent / SceneCameraUpdateEvent 等)
        """
        ...

    # ════════════════════════════════════════════════════════════
    # Overlay 回调机制 (编辑器解耦)
    # ════════════════════════════════════════════════════════════

    _overlay_callbacks: list[Callable] = []

    @classmethod
    def register_overlay_callback(cls, callback: Callable) -> None:
        """注册 overlay 渲染回调 — 每帧场景实体之后调用。

        EditorLayer 在 OnAttach 时注册 GridGizmo/Gizmo/Outline 等。
        渲染器不 import 任何 Editor 代码, 仅持有 Callable 引用。

        Args:
            callback: fn(view: np.ndarray, proj: np.ndarray) -> None
        """
        if callback not in cls._overlay_callbacks:
            cls._overlay_callbacks.append(callback)

    @classmethod
    def unregister_overlay_callback(cls, callback: Callable) -> None:
        """取消注册 overlay 回调。"""
        if callback in cls._overlay_callbacks:
            cls._overlay_callbacks.remove(callback)

    @classmethod
    def _render_overlays(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """调用所有已注册的 overlay 回调。"""
        for cb in cls._overlay_callbacks:
            cb(view, proj)


class RenderResourceManger(ABC):
    """GPU 资源管理器抽象基类 — 管理 Mesh/Shader/Texture 的上传与生命周期。

    资源注册表 (class-level dict，所有子类实例共享):
        registered_entities  : entity_id → entity_data_struct
        registered_meshes    : mesh_id   → mesh_data_struct
        registered_shaders   : shader_id → shader_data_struct
        registered_textures  : texture_id → texture_data_struct

    引用计数机制:
        每个资源有 ref_count，register 时 +1，unregister 时 -1。
        ref_count == 0 时释放 GPU 资源并从注册表中删除。
    """

    view_matrix = None     # 缓存的视图矩阵 (np.ndarray 4x4)
    proj_matrix = None     # 缓存的投影矩阵 (np.ndarray 4x4)

    # ════════════════════════════════════════════════════════════
    # 资源数据结构
    # ════════════════════════════════════════════════════════════

    @dataclass
    class entity_data_struct:
        """可渲染实体在 GPU 端的资源绑定记录。

        Attributes:
            shader_id   : 使用的着色器资源 ID
            texture_id  : 绑定的纹理资源 ID (0 表示无纹理)
            mesh_id     : 使用的网格资源 ID
            material_id : 使用的材质资源 ID
        """
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int

    @dataclass
    class mesh_data_struct:
        """网格在 GPU 端的资源记录。

        Attributes:
            vbo            : 顶点缓冲对象句柄
            vao            : 顶点数组对象句柄
            ebo            : 索引缓冲对象句柄
            elements_count : 索引数量 (用于 glDrawElements)
            ref_count      : 引用计数
        """
        vbo: int
        vao: int
        ebo: int
        elements_count: int
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        """着色器程序在 GPU 端的资源记录。

        Attributes:
            program       : 着色器程序句柄
            uniforms_type : uniform 名称 → GL 类型 的映射列表
            uniforms_loc  : uniform 名称 → location 的映射字典
            ref_count     : 引用计数
        """
        program: int
        uniforms_type: list[str]
        uniforms_loc: dict[str, int]
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        """纹理在 GPU 端的资源记录。

        Attributes:
            ref_count    : 引用计数
            gl_handle    : GPU 纹理句柄 (modernGL → mgl.Texture / OpenGL → GLuint)
            texture_unit : 分配的纹理单元编号 (-1 表示未分配)
        """
        ref_count: int = 0
        gl_handle: any = None
        texture_unit: int = -1

    # ════════════════════════════════════════════════════════════
    # 资源注册表
    # ════════════════════════════════════════════════════════════

    registered_entities: dict[entity_data_struct] = {}
    registered_meshes: dict[mesh_data_struct] = {}
    registered_shaders: dict[shader_data_struct] = {}
    registered_textures: dict[int, texture_data_struct]
    registered_textures: dict = {}

    # ════════════════════════════════════════════════════════════
    # 注册接口 (子类必须实现)
    # ════════════════════════════════════════════════════════════

    @classmethod
    @abstractmethod
    def register_entity(cls):
        """注册可渲染实体到 GPU。

        从 SceneManager 获取实体的 Mesh/Material/Shader，
        创建 VAO 并记录到 registered_entities。
        """
        ...

    @classmethod
    @abstractmethod
    def register_mesh(cls):
        """上传网格数据到 GPU。

        将顶点数据 (positions + UVs + normals) 和索引数据
        上传到 VBO/EBO，创建 VAO 并记录顶点属性布局。
        """
        ...

    @classmethod
    @abstractmethod
    def register_texture(cls):
        """上传纹理数据到 GPU。

        将 CPU 端像素数据上传为 GPU 纹理对象，
        设置过滤模式和 mipmap。
        """
        ...

    @classmethod
    def register_shader(cls):
        """编译并链接着色器程序 (基类提供默认空实现)。"""
        ...

    # ════════════════════════════════════════════════════════════
    # 卸载接口 (子类必须实现)
    # ════════════════════════════════════════════════════════════

    @classmethod
    @abstractmethod
    def unregister_entity(cls):
        """从 GPU 卸载实体。

        递减关联的 Mesh/Shader/Texture 引用计数，
        释放 VAO，从 registered_entities 中删除。
        """
        ...

    @classmethod
    @abstractmethod
    def unregister_mesh(cls):
        """从 GPU 卸载网格。

        递减引用计数，归零时释放 VBO/VAO/EBO 并删除记录。
        """
        ...

    @classmethod
    @abstractmethod
    def unregister_texture(cls):
        """从 GPU 卸载纹理。

        递减引用计数，归零时释放纹理对象并删除记录。
        """
        ...

    @classmethod
    def unregister_shader(cls):
        """从 GPU 卸载着色器 (基类提供默认空实现)。"""
        ...

    # ════════════════════════════════════════════════════════════
    # Editor Overlay 资源管理 (编辑器解耦桥梁)
    # ════════════════════════════════════════════════════════════
    #
    # 设计原则:
    #   - Renderer 不知道 Editor 的存在，只知道有"叠加层可绘制对象"
    #   - Editor (Grid/Gizmo) 不 import 任何图形 API，只提供纯数据
    #   - 渲染器负责将注册的 overlay 如实地绘制出来
    #
    # 典型流程:
    #   Grid._build_mesh_data() → 生成 vertices/indices (np.ndarray)
    #   Grid.register_to(renderer) → 调用 renderer.register_overlay_drawable(...)
    #   renderer.StartFrame() → 场景实体之后遍历 registered_overlays 绘制

    @dataclass
    class overlay_drawable_struct:
        """编辑器叠加层可绘制对象 — 纯数据载体，不依赖任何图形 API。

        Attributes:
            key          : 唯一标识符 (如 "editor_grid_lines", "editor_grid_x_axis")
            vertices     : 顶点位置数组 (N×3, float32)
            indices      : 索引数组 (M, uint32)
            vs_src       : GLSL 顶点着色器源码
            fs_src       : GLSL 片段着色器源码
            uniforms_setup: Callable[[int], None] — 接收 program handle,
                            负责设置该 overlay 专属的 uniform (颜色等)
            draw_mode    : 图元类型标识 ('lines' | 'triangles')
            depth_test   : 是否开启深度测试
            line_width   : 线宽 (仅 draw_mode='lines' 时有效)
        """
        key: str
        vertices: 'np.ndarray'
        indices: 'np.ndarray'
        vs_src: str
        fs_src: str
        uniforms_setup: 'Callable[[int], None]'
        draw_mode: str = 'lines'
        depth_test: bool = True
        line_width: float = 1.0
        blend: bool = False

    registered_overlays: dict[str, 'overlay_drawable_struct'] = {}

    @classmethod
    def register_overlay_drawable(
        cls,
        overlay: 'overlay_drawable_struct'
    ) -> None:
        """注册编辑器叠加层可绘制对象 (抽象接口，子类实现 GPU 上传)。

        调用时机: EditorLayer.OnAttach() → Grid.register_to(renderer)
                  (此时已在渲染线程，GL 上下文有效)

        Args:
            overlay: overlay_drawable_struct 包含所有渲染所需数据
        """
        ...

    @classmethod
    def unregister_overlay_drawable(cls, key: str) -> None:
        """取消注册并释放 GPU 资源 (抽象接口，子类实现)。

        Args:
            key: overlay 唯一标识符
        """
        ...

    @classmethod
    def _draw_registered_overlays(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """遍历 registered_overlays 并提交绘制命令 (抽象接口，子类实现)。

        Args:
            view: 4×4 视图矩阵
            proj: 4×4 投影矩阵
        """
        ...
