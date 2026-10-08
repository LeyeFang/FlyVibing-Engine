"""
OpenGLEntities — PyOpenGL 实体渲染器 (组合到 OpenGLRenderer)。

职责:
  - 遍历可渲染实体并提交 GL 绘制命令
  - 支持 FBO 重定向 (_scene_fbo_override)
  - 支持 Stencil 注入 (_outline_selected_ids → 写 stencil=1)

设计:
  - 组合模式: 通过 _renderer 回引用访问资源注册表
  - 不再通过 MRO 继承 — 避免 classmethod/instancemethod 冲突
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager


# ★ 逐实体上传时跳过的 uniform — model/view/projection 由渲染器管理,
#   uLight*/uAmbient/uCameraPos 由光照帧状态注入 (协议: Doc/Dev/shader_protocol.md)
_MATERIAL_SKIP_UNIFORMS = frozenset({
    'model', 'view', 'projection',
    'uAmbient', 'uCameraPos', 'uLightCount', 'uLightDir', 'uLightColor',
})


class OpenGLEntities:
    """PyOpenGL 实体渲染器 — 核心实体绘制管线。"""

    def __init__(self, renderer) -> None:
        self._renderer = renderer

    def render_entities(
        self,
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """渲染所有实体 — 支持 FBO 重定向 + stencil 注入。"""
        r = self._renderer
        target_fbo = r._scene_fbo_override
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target_fbo)
            gl.glViewport(0, 0, r.viewport_width, r.viewport_height)

        has_outline = bool(r._outline_selected_ids)
        last_program: int = 0  # ★ 缓存最后使用的 shader program，避免冗余切换
        lit_programs: set = set()  # ★ 已注入光照帧状态的 program (每帧/每 program 一次)

        # ── 收集可渲染实体 + 材质 (不透明 / 透明分流) ──
        opaque_items: list[tuple] = []   # (entity_id, entity, material)
        alpha_items: list[tuple] = []    # (depth, entity_id, entity, material)
        for entity_id in r._resources._visible_entities:
            entity = r.registered_entities.get(entity_id)
            if entity is None:
                r._resources._visible_entities.discard(entity_id)
                continue
            if not entity.render_visible:
                continue
            if entity.shader_id not in r.registered_shaders:
                continue
            if entity.mesh_id not in r.registered_meshes:
                continue
            try:
                material = ResourceManager.GetMaterial(entity.material_id)
            except Exception:
                material = None
            if material is not None and getattr(material, 'blend', 'opaque') == 'alpha':
                # ★ 透明: 记录视图空间深度 (行向量约定: v_view = v_world @ view),
                #   相机看向 -Z → -z 越大 = 越远 → 先画远的 (画家算法)
                try:
                    model = r.engine.scene.GetEntityModelMatrix(entity_id)
                    p = np.asarray(model, dtype=np.float64)[3, :3]
                    eye_z = float((np.array(
                        [p[0], p[1], p[2], 1.0]) @ np.asarray(view, dtype=np.float64))[2])
                except Exception:
                    eye_z = 0.0
                alpha_items.append((-eye_z, entity_id, entity, material))
            else:
                opaque_items.append((entity_id, entity, material))

        # ★ 不透明: 按 shader_id → material_id 排序，最大化 GPU 状态复用
        opaque_items.sort(key=lambda it: (it[1].shader_id, it[1].material_id))
        # ★ 透明: 由远到近 (画家算法; 不参与状态复用排序)
        alpha_items.sort(key=lambda it: it[0], reverse=True)

        # ── 光照帧状态 (面向所有带 Lighting 约定的 shader; 未声明者 no-op) ──
        light_frame = self._collect_light_frame(view)

        draw_seq = ([('opaque', it) for it in opaque_items]
                    + [('alpha', it[1:]) for it in alpha_items])

        blend_on = False
        for phase, (entity_id, entity, material) in draw_seq:

            # ★ 进入透明阶段: 开启混合 + 关闭深度写入 (保留深度测试)
            if phase == 'alpha' and not blend_on:
                gl.glEnable(gl.GL_BLEND)
                gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
                gl.glDepthMask(gl.GL_FALSE)
                blend_on = True

            if has_outline:
                if entity_id in r._outline_selected_ids:
                    gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                    gl.glStencilMask(0xFF)
                else:
                    gl.glStencilMask(0x00)

            # ★ 冗余消除: 只在 shader 变化时切换 program
            program = r.registered_shaders[entity.shader_id].program
            if program != last_program:
                gl.glUseProgram(program)
                last_program = program
                # ★ 冗余消除: view / proj 全帧不变，仅在 shader 切换后设置一次
                OpenGLUtils.set_uniform_mat4(
                    r.registered_shaders, entity.shader_id, 'view', view)
                OpenGLUtils.set_uniform_mat4(
                    r.registered_shaders, entity.shader_id, 'projection', proj)
                # ★ 光照帧状态注入 (每 program 每帧一次; 对 Basic/SSVEP 等
                #   未声明这些 uniform 的 shader 全部 no-op)
                if program not in lit_programs:
                    lit_programs.add(program)
                    self._inject_lighting(entity.shader_id, light_frame)

            model = self._renderer.engine.scene.GetEntityModelMatrix(entity_id)
            OpenGLUtils.set_uniform_mat4(
                r.registered_shaders, entity.shader_id, 'model', model)
            if entity.texture_id and entity.texture_id > 0:
                tex_data = r.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle:
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_data.gl_handle)
                    OpenGLUtils.set_uniform_int(
                        r.registered_shaders, entity.shader_id, 'uTexture', 0)
            if material is not None:
                for u_name, u_value in material.uniforms_data.items():
                    if u_name in _MATERIAL_SKIP_UNIFORMS:
                        continue
                    OpenGLUtils.set_uniform_value(
                        r.registered_shaders, entity.shader_id, u_name, u_value)
            gl.glBindVertexArray(entity.vao)
            mesh_data = r.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES,
                mesh_data.elements_count,
                gl.GL_UNSIGNED_INT,
                None
            )
            gl.glBindVertexArray(0)

        # ── 恢复透明阶段状态 ──
        if blend_on:
            gl.glDepthMask(gl.GL_TRUE)
            gl.glDisable(gl.GL_BLEND)

        # ── 恢复 stencil mask ──
        if has_outline:
            gl.glStencilMask(0xFF)

        # ── 解绑 FBO (回到默认帧缓冲) ──
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    # ════════════════════════════════════════════════════════════
    # 光照帧状态 (Lighting 约定 — 协议: Doc/Dev/shader_protocol.md)
    # ════════════════════════════════════════════════════════════

    def _collect_light_frame(self, view: np.ndarray) -> dict:
        """每帧收集一次场景光照状态 (环境光 + 至多 4 平面光 + 至多 4 点光)。

        - 平面光: 方向 = 实体 Transform 局部 -Z 前向 → 世界空间传播方向 (位置无关)
        - 点光: 位置 = 实体世界坐标; 衰减 = (1 - d/range)² (d ≥ range → 0)
        - 颜色 × 强度合并
        """
        r = self._renderer
        try:
            st = r.engine.scene
        except Exception:  # noqa: BLE001
            st = None
        ambient = np.array(
            getattr(st, 'ambient_color', (0.5, 0.5, 0.5)), dtype=np.float32)
        # 相机世界坐标 (行向量约定: 相机位 = inv(view) 的平移行)
        try:
            cam_pos = np.linalg.inv(
                np.asarray(view, dtype=np.float64))[3, :3].astype(np.float32)
        except Exception:  # noqa: BLE001
            cam_pos = np.zeros(3, dtype=np.float32)
        dirs = np.zeros((4, 3), dtype=np.float32)
        colors = np.zeros((4, 3), dtype=np.float32)
        point_pos = np.zeros((4, 3), dtype=np.float32)
        point_color = np.zeros((4, 3), dtype=np.float32)
        point_range = np.ones(4, dtype=np.float32)
        count = 0
        pcount = 0
        if st is not None:
            try:
                from Application.Core.Scene.BasicComponents import Light
                for eid, light in st.GetAllEntitiesWithComponent(Light):
                    try:
                        model = np.asarray(
                            st.GetEntityModelMatrix(eid), dtype=np.float64)
                    except Exception:  # noqa: BLE001
                        continue
                    inten = float(getattr(light, 'intensity', 1.0))
                    lc = np.array([
                        float(getattr(light, 'color_r', 1.0)) * inten,
                        float(getattr(light, 'color_g', 1.0)) * inten,
                        float(getattr(light, 'color_b', 1.0)) * inten,
                    ], dtype=np.float32)
                    ltype = str(getattr(light, 'light_type', 'directional')).lower()
                    if ltype == 'point':
                        if pcount >= 4:
                            continue
                        point_pos[pcount] = model[3, :3].astype(np.float32)
                        point_color[pcount] = lc
                        point_range[pcount] = max(
                            float(getattr(light, 'range', 10.0)), 1e-4)
                        pcount += 1
                    else:
                        if count >= 4:
                            continue
                        d = -model[2, :3]  # 局部 -Z 前向 → 世界空间光线传播方向
                        norm = float(np.linalg.norm(d))
                        d = np.array([0.0, -1.0, 0.0]) if norm < 1e-8 else d / norm
                        dirs[count] = d.astype(np.float32)
                        colors[count] = lc
                        count += 1
            except Exception:  # noqa: BLE001 — 组件未注册时保持无光
                pass
        # ★ 无灯回退: 场景无任何光源 → 满亮环境光 (默认开, 可关;
        #   shader_protocol §7.3 — 避免"未配置光照=默认变黑")
        if count == 0 and pcount == 0 and bool(getattr(st, 'lighting_fallback', True)):
            ambient = np.ones(3, dtype=np.float32)
        return {
            'ambient': ambient,
            'camera_pos': cam_pos,
            'dirs': dirs,
            'colors': colors,
            'count': count,
            'point_pos': point_pos,
            'point_color': point_color,
            'point_range': point_range,
            'point_count': pcount,
        }

    def _inject_lighting(self, shader_id: int, frame: dict) -> None:
        """将光照帧状态写入当前 shader — 未声明的 uniform 自动 no-op。"""
        sh = self._renderer.registered_shaders
        OpenGLUtils.set_uniform_vec3(sh, shader_id, 'uAmbient', frame['ambient'])
        OpenGLUtils.set_uniform_vec3(sh, shader_id, 'uCameraPos', frame['camera_pos'])
        OpenGLUtils.set_uniform_int(sh, shader_id, 'uLightCount', frame['count'])
        OpenGLUtils.set_uniform_vec3_array(sh, shader_id, 'uLightDir', frame['dirs'], 4)
        OpenGLUtils.set_uniform_vec3_array(sh, shader_id, 'uLightColor', frame['colors'], 4)
        OpenGLUtils.set_uniform_int(sh, shader_id, 'uPointCount', frame['point_count'])
        OpenGLUtils.set_uniform_vec3_array(sh, shader_id, 'uPointPos', frame['point_pos'], 4)
        OpenGLUtils.set_uniform_vec3_array(sh, shader_id, 'uPointColor', frame['point_color'], 4)
        OpenGLUtils.set_uniform_float_array(sh, shader_id, 'uPointRange', frame['point_range'], 4)
