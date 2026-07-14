"""
Diagnostic: 一步一步排查 ZenGL 渲染通路

步骤:
  1. 纯红色图像 blit 到屏幕 → 确认 blit 基础功能
  2. 三色三角形渲染到独立图像后 blit → 确认 pipeline 渲染 + blit
  3. ★ 用 samples=1 创建图像并 blit → 验证 samples=1 是否导致黑屏
  4. 用 samples=0 创建图像并 blit → 验证修复
  5. 渲染三角形到 _color_image (已改为 samples=0) → 确认修复后通路正常
  6. 用 register_entity 的 pipeline 渲染 → 确认实体渲染管线

运行: python Test/Application/Core/Renderer/ZenGL/test_diag.py
"""
from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup
import math, numpy as np, glfw, time

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from Application.Core.Events.Event import BindPackCallback
from Test.Application.Core.Renderer.ZenGL.Engine.ZenGLRenderer import ZenGLRenderer
from Test.Application.Core.Renderer.ZenGL.Engine.ZenGLCore import ZenGLCore

class _MockWindow:
    def __init__(self,w): self._glfw=w
    def GetSize(self): return glfw.get_framebuffer_size(self._glfw)
class _MockApp: editor_window=None

def main():
    import zengl

    if not glfw.init(): return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
    glfw.window_hint(glfw.SAMPLES, 0)
    glfw.window_hint(glfw.DEPTH_BITS, 0)

    w = glfw.create_window(1024, 768, "ZenGL Diag — Step by Step", None, None)
    if not w: glfw.terminate(); return
    glfw.make_context_current(w)
    glfw.swap_interval(1)
    fbw, fbh = glfw.get_framebuffer_size(w)
    print(f"[DIAG] Window: {fbw}x{fbh}")

    # ─── Step 0: Init ZenGL ───
    ZenGLCore.init_core((fbw, fbh))
    ctx = ZenGLCore.ctx
    print(f"[DIAG] ZenGL context created")

    # ─── Step 1: 创建纯红色图像并 blit ───
    red_img = ctx.image((fbw, fbh), 'rgba8unorm')
    red_img.clear_value = (1.0, 0.0, 0.0, 1.0)
    red_img.clear()
    ctx.new_frame()
    red_img.blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 1: Red image blit → 窗口应变红")

    time.sleep(0.5)

    # ─── Step 2: 三色三角形直接 blit ───
    tri_img = ctx.image((fbw, fbh), 'rgba8unorm')
    tri_pipe = ctx.pipeline(
        vertex_shader='''#version 440 core
vec2 v[3]=vec2[](vec2(-0.8,-0.7),vec2(0.8,-0.7),vec2(0,0.8));
vec3 c[3]=vec3[](vec3(1,0,0),vec3(0,1,0),vec3(0,0,1));
out vec3 col;
void main(){gl_Position=vec4(v[gl_VertexID],0,1);col=c[gl_VertexID];}''',
        fragment_shader='''#version 440 core
in vec3 col;out vec4 fc;
void main(){fc=vec4(col,1);}''',
        framebuffer=[tri_img],
        topology='triangles',
        vertex_count=3,
    )
    ctx.new_frame()
    tri_img.clear()
    tri_pipe.render()
    tri_img.blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 2: Triangle on separate image, blit → 应显示三色三角形")

    time.sleep(0.5)

    # ─── Step 3: ★ 验证 samples=1 是否导致 blit 失败 ───
    img_s1 = ctx.image((fbw, fbh), 'rgba8unorm', samples=1)
    img_s1.clear_value = (0.0, 1.0, 0.0, 1.0)  # 纯绿色
    ctx.new_frame()
    img_s1.clear()
    # 画一个蓝色三角形到 img_s1
    tri_s1 = ctx.pipeline(
        vertex_shader='''#version 440 core
vec2 v[3]=vec2[](vec2(-0.6,-0.5),vec2(0.6,-0.5),vec2(0,0.6));
vec3 c[3]=vec3[](vec3(0,0,1),vec3(0,0,1),vec3(0,0,1));
out vec3 col;
void main(){gl_Position=vec4(v[gl_VertexID],0,1);col=c[gl_VertexID];}''',
        fragment_shader='''#version 440 core
in vec3 col;out vec4 fc; void main(){fc=vec4(col,1);}''',
        framebuffer=[img_s1],
        topology='triangles', vertex_count=3,
    )
    tri_s1.render()
    img_s1.blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 3: samples=1 image (green bg + blue tri) → 如果黑屏, samples=1 就是元凶")

    time.sleep(0.5)

    # ─── Step 4: 三角形渲染到 _color_image (不传 samples, 非MSAA) 再 blit ───
    ctx.new_frame()
    ZenGLCore.clear_frame()
    tri_to_main = ctx.pipeline(
        vertex_shader='''#version 440 core
vec2 v[3]=vec2[](vec2(-0.8,-0.7),vec2(0.8,-0.7),vec2(0,0.8));
vec3 c[3]=vec3[](vec3(1,0,0),vec3(0,1,0),vec3(0,0,1));
out vec3 col;
void main(){gl_Position=vec4(v[gl_VertexID],0,1);col=c[gl_VertexID];}''',
        fragment_shader='''#version 440 core
in vec3 col;out vec4 fc;
void main(){fc=vec4(col,1);}''',
        framebuffer=ZenGLCore.get_framebuffer(),
        topology='triangles',
        vertex_count=3,
    )
    tri_to_main.render()
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 4: Triangle on _color_image (non-MSAA) → 应显示三色三角形在深灰背景上")

    time.sleep(0.5)

    # ═══════════════════════════════════════════════════════════════
    # 设置场景 (实体管线)
    # ═══════════════════════════════════════════════════════════════
    ma = _MockApp(); ma.editor_window = _MockWindow(w)
    ResourceManager.Init(ma)
    SceneManager.Init(ma)
    BindPackCallback(lambda e: print(e))

    # Patch shader (不用纹理)
    vs = """#version 440 core
layout(location=0) in vec3 aPos;layout(location=1) in vec2 aTexCoord;layout(location=2) in vec3 aNormal;
uniform mat4 model,view,projection;out vec2 TexCoord;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);TexCoord=aTexCoord;}"""
    fs = """#version 440 core
// no texture diag
in vec2 TexCoord;out vec4 FragColor;
void main(){FragColor=vec4(TexCoord.x,0.62,0.31,1.0);}"""
    s = ResourceManager.loaded_shader['1']['data']
    s.vs_src = vs; s.fs_src = fs
    s.uniforms_name_type = {'model':'mat4','view':'mat4','projection':'mat4'}
    print(f"[DIAG] Shader patched")

    renderer = ZenGLRenderer
    renderer.viewport_width = fbw
    renderer.viewport_height = fbh
    renderer.aspect_ratio = fbw/fbh if fbh else 1.0

    mid = ResourceManager.GetDefaultMesh('Cube')
    for pos in [(-2, 0, 0), (0, 0.5, 0), (2, -0.3, 0.5)]:
        eid = SceneManager._current().AddEntity()
        SceneManager.AddComponentToEntity(eid, MeshRenderer(mesh_id=mid))
        SceneManager.SetEntityTransform(eid, position_xyz=pos)
        renderer.register_entity(eid)
    print(f"[DIAG] {len(renderer.registered_entities)} entities registered")

    for eid, e in renderer.registered_entities.items():
        print(f"  entity {eid}: pipeline={e.pipeline} mesh={e.mesh_id}")

    # 简单摄像机
    import pyrr
    from pyrr import matrix44, Vector3
    yaw = math.pi * 0.6
    pitch = 0.25
    target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    distance = 8.0
    def cam_pos():
        x = distance * math.sin(yaw) * math.cos(pitch)
        y = distance * math.sin(pitch)
        z = distance * math.cos(yaw) * math.cos(pitch)
        return np.array([x, y, z], dtype=np.float32) + target
    view = matrix44.create_look_at(Vector3(cam_pos().tolist()), Vector3(target.tolist()), Vector3([0, 1, 0]))
    proj = matrix44.create_perspective_projection(45.0, fbw/fbh, 0.1, 100.0)
    from Application.Core.Math.Transform import calculate_entity_model

    # 取第一个实体数据用于独立测试
    first_eid = list(renderer.registered_entities.keys())[0]
    first_entity = renderer.registered_entities[first_eid]
    first_mesh_data = renderer.registered_meshes[first_entity.mesh_id]
    model_mat = calculate_entity_model(SceneManager.GetEntityTransform(first_eid))

    print(f"[DIAG] First entity mesh: {first_entity.mesh_id}, elements_count={first_mesh_data.elements_count}")

    # ─── Step 5: 直接用固定颜色 shader + 网格数据测试 ───
    # 用最简单的 shader (纯色, 只有位置属性) 直接渲染该 mesh
    cube_only_pipe = ctx.pipeline(
        vertex_shader='''#version 440 core
layout(location=0) in vec3 aPos;
void main(){gl_Position=vec4(aPos*0.5,1.0);}''',  # 缩放到 NDC
        fragment_shader='''#version 440 core
out vec4 fc; void main(){fc=vec4(0.0,1.0,0.0,1.0);}''',  # 纯绿色
        framebuffer=ZenGLCore.get_framebuffer(),
        topology='triangles',
        cull_face='back',
        depth={'func': 'less', 'write': True},
        vertex_buffers=zengl.bind(first_mesh_data.vbo, '3f', 0),  # 只有位置
        index_buffer=first_mesh_data.ebo,
        vertex_count=first_mesh_data.elements_count,
    )
    ctx.new_frame()
    ZenGLCore.clear_frame()
    cube_only_pipe.render()
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 5: Green cube (no MVP, raw mesh) → 显示绿色物体?")

    time.sleep(1.0)

    # ─── Step 6: 加上 MVP 测试 ───
    cube_mvp_pipe = ctx.pipeline(
        vertex_shader='''#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 model, view, projection;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);}''',
        fragment_shader='''#version 440 core
out vec4 fc; void main(){fc=vec4(0.0,0.0,1.0,1.0);}''',  # 纯蓝色
        framebuffer=ZenGLCore.get_framebuffer(),
        topology='triangles',
        cull_face='back',
        depth={'func': 'less', 'write': True},
        uniforms={'model': np.identity(4, 'f4').flatten().tolist(),
                  'view': np.identity(4, 'f4').flatten().tolist(),
                  'projection': np.identity(4, 'f4').flatten().tolist()},
        vertex_buffers=zengl.bind(first_mesh_data.vbo, '3f', 0),
        index_buffer=first_mesh_data.ebo,
        vertex_count=first_mesh_data.elements_count,
    )
    ctx.new_frame()
    ZenGLCore.clear_frame()
    cube_mvp_pipe.uniforms['model'][:] = model_mat.T.astype('f4').tobytes()
    cube_mvp_pipe.uniforms['view'][:] = view.T.astype('f4').tobytes()
    cube_mvp_pipe.uniforms['projection'][:] = proj.T.astype('f4').tobytes()
    cube_mvp_pipe.render()
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 6: Blue cube with MVP (same as entity pipeline) → 显示?")

    time.sleep(1.0)

    # ─── Step 7: 去掉 CULL_FACE 和 DEPTH 测试 ───
    cube_nocull_pipe = ctx.pipeline(
        vertex_shader='''#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 model, view, projection;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);}''',
        fragment_shader='''#version 440 core
out vec4 fc; void main(){fc=vec4(1.0,0.0,1.0,1.0);}''',  # 品红色
        framebuffer=ZenGLCore.get_framebuffer(),
        topology='triangles',
        # NO cull_face, NO depth
        uniforms={'model': np.identity(4, 'f4').flatten().tolist(),
                  'view': np.identity(4, 'f4').flatten().tolist(),
                  'projection': np.identity(4, 'f4').flatten().tolist()},
        vertex_buffers=zengl.bind(first_mesh_data.vbo, '3f', 0),
        index_buffer=first_mesh_data.ebo,
        vertex_count=first_mesh_data.elements_count,
    )
    ctx.new_frame()
    ZenGLCore.clear_frame()
    cube_nocull_pipe.uniforms['model'][:] = model_mat.T.astype('f4').tobytes()
    cube_nocull_pipe.uniforms['view'][:] = view.T.astype('f4').tobytes()
    cube_nocull_pipe.uniforms['projection'][:] = proj.T.astype('f4').tobytes()
    cube_nocull_pipe.render()
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 7: Magenta cube (no cull, no depth) → 显示?")

    time.sleep(1.0)

    # ─── Step 8: 矩阵不上传 .T (直接 column-major) ───
    cube_not_pipe = ctx.pipeline(
        vertex_shader='''#version 440 core
layout(location=0) in vec3 aPos;
uniform mat4 model, view, projection;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);}''',
        fragment_shader='''#version 440 core
out vec4 fc; void main(){fc=vec4(1.0,1.0,0.0,1.0);}''',  # 黄色
        framebuffer=ZenGLCore.get_framebuffer(),
        topology='triangles',
        uniforms={'model': np.identity(4, 'f4').flatten().tolist(),
                  'view': np.identity(4, 'f4').flatten().tolist(),
                  'projection': np.identity(4, 'f4').flatten().tolist()},
        vertex_buffers=zengl.bind(first_mesh_data.vbo, '3f', 0),
        index_buffer=first_mesh_data.ebo,
        vertex_count=first_mesh_data.elements_count,
    )
    ctx.new_frame()
    ZenGLCore.clear_frame()
    # ★ 不上传 .T — 直接 column-major 原始数据
    cube_not_pipe.uniforms['model'][:] = model_mat.astype('f4').tobytes()
    cube_not_pipe.uniforms['view'][:] = view.astype('f4').tobytes()
    cube_not_pipe.uniforms['projection'][:] = proj.astype('f4').tobytes()
    cube_not_pipe.render()
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 8: Yellow cube (no .T transpose, column-major) → 显示?")

    time.sleep(1.0)

    # ─── Step 9: 原始实体管线 ───
    ctx.new_frame()
    ZenGLCore.clear_frame()
    for eid in SceneManager.GetRenderableEntities():
        e = renderer.registered_entities.get(eid)
        if not e or not e.pipeline: continue
        print(f"[DIAG] Rendering entity {eid}")
        model = calculate_entity_model(SceneManager.GetEntityTransform(eid))
        try:
            e.pipeline.uniforms['model'][:] = model.T.astype('f4').tobytes()
            e.pipeline.uniforms['view'][:] = view.T.astype('f4').tobytes()
            e.pipeline.uniforms['projection'][:] = proj.T.astype('f4').tobytes()
        except Exception as ex:
            print(f"[DIAG]   uniform error: {ex}")
        try:
            e.pipeline.render()
        except Exception as ex:
            print(f"[DIAG]   render() error: {ex}")
    ZenGLCore.get_color_image().blit()
    ctx.end_frame()
    glfw.swap_buffers(w)
    print("[DIAG] Step 9: Original entity pipelines → 应显示 3 个橙蓝立方体")

    # 保持窗口打开
    print("[DIAG] 窗口保持打开，按 ESC 退出...")
    while not glfw.window_should_close(w):
        glfw.poll_events()
        time.sleep(0.1)
        if glfw.get_key(w, glfw.KEY_ESCAPE) == glfw.PRESS:
            glfw.set_window_should_close(w, True)

    glfw.terminate()
    print("[DIAG] Done")

if __name__ == "__main__":
    main()
