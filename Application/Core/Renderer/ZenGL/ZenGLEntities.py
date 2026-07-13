"""ZenGLEntities — ZenGL 实体渲染器"""
from __future__ import annotations
import numpy as np
from Application.Core.Scene.SceneManager import SceneManager
from Application.Resource.ResourceManager import ResourceManager


class ZenGLEntities:
    def _RenderEntities(self, view: np.ndarray, proj: np.ndarray) -> None:
        # ★ 预序列化 view/proj（全帧不变，避免每个 entity 重复 numpy→bytes 转换）
        view_bytes = view.astype('f4').tobytes()
        proj_bytes = proj.astype('f4').tobytes()
        for eid in self.engine.scene.GetRenderableEntities():
            e = self.registered_entities.get(eid)
            if not e or not e.pipeline: continue
            model = self.engine.scene.GetEntityModelMatrix(eid)
            try:
                e.pipeline.uniforms['model'][:] = model.astype('f4').tobytes()
                e.pipeline.uniforms['view'][:] = view_bytes
                e.pipeline.uniforms['projection'][:] = proj_bytes
            except Exception:
                pass
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
