import numpy as np
from OpenGL.GL import *
from pyrr import matrix44, matrix33, vector3, vector4, vector
from pyrr import Matrix44, Vector3, Vector4

from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowResizeEvent
from Application.Renderer.Renderer import Renderer
from Application.Resource.ResourceManager import ResourceManager
from Application.Resource.Mesh import Mesh
from Application.Scene.SceneManager import SceneManager
from Application.Scene.BasicComponents import *


class openglRenderer(Renderer):

    registered_mesh: dict[dict] = {}
    registered_shader: dict[dict] = {}

    @classmethod
    def Create(
        cls,
        app
    ):
        window_size = app.window.GetSize()
        glViewport(0, 0, window_size[0], window_size[1])
        return cls

    @classmethod
    def RegisterMesh(
        cls,
        mesh: Mesh,
        mesh_id: int
    ):
        if mesh_id in cls.registered_mesh.keys():
            return
        cls.registered_mesh[f'{mesh_id}'] = {}
        current_mesh = cls.registered_mesh[f'{mesh_id}']
        vertices: np.ndarray = mesh.vertices
        indices: np.ndarray = mesh.indices
        # VBO
        current_mesh['vbo'] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, current_mesh['vbo'])
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        # VAO
        current_mesh['vao'] = glGenVertexArrays(1)
        glBindVertexArray(current_mesh['vao'])
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(GLfloat), ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # EBO
        current_mesh['ebo'] = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, current_mesh['ebo'])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        # Counts
        current_mesh['counts'] = len(indices)

    @classmethod
    def RegisterShader(
        cls,
        vertex_shader_source: str,
        fragment_shader_source: str,
        shader_id: int
    ) -> None:
        if shader_id not in cls.registered_shader.keys():
            return
        # 编译顶点着色器
        vertex_shader = glCreateShader(GL_VERTEX_SHADER)
        glShaderSource(vertex_shader, vertex_shader_source)
        glCompileShader(vertex_shader)
        # 检查编译状态
        success = glGetShaderiv(vertex_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(vertex_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            raise RuntimeError(f"Vertex shader compilation failed:\n{log}")
        # 编译片段着色器
        fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
        glShaderSource(fragment_shader, fragment_shader_source)
        glCompileShader(fragment_shader)
        success = glGetShaderiv(fragment_shader, GL_COMPILE_STATUS)
        if not success:
            log = glGetShaderInfoLog(fragment_shader).decode('utf-8')
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Fragment shader compilation failed:\n{log}")
        # 创建着色器程序并链接
        program = glCreateProgram()
        glAttachShader(program, vertex_shader)
        glAttachShader(program, fragment_shader)
        glLinkProgram(program)
        # 检查链接状态
        success = glGetProgramiv(program, GL_LINK_STATUS)
        if not success:
            log = glGetProgramInfoLog(program).decode('utf-8')
            glDeleteProgram(program)
            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)
            raise RuntimeError(f"Shader program linking failed:\n{log}")
        # 着色器对象已链接到程序，可以删除
        glDeleteShader(vertex_shader)
        glDeleteShader(fragment_shader)
        # 存储到 registered_shader 字典中（与 mesh 类似）
        cls.registered_shader[f"{shader_id}"] = {
            'program': program
            # 如果需要，可以在这里缓存 uniform 位置等
            # 'uniform_locations': {}
        }


    @classmethod
    def StartFrame(
        cls
    ) -> None:
        # About Camera
        camera, transform = SceneManager.GetSceneCamera()
        view = Calculate_Camera_View(camera, transform)
        proj = Calculate_Camera_Proj(camera)
        # About Mesh and Shader
        renderable_entities = SceneManager.GetRenderableEntitiesModelShader()
        for model_id, shader_id in renderable_entities:
            mesh = ResourceManager.GetMesh(model_id)
            cls.RegisterMesh(mesh, model_id)
            vs, fs = ResourceManager.GetShader(shader_id)
            cls.RegisterShader(vs, fs, shader_id)
        # About Model Transform

    @classmethod
    def EndFrame(
        cls
    ) -> None:
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        for current_mesh in cls.registered_mesh.values():
            current_vao = current_mesh['vao']
            current_counts = current_mesh['counts']
            glBindVertexArray(current_vao)
            glDrawElements(GL_TRIANGLES, current_counts, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ):
        if event is WindowResizeEvent:
            width, height = event.Unpack()
            glViewport(0, 0, width, height)


def Calculate_Camera_View(
    camera: Camera,
    transform: Transform
) -> Matrix44:
    """根据摄像机的辅助参数和实体的变换组件计算视图矩阵"""
    pos = Vector3([transform.position_x, transform.position_y, transform.position_z])
    # 构建旋转矩阵（欧拉角顺序 ZYX，弧度）
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,   # pitch (X)
        transform.rotation_y,   # yaw   (Y)
        transform.rotation_z    # roll  (Z)
    ])
    # 世界前向 = 旋转矩阵 * 局部前向（齐次向量 w=0）
    local_forward = Vector3(camera.local_forward)
    local_forward = vector4.create_from_vector3(local_forward)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward)
    world_forward = vector3.create_from_vector4(world_forward_vec4)
    world_forward = vector.normalise(world_forward[0])
    target = pos + world_forward
    up = Vector3(camera.up_vector)
    return matrix44.create_look_at(pos, target, up)


def Calculate_Camera_Proj(
    camera: Camera
) -> Matrix44:
    """根据摄像机投影参数计算投影矩阵"""
    near = camera.near_plane
    far = camera.far_plane
    if camera.projection_type == ProjectionType.PERSPECTIVE:
        # fov 需要弧度（假设 camera.fov 是度数）
        import math
        fov_rad = math.radians(camera.fov)
        aspect = camera.aspect_ratio
        return matrix44.create_perspective_projection(
            fov_rad,
            aspect,
            near,
            far
        )
    else:
        half_h = camera.ortho_size
        half_w = half_h * camera.aspect_ratio
        return matrix44.create_orthogonal_projection(
            -half_w, half_w,   # left, right
            -half_h, half_h,   # bottom, top
            near, far
        )
