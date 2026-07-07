"""ZenGLOverlays — ZenGL 叠加层渲染器"""
from __future__ import annotations
import numpy as np

# ★ DEBUG: 设为 False 关闭诊断输出
_DEBUG_ZENGL_OVERLAY: bool = False
_seen_overlay_keys: set = set()  # 避免重复打印同一 overlay 的 uniform 缺失


class ZenGLOverlays:

    @classmethod
    def _render_overlay_drawables(cls, view: np.ndarray, proj: np.ndarray, layer: int = -1) -> None:
        vp_w, vp_h = cls.viewport_width, cls.viewport_height

        overlays = list(cls._overlay_gpu_resources.items())
        if layer >= 0:
            overlays = [(k, g) for k, g in overlays if getattr(g, 'render_layer', 0) == layer]
        if _DEBUG_ZENGL_OVERLAY:
            print(f"[ZG-OVERLAY] === Frame: {len(overlays)} overlay(s), vp={vp_w}x{vp_h} ===")

        for _key, gpu in overlays:
            if not gpu.pipeline:
                if _DEBUG_ZENGL_OVERLAY:
                    print(f"[ZG-OVERLAY]   SKIP '{_key}': no pipeline")
                continue

            if _DEBUG_ZENGL_OVERLAY and _key not in _seen_overlay_keys:
                # 仅首次打印 overlay 详情
                _seen_overlay_keys.add(_key)
                print(f"[ZG-OVERLAY]   '{_key}'  ignore_scene={gpu.ignore_scene_matrices}  depth={gpu.depth_test}  blend={gpu.blend}  uniforms_setup={gpu.uniforms_setup.__name__ if gpu.uniforms_setup else None}")

            if gpu.ignore_scene_matrices and gpu.model_matrix_cb:
                model = gpu.model_matrix_cb(vp_w, vp_h)
                if model is not None:
                    try: gpu.pipeline.uniforms['uModel'][:] = model.T.astype('f4').tobytes()
                    except Exception as e:
                        if _DEBUG_ZENGL_OVERLAY: print(f"[ZG-OVERLAY]     uModel set FAILED: {e}")
                try:
                    from Application.Core.Math.ViewGizmo import compute_ortho_proj
                    op = compute_ortho_proj(vp_w, vp_h)
                    gpu.pipeline.uniforms['uProj'][:] = op.astype('f4').tobytes()
                except Exception as e:
                    if _DEBUG_ZENGL_OVERLAY: print(f"[ZG-OVERLAY]     uProj set FAILED: {e}")
            else:
                try: gpu.pipeline.uniforms['uView'][:] = view.astype('f4').tobytes()
                except Exception as e:
                    if _DEBUG_ZENGL_OVERLAY: print(f"[ZG-OVERLAY]     uView set FAILED: {e}")
                try: gpu.pipeline.uniforms['uProj'][:] = proj.astype('f4').tobytes()
                except Exception as e:
                    if _DEBUG_ZENGL_OVERLAY: print(f"[ZG-OVERLAY]     uProj set FAILED: {e}")

            # ★ 声明式动态 uniform 解析 (替代旧的 uniforms_setup 回调)
            #    overlay.uniforms = {'uColor': np.array(...), 'uFadeCenter': 'camera.fade_center', ...}
            #    渲染器基类 _resolve_overlay_uniforms 将动态源解析为当前帧值
            if gpu.uniforms:
                resolved = cls._resolve_overlay_uniforms(gpu.uniforms)
                for uname, uval in resolved.items():
                    _try_set_uniform(gpu.pipeline, uname, uval, overlay_key=_key)
            # uniforms_setup 保留兼容 (旧 overlay 仍可用, 但失败无害)
            if gpu.uniforms_setup:
                try: gpu.uniforms_setup(gpu.pipeline)
                except Exception as e:
                    if _DEBUG_ZENGL_OVERLAY:
                        print(f"[ZG-OVERLAY]     uniforms_setup({gpu.uniforms_setup.__name__}) FAILED: {e}")
            try: gpu.pipeline.render()
            except Exception as ex:
                print(f"[ZG-OVERLAY]     render() ERROR: {ex}")


def _try_set_uniform(pipeline, name: str, value: np.ndarray, overlay_key: str = "?") -> None:
    try:
        if name not in pipeline.uniforms:
            if _DEBUG_ZENGL_OVERLAY:
                available = list(pipeline.uniforms.keys())
                print(f"[ZG-OVERLAY]     ★ UNIFORM '{name}' NOT in pipeline! Available: {available}")
            return
        pipeline.uniforms[name][:] = value.tobytes()
    except Exception as e:
        if _DEBUG_ZENGL_OVERLAY:
            print(f"[ZG-OVERLAY]     _try_set_uniform('{name}') FAILED: {e}")
