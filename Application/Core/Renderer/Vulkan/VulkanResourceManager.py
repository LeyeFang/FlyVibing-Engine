"""
VulkanResourceManager — Vulkan GPU 资源管理器 (Mesh / Shader / Texture / Entity)。

职责:
  - GPU 资源数据结构定义 (entity / mesh / shader / texture)
  - 资源注册表 (引用计数管理)
  - register_* : CPU 数据 → GPU 资源的上传与创建
  - unregister_* : GPU 资源的降引用与销毁
  - 管线创建 (per shader) 与 描述符集分配 (per entity)

依赖:
  - VulkanCore: 提供底层 Vulkan 对象 (device, cmd_pool, descriptor_pool 等)
  - ResourceManager (CPU 端): 提供 Mesh / Material / Shader / Texture 数据
  - SceneManager: 提供实体→资源的映射

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
import numpy as np
import vulkan as vk
from dataclasses import dataclass

from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader, Texture
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.Vulkan.VulkanCore import VulkanCore
from Application.Core.Renderer.VertexLayout import VertexLayout, STD_LAYOUT


class VulkanResourceManager:
    """Vulkan GPU 资源管理器 — Mesh/Shader/Texture/Entity 的注册与生命周期。"""

    # ════════════════════════════════════════════════════════════
    # GPU 资源数据结构
    # ════════════════════════════════════════════════════════════

    @dataclass
    class entity_data_struct:
        """Vulkan 实体资源记录。

        Attributes:
            shader_id       : 着色器资源 ID
            texture_id      : 纹理资源 ID (0 表示无纹理)
            mesh_id         : 网格资源 ID
            material_id     : 材质资源 ID
            descriptor_set  : VkDescriptorSet — 该实体的描述符集
        """
        shader_id: int
        texture_id: int
        mesh_id: int
        material_id: int
        descriptor_set: object = None

    @dataclass
    class mesh_data_struct:
        """Vulkan 网格资源记录。

        Attributes:
            vertex_buffer  : VkBuffer — 顶点缓冲 (交错: pos+uv+normal)
            vertex_memory  : VkDeviceMemory — 顶点缓冲 GPU 内存
            index_buffer   : VkBuffer — 索引缓冲
            index_memory   : VkDeviceMemory — 索引缓冲 GPU 内存
            elements_count : 索引数量 (三角形数 × 3)
            ref_count      : 引用计数
        """
        vertex_buffer: object = None
        vertex_memory: object = None
        index_buffer: object = None
        index_memory: object = None
        elements_count: int = 0
        layout: 'VertexLayout' = None  # ★ 顶点格式描述符
        ref_count: int = 0

    @dataclass
    class shader_data_struct:
        """Vulkan 着色器资源记录。

        Attributes:
            vs_module             : VkShaderModule — 顶点着色器
            fs_module             : VkShaderModule — 片段着色器
            descriptor_set_layout : VkDescriptorSetLayout
            pipeline_layout       : VkPipelineLayout (含 push constant)
            pipeline              : VkPipeline — 图形管线
            ref_count             : 引用计数
        """
        vs_module: object = None
        fs_module: object = None
        descriptor_set_layout: object = None
        pipeline_layout: object = None
        pipeline: object = None
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        """Vulkan 纹理资源记录。

        Attributes:
            image     : VkImage — GPU 纹理图像
            memory    : VkDeviceMemory — 纹理 GPU 内存
            view      : VkImageView — 图像视图
            sampler   : VkSampler — 采样器
            ref_count : 引用计数
        """
        image: object = None
        memory: object = None
        view: object = None
        sampler: object = None
        ref_count: int = 0

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

    def register_entity(self,
        """注册可渲染实体到 GPU — 级联注册 Mesh/Shader/Texture，创建 DescriptorSet。

        Args:
            entity_id: 实体 ID (SceneManager 分配)
        """
        mesh_id = self.engine.scene.GetEntityMesh(entity_id)
        material_id = self.engine.scene.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader = ResourceManager.GetShader(shader_id)

        # 级联注册依赖资源
        self.register_mesh(mesh, mesh_id)
        self.register_shader(shader, shader_id)

        # 注册纹理 (取 material 的第一张纹理作为 diffuse)
        if material.texture_id_list:
            tex_id = material.texture_id_list[0]
            texture = ResourceManager.GetTexture(tex_id)
            self.register_texture(texture, tex_id)
        else:
            tex_id = 0

        # 分配描述符集 (绑定 UBO + 纹理)
        descriptor_set = self._allocate_descriptor_set(
            shader_id, tex_id
        )

        self.registered_entities[entity_id] = self.entity_data_struct(
            shader_id=shader_id,
            texture_id=tex_id,
            mesh_id=mesh_id,
            material_id=material_id,
            descriptor_set=descriptor_set,
        )

    def register_mesh(self,
        """上传网格数据到 GPU — 创建 VertexBuffer + IndexBuffer。

        交错顶点格式 (每顶点 8 个 float, 32 bytes):
          [px, py, pz,  u, v,  nx, ny, nz]

        Args:
            mesh    : CPU 端 Mesh 资源
            mesh_id : 网格资源 ID
        """
        if mesh_id in self.registered_meshes:
            self.registered_meshes[mesh_id].ref_count += 1
            return

        vertices = mesh.vertices
        uvs = mesh.uvs
        normals = mesh.normals
        indices = mesh.indices

        ver_uv_nor = np.hstack((vertices, uvs, normals)).astype('float32')

        # 顶点缓冲
        vbo, vbo_mem = VulkanCore.create_buffer(
            size=ver_uv_nor.nbytes,
            usage=vk.VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
            properties=vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
                       | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        )
        VulkanCore.copy_to_buffer(vbo_mem, ver_uv_nor.tobytes())

        # 索引缓冲
        ibo, ibo_mem = VulkanCore.create_buffer(
            size=indices.nbytes,
            usage=vk.VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            properties=vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
                       | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        )
        idx_data = indices.astype('uint32')
        VulkanCore.copy_to_buffer(ibo_mem, idx_data.tobytes())

        self.registered_meshes[mesh_id] = self.mesh_data_struct(
            vertex_buffer=vbo,
            vertex_memory=vbo_mem,
            index_buffer=ibo,
            index_memory=ibo_mem,
            elements_count=int(indices.size),
            layout=mesh.layout or STD_LAYOUT.ENTITY_POS_UV_NORMAL,
            ref_count=1,
        )

    def register_shader(self,
        """编译 GLSL → SPIR-V → 创建 ShaderModule + Pipeline。

        若着色器已注册，仅增加引用计数。

        Args:
            shader    : CPU 端 Shader 资源 (vs_src + fs_src + uniforms_name_type)
            shader_id : 着色器资源 ID
        """
        if shader_id in self.registered_shaders:
            self.registered_shaders[shader_id].ref_count += 1
            return

        # 编译 GLSL → SPIR-V (优先用预编译的 .spv，否则运行时编译)
        if shader.vs_spv:
            vs_spv = shader.vs_spv
        else:
            vs_spv = VulkanCore.compile_glsl_to_spirv(shader.vs_src, 'vertex')
        if shader.fs_spv:
            fs_spv = shader.fs_spv
        else:
            fs_spv = VulkanCore.compile_glsl_to_spirv(shader.fs_src, 'fragment')

        # ShaderModule
        vs_module = VulkanCore.create_shader_module(vs_spv)
        fs_module = VulkanCore.create_shader_module(fs_spv)

        # DescriptorSetLayout → PipelineLayout → Pipeline
        descriptor_set_layout = VulkanCore.create_descriptor_set_layout(
            shader.uniforms_name_type
        )
        pipeline_layout = VulkanCore.create_pipeline_layout(descriptor_set_layout)
        pipeline = VulkanCore.create_graphics_pipeline(
            vs_module, fs_module, pipeline_layout
        )

        self.registered_shaders[shader_id] = self.shader_data_struct(
            vs_module=vs_module,
            fs_module=fs_module,
            descriptor_set_layout=descriptor_set_layout,
            pipeline_layout=pipeline_layout,
            pipeline=pipeline,
            ref_count=1,
        )

    def register_texture(self,
        """上传纹理数据到 GPU — 创建 Image + ImageView + Sampler。

        使用 staging buffer 将像素数据传输到 DEVICE_LOCAL 纹理内存。
        自动根据通道数选择格式。

        Args:
            texture    : CPU 端 Texture 资源
            texture_id : 纹理资源 ID

        Raises:
            ValueError: 不支持的通道数
        """
        if texture_id in self.registered_textures:
            self.registered_textures[texture_id].ref_count += 1
            return

        # 通道数 → VkFormat
        _CHANNEL_FORMAT = {
            1: vk.VK_FORMAT_R8_UNORM,
            3: vk.VK_FORMAT_R8G8B8_UNORM,
            4: vk.VK_FORMAT_R8G8B8A8_UNORM,
        }
        if texture.channels not in _CHANNEL_FORMAT:
            raise ValueError(f"不支持的纹理通道数: {texture.channels}")
        fmt = _CHANNEL_FORMAT[texture.channels]

        data = (texture.image_data.tobytes()
                if isinstance(texture.image_data, np.ndarray)
                else bytes(texture.image_data))

        # Staging buffer
        staging_buf, staging_mem = VulkanCore.create_buffer(
            size=len(data),
            usage=vk.VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
            properties=vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
                       | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        )
        VulkanCore.copy_to_buffer(staging_mem, data)

        # GPU Image
        image, image_mem = VulkanCore.create_image(
            width=texture.width,
            height=texture.height,
            fmt=fmt,
            usage=vk.VK_IMAGE_USAGE_TRANSFER_DST_BIT
                  | vk.VK_IMAGE_USAGE_SAMPLED_BIT,
            properties=vk.VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
        )

        # Staging → Image 数据传输 (使用单次提交的命令缓冲)
        self._copy_buffer_to_image(staging_buf, image, texture.width, texture.height)

        # ImageView + Sampler
        view = VulkanCore.create_image_view(image, fmt)
        sampler = VulkanCore.create_sampler()

        # 清理 staging
        VulkanCore.destroy_buffer(staging_buf, staging_mem)

        self.registered_textures[texture_id] = self.texture_data_struct(
            image=image,
            memory=image_mem,
            view=view,
            sampler=sampler,
            ref_count=1,
        )

    # ════════════════════════════════════════════════════════════
    # 资源卸载
    # ════════════════════════════════════════════════════════════

    def unregister_entity(self,
        """从 GPU 卸载实体 — 释放 DescriptorSet，递减关联资源引用计数。"""
        if entity_id not in self.registered_entities:
            return
        entity = self.registered_entities[entity_id]
        # 描述符集由 descriptor pool 统一管理，free descriptor set 通过 reset pool
        # (全局池不单独释放单个 set，池 reset 时统一回收)
        self._decref_mesh(entity.mesh_id)
        self._decref_shader(entity.shader_id)
        self._decref_texture(entity.texture_id)
        del self.registered_entities[entity_id]

    def unregister_mesh(self,
        """递减网格引用计数。"""
        self._decref_mesh(mesh_id)

    def unregister_shader(self,
        """递减着色器引用计数。"""
        self._decref_shader(shader_id)

    def unregister_texture(self,
        """递减纹理引用计数。"""
        self._decref_texture(texture_id)

    # ════════════════════════════════════════════════════════════
    # 引用计数辅助
    # ════════════════════════════════════════════════════════════

    def _decref_mesh(self,
        """递减网格引用计数，归零时释放 vertex/index buffer + memory。"""
        if mesh_id not in self.registered_meshes:
            return
        data = self.registered_meshes[mesh_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            if data.vertex_buffer is not None:
                VulkanCore.destroy_buffer(data.vertex_buffer, data.vertex_memory)
            if data.index_buffer is not None:
                VulkanCore.destroy_buffer(data.index_buffer, data.index_memory)
            del self.registered_meshes[mesh_id]

    def _decref_shader(self,
        """递减着色器引用计数，归零时释放 Pipeline / ShaderModule / Layout。"""
        if shader_id not in self.registered_shaders:
            return
        data = self.registered_shaders[shader_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            dev = VulkanCore.device
            if data.pipeline is not None:
                vk.vkDestroyPipeline(dev, data.pipeline, None)
            if data.pipeline_layout is not None:
                vk.vkDestroyPipelineLayout(dev, data.pipeline_layout, None)
            if data.descriptor_set_layout is not None:
                vk.vkDestroyDescriptorSetLayout(dev, data.descriptor_set_layout, None)
            if data.fs_module is not None:
                vk.vkDestroyShaderModule(dev, data.fs_module, None)
            if data.vs_module is not None:
                vk.vkDestroyShaderModule(dev, data.vs_module, None)
            del self.registered_shaders[shader_id]

    def _decref_texture(self,
        """递减纹理引用计数，归零时释放 Image / ImageView / Sampler / Memory。"""
        if texture_id not in self.registered_textures:
            return
        data = self.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            dev = VulkanCore.device
            if data.sampler is not None:
                vk.vkDestroySampler(dev, data.sampler, None)
            if data.view is not None:
                vk.vkDestroyImageView(dev, data.view, None)
            if data.image is not None:
                vk.vkDestroyImage(dev, data.image, None)
            if data.memory is not None:
                vk.vkFreeMemory(dev, data.memory, None)
            del self.registered_textures[texture_id]

    # ════════════════════════════════════════════════════════════
    # 描述符集分配
    # ════════════════════════════════════════════════════════════

    def _allocate_descriptor_set(
        self,
        shader_id: int,
        texture_id: int
    ) -> object:
        """为实体分配 VkDescriptorSet — 无 sampler shader 时返回 None。"""
        shader_data = self.registered_shaders[shader_id]
        layout = shader_data.descriptor_set_layout

        # 无 binding 的 shader (纯 push_constant)，跳过 descriptor set
        if layout is None:
            return None

        alloc_info = vk.VkDescriptorSetAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
            descriptorPool=VulkanCore.descriptor_pool,
            descriptorSetCount=1,
            pSetLayouts=[layout],
        )
        descriptor_set = vk.vkAllocateDescriptorSets(
            VulkanCore.device, alloc_info
        )[0]

        # 绑定纹理 sampler (binding=0)
        if texture_id and texture_id in self.registered_textures:
            tex_data = self.registered_textures[texture_id]
            image_info = vk.VkDescriptorImageInfo(
                sampler=tex_data.sampler,
                imageView=tex_data.view,
                imageLayout=vk.VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
            )
            write_descriptor = vk.VkWriteDescriptorSet(
                sType=vk.VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                dstSet=descriptor_set,
                dstBinding=0,
                descriptorType=vk.VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                descriptorCount=1,
                pImageInfo=[image_info],
            )
            vk.vkUpdateDescriptorSets(
                VulkanCore.device, 1, [write_descriptor], 0, None
            )

        return descriptor_set

    # ════════════════════════════════════════════════════════════
    # Staging → Image 传输
    # ════════════════════════════════════════════════════════════

    def _copy_buffer_to_image(
        self,
        buffer: object,
        image: object,
        width: int,
        height: int
    ) -> None:
        """使用单次提交命令缓冲将 staging buffer 拷贝到 VkImage。

        执行:
          1. Image layout: UNDEFINED → TRANSFER_DST_OPTIMAL
          2. vkCmdCopyBufferToImage
          3. Image layout: TRANSFER_DST_OPTIMAL → SHADER_READ_ONLY_OPTIMAL
        """
        dev = VulkanCore.device

        # 创建临时命令缓冲
        alloc_info = vk.VkCommandBufferAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            commandPool=VulkanCore.cmd_pool,
            level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            commandBufferCount=1,
        )
        tmp_cmd = vk.vkAllocateCommandBuffers(dev, alloc_info)[0]

        begin_info = vk.VkCommandBufferBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            flags=vk.VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        )
        vk.vkBeginCommandBuffer(tmp_cmd, begin_info)

        # Transition: UNDEFINED → TRANSFER_DST
        barrier1 = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            oldLayout=vk.VK_IMAGE_LAYOUT_UNDEFINED,
            newLayout=vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            srcQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED,
            dstQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED,
            image=image,
            subresourceRange=vk.VkImageSubresourceRange(
                aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                baseMipLevel=0, levelCount=1,
                baseArrayLayer=0, layerCount=1,
            ),
            srcAccessMask=0,
            dstAccessMask=vk.VK_ACCESS_TRANSFER_WRITE_BIT,
        )
        vk.vkCmdPipelineBarrier(
            tmp_cmd,
            vk.VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
            vk.VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, None, 0, None, 1, [barrier1],
        )

        # Copy buffer → image
        region = vk.VkBufferImageCopy(
            bufferOffset=0,
            bufferRowLength=0,
            bufferImageHeight=0,
            imageSubresource=vk.VkImageSubresourceLayers(
                aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                mipLevel=0,
                baseArrayLayer=0,
                layerCount=1,
            ),
            imageOffset=vk.VkOffset3D(x=0, y=0, z=0),
            imageExtent=vk.VkExtent3D(width, height, 1),
        )
        vk.vkCmdCopyBufferToImage(
            tmp_cmd, buffer, image,
            vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, [region],
        )

        # Transition: TRANSFER_DST → SHADER_READ_ONLY
        barrier2 = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            oldLayout=vk.VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            newLayout=vk.VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
            srcQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED,
            dstQueueFamilyIndex=vk.VK_QUEUE_FAMILY_IGNORED,
            image=image,
            subresourceRange=vk.VkImageSubresourceRange(
                aspectMask=vk.VK_IMAGE_ASPECT_COLOR_BIT,
                baseMipLevel=0, levelCount=1,
                baseArrayLayer=0, layerCount=1,
            ),
            srcAccessMask=vk.VK_ACCESS_TRANSFER_WRITE_BIT,
            dstAccessMask=vk.VK_ACCESS_SHADER_READ_BIT,
        )
        vk.vkCmdPipelineBarrier(
            tmp_cmd,
            vk.VK_PIPELINE_STAGE_TRANSFER_BIT,
            vk.VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
            0, 0, None, 0, None, 1, [barrier2],
        )

        vk.vkEndCommandBuffer(tmp_cmd)

        # 提交并等待完成
        submit_info = vk.VkSubmitInfo(
            sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO,
            commandBufferCount=1,
            pCommandBuffers=[tmp_cmd],
        )
        vk.vkQueueSubmit(VulkanCore.graphics_queue, 1, [submit_info], vk.VK_NULL_HANDLE)
        vk.vkQueueWaitIdle(VulkanCore.graphics_queue)

        # 释放临时命令缓冲
        vk.vkFreeCommandBuffers(dev, VulkanCore.cmd_pool, 1, [tmp_cmd])
