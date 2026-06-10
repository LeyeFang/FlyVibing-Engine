"""
Outliner — 编辑器轮廓高亮模块 (自包含渲染资源, 对齐 Grid 的解耦模式)。

职责:
  - 拥有轮廓/拾取/Blit 着色器源码 (纯字符串, 不 import GL 也可访问)
  - 管理 GPU 资源: 着色器程序 / FBO / Blit VAO (import GL)
  - 管理轮廓配置: selected_ids / xray / color / scale
  - 提供 render_scene_pass / render_outline_pass / blit / pick_at
    供渲染器在 StartFrame / EndFrame 中调用

编辑器/渲染器解耦:
  - EditorLayer → Outliner.set_config(selected_ids, xray)
  - openGLRenderer → 持有 Outliner 引用, 在 StartFrame/EndFrame 中委托
  - openGLRenderer 不知道 "选中" / "X-Ray" 的语义, 只传递 view/proj

用法 (编辑器中):
  outliner = Outliner()
  outliner.init(renderer, w, h)          # 编译着色器, 创建 FBO
  renderer.register_outliner(outliner)   # 渲染器接管 FBO 管线
  outliner.set_config(selected_ids={...}, xray=True)
  # 渲染器每帧自动调用 outliner 的方法

对比 Grid:
  - Grid.register_to(renderer)  → 注册 overlay 可绘制对象 (纯数据)
  - Outliner  → 注册轮廓渲染能力 (含 GPU 资源)
"""

from __future__ import annotations
import ctypes
from typing import TYPE_CHECKING

import numpy as np
from OpenGL import GL as gl

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Math.RendererMath import calculate_entity_model
from Application.Resource.ResourceManager import ResourceManager

if TYPE_CHECKING:
    from Application.Core.Renderer.OpenGL.openGLRenderer import openGLRenderer


# ═══════════════════════════════════════════════════════════════
# 内联着色器 (编辑器内部, 不走 ResourceManager)
# ═══════════════════════════════════════════════════════════════

_OUTLINE_VS: str = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
uniform float uOutlineScale;
void main() {
    gl_Position = projection * view * model * vec4(aPos * uOutlineScale, 1.0);
}
"""

_OUTLINE_FS: str = """#version 330 core
uniform vec3 uOutlineColor;
out vec4 fragColor;
void main() { fragColor = vec4(uOutlineColor, 1.0); }
"""

_PICK_VS: str = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}
"""

_PICK_FS: str = """#version 330 core
uniform float uPickID;
out vec4 fragColor;
void main() { fragColor = vec4(uPickID / 255.0, 0.0, 0.0, 1.0); }
"""

_BLIT_VS: str = """#version 330 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}
"""

_BLIT_FS: str = """#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uScreenTex;
void main() { fragColor = texture(uScreenTex, vUV); }
"""


# ═══════════════════════════════════════════════════════════════
# Outliner
# ═══════════════════════════════════════════════════════════════

class Outliner:
    """编辑器轮廓高亮 — 自包含的渲染资源 + 配置管理。

    编辑器层通过 set_config 控制轮廓外观,
    渲染器通过 render_scene_pass / render_outline_pass / blit / pick_at 调用 GPU 功能。
    """

    # ── 默认参数 ──────────────────────────────────────────────
    OUTLINE_COLOR: tuple = (0.976, 0.451, 0.024)     # 橙色
    OUTLINE_SCALE: float = 1.05

    # ════════════════════════════════════════════════════════
    # 实例状态
    # ════════════════════════════════════════════════════════

    def __init__(self) -> None:
        # ── 配置 (编辑器侧读写, 渲染器侧只读) ──
        self.selected_ids: set = set()
        self.outline_xray: bool = True
        self.outline_color: tuple = self.OUTLINE_COLOR
        self.outline_scale: float = self.OUTLINE_SCALE

        # ── GPU 资源 ──
        self._prog_outline: int = 0
        self._prog_pick: int = 0
        self._prog_blit: int = 0
        self._vao_blit: int = 0

        # ── FBO 资源 ──
        self._fbo_scene: int = 0
        self._fbo_scene_color: int = 0
        self._fbo_scene_ds: int = 0
        self._fbo_pick: int = 0
        self._fbo_pick_color: int = 0
        self._fbo_pick_depth: int = 0

        # ── 状态 ──
        self._w: int = 0
        self._h: int = 0
        self._initialized: bool = False

    # ════════════════════════════════════════════════════════
    # 配置接口 (编辑器 → Outliner, 不涉及 GL)
    # ════════════════════════════════════════════════════════

    def set_config(
        self,
        selected_ids: set = None,
        xray: bool = None,
        color: tuple = None,
        scale: float = None,
    ) -> None:
        """编辑器设置轮廓配置 (纯数据, 无 GL 调用)。

        对齐 Grid.register_to 的解耦模式:
          编辑器只传数据, Outliner 在渲染时读取配置。

        Args:
            selected_ids: 被选中实体 ID 集合
            xray:         True=穿透遮挡, False=仅可见边缘
            color:        轮廓颜色 RGB tuple
            scale:        轮廓放大系数
        """
        if selected_ids is not None:
            self.selected_ids = selected_ids
        if xray is not None:
            self.outline_xray = xray
        if color is not None:
            self.outline_color = color
        if scale is not None:
            self.outline_scale = scale

    # ════════════════════════════════════════════════════════
    # 生命周期 (渲染器调用, GL context 有效)
    # ════════════════════════════════════════════════════════

    def init(
        self,
        renderer: 'openGLRenderer',
        w: int,
        h: int,
    ) -> None:
        """初始化 GPU 资源。

        调用时机: EditorLayer.OnAttach (render thread, GL context 有效)。
        在 renderer.register_outliner(outliner) 时由渲染器调用。

        Args:
            renderer: openGLRenderer 实例 (用于访问 registered_entities 等)
            w, h:     视口尺寸
        """
        if self._initialized:
            return
        self._w, self._h = w, h

        # ── 编译着色器 ──
        self._prog_outline = self._compile_internal_program(
            _OUTLINE_VS, _OUTLINE_FS
        )
        self._prog_pick = self._compile_internal_program(
            _PICK_VS, _PICK_FS
        )
        self._prog_blit = self._compile_internal_program(
            _BLIT_VS, _BLIT_FS
        )

        # ── 全屏四边形 VAO ──
        self._vao_blit = self._create_fullscreen_quad()

        # ── FBO 资源 ──
        self._create_fbos(w, h)

        self._initialized = True
        print(
            f"[Outliner] initialized {w}×{h} — "
            f"FBO pick + Stencil outline"
        )

    def release(self) -> None:
        """释放所有 GPU 资源。"""
        self._delete_fbos()
        for prog in (self._prog_outline, self._prog_pick, self._prog_blit):
            if prog:
                gl.glDeleteProgram(prog)
        if self._vao_blit:
            gl.glDeleteVertexArrays(1, [self._vao_blit])
        self._prog_outline = self._prog_pick = self._prog_blit = 0
        self._vao_blit = 0
        self._initialized = False
        print("[Outliner] released")

    def resize(
        self,
        w: int,
        h: int,
    ) -> None:
        """重建 FBO (窗口 resize 时调用)。"""
        if w == self._w and h == self._h:
            return
        self._w, self._h = w, h
        self._delete_fbos()
        self._create_fbos(w, h)

    # ════════════════════════════════════════════════════════
    # 拾取 (渲染器调用)
    # ════════════════════════════════════════════════════════

    def pick_at(
        self,
        renderer: 'openGLRenderer',
        sx: float,
        sy: float,
    ) -> int:
        """FBO 拾取: 返回屏幕坐标处的实体 ID。

        每实体用 ECS entity_id 渲染到 pick FBO → glReadPixels。

        Args:
            renderer: 渲染器 (用于访问 registered_entities/meshes)
            sx, sy:   屏幕坐标 (像素)

        Returns:
            entity_id 或 -1
        """
        entities = SceneManager.GetRenderableEntities()
        if not entities:
            return -1

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_pick)
        gl.glViewport(0, 0, self._w, self._h)
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_STENCIL_TEST)

        gl.glUseProgram(self._prog_pick)
        self._set_uniform_mat4(
            self._prog_pick, 'view', renderer._cached_view
        )
        self._set_uniform_mat4(
            self._prog_pick, 'projection', renderer._cached_proj
        )

        for entity_id in entities:
            entity = renderer.registered_entities.get(entity_id)
            if entity is None:
                continue
            model = calculate_entity_model(
                SceneManager.GetEntityTransform(entity_id)
            )
            self._set_uniform_mat4(
                self._prog_pick, 'model',
                np.array(model, dtype=np.float32),
            )
            loc_id = gl.glGetUniformLocation(self._prog_pick, 'uPickID')
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(entity_id))

            gl.glBindVertexArray(entity.vao)
            mesh_data = renderer.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None,
            )
            gl.glBindVertexArray(0)

        gl.glFinish()
        px = max(0, min(int(round(sx)), self._w - 1))
        py = max(0, min(int(round(sy)), self._h - 1))
        pixel = (gl.GLfloat * 4)()
        gl.glReadPixels(
            px, self._h - 1 - py,
            1, 1, gl.GL_RGBA, gl.GL_FLOAT, pixel,
        )
        eid = int(pixel[0] * 255.0 + 0.5)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        return eid if eid >= 1 else -1

    # ════════════════════════════════════════════════════════
    # 渲染 Pass (渲染器在 StartFrame 中调用)
    # ════════════════════════════════════════════════════════

    def render_scene_pass(
        self,
        renderer: 'openGLRenderer',
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """Scene Pass: 渲染所有实体到 scene FBO, 被选中者写 stencil=1。

        Args:
            renderer: 渲染器 (用于访问 registered_entities/meshes/shaders)
            view:     视图矩阵
            proj:     投影矩阵
        """
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_scene)
        gl.glViewport(0, 0, self._w, self._h)
        gl.glClearColor(0.2, 0.2, 0.2, 1.0)
        gl.glClear(
            gl.GL_COLOR_BUFFER_BIT
            | gl.GL_DEPTH_BUFFER_BIT
            | gl.GL_STENCIL_BUFFER_BIT
        )

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)

        # 开启 stencil: always pass, 通过 depth test 时 replace
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)

        for entity_id in SceneManager.GetRenderableEntities():
            entity = renderer.registered_entities.get(entity_id)
            if entity is None:
                continue
            program = renderer.registered_shaders[
                entity.shader_id
            ].program

            gl.glUseProgram(program)

            model = calculate_entity_model(
                SceneManager.GetEntityTransform(entity_id)
            )
            renderer.set_uniform_mat4(
                entity.shader_id, 'model', model
            )
            renderer.set_uniform_mat4(
                entity.shader_id, 'view', view
            )
            renderer.set_uniform_mat4(
                entity.shader_id, 'projection', proj
            )

            # ── 纹理 ──
            if entity.texture_id and entity.texture_id > 0:
                tex_data = renderer.registered_textures.get(
                    entity.texture_id
                )
                if tex_data and tex_data.gl_handle:
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(
                        gl.GL_TEXTURE_2D, tex_data.gl_handle
                    )
                    renderer.set_uniform_int(
                        entity.shader_id, 'uTexture', 0
                    )

            # ── 材质 uniform ──
            material = ResourceManager.GetMaterial(
                entity.material_id
            )
            for u_name, u_value in material.uniforms_data.items():
                if u_name in ('model', 'view', 'projection'):
                    continue
                renderer.set_uniform_value(
                    entity.shader_id, u_name, u_value
                )

            # ── Stencil: 被选中实体写 stencil=1 ──
            is_selected = entity_id in self.selected_ids
            if is_selected:
                gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                gl.glStencilMask(0xFF)
            else:
                gl.glStencilMask(0x00)

            gl.glBindVertexArray(entity.vao)
            mesh_data = renderer.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None,
            )
            gl.glBindVertexArray(0)

    def render_outline_pass(
        self,
        renderer: 'openGLRenderer',
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """Outline Pass: stencil NOTEQUAL → 橙色轮廓 (scene FBO)。

        Args:
            renderer: 渲染器 (用于访问 registered_entities/meshes)
            view:     视图矩阵
            proj:     投影矩阵
        """
        if not self.selected_ids:
            return

        gl.glUseProgram(self._prog_outline)

        gl.glStencilFunc(gl.GL_NOTEQUAL, 1, 0xFF)
        gl.glStencilMask(0x00)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
        gl.glDepthMask(gl.GL_FALSE)

        if self.outline_xray:
            gl.glDisable(gl.GL_DEPTH_TEST)
        else:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LEQUAL)

        self._set_uniform_mat4(
            self._prog_outline, 'view', view
        )
        self._set_uniform_mat4(
            self._prog_outline, 'projection', proj
        )
        loc_color = gl.glGetUniformLocation(
            self._prog_outline, 'uOutlineColor'
        )
        if loc_color >= 0:
            gl.glUniform3f(loc_color, *self.outline_color)

        for entity_id in SceneManager.GetRenderableEntities():
            if entity_id not in self.selected_ids:
                continue
            entity = renderer.registered_entities.get(entity_id)
            if entity is None:
                continue
            model = calculate_entity_model(
                SceneManager.GetEntityTransform(entity_id)
            )
            self._set_uniform_mat4(
                self._prog_outline, 'model',
                np.array(model, dtype=np.float32),
            )
            loc_scale = gl.glGetUniformLocation(
                self._prog_outline, 'uOutlineScale'
            )
            if loc_scale >= 0:
                gl.glUniform1f(loc_scale, self.outline_scale)

            gl.glBindVertexArray(entity.vao)
            mesh_data = renderer.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None,
            )
            gl.glBindVertexArray(0)

        # ── 恢复状态 ──
        gl.glStencilMask(0xFF)
        gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)

    def blit_to_screen(self) -> None:
        """Blit scene FBO 颜色纹理到默认帧缓冲。"""
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glViewport(0, 0, self._w, self._h)
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glDisable(gl.GL_DEPTH_TEST)

        gl.glUseProgram(self._prog_blit)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._fbo_scene_color)
        loc_tex = gl.glGetUniformLocation(self._prog_blit, 'uScreenTex')
        if loc_tex >= 0:
            gl.glUniform1i(loc_tex, 0)
        gl.glBindVertexArray(self._vao_blit)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

    # ════════════════════════════════════════════════════════
    # FBO 管理 (内部)
    # ════════════════════════════════════════════════════════

    def _create_fbos(self, w: int, h: int) -> None:
        """创建 scene FBO (depth24+stencil8) + pick FBO (depth24)。"""
        self._delete_fbos()

        # ── Scene FBO ──
        self._fbo_scene_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._fbo_scene_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None,
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST
        )

        self._fbo_scene_ds = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._fbo_scene_ds)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH24_STENCIL8, w, h
        )

        self._fbo_scene = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_scene)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D, self._fbo_scene_color, 0,
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_STENCIL_ATTACHMENT,
            gl.GL_RENDERBUFFER, self._fbo_scene_ds,
        )
        if gl.glCheckFramebufferStatus(
            gl.GL_FRAMEBUFFER
        ) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Outliner: scene FBO incomplete")

        # ── Pick FBO ──
        self._fbo_pick_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._fbo_pick_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None,
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST
        )

        self._fbo_pick_depth = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._fbo_pick_depth)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h
        )

        self._fbo_pick = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo_pick)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D, self._fbo_pick_color, 0,
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
            gl.GL_RENDERBUFFER, self._fbo_pick_depth,
        )
        if gl.glCheckFramebufferStatus(
            gl.GL_FRAMEBUFFER
        ) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Outliner: pick FBO incomplete")

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    def _delete_fbos(self) -> None:
        """释放 FBO 资源。"""
        if self._fbo_scene:
            gl.glDeleteFramebuffers(1, [self._fbo_scene])
            self._fbo_scene = 0
        if self._fbo_scene_color:
            gl.glDeleteTextures(1, [self._fbo_scene_color])
            self._fbo_scene_color = 0
        if self._fbo_scene_ds:
            gl.glDeleteRenderbuffers(1, [self._fbo_scene_ds])
            self._fbo_scene_ds = 0
        if self._fbo_pick:
            gl.glDeleteFramebuffers(1, [self._fbo_pick])
            self._fbo_pick = 0
        if self._fbo_pick_color:
            gl.glDeleteTextures(1, [self._fbo_pick_color])
            self._fbo_pick_color = 0
        if self._fbo_pick_depth:
            gl.glDeleteRenderbuffers(1, [self._fbo_pick_depth])
            self._fbo_pick_depth = 0

    # ════════════════════════════════════════════════════════
    # 着色器编译辅助 (内部)
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _compile_internal_program(
        vs_src: str,
        fs_src: str,
    ) -> int:
        """编译着色器程序 (编辑器内部, 不走 ResourceManager)。"""
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, vs_src)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(vs).decode(errors='replace')
            gl.glDeleteShader(vs)
            raise RuntimeError(
                f"Outliner vertex shader compile failed:\n{log}"
            )

        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, fs_src)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(fs).decode(errors='replace')
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            raise RuntimeError(
                f"Outliner fragment shader compile failed:\n{log}"
            )

        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, fs)
        gl.glLinkProgram(program)
        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(program).decode(
                errors='replace'
            )
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            gl.glDeleteProgram(program)
            raise RuntimeError(
                f"Outliner shader link failed:\n{log}"
            )

        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)
        return program

    @staticmethod
    def _create_fullscreen_quad() -> int:
        """全屏四边形 VAO (用于 Blit)。"""
        verts = np.array(
            [-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32
        )
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(
            gl.GL_ARRAY_BUFFER, verts.nbytes,
            verts.tobytes(), gl.GL_STATIC_DRAW,
        )
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(
            0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0)
        )
        gl.glBindVertexArray(0)
        return vao

    @staticmethod
    def _set_uniform_mat4(
        prog: int,
        name: str,
        matrix: np.ndarray,
    ) -> None:
        """设置 mat4 uniform (辅助)。"""
        loc = gl.glGetUniformLocation(prog, name)
        if loc >= 0:
            data = np.ascontiguousarray(matrix.astype(np.float32))
            gl.glUniformMatrix4fv(loc, 1, gl.GL_FALSE, data)
