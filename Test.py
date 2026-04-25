import glfw
from OpenGL.GL import *


# 1. 初始化 GLFW
if not glfw.init():
    raise ("无法初始化 GLFW")

# 配置 OpenGL 版本（3.3 核心模式）
glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
# 2. 创建窗口
glfw_window = glfw.create_window(800, 600, "Modern OpenGL Square (VAO + EBO + Shader)", None, None)


if not glfw_window:
    print("无法创建窗口")
    glfw.terminate()
glfw.make_context_current(glfw_window)
for _ in range(3):
    vao = glGenVertexArrays(1)
    print(vao)
