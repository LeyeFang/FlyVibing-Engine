"""
VulkanCore — Vulkan 核心基础设施 (Instance / Device / SwapChain / 渲染管线基础)。

职责:
  - Vulkan 实例/设备/队列的创建与销毁
  - KHR 扩展函数的动态加载
  - 交换链 (SwapChain) 的创建与重建
  - 渲染通道 (RenderPass) 与帧缓冲 (Framebuffer)
  - 命令池/命令缓冲管理
  - GPU 内存分配辅助 (Buffer / Image / 内存类型)
  - 着色器模块编译 (GLSL → SPIR-V via glslc)
  - DescriptorSetLayout / PipelineLayout 创建
  - 帧同步原语 (Semaphore / Fence)
  - StartFrame / EndFrame 渲染流程

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import subprocess
import shutil
import tempfile
import os
import numpy as np
import vulkan as vk
from dataclasses import dataclass


class VulkanCore:
    """Vulkan 核心 — 管理 Instance / Device / SwapChain / 渲染管线基础设施。"""

    # ── Vulkan 核心对象 ──
    instance: object = None               # VkInstance
    physical_device: object = None        # VkPhysicalDevice
    device: object = None                 # VkDevice
    graphics_queue: object = None         # VkQueue
    graphics_family: int = -1             # 队列族索引

    # ── 表面 & 交换链 ──
    surface: object = None                # VkSurfaceKHR
    swapchain: object = None              # VkSwapchainKHR
    swapchain_images: list = []           # list[VkImage]
    swapchain_image_views: list = []      # list[VkImageView]
    swapchain_format: int = None          # VkFormat
    swapchain_width: int = 0              # int
    swapchain_height: int = 0             # int
    render_pass: object = None            # VkRenderPass
    framebuffers: list = []               # list[VkFramebuffer]

    # ── 命令 ──
    cmd_pool: object = None               # VkCommandPool
    cmd_buffer: object = None             # VkCommandBuffer (单缓冲，每帧录制)

    # ── 同步 ──
    image_available_sems: list = []     # list[VkSemaphore] — 每个交换链图像一个
    render_finished_sems: list = []     # list[VkSemaphore]
    frame_fences: list = []             # list[VkFence] — 每个交换链图像一个
    current_frame: int = 0              # 当前帧索引 (循环递增)
    _current_image_index: int = 0       # 当前 swapchain image 索引

    # ── 描述符池 (全局共享) ──
    descriptor_pool: object = None        # VkDescriptorPool
    imgui_descriptor_pool: object = None  # VkDescriptorPool (ImGui 专用)
    _imgui_initialized: bool = False

    # ── glslc 编译器路径缓存 ──
    _glslc_path: str = None

    # ════════════════════════════════════════════════════════════
    # KHR 扩展函数 (通过 vkGetInstanceProcAddr / vkGetDeviceProcAddr 加载)
    # ════════════════════════════════════════════════════════════

    # 实例级
    _vkDestroySurfaceKHR = None
    _vkGetPhysicalDeviceSurfaceCapabilitiesKHR = None
    _vkGetPhysicalDeviceSurfaceFormatsKHR = None
    _vkGetPhysicalDeviceSurfacePresentModesKHR = None
    _vkCreateWin32SurfaceKHR = None

    # 设备级
    _vkCreateSwapchainKHR = None
    _vkDestroySwapchainKHR = None
    _vkGetSwapchainImagesKHR = None
    _vkAcquireNextImageKHR = None
    _vkQueuePresentKHR = None

    # ════════════════════════════════════════════════════════════
    # 初始化与销毁
    # ════════════════════════════════════════════════════════════

    def init_core(
        self,
        window_handle,
        window_size: tuple[int, int]
    ) -> None:
        """初始化 Vulkan 核心基础设施。

        执行顺序:
          1. 创建 VkInstance (含验证层)
          2. 选择物理设备 (优先独立 GPU)
          3. 创建 VkDevice + 获取图形队列
          4. 加载 KHR 扩展函数
          5. 创建窗口表面 (VkSurfaceKHR)
          6. 创建交换链 + 图像视图
          7. 创建渲染通道 + 帧缓冲
          8. 创建命令池 + 命令缓冲
          9. 创建同步对象
          10. 创建全局描述符池

        Args:
            window_handle: GLFW window 对象 (用于创建 surface)
            window_size  : (width, height) 初始窗口尺寸
        """
        # ① 创建 Vulkan 实例
        self._create_instance()

        # ② 选择物理设备
        self._pick_physical_device()

        # ③ 创建逻辑设备 + 获取队列
        self._create_device()

        # ④ 加载 KHR 扩展函数
        self._load_khr_functions()

        # ⑤ 创建窗口表面
        self._create_surface(window_handle)

        # ⑥ 创建交换链
        self._create_swapchain(window_size)

        # ⑦ 创建渲染通道
        self._create_render_pass()

        # ⑧ 创建帧缓冲
        self._create_framebuffers()

        # ⑨ 创建命令池与命令缓冲
        self._create_command_pool()

        # ⑩ 创建同步对象
        self._create_sync_objects()

        # ⑪ 创建全局描述符池
        self._create_descriptor_pool()

        # GPU info logged via event system

    def destroy_core(self) -> None:
        """销毁所有 Vulkan 核心对象 (按创建逆序)。"""
        if self.device is not None:
            vk.vkDeviceWaitIdle(self.device)

            # 同步对象 (每个 swapchain image 一组)
            for sem in self.image_available_sems:
                vk.vkDestroySemaphore(self.device, sem, None)
            for sem in self.render_finished_sems:
                vk.vkDestroySemaphore(self.device, sem, None)
            for fence in self.frame_fences:
                vk.vkDestroyFence(self.device, fence, None)

            # 命令池
            if self.cmd_pool is not None:
                vk.vkDestroyCommandPool(self.device, self.cmd_pool, None)

            # 描述符池
            if self.descriptor_pool is not None:
                vk.vkDestroyDescriptorPool(self.device, self.descriptor_pool, None)

            # 帧缓冲
            for fb in self.framebuffers:
                vk.vkDestroyFramebuffer(self.device, fb, None)
            self.framebuffers.clear()

            # 渲染通道
            if self.render_pass is not None:
                vk.vkDestroyRenderPass(self.device, self.render_pass, None)

            # 图像视图
            for view in self.swapchain_image_views:
                vk.vkDestroyImageView(self.device, view, None)
            self.swapchain_image_views.clear()

            # 交换链
            if self.swapchain is not None:
                self._vkDestroySwapchainKHR(self.device, self.swapchain, None)

            # 逻辑设备
            vk.vkDestroyDevice(self.device, None)

        # 表面
        if self.surface is not None and self.instance is not None:
            self._vkDestroySurfaceKHR(self.instance, self.surface, None)

        # 实例
        if self.instance is not None:
            vk.vkDestroyInstance(self.instance, None)

    # ════════════════════════════════════════════════════════════
    # 帧循环 — StartFrame / EndFrame
    # ════════════════════════════════════════════════════════════

    def begin_frame(self) -> int:
        """开始一帧渲染 — 获取交换链图像并开始录制命令。

        Returns:
            当前帧的交换链图像索引 (用于选择 framebuffer)
        """
        # 等待当前帧的 fence
        vk.vkWaitForFences(self.device, 1, [self.frame_fences[self.current_frame]], vk.VK_TRUE, int(1e9))
        vk.vkResetFences(self.device, 1, [self.frame_fences[self.current_frame]])

        # 获取交换链图像
        try:
            image_index = self._vkAcquireNextImageKHR(
                self.device, self.swapchain, int(1e9),
                self.image_available_sems[self.current_frame], vk.VK_NULL_HANDLE
            )
        except vk.VkErrorOutOfDateKhr:
            # 窗口大小改变需要重建交换链 (后续扩展)
            raise

        # 开始录制命令缓冲
        vk.vkResetCommandBuffer(self.cmd_buffer, 0)
        begin_info = vk.VkCommandBufferBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            flags=vk.VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        )
        vk.vkBeginCommandBuffer(self.cmd_buffer, begin_info)

        # 开始渲染通道
        clear_color = [vk.VkClearValue(color=vk.VkClearColorValue(
            float32=[0.2, 0.2, 0.2, 1.0]
        ))]
        render_pass_begin = vk.VkRenderPassBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
            renderPass=self.render_pass,
            framebuffer=self.framebuffers[image_index],
            renderArea=vk.VkRect2D(
                offset=vk.VkOffset2D(x=0, y=0),
                extent=vk.VkExtent2D(width=self.swapchain_width, height=self.swapchain_height),
            ),
            clearValueCount=1,
            pClearValues=clear_color,
        )
        vk.vkCmdBeginRenderPass(
            self.cmd_buffer, render_pass_begin, vk.VK_SUBPASS_CONTENTS_INLINE
        )

        # 设置视口和剪刀
        viewport = vk.VkViewport(
            x=0, y=0,
            width=float(self.swapchain_width), height=float(self.swapchain_height),
            minDepth=0.0, maxDepth=1.0,
        )
        scissor = vk.VkRect2D(
            offset=vk.VkOffset2D(x=0, y=0),
            extent=vk.VkExtent2D(width=self.swapchain_width, height=self.swapchain_height),
        )
        vk.vkCmdSetViewport(self.cmd_buffer, 0, 1, [viewport])
        vk.vkCmdSetScissor(self.cmd_buffer, 0, 1, [scissor])

        self._current_image_index = image_index
        return image_index

    def end_scene_pass(self) -> None:
        """结束场景渲染通道 (必须在 ImGui 渲染之前调用)。"""
        vk.vkCmdEndRenderPass(self.cmd_buffer)

    def end_frame(self, image_index: int) -> None:
        """结束一帧 — 结束命令缓冲、提交、呈现。"""
        vk.vkEndCommandBuffer(self.cmd_buffer)

        # 提交
        submit_info = vk.VkSubmitInfo(
            sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO,
            waitSemaphoreCount=1,
            pWaitSemaphores=[self.image_available_sems[self.current_frame]],
            pWaitDstStageMask=[vk.VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT],
            commandBufferCount=1,
            pCommandBuffers=[self.cmd_buffer],
            signalSemaphoreCount=1,
            pSignalSemaphores=[self.render_finished_sems[self.current_frame]],
        )
        vk.vkQueueSubmit(self.graphics_queue, 1, [submit_info], self.frame_fences[self.current_frame])

        # 呈现
        present_info = vk.VkPresentInfoKHR(
            sType=vk.VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
            waitSemaphoreCount=1,
            pWaitSemaphores=[self.render_finished_sems[self.current_frame]],
            swapchainCount=1,
            pSwapchains=[self.swapchain],
            pImageIndices=[image_index],
        )
        try:
            self._vkQueuePresentKHR(self.graphics_queue, present_info)
        except vk.VkErrorOutOfDateKhr:
            pass

        self.current_frame = (self.current_frame + 1) % len(self.swapchain_images)        

    # ════════════════════════════════════════════════════════════
    # Vulkan 核心初始化
    # ════════════════════════════════════════════════════════════

    def _create_instance(self) -> None:
        """创建 VkInstance — 启用验证层 + GLFW surface 扩展。"""
        import glfw
        app_info = vk.VkApplicationInfo(
            sType=vk.VK_STRUCTURE_TYPE_APPLICATION_INFO,
            pApplicationName=b"GameEngine",
            applicationVersion=vk.VK_MAKE_VERSION(1, 0, 0),
            pEngineName=b"CustomEngine",
            engineVersion=vk.VK_MAKE_VERSION(1, 0, 0),
            apiVersion=vk.VK_API_VERSION_1_0,
        )
        validation_layers = [b"VK_LAYER_KHRONOS_validation"]
        glfw_extensions = glfw.get_required_instance_extensions()

        create_info = vk.VkInstanceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
            pApplicationInfo=app_info,
            enabledLayerCount=len(validation_layers),
            ppEnabledLayerNames=validation_layers,
            enabledExtensionCount=len(glfw_extensions),
            ppEnabledExtensionNames=glfw_extensions,
        )
        self.instance = vk.vkCreateInstance(create_info, None)

    def _pick_physical_device(self) -> None:
        """选择物理设备 — 优先独立 GPU，否则回退到第一个可用设备。"""
        devices = vk.vkEnumeratePhysicalDevices(self.instance)
        if not devices:
            raise RuntimeError("未找到支持 Vulkan 的 GPU")

        for device in devices:
            props = vk.vkGetPhysicalDeviceProperties(device)
            if props.deviceType == vk.VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:
                self.physical_device = device
                return

        self.physical_device = devices[0]

    def _create_device(self) -> None:
        """创建 VkDevice 并获取图形队列，启用 swapchain 扩展。"""
        queue_families = vk.vkGetPhysicalDeviceQueueFamilyProperties(
            self.physical_device
        )
        self.graphics_family = -1
        for i, qf in enumerate(queue_families):
            if qf.queueFlags & vk.VK_QUEUE_GRAPHICS_BIT:
                self.graphics_family = i
                break
        if self.graphics_family < 0:
            raise RuntimeError("未找到支持图形的队列族")

        queue_create_info = vk.VkDeviceQueueCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            queueFamilyIndex=self.graphics_family,
            queueCount=1,
            pQueuePriorities=[1.0],
        )
        device_create_info = vk.VkDeviceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            queueCreateInfoCount=1,
            pQueueCreateInfos=[queue_create_info],
            enabledExtensionCount=1,
            ppEnabledExtensionNames=[vk.VK_KHR_SWAPCHAIN_EXTENSION_NAME],
        )
        self.device = vk.vkCreateDevice(
            self.physical_device, device_create_info, None
        )
        self.graphics_queue = vk.vkGetDeviceQueue(
            self.device, self.graphics_family, 0
        )

    def _load_khr_functions(self) -> None:
        """加载 KHR 扩展函数 (实例级 + 设备级)。"""
        # 实例级
        self._vkDestroySurfaceKHR = vk.vkGetInstanceProcAddr(
            self.instance, 'vkDestroySurfaceKHR'
        )
        self._vkGetPhysicalDeviceSurfaceCapabilitiesKHR = vk.vkGetInstanceProcAddr(
            self.instance, 'vkGetPhysicalDeviceSurfaceCapabilitiesKHR'
        )
        self._vkGetPhysicalDeviceSurfaceFormatsKHR = vk.vkGetInstanceProcAddr(
            self.instance, 'vkGetPhysicalDeviceSurfaceFormatsKHR'
        )
        self._vkGetPhysicalDeviceSurfacePresentModesKHR = vk.vkGetInstanceProcAddr(
            self.instance, 'vkGetPhysicalDeviceSurfacePresentModesKHR'
        )
        self._vkCreateWin32SurfaceKHR = vk.vkGetInstanceProcAddr(
            self.instance, 'vkCreateWin32SurfaceKHR'
        )

        # 设备级
        self._vkCreateSwapchainKHR = vk.vkGetDeviceProcAddr(
            self.device, 'vkCreateSwapchainKHR'
        )
        self._vkDestroySwapchainKHR = vk.vkGetDeviceProcAddr(
            self.device, 'vkDestroySwapchainKHR'
        )
        self._vkGetSwapchainImagesKHR = vk.vkGetDeviceProcAddr(
            self.device, 'vkGetSwapchainImagesKHR'
        )
        self._vkAcquireNextImageKHR = vk.vkGetDeviceProcAddr(
            self.device, 'vkAcquireNextImageKHR'
        )
        self._vkQueuePresentKHR = vk.vkGetDeviceProcAddr(
            self.device, 'vkQueuePresentKHR'
        )

    def _create_surface(self, window_handle) -> None:
        """创建窗口表面 — 使用 Win32 原生接口 (绕过 GLFW 绑定的兼容问题)。"""
        import glfw
        import ctypes
        hwnd = glfw.get_win32_window(window_handle)
        hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        surface_info = vk.VkWin32SurfaceCreateInfoKHR(
            sType=vk.VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR,
            hinstance=hinstance,
            hwnd=hwnd,
        )
        self.surface = self._vkCreateWin32SurfaceKHR(self.instance, surface_info, None)

    def _create_swapchain(self, window_size: tuple[int, int]) -> None:
        """创建交换链 + 图像视图。

        Args:
            window_size: (width, height) 窗口尺寸
        """
        caps = self._vkGetPhysicalDeviceSurfaceCapabilitiesKHR(
            self.physical_device, self.surface
        )
        formats = self._vkGetPhysicalDeviceSurfaceFormatsKHR(
            self.physical_device, self.surface
        )
        present_modes = self._vkGetPhysicalDeviceSurfacePresentModesKHR(
            self.physical_device, self.surface
        )

        # 选择格式: 优先 SRGB，否则第一个
        surf_format = formats[0]
        for fmt in formats:
            if fmt.format == vk.VK_FORMAT_B8G8R8A8_SRGB:
                surf_format = fmt
                break

        # 选择呈现模式: 优先 MAILBOX (低延迟)，否则 FIFO
        present_mode = vk.VK_PRESENT_MODE_FIFO_KHR
        for mode in present_modes:
            if mode == vk.VK_PRESENT_MODE_MAILBOX_KHR:
                present_mode = mode
                break

        self.swapchain_format = surf_format.format
        # 直接用窗口尺寸作为 swapchain extent
        self.swapchain_width = window_size[0]
        self.swapchain_height = window_size[1]

        image_count = max(2, caps.minImageCount)
        if caps.maxImageCount > 0:
            image_count = min(image_count, caps.maxImageCount)

        swapchain_info = vk.VkSwapchainCreateInfoKHR(
            sType=vk.VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
            surface=self.surface,
            minImageCount=image_count,
            imageFormat=self.swapchain_format,
            imageColorSpace=surf_format.colorSpace,
            imageExtent=vk.VkExtent2D(width=self.swapchain_width, height=self.swapchain_height),
            imageArrayLayers=1,
            imageUsage=vk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
            imageSharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
            preTransform=caps.currentTransform,
            compositeAlpha=vk.VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
            presentMode=present_mode,
            clipped=vk.VK_TRUE,
        )
        self.swapchain = self._vkCreateSwapchainKHR(
            self.device, swapchain_info, None
        )
        self.swapchain_images = self._vkGetSwapchainImagesKHR(
            self.device, self.swapchain
        )

        # 创建图像视图
        self.swapchain_image_views = []
        for img in self.swapchain_images:
            view_info = vk.VkImageViewCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
                image=img,
                viewType=vk.VK_IMAGE_VIEW_TYPE_2D,
                format=self.swapchain_format,
                components=vk.VkComponentMapping(
                    r=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                    g=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                    b=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                    a=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                ),
                subresourceRange=vk.VkImageSubresourceRange(
                    aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                    baseMipLevel=0, levelCount=1,
                    baseArrayLayer=0, layerCount=1,
                ),
            )
            self.swapchain_image_views.append(
                vk.vkCreateImageView(self.device, view_info, None)
            )

    def _create_render_pass(self) -> None:
        """创建渲染通道 — 单颜色附件，适合简单前向渲染。"""
        color_attachment = vk.VkAttachmentDescription(
            format=self.swapchain_format,
            samples=vk.VK_SAMPLE_COUNT_1_BIT,
            loadOp=vk.VK_ATTACHMENT_LOAD_OP_CLEAR,
            storeOp=vk.VK_ATTACHMENT_STORE_OP_STORE,
            stencilLoadOp=vk.VK_ATTACHMENT_LOAD_OP_DONT_CARE,
            stencilStoreOp=vk.VK_ATTACHMENT_STORE_OP_DONT_CARE,
            initialLayout=vk.VK_IMAGE_LAYOUT_UNDEFINED,
            finalLayout=vk.VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
        )
        color_ref = vk.VkAttachmentReference(
            attachment=0,
            layout=vk.VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        )
        subpass = vk.VkSubpassDescription(
            pipelineBindPoint=vk.VK_PIPELINE_BIND_POINT_GRAPHICS,
            colorAttachmentCount=1,
            pColorAttachments=[color_ref],
        )
        # 子通道依赖 (确保渲染顺序)
        dependency = vk.VkSubpassDependency(
            srcSubpass=vk.VK_SUBPASS_EXTERNAL,
            dstSubpass=0,
            srcStageMask=vk.VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            dstStageMask=vk.VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            srcAccessMask=0,
            dstAccessMask=vk.VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
        )
        render_pass_info = vk.VkRenderPassCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
            attachmentCount=1,
            pAttachments=[color_attachment],
            subpassCount=1,
            pSubpasses=[subpass],
            dependencyCount=1,
            pDependencies=[dependency],
        )
        self.render_pass = vk.vkCreateRenderPass(self.device, render_pass_info, None)

    def _create_framebuffers(self) -> None:
        """为每个交换链图像创建帧缓冲。"""
        self.framebuffers = []
        for view in self.swapchain_image_views:
            fb_info = vk.VkFramebufferCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
                renderPass=self.render_pass,
                attachmentCount=1,
                pAttachments=[view],
                width=self.swapchain_width, height=self.swapchain_height,
                layers=1,
            )
            self.framebuffers.append(
                vk.vkCreateFramebuffer(self.device, fb_info, None)
            )

    def _create_command_pool(self) -> None:
        """创建命令池 + 分配主命令缓冲。"""
        pool_info = vk.VkCommandPoolCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            queueFamilyIndex=self.graphics_family,
            flags=vk.VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
        )
        self.cmd_pool = vk.vkCreateCommandPool(self.device, pool_info, None)

        cmd_buf_info = vk.VkCommandBufferAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            commandPool=self.cmd_pool,
            level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            commandBufferCount=1,
        )
        self.cmd_buffer = vk.vkAllocateCommandBuffers(self.device, cmd_buf_info)[0]

    def _create_sync_objects(self) -> None:
        """创建帧同步对象 — 每个交换链图像一组 (信号量 + Fence)。"""
        sem_info = vk.VkSemaphoreCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO
        )
        fence_info = vk.VkFenceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
            flags=vk.VK_FENCE_CREATE_SIGNALED_BIT,
        )
        n = len(self.swapchain_images)
        self.image_available_sems = [vk.vkCreateSemaphore(self.device, sem_info, None) for _ in range(n)]
        self.render_finished_sems = [vk.vkCreateSemaphore(self.device, sem_info, None) for _ in range(n)]
        self.frame_fences = [vk.vkCreateFence(self.device, fence_info, None) for _ in range(n)]

    def _create_descriptor_pool(self) -> None:
        """创建全局描述符池 (支持 Uniform Buffer + Combined Image Sampler)。"""
        pool_sizes = [
            vk.VkDescriptorPoolSize(
                type=vk.VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,
                descriptorCount=100,
            ),
            vk.VkDescriptorPoolSize(
                type=vk.VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                descriptorCount=100,
            ),
        ]
        pool_info = vk.VkDescriptorPoolCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
            maxSets=100,
            poolSizeCount=len(pool_sizes),
            pPoolSizes=pool_sizes,
        )
        self.descriptor_pool = vk.vkCreateDescriptorPool(
            self.device, pool_info, None
        )

    def _get_device_name(self) -> str:
        """获取物理设备名称。"""
        if self.physical_device is None:
            return "Unknown"
        props = vk.vkGetPhysicalDeviceProperties(self.physical_device)
        name = props.deviceName
        return name.decode('utf-8', errors='replace') if isinstance(name, bytes) else name

    # ════════════════════════════════════════════════════════════
    # ImGui Vulkan 集成
    # ════════════════════════════════════════════════════════════

    def init_imgui(self) -> None:
        """初始化 ImGui Vulkan 后端 (GLFW 已由 ImguiLayer 初始化)。"""
        if self._imgui_initialized:
            return

        from imgui_bundle import imgui

        # 创建 ImGui 专用描述符池
        pool_sizes = [
            vk.VkDescriptorPoolSize(type=vk.VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, descriptorCount=1),
        ]
        pool_info = vk.VkDescriptorPoolCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
            maxSets=1,
            poolSizeCount=len(pool_sizes),
            pPoolSizes=pool_sizes,
        )
        self.imgui_descriptor_pool = vk.vkCreateDescriptorPool(self.device, pool_info, None)

        # 初始化 ImGui Vulkan 后端
        init_info = imgui.backends.VulkanInitInfo(
            instance=self.instance,
            physical_device=self.physical_device,
            device=self.device,
            queue_family=self.graphics_family,
            queue=self.graphics_queue,
            descriptor_pool=self.imgui_descriptor_pool,
            render_pass=self.render_pass,
            min_image_count=2,
            image_count=len(self.swapchain_images),
        )
        imgui.backends.vulkan_init(init_info)
        imgui.backends.vulkan_create_fonts_texture()
        self._imgui_initialized = True

    def render_imgui(self, draw_data, image_index: int) -> None:
        """在命令缓冲中渲染 ImGui (必须在 end_scene_pass 之后调用)。
        
        Args:
            draw_data: imgui.get_draw_data() 返回的绘制数据
            image_index: 当前 swapchain image 索引
        """
        if draw_data is None:
            return

        from imgui_bundle import imgui

        # 为 ImGui 开启一个新的渲染通道 (loadOp=LOAD 保留场景内容)
        clear_color = [vk.VkClearValue(color=vk.VkClearColorValue(float32=[0.0, 0.0, 0.0, 1.0]))]
        render_pass_begin = vk.VkRenderPassBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
            renderPass=self.render_pass,
            framebuffer=self.framebuffers[image_index],
            renderArea=vk.VkRect2D(
                offset=vk.VkOffset2D(x=0, y=0),
                extent=vk.VkExtent2D(width=self.swapchain_width, height=self.swapchain_height),
            ),
            clearValueCount=1,
            pClearValues=clear_color,
        )
        vk.vkCmdBeginRenderPass(self.cmd_buffer, render_pass_begin, vk.VK_SUBPASS_CONTENTS_INLINE)

        imgui.backends.vulkan_render_draw_data(draw_data, self.cmd_buffer)

        vk.vkCmdEndRenderPass(self.cmd_buffer)

    # ════════════════════════════════════════════════════════════
    # GPU 内存管理
    # ════════════════════════════════════════════════════════════

    def _find_memory_type(
        self,
        type_filter: int,
        properties: int
    ) -> int:
        """查找满足属性要求的内存类型索引。"""
        mem_props = vk.vkGetPhysicalDeviceMemoryProperties(self.physical_device)
        for i in range(mem_props.memoryTypeCount):
            if (type_filter & (1 << i)) and \
               (mem_props.memoryTypes[i].propertyFlags & properties) == properties:
                return i
        raise RuntimeError("未找到满足要求的 Vulkan 内存类型")

    def create_buffer(
        self,
        size: int,
        usage: int,
        properties: int
    ) -> tuple[object, object]:
        """创建 VkBuffer + VkDeviceMemory。

        Returns:
            (VkBuffer, VkDeviceMemory)
        """
        buffer_info = vk.VkBufferCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            size=size,
            usage=usage,
            sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
        )
        buf = vk.vkCreateBuffer(self.device, buffer_info, None)

        mem_reqs = vk.vkGetBufferMemoryRequirements(self.device, buf)
        alloc_info = vk.VkMemoryAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            allocationSize=mem_reqs.size,
            memoryTypeIndex=self._find_memory_type(
                mem_reqs.memoryTypeBits, properties
            ),
        )
        mem = vk.vkAllocateMemory(self.device, alloc_info, None)
        vk.vkBindBufferMemory(self.device, buf, mem, 0)
        return buf, mem

    def destroy_buffer(self, buf, mem) -> None:
        """销毁 VkBuffer 并释放关联的 VkDeviceMemory。"""
        if buf is not None:
            vk.vkDestroyBuffer(self.device, buf, None)
        if mem is not None:
            vk.vkFreeMemory(self.device, mem, None)

    def create_image(
        self,
        width: int,
        height: int,
        fmt: int,
        usage: int,
        properties: int
    ) -> tuple[object, object]:
        """创建 VkImage + VkDeviceMemory (2D 纹理)。

        Returns:
            (VkImage, VkDeviceMemory)
        """
        image_info = vk.VkImageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            imageType=vk.VK_IMAGE_TYPE_2D,
            extent=vk.VkExtent3D(width, height, 1),
            mipLevels=1,
            arrayLayers=1,
            format=fmt,
            tiling=vk.VK_IMAGE_TILING_OPTIMAL,
            initialLayout=vk.VK_IMAGE_LAYOUT_UNDEFINED,
            usage=usage,
            sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
            samples=vk.VK_SAMPLE_COUNT_1_BIT,
        )
        image = vk.vkCreateImage(self.device, image_info, None)

        mem_reqs = vk.vkGetImageMemoryRequirements(self.device, image)
        alloc_info = vk.VkMemoryAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            allocationSize=mem_reqs.size,
            memoryTypeIndex=self._find_memory_type(
                mem_reqs.memoryTypeBits, properties
            ),
        )
        mem = vk.vkAllocateMemory(self.device, alloc_info, None)
        vk.vkBindImageMemory(self.device, image, mem, 0)
        return image, mem

    def create_image_view(self, image, fmt: int) -> object:
        """为 VkImage 创建默认 2D ImageView。"""
        view_info = vk.VkImageViewCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
            image=image,
            viewType=vk.VK_IMAGE_VIEW_TYPE_2D,
            format=fmt,
            subresourceRange=vk.VkImageSubresourceRange(
                aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                baseMipLevel=0, levelCount=1,
                baseArrayLayer=0, layerCount=1,
            ),
        )
        return vk.vkCreateImageView(self.device, view_info, None)

    def create_sampler(self) -> object:
        """创建默认纹理采样器 (线性过滤 + 重复寻址)。"""
        sampler_info = vk.VkSamplerCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
            magFilter=vk.VK_FILTER_LINEAR,
            minFilter=vk.VK_FILTER_LINEAR,
            mipmapMode=vk.VK_SAMPLER_MIPMAP_MODE_LINEAR,
            addressModeU=vk.VK_SAMPLER_ADDRESS_MODE_REPEAT,
            addressModeV=vk.VK_SAMPLER_ADDRESS_MODE_REPEAT,
            addressModeW=vk.VK_SAMPLER_ADDRESS_MODE_REPEAT,
            maxLod=1.0,
        )
        return vk.vkCreateSampler(self.device, sampler_info, None)

    def copy_to_buffer(
        self,
        memory: object,
        data: bytes,
        offset: int = 0
    ) -> None:
        """将 CPU 数据写入 HOST_VISIBLE GPU 内存 (vkMapMemory 返回 CFFI buffer，用 numpy 写入)。"""
        mapped = vk.vkMapMemory(self.device, memory, offset, len(data), 0)
        # mapped 是 CFFI buffer 对象，通过 numpy 写入
        mapped_arr = np.frombuffer(mapped, dtype=np.uint8)
        mapped_arr[:] = np.frombuffer(data, dtype=np.uint8)
        vk.vkUnmapMemory(self.device, memory)

    # ════════════════════════════════════════════════════════════
    # 着色器编译
    # ════════════════════════════════════════════════════════════

    def _find_glslc(self) -> str:
        """查找 glslc 编译器路径 (缓存结果)。

        Returns:
            glslc.exe 的完整路径

        Raises:
            RuntimeError: 未找到 glslc
        """
        if self._glslc_path is not None:
            return self._glslc_path

        # ① 尝试 PATH
        glslc = shutil.which('glslc')
        if glslc:
            self._glslc_path = glslc
            return glslc

        # ② 搜索常见 Vulkan SDK 路径
        candidates = [
            os.path.join(os.environ.get('VULKAN_SDK', ''), 'Bin', 'glslc.exe'),
        ]
        # 搜索 Program Files
        for base in [r'C:\VulkanSDK', r'C:\Program Files\VulkanSDK']:
            if os.path.isdir(base):
                for ver in sorted(os.listdir(base), reverse=True):
                    path = os.path.join(base, ver, 'Bin', 'glslc.exe')
                    if os.path.isfile(path):
                        self._glslc_path = path
                        return path

        for cand in candidates:
            if os.path.isfile(cand):
                self._glslc_path = cand
                return cand

        raise RuntimeError(
            "未找到 glslc 编译器。请安装 Vulkan SDK 或将 glslc 添加到 PATH。"
        )

    def compile_glsl_to_spirv(self, glsl_source: str, stage_name: str) -> bytes:
        """将 GLSL 源码编译为 SPIR-V 字节码。

        Args:
            glsl_source: GLSL 源码字符串
            stage_name : 'vertex' 或 'fragment'

        Returns:
            SPIR-V 二进制字节码

        Raises:
            RuntimeError: 编译失败
        """
        glslc = self._find_glslc()

        # 写入临时文件
        suffix = '.vert' if stage_name == 'vertex' else '.frag'
        with tempfile.NamedTemporaryFile(
            mode='w', suffix=suffix, delete=False, encoding='utf-8'
        ) as f:
            f.write(glsl_source)
            src_path = f.name

        spv_path = src_path + '.spv'
        try:
            result = subprocess.run(
                [glslc, src_path, '-o', spv_path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"SPIR-V 编译失败 ({stage_name}):\n{result.stderr}"
                )
            with open(spv_path, 'rb') as f:
                return f.read()
        finally:
            # 清理临时文件
            for p in (src_path, spv_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def create_shader_module(self, spirv_code: bytes) -> object:
        """从 SPIR-V 字节码创建 VkShaderModule。"""
        module_info = vk.VkShaderModuleCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
            codeSize=len(spirv_code),
            pCode=spirv_code,
        )
        return vk.vkCreateShaderModule(self.device, module_info, None)

    # ════════════════════════════════════════════════════════════
    # DescriptorSetLayout / PipelineLayout
    # ════════════════════════════════════════════════════════════

    def create_descriptor_set_layout(
        self,
        uniforms_name_type: dict
    ) -> object:
        """从 uniform 定义创建 VkDescriptorSetLayout — sampler2D 固定 binding=0。"""
        has_sampler = any(t in ('sampler2D', 'texture2D') for t in uniforms_name_type.values())
        if not has_sampler:
            return None
        bindings = [vk.VkDescriptorSetLayoutBinding(
            binding=0,
            descriptorType=vk.VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
            descriptorCount=1,
            stageFlags=vk.VK_SHADER_STAGE_FRAGMENT_BIT,
        )]

        layout_info = vk.VkDescriptorSetLayoutCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            bindingCount=len(bindings),
            pBindings=bindings,
        )
        return vk.vkCreateDescriptorSetLayout(self.device, layout_info, None)

    def create_pipeline_layout(
        self,
        descriptor_set_layout: object
    ) -> object:
        """创建 VkPipelineLayout — push constant 同时用于 vertex + fragment (128 bytes)。"""
        push_constant_range = vk.VkPushConstantRange(
            stageFlags=vk.VK_SHADER_STAGE_VERTEX_BIT
                      | vk.VK_SHADER_STAGE_FRAGMENT_BIT,
            offset=0,
            size=128,
        )
        layouts = [descriptor_set_layout] if descriptor_set_layout is not None else []
        layout_info = vk.VkPipelineLayoutCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
            setLayoutCount=len(layouts),
            pSetLayouts=layouts if layouts else None,
            pushConstantRangeCount=1,
            pPushConstantRanges=[push_constant_range],
        )
        return vk.vkCreatePipelineLayout(self.device, layout_info, None)

    # ════════════════════════════════════════════════════════════
    # 图形管线创建
    # ════════════════════════════════════════════════════════════

    def create_graphics_pipeline(
        self,
        vs_module: object,
        fs_module: object,
        pipeline_layout: object,
    ) -> object:
        """创建 VkPipeline — 使用默认的三角形列表管线状态。

        Args:
            vs_module       : 顶点着色器模块
            fs_module       : 片段着色器模块
            pipeline_layout : VkPipelineLayout

        Returns:
            VkPipeline
        """
        vert_stage = vk.VkPipelineShaderStageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            stage=vk.VK_SHADER_STAGE_VERTEX_BIT,
            module=vs_module,
            pName="main",
        )
        frag_stage = vk.VkPipelineShaderStageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            stage=vk.VK_SHADER_STAGE_FRAGMENT_BIT,
            module=fs_module,
            pName="main",
        )

        # 顶点输入 — 交错: pos(3f) + uv(2f) + normal(3f)
        binding_desc = vk.VkVertexInputBindingDescription(
            binding=0,
            stride=8 * 4,  # 8 floats × 4 bytes
            inputRate=vk.VK_VERTEX_INPUT_RATE_VERTEX,
        )
        attr_descs = [
            vk.VkVertexInputAttributeDescription(
                location=0, binding=0,
                format=vk.VK_FORMAT_R32G32B32_SFLOAT, offset=0,
            ),
            vk.VkVertexInputAttributeDescription(
                location=1, binding=0,
                format=vk.VK_FORMAT_R32G32_SFLOAT, offset=12,
            ),
            vk.VkVertexInputAttributeDescription(
                location=2, binding=0,
                format=vk.VK_FORMAT_R32G32B32_SFLOAT, offset=20,
            ),
        ]
        vertex_input = vk.VkPipelineVertexInputStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
            vertexBindingDescriptionCount=1,
            pVertexBindingDescriptions=[binding_desc],
            vertexAttributeDescriptionCount=len(attr_descs),
            pVertexAttributeDescriptions=attr_descs,
        )
        input_assembly = vk.VkPipelineInputAssemblyStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
            topology=vk.VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,
            primitiveRestartEnable=vk.VK_FALSE,
        )
        viewport_state = vk.VkPipelineViewportStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
            viewportCount=1, pViewports=None,
            scissorCount=1, pScissors=None,
        )
        rasterizer = vk.VkPipelineRasterizationStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
            depthClampEnable=vk.VK_FALSE,
            rasterizerDiscardEnable=vk.VK_FALSE,
            polygonMode=vk.VK_POLYGON_MODE_FILL,
            cullMode=vk.VK_CULL_MODE_BACK_BIT,
            frontFace=vk.VK_FRONT_FACE_COUNTER_CLOCKWISE,
            lineWidth=1.0,
        )
        multisampling = vk.VkPipelineMultisampleStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
            rasterizationSamples=vk.VK_SAMPLE_COUNT_1_BIT,
        )
        color_blend_attachment = vk.VkPipelineColorBlendAttachmentState(
            colorWriteMask=vk.VK_COLOR_COMPONENT_R_BIT
                          | vk.VK_COLOR_COMPONENT_G_BIT
                          | vk.VK_COLOR_COMPONENT_B_BIT
                          | vk.VK_COLOR_COMPONENT_A_BIT,
            blendEnable=vk.VK_FALSE,
        )
        color_blending = vk.VkPipelineColorBlendStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
            attachmentCount=1,
            pAttachments=[color_blend_attachment],
        )
        dynamic_states = [vk.VK_DYNAMIC_STATE_VIEWPORT, vk.VK_DYNAMIC_STATE_SCISSOR]
        dynamic_state = vk.VkPipelineDynamicStateCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
            dynamicStateCount=len(dynamic_states),
            pDynamicStates=dynamic_states,
        )

        pipeline_info = vk.VkGraphicsPipelineCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
            stageCount=2,
            pStages=[vert_stage, frag_stage],
            pVertexInputState=vertex_input,
            pInputAssemblyState=input_assembly,
            pViewportState=viewport_state,
            pRasterizationState=rasterizer,
            pMultisampleState=multisampling,
            pColorBlendState=color_blending,
            pDynamicState=dynamic_state,
            layout=pipeline_layout,
            renderPass=self.render_pass,
            subpass=0,
        )
        return vk.vkCreateGraphicsPipelines(
            self.device, vk.VK_NULL_HANDLE, 1, [pipeline_info], None
        )[0]
