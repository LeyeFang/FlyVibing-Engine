"""
Test: ZenGL 最小实体渲染 — 3 个立方体 (无 Overlay / Outliner)
验证 ZenGL 渲染管线基础通路。
运行: python Test/Application/Core/Renderer/ZenGL/test_cube_minimal.py
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup
import math, numpy as np, glfw
from pyrr import matrix44, Vector3

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from Application.Core.Events.Event import BindPackCallback

from Application.Core.Renderer.ZenGL.ZenGLRenderer import ZenGLRenderer
from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore

class _MockWindow:
    def __init__(self,w): self._glfw=w
    def GetSize(self): return glfw.get_framebuffer_size(self._glfw)
class _MockApp: editor_window=None
class TestCamera:
    def __init__(self):
        self.yaw=math.pi*0.6; self.pitch=0.25
        self.target=np.array([0,0,0],'f4'); self.distance=8.0
        self.fov=45.0; self.near=0.1; self.far=100.0
    @property
    def position(self):
        x=self.distance*math.sin(self.yaw)*math.cos(self.pitch)
        y=self.distance*math.sin(self.pitch)
        z=self.distance*math.cos(self.yaw)*math.cos(self.pitch)
        return np.array([x,y,z],'f4')+self.target
    def view_matrix(self):
        return matrix44.create_look_at(Vector3(self.position.tolist()),Vector3(self.target.tolist()),Vector3([0,1,0]))
    def projection_matrix(self,a):
        return matrix44.create_perspective_projection(self.fov,a,self.near,self.far)
    def orbit(self,dx,dy): self.yaw-=dx*0.005; self.pitch+=dy*0.005
    def zoom(self,d): self.distance=max(0.5,min(self.distance-d*0.5,50.0))

def main():
    if not glfw.init(): return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR,4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR,4)
    glfw.window_hint(glfw.OPENGL_PROFILE,glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT,glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES,0); glfw.window_hint(glfw.DEPTH_BITS,0)
    w=glfw.create_window(1024,768,"ZenGL Minimal — 3 Cubes",None,None)
    if not w: glfw.terminate(); return
    glfw.make_context_current(w); glfw.swap_interval(1)
    fbw,fbh=glfw.get_framebuffer_size(w)

    ma=_MockApp(); ma.editor_window=_MockWindow(w)
    ResourceManager.Init(ma); SceneManager.Init(ma)
    BindPackCallback(lambda e: print(e))

    vs="""#version 440 core
layout(location=0) in vec3 aPos;layout(location=1) in vec2 aTexCoord;layout(location=2) in vec3 aNormal;
uniform mat4 model,view,projection;out vec2 TexCoord;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);TexCoord=aTexCoord;}"""
    fs="""#version 440 core
// unique shader v2 no texture
in vec2 TexCoord;out vec4 FragColor;
void main(){FragColor=vec4(TexCoord.x,0.62,0.31,1.0);}"""
    s=ResourceManager.loaded_shader['1']['data']; s.vs_src=vs; s.fs_src=fs
    s.uniforms_name_type={'model':'mat4','view':'mat4','projection':'mat4'}
    print(f"[DEBUG] shader vs: {s.vs_src[:50]}...")
    print(f"[DEBUG] shader fs: {s.fs_src[:50]}...")
    print(f"[DEBUG] uniforms: {s.uniforms_name_type}")

    renderer=ZenGLRenderer
    renderer.viewport_width=fbw; renderer.viewport_height=fbh
    renderer.aspect_ratio=fbw/fbh if fbh else 1.0
    ZenGLCore.init_core((fbw,fbh))

    # ★ Debug: non-MSAA triangle (排除 MSAA 问题)
    import zengl
    dbg_img = ZenGLCore.ctx.image((fbw,fbh), 'rgba8unorm')  # 无 MSAA
    debug_tri = ZenGLCore.ctx.pipeline(
        vertex_shader='''#version 440 core
vec2 v[3]=vec2[](vec2(0,0.8),vec2(-0.8,-0.7),vec2(0.8,-0.7));
vec3 c[3]=vec3[](vec3(1,0,0),vec3(0,1,0),vec3(0,0,1));
out vec3 col;void main(){gl_Position=vec4(v[gl_VertexID],0,1);col=c[gl_VertexID];}''',
        fragment_shader='''#version 440 core
in vec3 col;out vec4 fc;void main(){fc=vec4(col,1);}''',
        framebuffer=[dbg_img], topology='triangles', vertex_count=3)

    mid=ResourceManager.GetDefaultMesh('Cube')
    for pos in [(-2,0,0),(0,0.5,0),(2,-0.3,0.5)]:
        eid=SceneManager._current().AddEntity()
        SceneManager.AddComponentToEntity(eid,MeshRenderer(mesh_id=mid))
        SceneManager.SetEntityTransform(eid,position_xyz=pos)
        renderer.register_entity(eid)
    print(f"[TEST] 3 cubes registered, {len(renderer.registered_entities)} entities")
    # Debug: check first entity pipeline
    for eid, e in renderer.registered_entities.items():
        print(f"  entity {eid}: pipeline={e.pipeline} vao={e.vao} mesh={e.mesh_id} shader={e.shader_id}")

    cam=TestCamera(); dragging=False; lmx=lmy=0.0
    def on_key(win,k,sc,act,mods):
        if act==glfw.PRESS and k==glfw.KEY_ESCAPE: glfw.set_window_should_close(win,True)
    def on_mouse(win,btn,act,mods):
        nonlocal dragging,lmx,lmy
        if btn==glfw.MOUSE_BUTTON_LEFT:
            if act==glfw.PRESS: dragging=True; lmx,lmy=glfw.get_cursor_pos(win)
            else: dragging=False
    def on_cursor(win,x,y):
        nonlocal lmx,lmy
        if dragging: cam.orbit(x-lmx,y-lmy); lmx,lmy=x,y
    def on_scroll(win,xo,yo): cam.zoom(yo)
    glfw.set_key_callback(w,on_key); glfw.set_mouse_button_callback(w,on_mouse)
    glfw.set_cursor_pos_callback(w,on_cursor); glfw.set_scroll_callback(w,on_scroll)

    frame=0
    while not glfw.window_should_close(w):
        glfw.poll_events()
        fbw,fbh=glfw.get_framebuffer_size(w); asp=fbw/fbh if fbh else 1.0
        renderer._cached_view=cam.view_matrix(); renderer._cached_proj=cam.projection_matrix(asp)
        renderer.viewport_width=fbw; renderer.viewport_height=fbh; renderer.aspect_ratio=asp
        if frame < 3:
            # 前 3 帧用 debug triangle 确认通路
            ZenGLCore.ctx.new_frame()
            ZenGLCore.clear_frame()
            debug_tri.render()
            ZenGLCore.get_color_image().blit()
            ZenGLCore.ctx.end_frame()
        else:
            renderer._do_start_frame()
        glfw.swap_buffers(w)
        frame+=1
    glfw.terminate()

if __name__=="__main__": main()
