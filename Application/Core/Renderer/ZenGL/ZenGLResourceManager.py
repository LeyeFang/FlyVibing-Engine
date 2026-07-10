"""
ZenGLResourceManager — GPU 资源管理器 (Mesh/Shader/Texture/Entity/Overlay)。
对应主线: Application/Core/Renderer/OpenGL/OpenGLResourceManager.py
"""

from __future__ import annotations
import re, numpy as np
from dataclasses import dataclass, field
import zengl

from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Resource.Material import Material, Shader as CPU_Shader, Texture as CPU_Texture
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.Renderer import RenderResourceManger as RRM
from Application.Core.Renderer.VertexLayout import VertexLayout, STD_LAYOUT
from Application.Core.Renderer.ZenGL.ZenGLOverlays import _DEBUG_ZENGL_OVERLAY


class ZenGLResourceManager:

    def __init__(self) -> None:
        super().__init__()
        self.registered_entities: dict = {}
        self.registered_meshes: dict = {}
        self.registered_shaders: dict = {}
        self.registered_textures: dict = {}
        self._overlay_gpu_resources: dict = {}
        self._overlay_pick_key_map: dict = {}

    @dataclass
    class entity_data_struct:
        shader_id: int; texture_id: int; mesh_id: int; material_id: int
        pipeline: any = None; vao: int = 0

    @dataclass
    class mesh_data_struct:
        vbo: any = None; ebo: any = None
        elements_count: int = 0; vertex_stride: int = 32; ref_count: int = 0
        layout: 'VertexLayout' = None  # ★ 顶点格式描述符

    @dataclass
    class shader_data_struct:
        vs_src: str = ""; fs_src: str = ""
        uniforms_type: dict = field(default_factory=dict)
        ref_count: int = 0

    @dataclass
    class texture_data_struct:
        image: any = None; ref_count: int = 0

    @dataclass
    class overlay_gpu_struct:
        key: str = ""; pipeline: any = None; pick_pipeline: any = None
        draw_mode: str = 'triangles'; elements_count: int = 0
        depth_test: bool = True; blend: bool = False; cull_face: bool = False
        ignore_scene_matrices: bool = False
        uniforms_setup: any = None; uniforms: dict = None; texture: any = None
        texture_uniform: str = 'uLetterTex'
        model_matrix_cb: any = None; pick_type: int = 0; pick_id: int = 0; render_layer: int = 0
        layout: 'VertexLayout' = None  # ★ 顶点格式描述符
        # 惰性 pick pipeline 构造参数 (ZenGL Pipeline 不暴露内部属性)
        _pick_vs: str = ""; _pick_topo: str = "triangles"
        _pick_ebo: any = None; _pick_muni: list = field(default_factory=list)
        _pick_vbo: any = None; _pick_fmt: str = ""; _pick_locs: list = field(default_factory=list)
        _pick_vcount: int = 0; _pick_stride: int = 0
        # ★ resize 重建用: 保存原始 overlay 定义
        _orig_vs: str = ""; _orig_fs: str = ""
        _orig_vertices: any = None; _orig_indices: any = None
        _orig_stride: int = 0; _orig_attrs: tuple = ()

    def register_entity(self, entity_id: int) -> None:
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader: CPU_Shader = ResourceManager.GetShader(shader_id)

        self.register_mesh(mesh, mesh_id)
        self.register_shader(shader, shader_id)

        tex_id = material.texture_id_list[0] if material.texture_id_list else 0
        if tex_id:
            tex = ResourceManager.GetTexture(tex_id)
            self.register_texture(tex, tex_id)

        mesh_data = self.registered_meshes[mesh_id]
        shader_data = self.registered_shaders[shader_id]
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore

        # uniforms → flat list (ZenGL 要求)
        uniforms = {}
        layout = []; resources = []
        for n, t in shader_data.uniforms_type.items():
            if t in ('sampler2D', 'sampler'): continue
            if t == 'mat4': uniforms[n] = np.identity(4, 'f4').flatten().tolist()
            elif t in ('float', 'double'): uniforms[n] = 0.0
            elif t in ('int',): uniforms[n] = 0

        # 纹理 — 只在 shader 中实际有 sampler 时才加 layout
        has_sampler = any(t in ('sampler2D', 'sampler') for t in shader_data.uniforms_type.values())
        if tex_id and has_sampler and tex_id in self.registered_textures:
            td = self.registered_textures[tex_id]
            layout.append({'name': 'uTexture', 'binding': 0})
            resources.append({'type': 'sampler', 'binding': 0, 'image': td.image,
                              'min_filter': 'linear', 'mag_filter': 'linear'})

        # ★ 顶点格式: 优先使用 mesh.layout, 回退到旧硬编码
        mesh_layout = getattr(mesh_data, 'layout', None) or STD_LAYOUT.ENTITY_POS_UV_NORMAL
        VertexLayout.check_shader_consistency(
            mesh_layout, shader_data.vs_src, f"entity shader '{shader_id}'")

        pipeline = self.ctx.pipeline(
            vertex_shader=shader_data.vs_src,
            fragment_shader=shader_data.fs_src,
            uniforms=uniforms, layout=layout, resources=resources,
            framebuffer=self.get_framebuffer(),
            topology='triangles', cull_face='none',
            depth={'func': 'less', 'write': True},
            vertex_buffers=zengl.bind(
                mesh_data.vbo,
                mesh_layout.to_zengl_format(),
                *mesh_layout.get_active_locations(shader_data.vs_src)),
            index_buffer=mesh_data.ebo,
            vertex_count=mesh_data.elements_count,
        )

        self.registered_entities[entity_id] = self.entity_data_struct(
            shader_id=shader_id, texture_id=tex_id, mesh_id=mesh_id,
            material_id=material_id, pipeline=pipeline, vao=0)

    def _rebuild_entity_pipelines(self) -> None:
        """resize 后重建所有实体管线 — 新 framebuffer images 已创建，
        但已有 pipeline 仍引用旧 images。此方法用当前 framebuffer 重建管线。
        """
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        for entity_id, entity in list(self.registered_entities.items()):
            try:
                mesh_data = self.registered_meshes.get(entity.mesh_id)
                shader_data = self.registered_shaders.get(entity.shader_id)
                if mesh_data is None or shader_data is None:
                    continue

                # ── 重建 uniforms / layout / resources (与 register_entity 一致) ──
                uniforms = {}
                layout = []; resources = []
                for n, t in shader_data.uniforms_type.items():
                    if t in ('sampler2D', 'sampler'): continue
                    if t == 'mat4': uniforms[n] = np.identity(4, 'f4').flatten().tolist()
                    elif t in ('float', 'double'): uniforms[n] = 0.0
                    elif t in ('int',): uniforms[n] = 0

                has_sampler = any(
                    t in ('sampler2D', 'sampler') for t in shader_data.uniforms_type.values())
                if entity.texture_id and has_sampler and entity.texture_id in self.registered_textures:
                    td = self.registered_textures[entity.texture_id]
                    layout.append({'name': 'uTexture', 'binding': 0})
                    resources.append({
                        'type': 'sampler', 'binding': 0, 'image': td.image,
                        'min_filter': 'linear', 'mag_filter': 'linear'})

                mesh_layout = getattr(mesh_data, 'layout', None) or STD_LAYOUT.ENTITY_POS_UV_NORMAL
                VertexLayout.check_shader_consistency(
                    mesh_layout, shader_data.vs_src, f"entity shader '{entity.shader_id}'")

                # ★ 关键: 用当前 framebuffer 重建管线
                new_pipeline = self.ctx.pipeline(
                    vertex_shader=shader_data.vs_src,
                    fragment_shader=shader_data.fs_src,
                    uniforms=uniforms, layout=layout, resources=resources,
                    framebuffer=self.get_framebuffer(),
                    topology='triangles', cull_face='none',
                    depth={'func': 'less', 'write': True},
                    vertex_buffers=zengl.bind(
                        mesh_data.vbo,
                        mesh_layout.to_zengl_format(),
                        *mesh_layout.get_active_locations(shader_data.vs_src)),
                    index_buffer=mesh_data.ebo,
                    vertex_count=mesh_data.elements_count,
                )
                entity.pipeline = new_pipeline
            except Exception:
                pass

    def _rebuild_overlay_pipelines(self) -> None:
        """resize 后重建所有 overlay 管线 — 用当前 framebuffer 重建。"""
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        ctx = self.ctx
        for key, gpu in list(self._overlay_gpu_resources.items()):
            try:
                if not gpu._orig_vs or gpu._orig_vertices is None:
                    continue
                verts = gpu._orig_vertices
                vbo = ctx.buffer(verts.tobytes() if isinstance(verts, np.ndarray) else verts)
                ebo = None
                if gpu._orig_indices is not None:
                    idx = gpu._orig_indices.astype('i4') if isinstance(gpu._orig_indices, np.ndarray) else np.array(gpu._orig_indices, 'i4')
                    ebo = ctx.buffer(idx.tobytes(), index=True)

                ol_layout = gpu.layout
                if ol_layout is None:
                    attrs = gpu._orig_attrs or ((0, 3, 0),)
                    ol_layout = VertexLayout(attributes=tuple(attrs), stride=gpu._orig_stride or 12)
                fmt_str = ol_layout.to_zengl_format()
                locs = ol_layout.to_zengl_locations()
                vb = zengl.bind(vbo, fmt_str, *locs)
                vc = vbo.size // (gpu._orig_stride or 12) if ebo is None else ebo.size // 4

                topo_map = {'triangles':'triangles','lines':'lines','line_strip':'line_strip','points':'points'}
                topo = topo_map.get(gpu.draw_mode, 'triangles')

                import re as _re
                fs_p = _re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', gpu._orig_fs)
                vs_p = _re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', gpu._orig_vs)

                kw = {'vertex_shader': vs_p, 'fragment_shader': fs_p,
                      'framebuffer': self.get_overlay_framebuffer(),
                      'topology': topo, 'vertex_buffers': vb, 'vertex_count': vc}
                if ebo: kw['index_buffer'] = ebo
                kw['depth'] = {'func':'less','write':True} if gpu.depth_test else {'func':'always','write':False}
                if gpu.blend: kw['blend'] = {'enable':True,'src_color':'src_alpha','dst_color':'one_minus_src_alpha'}
                if gpu.cull_face: kw['cull_face'] = 'back'

                # 重建 uniforms
                ou = {}
                _UNIFORM_RE = _re.compile(r'uniform\s+(\w+)\s+(\w+)\s*;')
                _SAMPLER_TYPES = {'sampler2D', 'sampler3D', 'samplerCube', 'sampler2DShadow',
                                  'sampler', 'usampler2D', 'isampler2D', 'image2D'}
                for src in (gpu._orig_vs, gpu._orig_fs):
                    for m in _UNIFORM_RE.finditer(src):
                        utype, uname = m.group(1), m.group(2)
                        if uname in ou or utype in _SAMPLER_TYPES:
                            continue
                        if utype in ('mat4',): ou[uname] = np.identity(4, 'f4').flatten().tolist()
                        elif utype in ('mat3',): ou[uname] = np.identity(3, 'f4').flatten().tolist()
                        elif utype in ('vec4',): ou[uname] = [1.0, 1.0, 1.0, 1.0]
                        elif utype in ('vec3',): ou[uname] = [0.0, 0.0, 0.0]
                        elif utype in ('vec2',): ou[uname] = [0.0, 0.0]
                        elif utype in ('float', 'double',): ou[uname] = [1.0]
                        elif utype in ('int', 'uint', 'bool',): ou[uname] = [0]
                if gpu.uniforms:
                    for uname, uval in gpu.uniforms.items():
                        if isinstance(uval, np.ndarray): ou[uname] = uval.flatten().tolist()
                        elif isinstance(uval, (list, tuple)): ou[uname] = list(uval)
                kw['uniforms'] = ou

                if gpu.texture is not None:
                    kw['layout'] = [{'name': gpu.texture_uniform or 'uLetterTex', 'binding': 0}]
                    kw['resources'] = [{'type': 'sampler', 'binding': 0, 'image': gpu.texture,
                                        'min_filter': 'linear', 'mag_filter': 'linear'}]

                new_pipeline = ctx.pipeline(**kw)
                gpu.pipeline = new_pipeline
                gpu.pick_pipeline = None  # 惰性重建
            except Exception:
                pass

    def register_mesh(self, mesh: Mesh, mesh_id: int) -> None:
        if mesh_id in self.registered_meshes:
            self.registered_meshes[mesh_id].ref_count += 1; return
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        vn = np.hstack((mesh.vertices, mesh.uvs, mesh.normals)).astype('f4')
        idx = mesh.indices.astype('i4')
        vbo = self.ctx.buffer(vn.tobytes())
        ebo = self.ctx.buffer(idx.tobytes(), index=True)
        self.registered_meshes[mesh_id] = self.mesh_data_struct(
            vbo=vbo, ebo=ebo,
            elements_count=int(idx.size), ref_count=1,
            layout=mesh.layout or STD_LAYOUT.ENTITY_POS_UV_NORMAL,
        )

    def register_shader(self, shader: CPU_Shader, shader_id: int) -> None:
        if shader_id in self.registered_shaders:
            self.registered_shaders[shader_id].ref_count += 1; return
        ut = shader.uniforms_name_type.copy()
        self.registered_shaders[shader_id] = self.shader_data_struct(
            vs_src=shader.vs_src, fs_src=shader.fs_src,
            uniforms_type=ut, ref_count=1)

    def register_texture(self, texture: CPU_Texture, texture_id: int) -> None:
        if texture_id in self.registered_textures:
            self.registered_textures[texture_id].ref_count += 1; return
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        px = texture.image_data
        if px is None: px = np.array([[[255,255,255,255]]], 'uint8')
        ch = texture.channels or (px.shape[2] if len(px.shape)==3 else 1)
        h, w = px.shape[:2]
        fmt = 'rgba8unorm' if ch>=3 else 'r8unorm'
        if ch==3:
            p = np.zeros((h,w,4),'uint8'); p[:,:,:3]=px; px=p
        img = self.ctx.image((w,h), fmt, px.tobytes())
        self.registered_textures[texture_id] = self.texture_data_struct(image=img, ref_count=1)

    def register_overlay_drawable(self, overlay: 'RRM.overlay_drawable_struct') -> None:
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore; ctx = self.ctx
        verts = overlay.vertices
        vbo = ctx.buffer(verts.tobytes() if isinstance(verts, np.ndarray) else verts)
        ebo = None
        if overlay.indices is not None:
            idx = overlay.indices.astype('i4') if isinstance(overlay.indices, np.ndarray) else np.array(overlay.indices, 'i4')
            ebo = ctx.buffer(idx.tobytes(), index=True)

        # ★ 顶点格式: 优先 overlay.layout, 回退从 vertex_attrs 构造
        ol_layout = overlay.layout
        if ol_layout is None:
            vs_stride = getattr(overlay, 'vertex_stride', 0)
            vs_attrs = getattr(overlay, 'vertex_attrs', [(0, 3, 0)])
            ol_layout = VertexLayout(
                attributes=tuple(vs_attrs),
                stride=vs_stride or 12,
            )
        VertexLayout.check_shader_consistency(
            ol_layout, overlay.vs_src, f"overlay '{overlay.key}'")
        fmt_str = ol_layout.to_zengl_format()
        locs = ol_layout.to_zengl_locations()
        vb = zengl.bind(vbo, fmt_str, *locs)
        vs_stride = ol_layout.stride
        vc = vbo.size // vs_stride if ebo is None else ebo.size // 4

        # ★ 创建 position-only VBO 供 pick pipeline 使用
        #    从 VertexLayout 读取 location=0 的属性参数
        ploc, pcount, poffset = ol_layout.get_position_attr()
        pos_offset_floats = poffset // 4   # byte offset → float index
        if isinstance(verts, np.ndarray):
            pos_data = np.ascontiguousarray(
                verts[:, pos_offset_floats:pos_offset_floats + pcount].astype('f4'))
            pick_vbo = ctx.buffer(pos_data.tobytes())
        else:
            pick_vbo = vbo  # 非 numpy 回退 (不应发生)

        topo_map = {'triangles':'triangles','lines':'lines','line_strip':'line_strip','points':'points'}
        topo = topo_map.get(overlay.draw_mode, 'triangles')

        # 补丁 sampler → layout(binding=)
        fs_p = re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', overlay.fs_src)
        vs_p = re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', overlay.vs_src)

        kw = {'vertex_shader': vs_p, 'fragment_shader': fs_p,
              'framebuffer': self.get_overlay_framebuffer(),
              'topology': topo, 'vertex_buffers': vb, 'vertex_count': vc}
        if ebo: kw['index_buffer'] = ebo
        kw['depth'] = {'func':'less','write':True} if overlay.depth_test else {'func':'always','write':False}
        if overlay.blend: kw['blend'] = {'enable':True,'src_color':'src_alpha','dst_color':'one_minus_src_alpha'}
        if overlay.cull_face: kw['cull_face'] = 'back'

        # overlay uniforms — 全部由 shader 源码自动检测 (不预填充任何矩阵)
        #    ZenGL 只创建显式声明的 uniform 槽位, 预填不存在的 uniform (如 uProj) 会崩溃
        ou = {}
        _UNIFORM_RE = re.compile(r'uniform\s+(\w+)\s+(\w+)\s*;')
        _SAMPLER_TYPES = {'sampler2D', 'sampler3D', 'samplerCube', 'sampler2DShadow',
                          'sampler', 'usampler2D', 'isampler2D', 'image2D'}
        for src in (overlay.vs_src, overlay.fs_src):
            for m in _UNIFORM_RE.finditer(src):
                utype, uname = m.group(1), m.group(2)
                if uname in ou or utype in _SAMPLER_TYPES:
                    continue
                if utype in ('mat4',):
                    ou[uname] = np.identity(4, 'f4').flatten().tolist()
                elif utype in ('mat3',):
                    ou[uname] = np.identity(3, 'f4').flatten().tolist()
                elif utype in ('vec4',):
                    ou[uname] = [1.0, 1.0, 1.0, 1.0]
                elif utype in ('vec3',):
                    ou[uname] = [0.0, 0.0, 0.0]
                elif utype in ('vec2',):
                    ou[uname] = [0.0, 0.0]
                elif utype in ('float', 'double',):
                    ou[uname] = [1.0]
                elif utype in ('int', 'uint', 'bool',):
                    ou[uname] = [0]

        # overlay 声明式 uniform 初始值 — 覆盖自动检测的默认值
        if getattr(overlay, 'uniforms', None):
            for uname, uval in overlay.uniforms.items():
                if isinstance(uval, np.ndarray):
                    ou[uname] = uval.flatten().tolist()
                elif isinstance(uval, (list, tuple)):
                    ou[uname] = list(uval)

        kw['uniforms'] = ou

        # 纹理
        ot = None; tl = []; tr = []
        if hasattr(overlay,'texture_pixels') and overlay.texture_pixels is not None:
            px = overlay.texture_pixels
            if isinstance(px, np.ndarray):
                h,w = px.shape[:2]; ch = px.shape[2] if len(px.shape)>=3 else 1
                fmt = 'rgba8unorm' if ch>=3 else 'r8unorm'
                if ch==3: p=np.zeros((h,w,4),'uint8'); p[:,:,:3]=px; px=p
                ot = ctx.image((w,h), fmt, px.tobytes())
                tl = [{'name': getattr(overlay, 'texture_uniform', 'uLetterTex') or 'uLetterTex', 'binding': 0}]
                tr = [{'type':'sampler','binding':0,'image':ot,'min_filter':'linear','mag_filter':'linear'}]
        kw['layout'] = tl; kw['resources'] = tr

        pipeline = ctx.pipeline(**kw)

        # ★ DEBUG: 检查 pipeline 中实际有哪些 uniform 槽位
        if _DEBUG_ZENGL_OVERLAY:
            declared = list(ou.keys())
            actual = list(pipeline.uniforms.keys()) if hasattr(pipeline, 'uniforms') else []
            missing = [u for u in ['uColor', 'uFadeCenter', 'uFadeRadius'] if u not in actual]
            extra = [u for u in actual if u not in declared]
            vshape = verts.shape if isinstance(verts, np.ndarray) else '?'
            ishape = overlay.indices.shape if isinstance(overlay.indices, np.ndarray) and overlay.indices is not None else 'None'
            print(f"[ZG-REGISTER] '{overlay.key}'  mode={overlay.draw_mode}  verts={vshape}  idx={ishape}  vcount={vc}")
            print(f"[ZG-REGISTER]   declared uniforms: {declared}")
            print(f"[ZG-REGISTER]   actual   uniforms: {actual}")
            if missing:
                print(f"[ZG-REGISTER]   ★★★ MISSING (will be 0 → invisible!): {missing}")
            if extra:
                print(f"[ZG-REGISTER]   auto-detected extras: {extra}")
            print(f"[ZG-REGISTER]   depth={kw.get('depth')}  blend={kw.get('blend')}")

        self._overlay_gpu_resources[overlay.key] = self.overlay_gpu_struct(
            key=overlay.key, pipeline=pipeline, pick_pipeline=None,
            draw_mode=overlay.draw_mode,
            elements_count=vc, depth_test=overlay.depth_test, blend=overlay.blend,
            cull_face=overlay.cull_face, ignore_scene_matrices=overlay.ignore_scene_matrices,
            uniforms_setup=overlay.uniforms_setup,
            uniforms=getattr(overlay, 'uniforms', None), texture=ot,
            texture_uniform=getattr(overlay,'texture_uniform','uLetterTex'),
            model_matrix_cb=overlay.model_matrix_cb,
            layout=ol_layout,
            pick_type=overlay.pick_type, pick_id=overlay.pick_id,
            render_layer=getattr(overlay, 'render_layer', 0),
            # 缓存 pick pipeline 构造参数 (ZenGL Pipeline 不暴露 vertex_shader 等属性)
            _pick_vs=vs_p, _pick_topo=topo, _pick_ebo=ebo,
            _pick_muni=[mn for mn in ('uModel', 'uView', 'uProj') if mn in ou],
            _pick_vbo=pick_vbo, _pick_fmt=fmt_str, _pick_locs=locs, _pick_vcount=vc,
            _pick_stride=vs_stride,
            # ★ resize 重建用: 保存原始 overlay 定义
            _orig_vs=overlay.vs_src, _orig_fs=overlay.fs_src,
            _orig_vertices=verts, _orig_indices=overlay.indices,
            _orig_stride=vs_stride, _orig_attrs=(getattr(overlay, 'vertex_attrs', None) or ol_layout.attributes),
        )
        if overlay.pick_type > 0:
            self._overlay_pick_key_map[(overlay.pick_type, overlay.pick_id)] = overlay.key
            # pick_pipeline 在首帧 _render_overlay_pick_pass 中惰性创建

    def unregister_overlay_drawable(self, key: str) -> None:
        self._overlay_gpu_resources.pop(key, None)
        rm = [k for k,v in self._overlay_pick_key_map.items() if v==key]
        for k in rm: self._overlay_pick_key_map.pop(k, None)

    # ════════════════════════════════════════════════════════════
    # 资源卸载 (引用计数管理)
    # ════════════════════════════════════════════════════════════

    def unregister_entity(self, entity_id: int) -> None:
        """从 GPU 卸载实体 (ZenGL pipeline 由 GC 自动回收)。"""
        if entity_id not in self.registered_entities:
            return
        entity = self.registered_entities[entity_id]
        self._decref_mesh(entity.mesh_id)
        self._decref_shader(entity.shader_id)
        self._decref_texture(entity.texture_id)
        del self.registered_entities[entity_id]

    def unregister_mesh(self, mesh_id: int) -> None:
        self._decref_mesh(mesh_id)

    def unregister_shader(self, shader_id: int) -> None:
        self._decref_shader(shader_id)

    def unregister_texture(self, texture_id: int) -> None:
        self._decref_texture(texture_id)

    # ════════════════════════════════════════════════════════════
    # 引用计数辅助
    # ════════════════════════════════════════════════════════════

    def _decref_mesh(self, mesh_id: int) -> None:
        if mesh_id not in self.registered_meshes:
            return
        data = self.registered_meshes[mesh_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            del self.registered_meshes[mesh_id]

    def _decref_shader(self, shader_id: int) -> None:
        if shader_id not in self.registered_shaders:
            return
        data = self.registered_shaders[shader_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            del self.registered_shaders[shader_id]

    def _decref_texture(self, texture_id: int) -> None:
        if texture_id not in self.registered_textures:
            return
        data = self.registered_textures[texture_id]
        data.ref_count -= 1
        if data.ref_count <= 0:
            del self.registered_textures[texture_id]

    # ════════════════════════════════════════════════════════════
    # 批量资源清理 (Shutdown 时调用)
    # ════════════════════════════════════════════════════════════

    def _unregister_all_entities(self) -> None:
        """卸载所有已注册实体的 GPU 资源，级联降引用 mesh/shader/texture。"""
        for entity_id in list(self.registered_entities.keys()):
            self.unregister_entity(entity_id)

    def _unregister_all_overlays(self) -> None:
        """卸载所有 overlay 的 GPU 资源。"""
        for key in list(self._overlay_gpu_resources.keys()):
            self.unregister_overlay_drawable(key)
