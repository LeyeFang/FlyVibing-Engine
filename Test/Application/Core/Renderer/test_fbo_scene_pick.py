"""
Test: FBO Scene Pick — FBO Entity Picking via SceneManager + SelecteEntityEvent
═══════════════════════════════════════════════════════════════════════════════

本测试验证编辑器拾取工作流:
  1. 通过 SceneManager 管理实体 (Transform + MeshRenderer)
  2. 通过 ResourceManager 获取网格顶点数据
  3. FBO 渲染每个实体为唯一 ID 颜色 → readPixels 获取点击物体
  4. 选中实体后, 用 SelecteEntityEvent.Pack() 打包事件, 并 print 出来

渲染流程:
  Pick Pass  : SceneManager.GetRenderableEntities() → 每实体分配 ECS entity_id
               → pick FBO → readPixels 获取点击的 entity_id
  Scene Pass : 绘制所有实体到 scene FBO (简单光照)
  Blit       : scene FBO → 屏幕

操作:
  左键拖拽 = 旋转摄像机
  滚轮     = 缩放
  左键点击 = 拾取/选中实体 (触发 SelecteEntityEvent)
  空格     = 清除选中
  ESC      = 退出

依赖: pip install PyOpenGL glfw trimesh pyrr numpy esper
运行: python Test/test_fbo_scene_pick.py   (工作目录任意)
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402
import ctypes, math, os, sys
import numpy as np
import glfw
from pyrr import matrix44, Vector3
from OpenGL.GL import *
from OpenGL.GL import shaders as gls

# ── 引擎模块 ──
from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer, Transform
from Application.Core.Math.Transform import calculate_entity_model
from Application.Editor.EditorEvent import SelecteEntityEvent, DeselectEntityEvent, ClearSelectionEvent


# ═══════════════════════════════════════════════════════════════
# Mock Application — 满足 ResourceManager / SceneManager 初始化
# ═══════════════════════════════════════════════════════════════

class _MockWindow:
    """模拟编辑器窗口, 提供 GetSize() 接口"""
    def __init__(self, glfw_window):
        self._glfw = glfw_window

    def GetSize(self):
        return glfw.get_framebuffer_size(self._glfw)


class _MockApp:
    """模拟 Application, 仅持有 editor_window 引用"""
    editor_window = None


# ═══════════════════════════════════════════════════════════════
# Shader 源码
# ═══════════════════════════════════════════════════════════════

_SCENE_VS = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTC;
layout(location=2) in vec3 aN;
uniform mat4 uM, uV, uP;
out vec3 vN, vP;
void main() {
    vec4 w = uM * vec4(aPos, 1.0);
    vP = w.xyz;
    vN = mat3(transpose(inverse(uM))) * aN;
    gl_Position = uP * uV * w;
}"""

_SCENE_FS = """#version 330 core
in vec3 vN, vP;
out vec4 f;
uniform vec3 uL, uC;
void main() {
    vec3 l = normalize(uL - vP);
    vec3 n = normalize(vN);
    float d = max(dot(n, l), 0.0);
    f = vec4((0.15 + d) * uC, 1.0);
}"""

_PICK_VS = _SCENE_VS

_PICK_FS = """#version 330 core
uniform float uID;
out vec4 f;
void main() { f = vec4(uID / 255.0, 0.0, 0.0, 1.0); }"""

_BLIT_VS = """#version 330 core
in vec2 aP;
out vec2 vU;
void main() {
    gl_Position = vec4(aP, 0.0, 1.0);
    vU = aP * 0.5 + 0.5;
}"""

_BLIT_FS = """#version 330 core
in vec2 vU;
out vec4 f;
uniform sampler2D uT;
void main() { f = texture(uT, vU); }"""


# ═══════════════════════════════════════════════════════════════
# OpenGL 工具函数
# ═══════════════════════════════════════════════════════════════

def compile_shader(vs_src: str, fs_src: str) -> int:
    try:
        vs = gls.compileShader(vs_src, GL_VERTEX_SHADER)
        fs = gls.compileShader(fs_src, GL_FRAGMENT_SHADER)
        prog = gls.compileProgram(vs, fs)
        glDeleteShader(vs); glDeleteShader(fs)
        return prog
    except RuntimeError as e:
        print(f"Shader compile error:\n{e}")
        raise


def _make_texture(w: int, h: int, internal_fmt=GL_RGBA8, fmt=GL_RGBA, dtype=GL_UNSIGNED_BYTE) -> int:
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt, dtype, None)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glBindTexture(GL_TEXTURE_2D, 0)
    return tid


def create_scene_fbo(w: int, h: int):
    color_tex = _make_texture(w, h)
    ds_rbo = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, ds_rbo)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, w, h)
    glBindRenderbuffer(GL_RENDERBUFFER, 0)

    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color_tex, 0)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, ds_rbo)
    if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("Scene FBO incomplete")
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    return fbo, color_tex, ds_rbo


def create_pick_fbo(w: int, h: int):
    color_tex = _make_texture(w, h)
    depth_rbo = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rbo)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h)
    glBindRenderbuffer(GL_RENDERBUFFER, 0)

    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color_tex, 0)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depth_rbo)
    if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("Pick FBO incomplete")
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    return fbo, color_tex, depth_rbo


def create_vao_from_mesh(prog: int, vertices: np.ndarray, normals: np.ndarray,
                          uvs: np.ndarray, indices: np.ndarray) -> int:
    """
    从 ResourceManager Mesh 数据 (分离数组) 创建 VAO。
    vertices: (N,3) float32
    normals:  (N,3) float32
    uvs:      (N,2) float32
    indices:  (M,)  uint32 (flattened faces)
    """
    interleaved = np.hstack([vertices, uvs, normals]).astype(np.float32)
    vao = glGenVertexArrays(1)
    vbo = glGenBuffers(1)
    ebo = glGenBuffers(1)
    glBindVertexArray(vao)

    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_STATIC_DRAW)
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

    stride = 8 * 4  # pos(3) + uv(2) + normal(3)
    loc_pos = glGetAttribLocation(prog, 'aPos')
    loc_uv  = glGetAttribLocation(prog, 'aTC')
    loc_n   = glGetAttribLocation(prog, 'aN')

    if loc_pos >= 0:
        glEnableVertexAttribArray(loc_pos)
        glVertexAttribPointer(loc_pos, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
    if loc_uv >= 0:
        glEnableVertexAttribArray(loc_uv)
        glVertexAttribPointer(loc_uv, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
    if loc_n >= 0:
        glEnableVertexAttribArray(loc_n)
        glVertexAttribPointer(loc_n, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(20))

    glBindVertexArray(0)
    return vao, len(indices)


def create_fullscreen_quad(prog: int) -> int:
    verts = np.array([-1, -1,  1, -1,  -1, 1,  1, 1], dtype='f4')
    vao = glGenVertexArrays(1)
    vbo = glGenBuffers(1)
    glBindVertexArray(vao)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
    loc = glGetAttribLocation(prog, 'aP')
    if loc >= 0:
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
    glBindVertexArray(0)
    return vao


# ═══════════════════════════════════════════════════════════════
# 简易轨道摄像机
# ═══════════════════════════════════════════════════════════════

class Camera:
    def __init__(self):
        self.yaw = math.pi * 0.7
        self.pitch = 0.2
        self.target = np.array([0.0, 0.0, 0.0], 'f4')
        self.distance = 6.0
        self.fov = 45.0
        self.near = 0.1
        self.far = 100.0

    @property
    def position(self):
        x = self.distance * math.sin(self.yaw) * math.cos(self.pitch)
        y = self.distance * math.sin(self.pitch)
        z = self.distance * math.cos(self.yaw) * math.cos(self.pitch)
        return np.array([x, y, z], 'f4') + self.target

    def view_matrix(self):
        return matrix44.create_look_at(
            Vector3(self.position.tolist()),
            Vector3(self.target.tolist()),
            Vector3([0, 1, 0])
        )

    def projection_matrix(self, aspect: float):
        return matrix44.create_perspective_projection(
            self.fov, aspect, self.near, self.far
        )

    def orbit(self, dx: float, dy: float):
        self.yaw   -= dx * 0.005
        self.pitch += dy * 0.005
        self.pitch = max(-math.pi / 2 + 0.01, min(math.pi / 2 - 0.01, self.pitch))

    def zoom(self, delta: float):
        self.distance = max(0.5, min(self.distance - delta * 0.5, 50.0))


# ═══════════════════════════════════════════════════════════════
# SceneFBOPicker — FBO Pick + Scene Render (内联渲染器)
# ═══════════════════════════════════════════════════════════════

class SceneFBOPicker:
    """
    内联渲染器:
      - 通过 SceneManager 查询可渲染实体
      - 通过 ResourceManager 获取网格数据 → 创建 VAO
      - Pick Pass: FBO 渲染实体 ID → readPixels
      - Scene Pass: FBO 渲染实体颜色 → blit 到屏幕
    """

    def __init__(self):
        self._w = self._h = 0
        self._sfbo = self._s_color = self._s_ds = 0
        self._pfbo = self._p_color = self._p_depth = 0

        self._prog_scene = 0
        self._prog_pick  = 0
        self._prog_blit  = 0
        self._vao_blit   = 0

        # entity_id → {'vao': int, 'idx_count': int, 'mesh_id': int}
        self._entity_gpu: dict[int, dict] = {}
        self._ok = False

    # ── 初始化 ──────────────────────────────────────────────

    def init(self, w: int, h: int):
        if self._ok:
            return
        self._w, self._h = w, h

        # 编译 shader
        self._prog_scene = compile_shader(_SCENE_VS, _SCENE_FS)
        self._prog_pick  = compile_shader(_PICK_VS, _PICK_FS)
        self._prog_blit  = compile_shader(_BLIT_VS, _BLIT_FS)
        self._vao_blit   = create_fullscreen_quad(self._prog_blit)

        self._rebuild_scene_fbo()
        self._rebuild_pick_fbo()
        self._ok = True
        print(f"[SceneFBOPicker] init {w}×{h}")

    def _rebuild_scene_fbo(self):
        if self._sfbo:
            glDeleteFramebuffers(1, [self._sfbo])
            glDeleteTextures(1, [self._s_color])
            glDeleteRenderbuffers(1, [self._s_ds])
        self._sfbo, self._s_color, self._s_ds = create_scene_fbo(self._w, self._h)

    def _rebuild_pick_fbo(self):
        if self._pfbo:
            glDeleteFramebuffers(1, [self._pfbo])
            glDeleteTextures(1, [self._p_color])
            glDeleteRenderbuffers(1, [self._p_depth])
        self._pfbo, self._p_color, self._p_depth = create_pick_fbo(self._w, self._h)

    def resize(self, w: int, h: int):
        if w == self._w and h == self._h:
            return
        self._w, self._h = w, h
        self._rebuild_scene_fbo()
        self._rebuild_pick_fbo()

    # ── GPU 实体管理 ────────────────────────────────────────

    def sync_entities(self):
        """
        从 SceneManager 同步实体列表 → 为每个新 mesh 创建 VAO。
        如果 mesh_id 变更, 会重建 VAO。
        """
        renderable = SceneManager.GetRenderableEntities()
        known = set(self._entity_gpu.keys())

        for eid in renderable:
            mesh_id = SceneManager.GetEntityMesh(eid)
            if eid in self._entity_gpu:
                old = self._entity_gpu[eid]
                if old['mesh_id'] != mesh_id:
                    # mesh 变更 → 重建 VAO
                    glDeleteVertexArrays(1, [old['vao']])
                    del self._entity_gpu[eid]
                else:
                    continue  # 无需更新

            # 创建新 VAO
            mesh = ResourceManager.GetMesh(mesh_id)
            vao, idx_count = create_vao_from_mesh(
                self._prog_scene,
                mesh.GetVertices(),
                mesh.GetNormals(),
                mesh.GetUVs(),
                mesh.GetIndices().flatten(),
            )
            self._entity_gpu[eid] = {
                'vao': vao,
                'idx_count': idx_count,
                'mesh_id': mesh_id,
            }

        # 清理已删除的实体
        for eid in known - set(renderable):
            glDeleteVertexArrays(1, [self._entity_gpu[eid]['vao']])
            del self._entity_gpu[eid]

    # ── Pick ────────────────────────────────────────────────

    def pick(self, sx: float, sy: float, view: np.ndarray, proj: np.ndarray) -> int:
        """
        FBO 拾取: 每个实体用其 ECS entity_id 作为 pick ID 渲染到 pick FBO。
        返回 entity_id, 未命中返回 -1。
        """
        self.sync_entities()
        entities = SceneManager.GetRenderableEntities()
        if not entities:
            return -1

        glBindFramebuffer(GL_FRAMEBUFFER, self._pfbo)
        glViewport(0, 0, self._w, self._h)
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_TRUE)

        glUseProgram(self._prog_pick)
        glUniformMatrix4fv(
            glGetUniformLocation(self._prog_pick, 'uV'), 1, GL_FALSE, view.astype('f4'))
        glUniformMatrix4fv(
            glGetUniformLocation(self._prog_pick, 'uP'), 1, GL_FALSE, proj.astype('f4'))

        for eid in entities:
            gpu = self._entity_gpu.get(eid)
            if gpu is None:
                continue
            transform = SceneManager.GetEntityTransform(eid)
            model = calculate_entity_model(transform)
            glUniformMatrix4fv(
                glGetUniformLocation(self._prog_pick, 'uM'), 1, GL_FALSE,
                np.array(model, dtype=np.float32))
            glUniform1f(
                glGetUniformLocation(self._prog_pick, 'uID'), float(eid))
            glBindVertexArray(gpu['vao'])
            glDrawElements(GL_TRIANGLES, gpu['idx_count'], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

        # glFinish()
        px = max(0, min(int(round(sx)), self._w - 1))
        py = max(0, min(int(round(sy)), self._h - 1))
        pixel = (GLfloat * 4)()
        glReadPixels(px, self._h - 1 - py, 1, 1, GL_RGBA, GL_FLOAT, pixel)
        eid = int(pixel[0] * 255.0 + 0.5)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        return eid if eid >= 1 else -1

    # ── 渲染 ────────────────────────────────────────────────

    def render_frame(self, view: np.ndarray, proj: np.ndarray):
        self.sync_entities()
        entities = SceneManager.GetRenderableEntities()

        # ── Scene Pass → scene FBO ──
        glBindFramebuffer(GL_FRAMEBUFFER, self._sfbo)
        glViewport(0, 0, self._w, self._h)
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_TRUE)

        glUseProgram(self._prog_scene)
        glUniformMatrix4fv(
            glGetUniformLocation(self._prog_scene, 'uV'), 1, GL_FALSE, view.astype('f4'))
        glUniformMatrix4fv(
            glGetUniformLocation(self._prog_scene, 'uP'), 1, GL_FALSE, proj.astype('f4'))

        # 给每个实体分配不同的颜色以便区分
        colors = [
            (0.3, 0.5, 0.9),  # blue
            (0.3, 0.8, 0.4),  # green
            (0.9, 0.3, 0.3),  # red
            (0.9, 0.7, 0.2),  # orange
            (0.7, 0.3, 0.9),  # purple
            (0.3, 0.9, 0.9),  # cyan
        ]

        for i, eid in enumerate(entities):
            gpu = self._entity_gpu.get(eid)
            if gpu is None:
                continue
            transform = SceneManager.GetEntityTransform(eid)
            model = calculate_entity_model(transform)
            color = colors[i % len(colors)]

            glUniformMatrix4fv(
                glGetUniformLocation(self._prog_scene, 'uM'), 1, GL_FALSE,
                np.array(model, dtype=np.float32))
            glUniform3f(
                glGetUniformLocation(self._prog_scene, 'uL'), 5.0, 8.0, 5.0)
            glUniform3f(
                glGetUniformLocation(self._prog_scene, 'uC'), *color)
            glBindVertexArray(gpu['vao'])
            glDrawElements(GL_TRIANGLES, gpu['idx_count'], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

        # ── Blit to screen ──
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, self._w, self._h)
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT)
        glDisable(GL_DEPTH_TEST)

        glUseProgram(self._prog_blit)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._s_color)
        glUniform1i(glGetUniformLocation(self._prog_blit, 'uT'), 0)
        glBindVertexArray(self._vao_blit)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)

    # ── 清理 ────────────────────────────────────────────────

    def release(self):
        for fbo in (self._sfbo, self._pfbo):
            if fbo: glDeleteFramebuffers(1, [fbo])
        for tex in (self._s_color, self._p_color):
            if tex: glDeleteTextures(1, [tex])
        for rbo in (self._s_ds, self._p_depth):
            if rbo: glDeleteRenderbuffers(1, [rbo])
        for prog in (self._prog_scene, self._prog_pick, self._prog_blit):
            if prog: glDeleteProgram(prog)
        for gpu in self._entity_gpu.values():
            if gpu['vao']: glDeleteVertexArrays(1, [gpu['vao']])
        if self._vao_blit: glDeleteVertexArrays(1, [self._vao_blit])
        self._entity_gpu.clear()
        self._ok = False
        print("[SceneFBOPicker] released")


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ★ 工作目录已由 _path_setup 切换到项目根, 此处无需再 chdir
    print(f"[TEST] Working directory: {os.getcwd()}")

    # ── GLFW 初始化 ──
    if not glfw.init():
        print("glfw.init() failed")
        return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)

    window = glfw.create_window(1024, 768, "FBO Scene Pick — SceneManager + SelecteEntityEvent", None, None)
    if not window:
        glfw.terminate()
        return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    fbw, fbh = glfw.get_framebuffer_size(window)

    # ── 绑定事件回调 (使 Event.Pack() → print) ──
    BindPackCallback(lambda event_cls: print(event_cls))

    # ── 初始化 ResourceManager & SceneManager ──
    mock_app = _MockApp()
    mock_app.editor_window = _MockWindow(window)
    ResourceManager.Init(mock_app)
    SceneManager.Init(mock_app)
    print("[TEST] ResourceManager & SceneManager initialized")

    # ── 获取默认 Cube mesh 的 ID ──
    cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')
    print(f"[TEST] Cube mesh_id = {cube_mesh_id}")

    # ── 通过 SceneManager 创建实体 ──
    entity_ids = []
    positions = [(-1.5, 0, 0), (0.0, 0, 0), (1.5, 0, 0)]

    for pos in positions:
        eid = SceneManager.AddEntity()
        entity_ids.append(eid)
        # 添加 MeshRenderer (默认绑定 mesh_id=1, 并自动创建 material)
        mesh_renderer = MeshRenderer(mesh_id=cube_mesh_id)
        SceneManager.AddComponentToEntity(eid, mesh_renderer)
        # 设置位置
        SceneManager.SetEntityTransform(eid, position_xyz=pos)

    print(f"[TEST] Created entities: {entity_ids}")
    print(f"[TEST] Renderable entities: {SceneManager.GetRenderableEntities()}")

    # ── 初始化内联渲染器 ──
    picker = SceneFBOPicker()
    picker.init(fbw, fbh)

    # ── 摄像机 ──
    cam = Camera()
    cam.yaw = math.pi * 0.7
    cam.pitch = 0.2
    cam.target = np.array([0, 0, 0], 'f4')
    cam.distance = 6.0

    # ── 交互状态 ──
    selected: set[int] = set()
    dragging = False
    last_mx = last_my = 0.0
    press_mx = press_my = 0.0

    def update_title():
        s = ",".join(str(i) for i in sorted(selected)) or "none"
        glfw.set_window_title(
            window,
            f"FBO Scene Pick — sel=[{s}]  Click/Drag/Scroll/Space/ESC"
        )

    # ── 回调 ──
    def on_key(win, key, scancode, action, mods):
        nonlocal selected
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(win, True)
        elif key == glfw.KEY_SPACE:
            if selected:
                old = set(selected)
                selected.clear()
                ClearSelectionEvent.Pack()
                print(f"  (Cleared selection: {sorted(old)})")
            update_title()

    def on_mouse_button(win, button, action, mods):
        nonlocal dragging, last_mx, last_my, press_mx, press_my, selected
        if button != glfw.MOUSE_BUTTON_LEFT:
            return
        if action == glfw.PRESS:
            dragging = True
            last_mx, last_my = glfw.get_cursor_pos(win)
            press_mx, press_my = last_mx, last_my
        else:
            dragging = False
            cx, cy = glfw.get_cursor_pos(win)
            # 短拖拽 → 视为点击 → 拾取
            if abs(cx - press_mx) < 4 and abs(cy - press_my) < 4:
                fbw2, fbh2 = glfw.get_framebuffer_size(win)
                asp = fbw2 / fbh2 if fbh2 else 1.0
                pid = picker.pick(cx, cy, cam.view_matrix(), cam.projection_matrix(asp))
                print(f"[PICK] screen=({cx:.0f},{cy:.0f}) → entity_id={pid}")

                if pid >= 0 and pid != -1:
                    # 触发 SelecteEntityEvent
                    SelecteEntityEvent.Pack(pid)
                    selected = {pid}
                else:
                    if selected:
                        old = set(selected)
                        # 取消选中旧实体
                        for eid in old:
                            DeselectEntityEvent.Pack(eid)
                        selected.clear()
                        print(f"  (Deselected: {sorted(old)})")
                update_title()

    def on_cursor(win, x, y):
        nonlocal last_mx, last_my
        if dragging:
            cam.orbit(x - last_mx, y - last_my)
            last_mx, last_my = x, y

    def on_scroll(win, xoff, yoff):
        cam.zoom(yoff)

    glfw.set_key_callback(window, on_key)
    glfw.set_mouse_button_callback(window, on_mouse_button)
    glfw.set_cursor_pos_callback(window, on_cursor)
    glfw.set_scroll_callback(window, on_scroll)
    update_title()

    # ── 主循环 ──
    while not glfw.window_should_close(window):
        glfw.poll_events()

        fbw, fbh = glfw.get_framebuffer_size(window)
        asp = fbw / fbh if fbh else 1.0
        picker.resize(fbw, fbh)

        view = cam.view_matrix()
        proj = cam.projection_matrix(asp)

        picker.render_frame(view, proj)
        glfw.swap_buffers(window)

    # ── 清理 ──
    picker.release()
    glfw.terminate()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
