"""ZenGLEntityRenderer — ZenGL 实体渲染器"""
from __future__ import annotations
import numpy as np
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Math.Transform import calculate_entity_model


class ZenGLEntityRenderer:
    @classmethod
    def _RenderEntities(cls, view: np.ndarray, proj: np.ndarray) -> None:
        for eid in SceneManager.GetRenderableEntities():
            e = cls.registered_entities.get(eid)
            if not e or not e.pipeline: continue
            model = calculate_entity_model(SceneManager.GetEntityTransform(eid))
            try:
                e.pipeline.uniforms['model'][:] = model.astype('f4').tobytes()
                e.pipeline.uniforms['view'][:] = view.astype('f4').tobytes()
                e.pipeline.uniforms['projection'][:] = proj.astype('f4').tobytes()
            except: pass
            e.pipeline.render()
