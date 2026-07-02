"""
vulkanRenderer — Vulkan 渲染器后端 (继承 VulkanCore + VulkanResourceManager)。

特性:
  - 显式 GPU 内存管理 (VkBuffer / VkImage / VkDeviceMemory)
  - 引用计数 GPU 资源管理
  - Push constant 传递 MVP 矩阵 (快速更新)
  - View/Proj 矩阵缓存 (仅在 SceneCameraUpdateEvent 时重算)
  - 延迟 resize 处理 (后续扩展)

架构:
  vulkanRenderer 继承:
    - VulkanCore            : Instance / Device / SwapChain / 渲染流程
    - VulkanResourceManager : Mesh / Shader / Texture / Entity 注册与管理
    - Renderer              : 生命周期接口
    - RenderResourceManger  : 资源管理抽象接口

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Core.Engine import Engine

from Application.Core.Events.Event import Event
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.RenderCommand import (
    CameraUpdateCommand,
)
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Renderer.Vulkan.VulkanCore import VulkanCore
from Application.Core.Renderer.Vulkan.VulkanResourceManager import VulkanResourceManager
from Application.Core.Math.Transform import calculate_entity_model

import numpy as np
import vulkan as vk


class vulkanRenderer(VulkanCore, VulkanResourceManager, Renderer, RenderResourceManger):
    """Vulkan 渲染器 — 低级图形 API 后端。"""

    @classmethod
    def Create(cls) -> "vulkanRenderer":
        """初始化 Vulkan 渲染器。"""
        from Application.Editor.EditorHost import EditorHost
        window_size = EditorHost.editor_window.GetSize()
        VulkanCore.init_core(EditorHost.editor_window.glfw_window, window_size)
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]
        # ── 缓存初始相机矩阵 (由 set_active_camera 在 OnAttach 中设置) ──
        if cls._active_camera is not None:
            cls._cached_view = cls._active_camera.get_view_matrix()
            cls._cached_proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)
        cls._command_queue = CommandQueue()
        return cls

    @classmethod
    def _do_start_frame(cls) -> None:
        """开始一帧渲染 — acquire → draw entities → present。"""
        if cls._pending_resize is not None:
            cls._pending_resize = None

        view = cls._cached_view
        proj = cls._cached_proj
        vp = (proj @ view).astype('float32')

        try:
            image_index = VulkanCore.begin_frame()
        except vk.VkErrorOutOfDateKhr:
            return

        cmd = VulkanCore.cmd_buffer
        renderable_entities = SceneManager.GetRenderableEntities()
        for entity_id in renderable_entities:
            if entity_id not in cls.registered_entities:
                continue
            entity = cls.registered_entities[entity_id]
            shader_data = cls.registered_shaders.get(entity.shader_id)
            mesh_data = cls.registered_meshes.get(entity.mesh_id)
            if shader_data is None or mesh_data is None:
                continue

            vk.vkCmdBindPipeline(cmd, vk.VK_PIPELINE_BIND_POINT_GRAPHICS, shader_data.pipeline)
            vk.vkCmdBindVertexBuffers(cmd, 0, 1, [mesh_data.vertex_buffer], [0])
            vk.vkCmdBindIndexBuffer(cmd, mesh_data.index_buffer, 0, vk.VK_INDEX_TYPE_UINT32)

            if entity.descriptor_set is not None:
                vk.vkCmdBindDescriptorSets(
                    cmd, vk.VK_PIPELINE_BIND_POINT_GRAPHICS,
                    shader_data.pipeline_layout, 0, 1, [entity.descriptor_set], 0, None,
                )

            model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))
            mvp = (vp @ model).astype('float32')
            # push constant 必须传 CFFI float 数组，不能传 bytes
            vk.vkCmdPushConstants(
                cmd, shader_data.pipeline_layout,
                vk.VK_SHADER_STAGE_VERTEX_BIT | vk.VK_SHADER_STAGE_FRAGMENT_BIT,
                0, 64,
                vk.ffi.new("float[]", mvp.T.flatten().tolist()),
            )
            vk.vkCmdDrawIndexed(cmd, mesh_data.elements_count, 1, 0, 0, 0)

        VulkanCore.end_scene_pass()
        VulkanCore.end_frame(image_index)

    @classmethod
    def EndFrame(cls) -> None:
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        """事件处理 — enqueue 命令到队列，由 StartFrame 消费。

        注意:
          - 窗口 resize 已改为直接 Command (glfwWindow 回调中提交)。
          - 实体注册/解注册使用 renderer.enqueue(EntityRegistrationCommand(...))。
        """
        if isinstance(event, SceneCameraUpdateEvent):
            cls.enqueue(CameraUpdateCommand())
