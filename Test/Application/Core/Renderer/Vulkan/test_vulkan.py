import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402
import glfw
import numpy as np
import vulkan as vk

def find_memory_type(physical_device, memory_type_bits, property_flags):
    mem_props = vk.vkGetPhysicalDeviceMemoryProperties(physical_device)
    for i in range(mem_props.memoryTypeCount):
        if (memory_type_bits & (1 << i)) and (mem_props.memoryTypes[i].propertyFlags & property_flags) == property_flags:
            return i
    raise RuntimeError("找不到合适的内存类型")

def load_shader(device, filename):
    with open(filename, 'rb') as f:
        code = f.read()
    module_info = vk.VkShaderModuleCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        codeSize=len(code),
        pCode=code,
    )
    return vk.vkCreateShaderModule(device, module_info, None)

def create_buffer(device, physical_device, size, usage, memory_properties):
    buffer_info = vk.VkBufferCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        size=size,
        usage=usage,
        sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
    )
    buffer = vk.vkCreateBuffer(device, buffer_info, None)
    mem_reqs = vk.vkGetBufferMemoryRequirements(device, buffer)
    alloc_info = vk.VkMemoryAllocateInfo(
        sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        allocationSize=mem_reqs.size,
        memoryTypeIndex=find_memory_type(physical_device, mem_reqs.memoryTypeBits, memory_properties),
    )
    memory = vk.vkAllocateMemory(device, alloc_info, None)
    vk.vkBindBufferMemory(device, buffer, memory, 0)
    return buffer, memory

# ---------- 主程序 ----------
def main():
    # 1. 窗口初始化
    glfw.init()
    glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
    window = glfw.create_window(800, 600, "Vulkan Triangle Loop", None, None)
    if not window:
        glfw.terminate()
        return

    # 2. 创建 Vulkan 实例
    app_info = vk.VkApplicationInfo(
        sType=vk.VK_STRUCTURE_TYPE_APPLICATION_INFO,
        pApplicationName="Vulkan Triangle Loop",
        applicationVersion=vk.VK_MAKE_VERSION(1, 0, 0),
        pEngineName="No Engine",
        engineVersion=vk.VK_MAKE_VERSION(1, 0, 0),
        apiVersion=vk.VK_API_VERSION_1_0,
    )
    glfw_extensions = glfw.get_required_instance_extensions()
    inst_info = vk.VkInstanceCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        pApplicationInfo=app_info,
        enabledExtensionCount=len(glfw_extensions),
        ppEnabledExtensionNames=glfw_extensions,
        enabledLayerCount=0,
        ppEnabledLayerNames=None,
    )
    instance = vk.vkCreateInstance(inst_info, None)

    # 3. 选择物理设备
    physical_devices = vk.vkEnumeratePhysicalDevices(instance)
    physical_device = physical_devices[0]

    # 4. 查找图形队列族
    queue_family_props = vk.vkGetPhysicalDeviceQueueFamilyProperties(physical_device)
    graphics_queue_family_index = None
    for i, props in enumerate(queue_family_props):
        if props.queueFlags & vk.VK_QUEUE_GRAPHICS_BIT:
            graphics_queue_family_index = i
            break

    # 5. 创建逻辑设备
    queue_priority = [1.0]
    queue_create_info = vk.VkDeviceQueueCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        queueFamilyIndex=graphics_queue_family_index,
        queueCount=1,
        pQueuePriorities=queue_priority,
    )
    device_create_info = vk.VkDeviceCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        queueCreateInfoCount=1,
        pQueueCreateInfos=[queue_create_info],
        enabledExtensionCount=1,
        ppEnabledExtensionNames=[vk.VK_KHR_SWAPCHAIN_EXTENSION_NAME],
        enabledLayerCount=0,
        pEnabledFeatures=None,
    )
    device = vk.vkCreateDevice(physical_device, device_create_info, None)
    graphics_queue = vk.vkGetDeviceQueue(device, graphics_queue_family_index, 0)

    # ★ 加载实例级 KHR 扩展函数（必须在 instance 创建后、使用前调用）
    _vkDestroySurfaceKHR = vk.vkGetInstanceProcAddr(instance, 'vkDestroySurfaceKHR')
    _vkGetPhysicalDeviceSurfaceCapabilitiesKHR = vk.vkGetInstanceProcAddr(instance, 'vkGetPhysicalDeviceSurfaceCapabilitiesKHR')
    _vkGetPhysicalDeviceSurfaceFormatsKHR = vk.vkGetInstanceProcAddr(instance, 'vkGetPhysicalDeviceSurfaceFormatsKHR')
    _vkGetPhysicalDeviceSurfacePresentModesKHR = vk.vkGetInstanceProcAddr(instance, 'vkGetPhysicalDeviceSurfacePresentModesKHR')

    # ★ 加载设备级 KHR 扩展函数（必须在 device 创建后、使用前调用）
    _vkCreateSwapchainKHR = vk.vkGetDeviceProcAddr(device, 'vkCreateSwapchainKHR')
    _vkDestroySwapchainKHR = vk.vkGetDeviceProcAddr(device, 'vkDestroySwapchainKHR')
    _vkGetSwapchainImagesKHR = vk.vkGetDeviceProcAddr(device, 'vkGetSwapchainImagesKHR')
    _vkAcquireNextImageKHR = vk.vkGetDeviceProcAddr(device, 'vkAcquireNextImageKHR')
    _vkQueuePresentKHR = vk.vkGetDeviceProcAddr(device, 'vkQueuePresentKHR')

    # 6. 创建表面（glfw 绑定需要传入 CFFI 指针作为输出参数）
    surface_ptr = vk.ffi.new("VkSurfaceKHR*")
    glfw.create_window_surface(instance, window, None, surface_ptr)
    surface = surface_ptr[0]  # 解引用获取 VkSurfaceKHR 句柄

    # 7. 获取表面能力并创建交换链
    surf_capabilities = _vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical_device, surface)
    surf_formats = _vkGetPhysicalDeviceSurfaceFormatsKHR(physical_device, surface)
    surf_format = surf_formats[0]
    present_modes = _vkGetPhysicalDeviceSurfacePresentModesKHR(physical_device, surface)
    present_mode = present_modes[0]   # 通常为 FIFO，可改为 MAILBOX 获得更低延迟
    image_count = max(2, surf_capabilities.minImageCount)
    swapchain_create_info = vk.VkSwapchainCreateInfoKHR(
        sType=vk.VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
        surface=surface,
        minImageCount=image_count,
        imageFormat=surf_format.format,
        imageColorSpace=surf_format.colorSpace,
        imageExtent=surf_capabilities.currentExtent,
        imageArrayLayers=1,
        imageUsage=vk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
        imageSharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
        preTransform=surf_capabilities.currentTransform,
        compositeAlpha=vk.VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
        presentMode=present_mode,
        clipped=vk.VK_TRUE,
        oldSwapchain=None,
    )
    swapchain = _vkCreateSwapchainKHR(device, swapchain_create_info, None)
    swapchain_images = _vkGetSwapchainImagesKHR(device, swapchain)

    # 8. 创建图像视图
    swapchain_image_views = []
    for img in swapchain_images:
        view_create_info = vk.VkImageViewCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
            image=img,
            viewType=vk.VK_IMAGE_VIEW_TYPE_2D,
            format=surf_format.format,
            components=vk.VkComponentMapping(
                r=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                g=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                b=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
                a=vk.VK_COMPONENT_SWIZZLE_IDENTITY,
            ),
            subresourceRange=vk.VkImageSubresourceRange(
                aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                baseMipLevel=0,
                levelCount=1,
                baseArrayLayer=0,
                layerCount=1,
            ),
        )
        view = vk.vkCreateImageView(device, view_create_info, None)
        swapchain_image_views.append(view)

    # 9. 创建渲染通道
    color_attachment = vk.VkAttachmentDescription(
        format=surf_format.format,
        samples=vk.VK_SAMPLE_COUNT_1_BIT,
        loadOp=vk.VK_ATTACHMENT_LOAD_OP_CLEAR,
        storeOp=vk.VK_ATTACHMENT_STORE_OP_STORE,
        stencilLoadOp=vk.VK_ATTACHMENT_LOAD_OP_DONT_CARE,
        stencilStoreOp=vk.VK_ATTACHMENT_STORE_OP_DONT_CARE,
        initialLayout=vk.VK_IMAGE_LAYOUT_UNDEFINED,
        finalLayout=vk.VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
    )
    color_attachment_ref = vk.VkAttachmentReference(
        attachment=0,
        layout=vk.VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
    )
    subpass = vk.VkSubpassDescription(
        pipelineBindPoint=vk.VK_PIPELINE_BIND_POINT_GRAPHICS,
        colorAttachmentCount=1,
        pColorAttachments=[color_attachment_ref],
    )
    render_pass_info = vk.VkRenderPassCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
        attachmentCount=1,
        pAttachments=[color_attachment],
        subpassCount=1,
        pSubpasses=[subpass],
    )
    render_pass = vk.vkCreateRenderPass(device, render_pass_info, None)

    # 10. 创建帧缓冲
    framebuffers = []
    for view in swapchain_image_views:
        fb_info = vk.VkFramebufferCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
            renderPass=render_pass,
            attachmentCount=1,
            pAttachments=[view],
            width=surf_capabilities.currentExtent.width,
            height=surf_capabilities.currentExtent.height,
            layers=1,
        )
        fb = vk.vkCreateFramebuffer(device, fb_info, None)
        framebuffers.append(fb)

    # 11. 创建顶点缓冲区
    vertices = np.array([
        -0.5, -0.5,
         0.5, -0.5,
         0.0,  0.5,
    ], dtype=np.float32)
    vertex_buffer, vertex_memory = create_buffer(
        device, physical_device,
        vertices.nbytes,
        vk.VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
        vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
    )
    # 上传顶点数据（vkMapMemory 返回 CFFI buffer，用 numpy 写入）
    data_ptr = vk.vkMapMemory(device, vertex_memory, 0, vertices.nbytes, 0)
    mapped_array = np.frombuffer(data_ptr, dtype=np.float32)
    np.copyto(mapped_array, vertices)
    vk.vkUnmapMemory(device, vertex_memory)

    # 12. 创建管线布局和图形管线
    pipeline_layout_info = vk.VkPipelineLayoutCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        setLayoutCount=0,
        pSetLayouts=None,
        pushConstantRangeCount=0,
        pPushConstantRanges=None,
    )
    pipeline_layout = vk.vkCreatePipelineLayout(device, pipeline_layout_info, None)

    # 加载着色器模块
    vert_module = load_shader(device, "triangle.vert.spv")
    frag_module = load_shader(device, "triangle.frag.spv")
    vert_stage = vk.VkPipelineShaderStageCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
        stage=vk.VK_SHADER_STAGE_VERTEX_BIT,
        module=vert_module,
        pName="main",
    )
    frag_stage = vk.VkPipelineShaderStageCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
        stage=vk.VK_SHADER_STAGE_FRAGMENT_BIT,
        module=frag_module,
        pName="main",
    )
    shader_stages = [vert_stage, frag_stage]

    # 顶点输入描述
    binding_desc = vk.VkVertexInputBindingDescription(
        binding=0,
        stride=2 * 4,
        inputRate=vk.VK_VERTEX_INPUT_RATE_VERTEX,
    )
    attr_desc = vk.VkVertexInputAttributeDescription(
        location=0,
        binding=0,
        format=vk.VK_FORMAT_R32G32_SFLOAT,
        offset=0,
    )
    vertex_input_info = vk.VkPipelineVertexInputStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        vertexBindingDescriptionCount=1,
        pVertexBindingDescriptions=[binding_desc],
        vertexAttributeDescriptionCount=1,
        pVertexAttributeDescriptions=[attr_desc],
    )
    input_assembly = vk.VkPipelineInputAssemblyStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        topology=vk.VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,
        primitiveRestartEnable=vk.VK_FALSE,
    )
    viewport_state = vk.VkPipelineViewportStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
        viewportCount=1,
        pViewports=None,
        scissorCount=1,
        pScissors=None,
    )
    rasterizer = vk.VkPipelineRasterizationStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        depthClampEnable=vk.VK_FALSE,
        rasterizerDiscardEnable=vk.VK_FALSE,
        polygonMode=vk.VK_POLYGON_MODE_FILL,
        cullMode=vk.VK_CULL_MODE_BACK_BIT,
        frontFace=vk.VK_FRONT_FACE_CLOCKWISE,
        depthBiasEnable=vk.VK_FALSE,
        lineWidth=1.0,
    )
    multisampling = vk.VkPipelineMultisampleStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        rasterizationSamples=vk.VK_SAMPLE_COUNT_1_BIT,
        sampleShadingEnable=vk.VK_FALSE,
    )
    color_blend_attachment = vk.VkPipelineColorBlendAttachmentState(
        colorWriteMask=(
            vk.VK_COLOR_COMPONENT_R_BIT |
            vk.VK_COLOR_COMPONENT_G_BIT |
            vk.VK_COLOR_COMPONENT_B_BIT |
            vk.VK_COLOR_COMPONENT_A_BIT
        ),
        blendEnable=vk.VK_FALSE,
    )
    color_blending = vk.VkPipelineColorBlendStateCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        logicOpEnable=vk.VK_FALSE,
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
        pStages=shader_stages,
        pVertexInputState=vertex_input_info,
        pInputAssemblyState=input_assembly,
        pViewportState=viewport_state,
        pRasterizationState=rasterizer,
        pMultisampleState=multisampling,
        pColorBlendState=color_blending,
        pDynamicState=dynamic_state,
        layout=pipeline_layout,
        renderPass=render_pass,
        subpass=0,
    )
    graphics_pipeline = vk.vkCreateGraphicsPipelines(device, vk.VK_NULL_HANDLE, 1, [pipeline_info], None)[0]

    # 13. 创建命令池和命令缓冲
    cmd_pool_info = vk.VkCommandPoolCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        queueFamilyIndex=graphics_queue_family_index,
        flags=vk.VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
    )
    cmd_pool = vk.vkCreateCommandPool(device, cmd_pool_info, None)
    cmd_buf_info = vk.VkCommandBufferAllocateInfo(
        sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        commandPool=cmd_pool,
        level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
        commandBufferCount=1,
    )
    cmd_buffer = vk.vkAllocateCommandBuffers(device, cmd_buf_info)[0]

    # 14. 创建同步对象
    sem_info = vk.VkSemaphoreCreateInfo(sType=vk.VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO)
    image_available_sem = vk.vkCreateSemaphore(device, sem_info, None)
    render_finished_sem = vk.vkCreateSemaphore(device, sem_info, None)

    # ★ 关键修复：添加 Fence 做 CPU-GPU 帧同步，防止 acquire 无限阻塞
    fence_info = vk.VkFenceCreateInfo(
        sType=vk.VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
        flags=vk.VK_FENCE_CREATE_SIGNALED_BIT,  # 初始为 signaled，第一帧可以立即进入
    )
    frame_fence = vk.vkCreateFence(device, fence_info, None)

    # 15. 主循环
    while not glfw.window_should_close(window):
        glfw.poll_events()

        # ★ 等待上一帧的 GPU 工作完成（防止 CPU 超前太多导致 acquire 阻塞）
        vk.vkWaitForFences(device, 1, [frame_fence], vk.VK_TRUE, int(1e9))  # 1秒超时
        vk.vkResetFences(device, 1, [frame_fence])

        # 15.1 获取下一张交换链图像索引（vkAcquireNextImageKHR 直接返回 int，不是 tuple）
        try:
            image_index = _vkAcquireNextImageKHR(device, swapchain, int(1e9), image_available_sem, vk.VK_NULL_HANDLE)
        except vk.VkErrorOutOfDateKhr:
            # 窗口大小改变，需要重建交换链（本例简化处理，直接退出）
            break

        # 15.2 记录命令缓冲
        vk.vkResetCommandBuffer(cmd_buffer, 0)
        begin_info = vk.VkCommandBufferBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            flags=vk.VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        )
        vk.vkBeginCommandBuffer(cmd_buffer, begin_info)

        # 绑定管线
        vk.vkCmdBindPipeline(cmd_buffer, vk.VK_PIPELINE_BIND_POINT_GRAPHICS, graphics_pipeline)
        # 绑定顶点缓冲
        vk.vkCmdBindVertexBuffers(cmd_buffer, 0, 1, [vertex_buffer], [0])

        # 动态设置视口和剪刀（匹配当前帧缓冲尺寸）
        viewport = vk.VkViewport(
            x=0, y=0,
            width=surf_capabilities.currentExtent.width,
            height=surf_capabilities.currentExtent.height,
            minDepth=0.0, maxDepth=1.0,
        )
        scissor = vk.VkRect2D(
            offset=vk.VkOffset2D(x=0, y=0),
            extent=surf_capabilities.currentExtent,
        )
        vk.vkCmdSetViewport(cmd_buffer, 0, 1, viewport)
        vk.vkCmdSetScissor(cmd_buffer, 0, 1, scissor)

        # 开始渲染通道
        clear_color = [vk.VkClearValue(color=vk.VkClearColorValue(float32=[0.1, 0.2, 0.3, 1.0]))]
        render_pass_begin_info = vk.VkRenderPassBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
            renderPass=render_pass,
            framebuffer=framebuffers[image_index],
            renderArea=vk.VkRect2D(offset=vk.VkOffset2D(x=0, y=0), extent=surf_capabilities.currentExtent),
            clearValueCount=1,
            pClearValues=clear_color,
        )
        vk.vkCmdBeginRenderPass(cmd_buffer, render_pass_begin_info, vk.VK_SUBPASS_CONTENTS_INLINE)
        vk.vkCmdDraw(cmd_buffer, 3, 1, 0, 0)
        vk.vkCmdEndRenderPass(cmd_buffer)

        vk.vkEndCommandBuffer(cmd_buffer)

        # 15.3 提交命令缓冲
        submit_info = vk.VkSubmitInfo(
            sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO,
            waitSemaphoreCount=1,
            pWaitSemaphores=[image_available_sem],
            pWaitDstStageMask=[vk.VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT],
            commandBufferCount=1,
            pCommandBuffers=[cmd_buffer],
            signalSemaphoreCount=1,
            pSignalSemaphores=[render_finished_sem],
        )
        vk.vkQueueSubmit(graphics_queue, 1, submit_info, frame_fence)  # ★ 传入 fence

        # 15.4 呈现
        present_info = vk.VkPresentInfoKHR(
            sType=vk.VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
            waitSemaphoreCount=1,
            pWaitSemaphores=[render_finished_sem],
            swapchainCount=1,
            pSwapchains=[swapchain],
            pImageIndices=[image_index],
        )
        _vkQueuePresentKHR(graphics_queue, present_info)

        # 简单限速，避免 CPU 跑满（实际应用中可以用 fence 等待前一帧完成）
        # 这里不等待，让 GPU 队列尽量满，但为了演示稳定性，加入一个小延时
        # time.sleep(0.001)   # 可去掉

    # 16. 等待设备空闲并清理资源
    vk.vkDeviceWaitIdle(device)

    vk.vkDestroySemaphore(device, image_available_sem, None)
    vk.vkDestroySemaphore(device, render_finished_sem, None)
    vk.vkDestroyFence(device, frame_fence, None)
    vk.vkDestroyCommandPool(device, cmd_pool, None)
    vk.vkDestroyPipeline(device, graphics_pipeline, None)
    vk.vkDestroyPipelineLayout(device, pipeline_layout, None)
    vk.vkDestroyRenderPass(device, render_pass, None)
    for fb in framebuffers:
        vk.vkDestroyFramebuffer(device, fb, None)
    for view in swapchain_image_views:
        vk.vkDestroyImageView(device, view, None)
    _vkDestroySwapchainKHR(device, swapchain, None)
    vk.vkDestroyShaderModule(device, vert_module, None)
    vk.vkDestroyShaderModule(device, frag_module, None)
    vk.vkDestroyBuffer(device, vertex_buffer, None)
    vk.vkFreeMemory(device, vertex_memory, None)
    vk.vkDestroyDevice(device, None)
    _vkDestroySurfaceKHR(instance, surface, None)
    vk.vkDestroyInstance(instance, None)
    glfw.destroy_window(window)
    glfw.terminate()

if __name__ == "__main__":
    main()
