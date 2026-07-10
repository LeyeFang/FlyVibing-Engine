"""
vulkanRenderer — Vulkan 渲染器后端 (继承 VulkanCore + VulkanResourceManager)。

特性:
  - 显式 GPU 内存管理 (VkBuffer / VkImage / VkDeviceMemory)
  - 引用计数 GPU 资源管理
  - Push constant 传递 MVP 矩阵 (快速更新)
  - View/Proj 矩阵通过 SetViewProjectionCommand 由逻辑线程推送
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

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Renderer.Vulkan.VulkanCore import VulkanCore
from Application.Core.Renderer.Vulkan.VulkanResourceManager import VulkanResourceManager

import numpy as np
import vulkan as vk


class vulkanRenderer(VulkanCore, VulkanResourceManager, Renderer, RenderResourceManger):
    """Vulkan 渲染器 — 低级图形 API 后端。"""

    @classmethod
    def Create(cls, window=None) -> "vulkanRenderer":
        """初始化 Vulkan 渲染器。

        Args:
            window: Engine 传入的 Window 实例。
        """
        from Application.Core.Renderer.CommandQueue import CommandQueue
        instance = cls()
        if window is not None:
            window_size = window.GetSize()
            native_handle = window.GetNativeHandle()
            VulkanCore.init_core(native_handle, window_size)
        else:
            import glfw as _glfw
            _glfw_win = _glfw.get_current_context()
            if _glfw_win is not None:
                window_size = _glfw.get_framebuffer_size(_glfw_win)
                VulkanCore.init_core(_glfw_win, window_size)
            else:
                window_size = (800, 600)
                VulkanCore.init_core(None, window_size)
        instance.viewport_width = window_size[0]
        instance.viewport_height = window_size[1]
        instance.aspect_ratio = window_size[0] / window_size[1]
        instance._command_queue = CommandQueue()
        return instance

    def _do_start_frame(self) -> None:
        """开始一帧渲染 — acquire → draw entities → present。"""
        if self._pending_resize is not None:
            self._pending_resize = None

        view = self._cached_view
        proj = self._cached_proj
        vp = (proj @ view).astype('float32')

        try:
            image_index = VulkanCore.begin_frame()
        except vk.VkErrorOutOfDateKhr:
            return

        cmd = VulkanCore.cmd_buffer
        renderable_entities = SceneManager.GetRenderableEntities()
        for entity_id in renderable_entities:
            if entity_id not in self.registered_entities:
                continue
            entity = self.registered_entities[entity_id]
            shader_data = self.registered_shaders.get(entity.shader_id)
            mesh_data = self.registered_meshes.get(entity.mesh_id)
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

            model = SceneManager.GetEntityModelMatrix(entity_id)
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

    def EndFrame(self) -> None:
        pass
