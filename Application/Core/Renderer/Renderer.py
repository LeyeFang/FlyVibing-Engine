"""
渲染器抽象基类 — 定义所有渲染后端的统一接口。

架构说明:
  - Renderer       : 渲染生命周期 + 命令队列 (Create / StartFrame / EndFrame / enqueue)
  - RenderResourceManger : GPU 资源注册/卸载接口 (Mesh / Shader / Texture / Entity)

RHI 命令模型:
  - 主线程通过 enqueue(cmd) 提交命令
  - StartFrame 自动消费命令队列 → _do_start_frame (子类渲染逻辑)
  - 事件→命令转换由 EditorHost._on_event 负责，渲染器不直接处理 Event

子类实现:
  - openGLRenderer   : OpenGL/  — PyOpenGL 后端
  - vulkanRenderer   : Vulkan/  — Vulkan 后端
  - ZenGLRenderer    : ZenGL/   — ZenGL 后端

相机矩阵:
  Renderer 不持有相机引用。view/proj 矩阵由逻辑线程的相机模块计算后，
  通过 SetViewProjectionCommand 推送给渲染器。
  Editor / GameRuntime 各自持有并管理自己的相机实例。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import numpy as np

from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Renderer.RenderCommand import RenderCommand


class Renderer(ABC):
    """渲染器抽象基类 — 命令队列 + 帧循环 + 事件处理接口。

    Class-level 属性 (所有方法均为 @classmethod，单例模式):
        viewport_width  : 视口像素宽度
        viewport_height : 视口像素高度
        aspect_ratio    : 宽高比 (width / height)
    """

    app = None
    viewport_width: int
    viewport_height: int
    aspect_ratio: float
    camera_id: int

    # ── 命令队列 (主线程安全的渲染通信通道) ──
    _command_queue: CommandQueue = None

    @classmethod
    def enqueue(cls, cmd: RenderCommand) -> None:
        """主线程安全: 提交一条渲染命令。

        使用方式:
          renderer.enqueue(EntityRegistrationCommand(entity_id, True))
          renderer.enqueue(ResizeCommand(width, height))

        Command 的 execute(renderer) 在渲染线程被调用，
        调用方无需知道 renderer 的具体实现。
        """
        if cls._command_queue is not None:
            cls._command_queue.enqueue(cmd)

    # ── 相机矩阵缓存 (所有后端共享, 由 SetViewProjectionCommand 写入) ──
    _cached_view: 'np.ndarray' = None       # 4x4 视图矩阵 (float32)
    _cached_proj: 'np.ndarray' = None       # 4x4 投影矩阵 (float32)
    _pending_resize: tuple = None           # (width, height) or None

    # ── 相机元数据缓存 (由 SetViewProjectionCommand 写入, 供动态 uniform 解析) ──
    _cam_orbit_target: 'np.ndarray' = None  # 轨道注视点
    _cam_orbit_distance: float = 10.0       # 摄像机距离
    _cam_is_orthographic: bool = False      # 是否正交投影
    _cam_ortho_size: float = 10.0           # 正交半高

    @classmethod
    @abstractmethod
    def Create(cls, window: 'Window' = None):
        """初始化渲染器 — 在渲染线程调用。

        Args:
            window: 所属的 Window 实例（Engine 传入）。
                    渲染器通过 window.GetSize() 获取初始尺寸，
                    通过 window.GetNativeHandle() 获取平台句柄（Vulkan Surface 等）。
                    不再需要通过 GLFW 上下文或 EditorHost 回退获取窗口信息。

        调用方 (Engine._create_renderer) 在调用前已确保 GL 上下文绑定到当前线程。
        """
        ...

    # ════════════════════════════════════════════════════════════
    # 帧渲染 (两级架构: 基类消费命令 → 子类执行渲染)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def StartFrame(cls) -> None:
        """帧开始 — 消费命令队列 → 子类渲染逻辑。

        基类提供编排，子类通过覆写 _do_start_frame() 注入渲染管线。
        """
        if cls._command_queue is not None:
            cls._command_queue.execute_all(cls)
        cls._do_start_frame()

    @classmethod
    @abstractmethod
    def _do_start_frame(cls) -> None:
        """子类渲染管线 (clear → pick → entities → overlays → ...)。

        由 StartFrame 在消费命令后调用。子类必须实现。
        """
        ...

    @classmethod
    @abstractmethod
    def EndFrame(cls):
        """帧结束 — 后处理、GPU query、present 等。"""
        ...

    @classmethod
    def Shutdown(cls) -> None:
        """释放所有 GPU 资源 — 渲染线程、GL 上下文有效时调用。

        子类应覆写以释放各自后端的 GPU 对象 (VAO/VBO/Shader/FBO 等)。
        基类负责清理跨后端共享的状态 (命令队列、overlay 回调、相机缓存)。
        """
        cls._command_queue = None
        cls._overlay_callbacks.clear()
        cls._cached_view = None
        cls._cached_proj = None
        cls._pending_resize = None
        cls._cam_orbit_target = None
        cls._cam_orbit_distance = 10.0
        cls._cam_is_orthographic = False
        cls._cam_ortho_size = 10.0

    # ════════════════════════════════════════════════════════════
    # 窗口尺寸变更 (子类通过 ResizeCommand 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _on_window_resize(cls, width: int, height: int) -> None:
        """子类在 resize 处理中调用 — 更新缓存、宽高比与视口尺寸。

        注意: 投影矩阵的重算不再由渲染器负责。
        逻辑线程侧的相机模块应在收到 resize 通知后，
        重新计算 proj 并通过 SetViewProjectionCommand 推送。
        """
        if width <= 0 or height <= 0:
            return  # 忽略无效尺寸 (窗口最小化或初始化时可能收到 (0,0))
        cls._pending_resize = (width, height)
        cls.viewport_width = width
        cls.viewport_height = height
        cls.aspect_ratio = width / height

    # ════════════════════════════════════════════════════════════
    # 拾取接口 (main thread 安全, 零 GL 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def pick_at(cls, x: float, y: float) -> tuple:
        """统一拾取 → (type, value)。

        基类默认返回 (None, None) — 不支持拾取的后端无需覆写。
        OpenGL 后端通过 OpenGLPickSystem mixin 覆写, 实现 GPU 拾取。

        Returns:
            ('entity', entity_id) | ('overlay', key) | (None, None)
        """
        return (None, None)

    @classmethod
    def update_pick_mouse(cls, x: float, y: float) -> None:
        """更新鼠标位置用于拾取预读 (main thread, 可选)。

        基类默认空操作 — 不支持拾取的后端无需覆写。
        """
        pass

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

    # ════════════════════════════════════════════════════════════
    # 声明式动态 Uniform 解析 (后端无关)
    # ════════════════════════════════════════════════════════════
    #
    # Overlay 通过 uniforms={'uColor': np.array(...), 'uFadeCenter': 'camera.fade_center'}
    # 声明 uniform 需求，不感知后端类型。
    #
    # 静态值 (np.ndarray / list) → 注册时直接注入 GPU
    # 动态源 (str) → 每帧由渲染器解析为当前值

    # 已知动态 uniform 源 → 解析函数 (返回 np.ndarray)
    _DYNAMIC_UNIFORM_SOURCES: dict = {
        'camera.fade_center':  lambda cls: (
            cls._cam_orbit_target if cls._cam_orbit_target is not None
            else np.zeros(3, 'f4')
        ),
        'camera.fade_radius': lambda cls: cls._resolve_fade_radius(),
    }

    @classmethod
    def _resolve_fade_radius(cls) -> 'np.ndarray':
        """解析 Grid 淡出半径 — 3D 透视用 orbit_distance, 2D 正交用 ortho_size。
        
        在 2D 正交模式下，缩放由 ortho_size 控制而非 orbit_distance，
        因此 fade_radius 需要跟随 ortho_size 动态缩放，
        否则 Grid 在 2D 下拉远时不会像 3D 那样显示更多网格线。
        """
        # ── 2D 正交模式: fade_radius 基于可见区域 ──
        if cls._cam_is_orthographic:
            ortho_size = cls._cam_ortho_size
            aspect = cls.aspect_ratio if hasattr(cls, 'aspect_ratio') else 1.0
            radius = ortho_size * max(aspect, 1.0) * 1.5
            return np.array([radius], 'f4')

        # ── 3D 透视模式: fade_radius = orbit_distance ──
        return np.array([cls._cam_orbit_distance], 'f4')

    @classmethod
    def _resolve_overlay_uniforms(cls, uniforms: dict | None) -> dict[str, 'np.ndarray']:
        """解析 overlay 的声明式 uniform → 当前帧的 np.ndarray 值。

        后端调用此方法获取每帧的 uniform 值，然后用自己的 API 上传到 GPU。
        OpenGL: glUniform*    ZenGL: pipeline.uniforms[name][:] = value

        Args:
            uniforms: overlay.uniforms 字典 (静态值 | 动态源标识符)
        Returns:
            {name: np.ndarray} — 全部解析为具体数值
        """
        if not uniforms:
            return {}
        resolved = {}
        for name, value in uniforms.items():
            if isinstance(value, str) and value in cls._DYNAMIC_UNIFORM_SOURCES:
                try:
                    resolved[name] = cls._DYNAMIC_UNIFORM_SOURCES[value](cls)
                except Exception:
                    resolved[name] = np.zeros(1, 'f4')
            elif isinstance(value, np.ndarray):
                resolved[name] = value
            elif isinstance(value, (list, tuple)):
                resolved[name] = np.array(value, 'f4')
            elif callable(value):
                try:
                    resolved[name] = value()
                except Exception:
                    pass  # 回调失败则跳过, 保留 pipeline 默认值
            # 其他类型静默跳过
        return resolved

    @classmethod
    def _render_overlay_drawables(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """遍历数据驱动 overlay 并绘制 — 子类 (OpenGL/ZenGL) 实现。

        声明式 overlay: Editor 提供纯数据 (overlay_drawable_struct),
        渲染器负责 GPU 上传和绘制 (如 Grid/Gizmo)。

        基类默认空实现, 后端覆盖。
        """
        pass

    @classmethod
    def _render_all_overlays(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """统一 overlay 渲染入口 — 两层渲染。

        渲染顺序 (bottom→top):
          Layer 0: scene-space overlay (Grid) — 深度测试 vs 实体, 不额外清深度
          Clear depth — 为 screen-space overlay 准备
          Layer 1: screen-space overlay (ViewGizmo, TransformGizmo)

        注意:
          - PostProcess (轮廓高亮等) 在 _render_post_process 中执行,
            位于 _RenderEntities 之后、本方法之前。
          - Layer 0 不清深度：Grid 应通过深度测试被实体遮挡，
            Grid 线跟实体同深度时实体在前。
          - Layer 1 清深度：屏幕空间覆盖物（Gizmo）始终最前。
        """
        cls._render_overlay_drawables(view, proj, layer=0)
        cls._clear_depth_for_overlays()
        cls._render_overlay_drawables(view, proj, layer=1)

    @classmethod
    def _clear_depth_for_overlays(cls) -> None:
        """子类覆写: 为 screen-space overlay 清理深度缓冲。"""
        pass


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
            layout         : VertexLayout — 顶点格式描述符 (跨后端)
            ref_count      : 引用计数
        """
        vbo: int
        vao: int
        ebo: int
        elements_count: int
        layout: 'VertexLayout' = None
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
            gl_handle    : GPU 纹理句柄 (OpenGL → GLuint)
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
            key          : 唯一标识符 (如 "editor_grid_lines")
            vertices     : 顶点数组 (N×M, float32)
            indices      : 索引数组 (K, uint32)
            vs_src       : GLSL 顶点着色器源码
            fs_src       : GLSL 片段着色器源码
            draw_mode    : 图元类型标识 ('lines' | 'triangles')
            depth_test   : 是否开启深度测试
            blend        : 是否开启混合
            cull_face    : 是否开启背面剔除
            line_width   : 线宽 (仅 draw_mode='lines' 时有效)
            uniforms_setup: fn(program) — 设置专属 uniform (颜色等)
            ignore_scene_matrices: 不使用场景 view/proj (直接 NDC 渲染)
            model_matrix_cb: fn(w, h) → 4×4 model 矩阵 (仅 ignore_scene_matrices 时)
            texture_pixels: RGBA uint8 纹理像素 (H, W, 4)
            texture_uniform: 片段着色器中 sampler 名称
            vertex_stride : 每顶点字节数 (旧, 建议改用 layout)
            vertex_attrs  : [(location, size_floats, offset_bytes), ...] (旧, 建议改用 layout)
            layout        : VertexLayout — 顶点格式描述符 (新, 优先于 vertex_stride/vertex_attrs)
            pick_type     : 拾取类型 (0=不可拾取, 1=gizmo面, 2=entity, ...)
            pick_id       : 拾取 ID (该类型内唯一, 0~65535)
        """
        key: str
        vertices: 'np.ndarray'
        indices: 'np.ndarray'
        vs_src: str
        fs_src: str
        draw_mode: str = 'lines'
        depth_test: bool = True
        blend: bool = False
        cull_face: bool = False
        line_width: float = 1.0
        uniforms_setup: 'Callable[[int], None]' = None
        ignore_scene_matrices: bool = False
        model_matrix_cb: 'Callable[[int, int], np.ndarray]' = None
        texture_pixels: 'np.ndarray' = None
        texture_uniform: str = ''
        vertex_stride: int = 12
        vertex_attrs: list = None
        layout: 'VertexLayout' = None  # ★ 新: 跨后端顶点格式描述符 (优先于 vertex_stride/vertex_attrs)
        pick_type: int = 0
        pick_id: int = 0
        render_layer: int = 0
        """渲染层级: 0=场景空间 (vs entity depth), 1=屏幕空间 (depth cleared)
        渲染顺序 (bottom→top): Entities → PostProcess → Layer 0 → 深度清理 → Layer 1
        - Grid:      layer=0 (默认, 在实体和后处理之上绘制)
        - ViewGizmo: layer=1 (screen-space, 始终最前)
        - TransformGizmo: layer=1
        """
        uniforms: dict = None
        """声明式 uniform 初始值 (后端无关): {name: value}
        value 类型:
          - np.ndarray / list → 静态值 (颜色, 常量等)，注册时注入 GPU
          - str → 动态源标识符 (如 'camera.fade_center')，渲染器每帧解析
        
        替代 uniforms_setup 回调 — overlay 不应感知后端类型。
        例如: {'uColor': np.array([0.45,0.45,0.45,1.0], 'f4')}
        """

        def __post_init__(self):
            if self.vertex_attrs is None:
                self.vertex_attrs = [(0, 3, 0)]  # 默认: 仅位置 vec3

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
    def _render_overlay_drawables(cls, view: np.ndarray, proj: np.ndarray, layer: int = -1) -> None:
        """遍历 registered_overlays 并提交绘制命令 (子类实现 GPU 绘制)。
        Args:
            view: 4×4 视图矩阵
            proj: 4×4 投影矩阵
            layer: -1=全部, 0=scene, 1=screen
        """
        pass
