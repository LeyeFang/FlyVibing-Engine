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
from Application.Core.Renderer.ZenGL.ZenGLOverlayRenderer import _DEBUG_ZENGL_OVERLAY


class ZenGLResourceManager:
    @dataclass
    class entity_data_struct:
        shader_id: int; texture_id: int; mesh_id: int; material_id: int
        pipeline: any = None; vao: int = 0

    @dataclass
    class mesh_data_struct:
        vbo: any = None; ebo: any = None
        elements_count: int = 0; vertex_stride: int = 32; ref_count: int = 0

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
        # 惰性 pick pipeline 构造参数 (ZenGL Pipeline 不暴露内部属性)
        _pick_vs: str = ""; _pick_topo: str = "triangles"
        _pick_ebo: any = None; _pick_muni: list = field(default_factory=list)
        _pick_vbo: any = None; _pick_fmt: str = ""; _pick_locs: list = field(default_factory=list)
        _pick_vcount: int = 0; _pick_stride: int = 0

    registered_entities: dict = {}
    registered_meshes: dict = {}
    registered_shaders: dict = {}
    registered_textures: dict = {}
    _overlay_gpu_resources: dict = {}
    _overlay_pick_key_map: dict = {}

    _VERTEX_STRIDE = 32; _POS_OFFSET = 0; _UV_OFFSET = 12; _NORMAL_OFFSET = 20

    @classmethod
    def register_entity(cls, entity_id: int) -> None:
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        mesh_id = SceneManager.GetEntityMesh(entity_id)
        material_id = SceneManager.GetEntityMaterial(entity_id)
        mesh = ResourceManager.GetMesh(mesh_id)
        material: Material = ResourceManager.GetMaterial(material_id)
        shader_id = material.shader_id
        shader: CPU_Shader = ResourceManager.GetShader(shader_id)

        cls.register_mesh(mesh, mesh_id)
        cls.register_shader(shader, shader_id)

        tex_id = material.texture_id_list[0] if material.texture_id_list else 0
        if tex_id:
            tex = ResourceManager.GetTexture(tex_id)
            cls.register_texture(tex, tex_id)

        mesh_data = cls.registered_meshes[mesh_id]
        shader_data = cls.registered_shaders[shader_id]
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
        if tex_id and has_sampler and tex_id in cls.registered_textures:
            td = cls.registered_textures[tex_id]
            layout.append({'name': 'uTexture', 'binding': 0})
            resources.append({'type': 'sampler', 'binding': 0, 'image': td.image,
                              'min_filter': 'linear', 'mag_filter': 'linear'})

        pipeline = ZenGLCore.ctx.pipeline(
            vertex_shader=shader_data.vs_src,
            fragment_shader=shader_data.fs_src,
            uniforms=uniforms, layout=layout, resources=resources,
            framebuffer=ZenGLCore.get_framebuffer(),
            topology='triangles', cull_face='none',
            depth={'func': 'less', 'write': True},
            vertex_buffers=zengl.bind(mesh_data.vbo, '3f 2f 3f', 0, 1, -1),
            index_buffer=mesh_data.ebo,
            vertex_count=mesh_data.elements_count,
        )

        cls.registered_entities[entity_id] = cls.entity_data_struct(
            shader_id=shader_id, texture_id=tex_id, mesh_id=mesh_id,
            material_id=material_id, pipeline=pipeline, vao=0)

    @classmethod
    def register_mesh(cls, mesh: Mesh, mesh_id: int) -> None:
        if mesh_id in cls.registered_meshes:
            cls.registered_meshes[mesh_id].ref_count += 1; return
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        vn = np.hstack((mesh.vertices, mesh.uvs, mesh.normals)).astype('f4')
        idx = mesh.indices.astype('i4')
        vbo = ZenGLCore.ctx.buffer(vn.tobytes())
        ebo = ZenGLCore.ctx.buffer(idx.tobytes(), index=True)
        cls.registered_meshes[mesh_id] = cls.mesh_data_struct(
            vbo=vbo, ebo=ebo,
            elements_count=int(idx.size), ref_count=1)

    @classmethod
    def register_shader(cls, shader: CPU_Shader, shader_id: int) -> None:
        if shader_id in cls.registered_shaders:
            cls.registered_shaders[shader_id].ref_count += 1; return
        ut = shader.uniforms_name_type.copy()
        cls.registered_shaders[shader_id] = cls.shader_data_struct(
            vs_src=shader.vs_src, fs_src=shader.fs_src,
            uniforms_type=ut, ref_count=1)

    @classmethod
    def register_texture(cls, texture: CPU_Texture, texture_id: int) -> None:
        if texture_id in cls.registered_textures:
            cls.registered_textures[texture_id].ref_count += 1; return
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        px = texture.image_data
        if px is None: px = np.array([[[255,255,255,255]]], 'uint8')
        ch = texture.channels or (px.shape[2] if len(px.shape)==3 else 1)
        h, w = px.shape[:2]
        fmt = 'rgba8unorm' if ch>=3 else 'r8unorm'
        if ch==3:
            p = np.zeros((h,w,4),'uint8'); p[:,:,:3]=px; px=p
        img = ZenGLCore.ctx.image((w,h), fmt, px.tobytes())
        cls.registered_textures[texture_id] = cls.texture_data_struct(image=img, ref_count=1)

    @classmethod
    def register_overlay_drawable(cls, overlay: 'RRM.overlay_drawable_struct') -> None:
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore; ctx = ZenGLCore.ctx
        verts = overlay.vertices
        vbo = ctx.buffer(verts.tobytes() if isinstance(verts, np.ndarray) else verts)
        ebo = None
        if overlay.indices is not None:
            idx = overlay.indices.astype('i4') if isinstance(overlay.indices, np.ndarray) else np.array(overlay.indices, 'i4')
            ebo = ctx.buffer(idx.tobytes(), index=True)

        vs_stride = getattr(overlay, 'vertex_stride', 0)
        vs_attrs = getattr(overlay, 'vertex_attrs', [(0,3,0)])
        fmt_parts = [f'{c}f' for _,c,_ in sorted(vs_attrs, key=lambda x:x[2])]
        locs = [loc for loc,_,_ in sorted(vs_attrs, key=lambda x:x[2])]
        fmt_str = ' '.join(fmt_parts)
        vb = zengl.bind(vbo, fmt_str, *locs)
        vc = vbo.size // vs_stride if ebo is None else ebo.size // 4

        topo_map = {'triangles':'triangles','lines':'lines','line_strip':'line_strip','points':'points'}
        topo = topo_map.get(overlay.draw_mode, 'triangles')

        # 补丁 sampler → layout(binding=)
        fs_p = re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', overlay.fs_src)
        vs_p = re.sub(r'uniform\s+sampler(\S+)\s+(\w+)\s*;', r'layout(binding=0) uniform sampler\1 \2;', overlay.vs_src)

        kw = {'vertex_shader': vs_p, 'fragment_shader': fs_p,
              'framebuffer': ZenGLCore.get_overlay_framebuffer(),
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
                tl = [{'name':'uLetterTex','binding':0}]
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

        cls._overlay_gpu_resources[overlay.key] = cls.overlay_gpu_struct(
            key=overlay.key, pipeline=pipeline, pick_pipeline=None,
            draw_mode=overlay.draw_mode,
            elements_count=vc, depth_test=overlay.depth_test, blend=overlay.blend,
            cull_face=overlay.cull_face, ignore_scene_matrices=overlay.ignore_scene_matrices,
            uniforms_setup=overlay.uniforms_setup,
            uniforms=getattr(overlay, 'uniforms', None), texture=ot,
            texture_uniform=getattr(overlay,'texture_uniform','uLetterTex'),
            model_matrix_cb=overlay.model_matrix_cb,
            pick_type=overlay.pick_type, pick_id=overlay.pick_id,
            render_layer=getattr(overlay, 'render_layer', 0),
            # 缓存 pick pipeline 构造参数 (ZenGL Pipeline 不暴露 vertex_shader 等属性)
            _pick_vs=vs_p, _pick_topo=topo, _pick_ebo=ebo,
            _pick_muni=[mn for mn in ('uModel', 'uView', 'uProj') if mn in ou],
            _pick_vbo=vbo, _pick_fmt=fmt_str, _pick_locs=locs, _pick_vcount=vc,
            _pick_stride=vs_stride,
        )
        if overlay.pick_type > 0:
            cls._overlay_pick_key_map[(overlay.pick_type, overlay.pick_id)] = overlay.key
            # pick_pipeline 在首帧 _render_overlay_pick_pass 中惰性创建

    @classmethod
    def unregister_overlay_drawable(cls, key: str) -> None:
        cls._overlay_gpu_resources.pop(key, None)
        rm = [k for k,v in cls._overlay_pick_key_map.items() if v==key]
        for k in rm: cls._overlay_pick_key_map.pop(k, None)
