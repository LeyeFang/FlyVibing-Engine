"""ZenGLEntityRenderer — ZenGL 实体渲染器"""
from __future__ import annotations
import numpy as np
from Application.Core.Scene.SceneManager import SceneManager
from Application.Resource.ResourceManager import ResourceManager


class ZenGLEntityRenderer:
    @classmethod
    def _RenderEntities(cls, view: np.ndarray, proj: np.ndarray) -> None:
        for eid in SceneManager.GetRenderableEntities():
            e = cls.registered_entities.get(eid)
            if not e or not e.pipeline: continue
            model = SceneManager.GetEntityModelMatrix(eid)
            try:
                e.pipeline.uniforms['model'][:] = model.astype('f4').tobytes()
                e.pipeline.uniforms['view'][:] = view.astype('f4').tobytes()
                e.pipeline.uniforms['projection'][:] = proj.astype('f4').tobytes()
            except: pass
            # ── 材质 uniform — 每帧从 Material 读取最新值上传 ──
            try:
                material = ResourceManager.GetMaterial(e.material_id)
                for u_name, u_value in material.uniforms_data.items():
                    if u_name in ('model', 'view', 'projection'):
                        continue
                    arr = np.array([u_value], dtype='f4') if not hasattr(u_value, '__len__') else np.array(u_value, dtype='f4')
                    try:
                        e.pipeline.uniforms[u_name][:] = arr.tobytes()
                    except Exception:
                        pass
            except Exception:
                pass
            e.pipeline.render()
