"""ZenGLRenderer — ZenGL 渲染器 MRO 编排层。对应主线 openGLRenderer。"""
from __future__ import annotations
from typing import Callable
import numpy as np

from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
from Application.Core.Renderer.ZenGL.ZenGLResourceManager import ZenGLResourceManager
from Application.Core.Renderer.ZenGL.ZenGLEntityRenderer import ZenGLEntityRenderer
from Application.Core.Renderer.ZenGL.ZenGLOverlayRenderer import ZenGLOverlayRenderer


class ZenGLRenderer(
    ZenGLCore, ZenGLResourceManager,
    ZenGLEntityRenderer, ZenGLOverlayRenderer,
    Renderer, RenderResourceManger,
):
    _scene_fbo_override: int = 0
    _outline_selected_ids: set = set()
    _pre_overlay_callbacks: list = []
    _outliner: any = None

    @classmethod
    def register_pre_overlay_callback(cls, cb): 
        if cb not in cls._pre_overlay_callbacks: cls._pre_overlay_callbacks.append(cb)
    @classmethod
    def unregister_pre_overlay_callback(cls, cb):
        if cb in cls._pre_overlay_callbacks: cls._pre_overlay_callbacks.remove(cb)
    @classmethod
    def register_outliner(cls, o): cls._outliner = o
    @classmethod
    def unregister_outliner(cls): cls._outliner = None

    @classmethod
    def Create(cls):
        from Application.Editor.EditorHost import EditorHost
        from Application.Core.Renderer.CommandQueue import CommandQueue
        sz = EditorHost.editor_window.GetSize()
        ZenGLCore.init_core(sz)
        cls.viewport_width, cls.viewport_height = sz
        cls.aspect_ratio = sz[0]/sz[1]
        # 缓存初始相机矩阵
        if cls._active_camera is not None:
            cls._cached_view = cls._active_camera.get_view_matrix()
            cls._cached_proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)
        # 初始化命令队列
        cls._command_queue = CommandQueue()
        return cls

    @classmethod
    def _do_start_frame(cls) -> None:
        ctx = ZenGLCore.ctx
        ctx.new_frame()
        if cls._pending_resize:
            w,h = cls._pending_resize; ZenGLCore.rebuild_images(w,h); cls._pending_resize = None
        view = cls._cached_view if cls._cached_view is not None else np.identity(4, 'f4')
        proj = cls._cached_proj if cls._cached_proj is not None else np.identity(4, 'f4')
        ZenGLCore.clear_frame()

        for cb in cls._pre_overlay_callbacks:
            try: cb(view, proj, cls.viewport_width, cls.viewport_height)
            except: pass

        cls._RenderEntities(view, proj)
        # ★ 走 _render_all_overlays (分层: layer 0 → callbacks → clear depth → layer 1)
        cls._render_all_overlays(view, proj)
        # Overlay pick pass
        # ★ Overlay pick pass — 对齐 OpenGLPickSystem._render_overlays_pick_pass
        cls._ensure_pick_images(cls.viewport_width, cls.viewport_height)
        cls._render_overlay_pick_pass(view, proj)
        # _render_overlays 已由 _render_all_overlays 内部调用
        ctx.end_frame()
        # 每帧结束后读取 pick buffer
        cls._read_pick_buffer()
        # ★ 最终 blit: 确保 layer 1 (screen overlay) 写入 color_image 后刷到屏幕
        try: ZenGLCore._color_image.blit()
        except Exception: pass

    @classmethod
    def EndFrame(cls) -> None: pass

    # ════════════════════════════════════════════════════════════
    # 拾取系统 (entity + overlay)
    # ════════════════════════════════════════════════════════════

    _zg_pick_data: bytes = b''
    _zg_pick_size: tuple = (0, 0)

    _zg_overlay_pick_img: any = None        # rgba8unorm — overlay pick target
    _zg_overlay_pick_data: bytes = b''
    _zg_overlay_pick_size: tuple = (0, 0)

    @classmethod
    def _ensure_pick_images(cls, w: int, h: int) -> None:
        """确保 overlay pick 图像存在且尺寸匹配。resize 时清空 pick pipeline 缓存。"""
        ctx = ZenGLCore.ctx
        if cls._zg_overlay_pick_img is None or cls._zg_overlay_pick_img.size != (w, h):
            cls._zg_overlay_pick_img = ctx.image((w, h), 'rgba8unorm')
            cls._zg_overlay_pick_img.clear_value = (0.0, 0.0, 0.0, 1.0)
            # resize → 清空惰性 pick pipeline, 下帧重建
            for gpu in cls._overlay_gpu_resources.values():
                gpu.pick_pipeline = None

    @classmethod
    def _render_overlay_pick_pass(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """Overlay 拾取 pass — 将 pick_type>0 的 overlay 渲染到 _zg_overlay_pick_img。
        编码: R=0 (标记 overlay), G=pick_type, B=pick_id
        """
        img = cls._zg_overlay_pick_img
        if img is None:
            return

        pickable = [(k, g) for k, g in cls._overlay_gpu_resources.items() if g.pick_type > 0]
        if not pickable:
            return

        img.clear()
        vp_w, vp_h = cls.viewport_width, cls.viewport_height
        ctx = ZenGLCore.ctx

        # ★ Pick VS — 极简, 只用 location=0, 根据 overlay 实际声明的矩阵选择变体
        _PICK_FS = """#version 440 core
uniform float uPickType;
uniform float uPickID;
out vec4 fragColor;
void main() {
    fragColor = vec4(0.0, uPickType / 255.0, uPickID / 255.0, 1.0);
}"""

        _PICK_VS_MODEL_ONLY = """#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 uModel;
void main() {
    gl_Position = uModel * vec4(aPos, 1.0);
}"""

        _PICK_VS_MODEL_PROJ = """#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 uModel;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uModel * vec4(aPos, 1.0);
}"""

        _PICK_VS_VIEW_PROJ = """#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}"""

        for _key, gpu in pickable:
            pp = gpu.pick_pipeline
            if pp is None:
                try:
                    import zengl as _zengl
                    # ★ 只用 position (location=0), 但 stride 要与 interleaved 格式一致
                    pick_vb = _zengl.bind(gpu._pick_vbo, '3f', 0)
                    # 根据 VS 源码中 gl_Position 的实际计算选择 pick VS 变体
                    vs = gpu._pick_vs
                    gl_line = [l for l in vs.split('\n') if 'gl_Position' in l]
                    uses_uview = any('uView' in l for l in gl_line)
                    uses_uproj = any('uProj' in l for l in gl_line)
                    if uses_uview:
                        pick_vs = _PICK_VS_VIEW_PROJ      # gl_Position = uProj * uView * ...
                    elif uses_uproj:
                        pick_vs = _PICK_VS_MODEL_PROJ     # gl_Position = uProj * uModel * ...
                    else:
                        pick_vs = _PICK_VS_MODEL_ONLY     # gl_Position = uModel * ...
                    pick_kw = {
                        'vertex_shader': pick_vs,
                        'fragment_shader': _PICK_FS,
                        'topology':     gpu._pick_topo,
                        'vertex_buffers': pick_vb,
                        'vertex_count': gpu._pick_vcount,
                        'framebuffer':  [img],
                    }
                    if gpu._pick_ebo is not None:
                        pick_kw['index_buffer'] = gpu._pick_ebo
                    pu = {}
                    for mn in gpu._pick_muni:
                        pu[mn] = [0.0]*16
                    pu['uPickType'] = [float(gpu.pick_type)]
                    pu['uPickID']  = [float(gpu.pick_id)]
                    pick_kw['uniforms'] = pu
                    pp = ctx.pipeline(**pick_kw)
                    gpu.pick_pipeline = pp
                except Exception as e:
                    print(f"[ZG-PICK] lazy pick pipeline failed for '{_key}': {e}")
                    continue

            # 设置矩阵 (与 visual pass 一致)
            if gpu.ignore_scene_matrices and gpu.model_matrix_cb:
                model = gpu.model_matrix_cb(vp_w, vp_h)
                if model is not None:
                    try: pp.uniforms['uModel'][:] = model.T.astype('f4').tobytes()
                    except: pass
                try:
                    from Application.Core.Math.ViewGizmo import compute_ortho_proj
                    op = compute_ortho_proj(vp_w, vp_h)
                    pp.uniforms['uProj'][:] = op.astype('f4').tobytes()
                except: pass
            else:
                try: pp.uniforms['uView'][:] = view.astype('f4').tobytes()
                except: pass
                try: pp.uniforms['uProj'][:] = proj.astype('f4').tobytes()
                except: pass
            try: pp.uniforms['uPickType'][:] = np.array([float(gpu.pick_type)], 'f4').tobytes()
            except: pass
            try: pp.uniforms['uPickID'][:] = np.array([float(gpu.pick_id)], 'f4').tobytes()
            except: pass
            try: pp.render()
            except Exception: pass

    @classmethod
    def _read_pick_buffer(cls) -> None:
        """每帧结束后读取 entity + overlay pick 图像。"""
        # Entity pick (OutlinerID)
        from Application.Editor.Rendering.OutlinerID import OutlinerID
        if OutlinerID._zg_pick_img is not None:
            try:
                cls._zg_pick_data = OutlinerID._zg_pick_img.read()
                cls._zg_pick_size = OutlinerID._zg_pick_img.size
            except Exception:
                pass
        # Overlay pick
        if cls._zg_overlay_pick_img is not None:
            try:
                cls._zg_overlay_pick_data = cls._zg_overlay_pick_img.read()
                cls._zg_overlay_pick_size = cls._zg_overlay_pick_img.size
            except Exception:
                pass

    @classmethod
    def pick_at(cls, x, y) -> tuple:
        """统一拾取 → ('overlay', key) | ('entity', id) | (None, None)。"""
        # 1. Overlay pick (gizmo 在 entity 之上, 优先)
        ow, oh = cls._zg_overlay_pick_size
        if cls._zg_overlay_pick_data and ow > 0 and oh > 0:
            try:
                px = max(0, min(int(x), ow - 1))
                py = max(0, min(oh - int(y) - 1, oh - 1))
                offset = (py * ow + px) * 4
                r = cls._zg_overlay_pick_data[offset]
                g = cls._zg_overlay_pick_data[offset + 1]
                b = cls._zg_overlay_pick_data[offset + 2]
                if r == 0 and g > 0:
                    key = cls._overlay_pick_key_map.get((g, b))
                    if key is not None:
                        return ('overlay', key)
            except Exception:
                pass

        # 2. Entity pick
        w, h = cls._zg_pick_size
        if cls._zg_pick_data and w > 0 and h > 0:
            try:
                px = max(0, min(int(x), w - 1))
                py = max(0, min(h - int(y) - 1, h - 1))
                offset = (py * w + px) * 4
                entity_id = int.from_bytes(cls._zg_pick_data[offset:offset + 4], 'little')
                if entity_id > 0:
                    return ('entity', entity_id)
            except Exception:
                pass

        return (None, None)

    @classmethod
    def update_pick_mouse(cls, x, y) -> None: pass

    @classmethod
    def register_overlay_drawable(cls, overlay):
        ZenGLResourceManager.register_overlay_drawable(overlay)
    @classmethod
    def unregister_overlay_drawable(cls, key):
        ZenGLResourceManager.unregister_overlay_drawable(key)

    # 为兼容 Engine.Create() 期望的 start_frame/end_frame
    @classmethod
    def StartFrame(cls): cls._do_start_frame()
