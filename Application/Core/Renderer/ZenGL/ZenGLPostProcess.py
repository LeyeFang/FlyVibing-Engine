"""
ZenGLPostProcess — ZenGL 屏幕空间后处理管线 (Mixin)。

职责:
  - Highlight 效果: MRT Image 管理 + 边缘检测 pipeline + 全屏三角形
  - 管理后处理专用的 ZenGL 资源 (不与 entity/overlay 共享)

管线 (每帧 _render_highlight):
  Pass 1 — Entity MRT: 遍历实体 → MRT Images (color + selected + entity_id + depth)
  Pass 2 — Edge Detect: 读 id_img → Roberts Cross 边缘检测 → edge_img (R8)
  Pass 3 — Composite:   读 edge_img → alpha blend 叠加到 color_image

MRO 位置:
  ZenGLRenderer → ... → ZenGLOverlayRenderer → ZenGLPostProcess → Renderer → ...
"""

from __future__ import annotations
import numpy as np

from Application.Core.Renderer.PostProcess import PostProcess, HighlightEffectConfig


class ZenGLPostProcess(PostProcess):
    """ZenGL 后处理管线 — 当前支持 Highlight 效果。"""

    def __init__(self) -> None:
        super().__init__()
        self._pp_ctx = None
        self._pp_color_img = None
        self._pp_id_img = None
        self._pp_pick_img = None
        self._pp_depth_img = None
        self._pp_entity_pipelines: dict[int, any] = {}
        self._pp_mrt_vs: str = ''
        self._pp_mrt_fs: str = ''

    # ════════════════════════════════════════════════════════
    # PostProcess 接口实现
    # ════════════════════════════════════════════════════════

    def _init_highlight(self, config: HighlightEffectConfig) -> None:
        """获取 ZenGL context → 创建 MRT Images → 编译 shader 模板。"""
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        self._pp_ctx = self.ctx
        self._create_fbo(
            self.viewport_width, self.viewport_height)
        self._compile_entity_shaders()

    def _release_highlight(self) -> None:
        """释放所有 highlight GPU 资源。"""
        self._pp_entity_pipelines.clear()
        self._release_fbo()
        self._pp_ctx = None

    def _render_highlight(self, view: np.ndarray, proj: np.ndarray) -> None:
        """Pass 1 Entity MRT → Pass 2 Edge → Pass 3 Composite。"""
        ctx = self._pp_ctx
        if ctx is None:
            return
        vp_w, vp_h = self.viewport_width, self.viewport_height
        if vp_w == 0 or vp_h == 0:
            return

        self._ensure_fbo(vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Pass 1: Entity MRT
        #   每个实体一个 ZenGL pipeline, 渲染到 MRT Images
        # ══════════════════════════════════════════════════
        self._pp_depth_img.clear()
        try:
            self._pp_id_img.clear()
        except Exception:
            pass
        try:
            self._pp_pick_img.clear()
        except Exception:
            pass

        from Application.Core.Scene.SceneManager import SceneManager

        active_ids = self._highlight_config.selected_ids if self._highlight_config else set()

        for eid in self.engine.scene.GetRenderableEntities():
            entity = self.registered_entities.get(eid)
            if entity is None:
                continue

            if eid not in self._pp_entity_pipelines:
                self._build_entity_pipeline(eid)
            p = self._pp_entity_pipelines.get(eid)
            if p is None:
                continue

            try:
                model = self.engine.scene.GetEntityModelMatrix(eid)
                p.uniforms['model'][:] = model.astype('float32').tobytes()
                p.uniforms['view'][:] = view.astype('float32').tobytes()
                p.uniforms['projection'][:] = proj.astype(
                    'float32').tobytes()
                p.uniforms['uSelectedFlag'][:] = int(
                    1 if eid in active_ids else 0
                ).to_bytes(4, 'little')
                p.uniforms['uEntityID'][:] = int(eid).to_bytes(
                    4, 'little')
            except Exception:
                pass
            p.render()

        # ══════════════════════════════════════════════════
        # Pass 2: 边缘检测 → edge_img (R8)
        # ══════════════════════════════════════════════════
        width_val = self._highlight_config.width if self._highlight_config else 3
        out_edge_img = ctx.image((vp_w, vp_h), 'r8unorm')

        edge_pipe = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](
                    vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader='''#version 420 core
in vec2 vUV;
layout(binding=0) uniform usampler2D uIDTex;
layout(location=0) out float outEdge;
void main() {
    ivec2 tx = ivec2(gl_FragCoord.xy);
    uint c = texelFetch(uIDTex, tx, 0).r;
    float edge = 0.0;
    int w = ''' + str(width_val) + ''';
    for (int dx = -w; dx <= w; dx++) {
        for (int dy = -w; dy <= w; dy++) {
            uint n = texelFetch(uIDTex, tx + ivec2(dx, dy), 0).r;
            if (n != c) { edge = 1.0; }
        }
    }
    outEdge = edge;
}''',
            layout=[{'name': 'uIDTex', 'binding': 0}],
            resources=[{'type': 'sampler', 'binding': 0,
                        'image': self._pp_id_img}],
            framebuffer=[out_edge_img],
            topology='triangles',
            vertex_count=3,
        )
        out_edge_img.clear()
        edge_pipe.render()

        # ══════════════════════════════════════════════════
        # Pass 3: Composite (alpha-blended)
        #   读 edge_img → 仅输出轮廓到默认 color_image
        # ══════════════════════════════════════════════════
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore

        xray_mode = self._highlight_config.xray if self._highlight_config else True
        outline_col = list(self._highlight_config.color) if self._highlight_config else [
            0.878, 0.416, 0.153]

        _COMP_FS = '''#version 420 core
in vec2 vUV;
layout(binding=0) uniform sampler2D uEdgeTex;
uniform vec3 uOutlineColor;
layout(location=0) out vec4 outColor;
void main() {
    float edge = texture(uEdgeTex, vUV).r;
    ''' + ('' if xray_mode else 'if (edge < 0.5) discard;') + '''
    outColor = vec4(uOutlineColor, edge);
}'''
        comp = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](
                    vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader=_COMP_FS,
            layout=[{'name': 'uEdgeTex', 'binding': 0}],
            resources=[{'type': 'sampler', 'binding': 0,
                        'image': out_edge_img}],
            uniforms={'uOutlineColor': outline_col},
            framebuffer=[self._color_image, self._depth_image],
            blend={'enable': True, 'src_color': 'src_alpha',
                   'dst_color': 'one_minus_src_alpha'},
            topology='triangles',
            vertex_count=3,
        )
        comp.render()

    # ════════════════════════════════════════════════════════
    # MRT Entity Shader 模板
    # ════════════════════════════════════════════════════════

    def _compile_entity_shaders(self) -> None:
        """编译 MRT 实体着色器模板 — 供 _build_entity_pipeline 复用。"""
        self._pp_mrt_vs = '''#version 440 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
uniform mat4 model, view, projection;
out vec2 TexCoord;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}'''
        self._pp_mrt_fs = '''#version 440 core
in vec2 TexCoord;
layout(binding=0) uniform sampler2D uTexture;
uniform uint uSelectedFlag;
uniform uint uEntityID;
layout(location=0) out vec4 outColor;
layout(location=1) out uint outSelected;
layout(location=2) out uint outEntityID;
void main() {
    outColor = texture(uTexture, TexCoord);
    outSelected = uSelectedFlag;
    outEntityID = uEntityID;
}'''

    # ════════════════════════════════════════════════════════
    # MRT Image 管理
    # ════════════════════════════════════════════════════════

    def _create_fbo(self, w: int, h: int) -> None:
        """创建 ZenGL MRT Images。"""
        ctx = self._pp_ctx
        self._pp_color_img = ctx.image((w, h), 'rgba8unorm')
        self._pp_id_img = ctx.image((w, h), 'r32uint')      # 选中标记, 边缘检测输入
        self._pp_pick_img = ctx.image((w, h), 'r32uint')     # 实体 ID, 拾取用
        self._pp_depth_img = ctx.image((w, h), 'depth24plus')
        self._pp_color_img.clear_value = (0.2, 0.2, 0.2, 1.0)

    def _ensure_fbo(self, w: int, h: int) -> None:
        """确保 MRT Images 尺寸匹配 (resize 时重建)。"""
        if self._pp_color_img is not None and self._pp_color_img.size == (w, h):
            return
        self._release_fbo()
        self._create_fbo(w, h)
        # ★ 重建后清除实体 pipeline 缓存 — 旧 pipeline 引用已释放的旧 images
        self._pp_entity_pipelines.clear()

    def _release_fbo(self) -> None:
        """释放 MRT Images (ZenGL GC 自动回收, 仅置空引用)。"""
        self._pp_color_img = None
        self._pp_id_img = None
        self._pp_pick_img = None
        self._pp_depth_img = None

    # ════════════════════════════════════════════════════════
    # Entity Pipeline 构建 (惰性, 每实体首次渲染时创建)
    # ════════════════════════════════════════════════════════

    def _build_entity_pipeline(self, eid: int) -> None:
        """为实体创建 MRT 场景 pipeline。

        需要 self.registered_entities / self.registered_meshes /
        self.registered_textures 已在 MRO 中可用 (由 ZenGLResourceManager 提供)。
        """
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        ctx = self.ctx
        entity = self.registered_entities.get(eid)
        if entity is None:
            return
        mesh_data = self.registered_meshes.get(entity.mesh_id)
        if mesh_data is None:
            return

        # 获取实体纹理
        from Application.Core.Renderer.ZenGL.ZenGLResourceManager import ZenGLResourceManager as ZRM
        tex_id = entity.texture_id
        tex_resources = []
        tex_layout = []
        if tex_id and tex_id in self.registered_textures:
            td = self.registered_textures[tex_id]
            tex_layout.append({'name': 'uTexture', 'binding': 0})
            tex_resources.append({
                'type': 'sampler', 'binding': 0, 'image': td.image,
                'min_filter': 'linear', 'mag_filter': 'linear',
            })

        from Application.Core.Renderer.VertexLayout import VertexLayout
        VertexLayout.check_shader_consistency(
            mesh_data.layout, self._pp_mrt_vs, "PostProcess MRT")

        pipeline = ctx.pipeline(
            vertex_shader=self._pp_mrt_vs,
            fragment_shader=self._pp_mrt_fs,
            layout=tex_layout,
            resources=tex_resources,
            uniforms={
                'model': np.identity(4, dtype='f4').flatten().tolist(),
                'view': np.identity(4, dtype='f4').flatten().tolist(),
                'projection': np.identity(4, dtype='f4').flatten().tolist(),
                'uSelectedFlag': 0,
                'uEntityID': 0,
            },
            framebuffer=[
                self._pp_color_img,
                self._pp_id_img,
                self._pp_pick_img,
                self._pp_depth_img,
            ],
            topology='triangles',
            cull_face='none',
            depth={'func': 'less', 'write': True},
            vertex_buffers=__import__('zengl').bind(
                mesh_data.vbo,
                mesh_data.layout.to_zengl_format(),
                *mesh_data.layout.get_active_locations(self._pp_mrt_vs),
            ),
            index_buffer=mesh_data.ebo,
            vertex_count=mesh_data.elements_count,
        )
        self._pp_entity_pipelines[eid] = pipeline
