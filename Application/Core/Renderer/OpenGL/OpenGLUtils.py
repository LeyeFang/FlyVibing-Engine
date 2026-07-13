"""
OpenGLUtils — PyOpenGL 工具函数 (着色器编译 + Uniform 设置)。

职责:
  - GLSL 着色器编译与链接
  - Uniform 位置查询与值设置

说明:
  - 所有方法均为 @staticmethod，不依赖任何类状态
  - uniform 方法接受 registered_shaders 作为显式参数
  - OpenGLResourceManager 保留薄封装层，传递 cls.registered_shaders

所有方法均为 @staticmethod，纯函数式设计。
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl


class OpenGLUtils:
    """PyOpenGL 工具集 — 纯 GL 操作，无状态依赖。"""

    # ════════════════════════════════════════════════════════════
    # 着色器编译
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def compile_program(vs_src: str, fs_src: str) -> int:
        """编译顶点/片段着色器并链接为程序。

        Args:
            vs_src: GLSL 顶点着色器源码
            fs_src: GLSL 片段着色器源码

        Returns:
            GLuint 着色器程序句柄

        Raises:
            RuntimeError: 编译或链接失败
        """
        # ── 编译顶点着色器 ──
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, vs_src)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(vs).decode(errors='replace')
            gl.glDeleteShader(vs)
            raise RuntimeError(f"Vertex shader compilation failed:\n{log}")
        # ── 编译片段着色器 ──
        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, fs_src)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(fs).decode(errors='replace')
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            raise RuntimeError(f"Fragment shader compilation failed:\n{log}")
        # ── 链接程序 ──
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, fs)
        gl.glLinkProgram(program)
        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(program).decode(errors='replace')
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            gl.glDeleteProgram(program)
            raise RuntimeError(f"Shader program linking failed:\n{log}")
        # ── 清理 shader 对象 (已链接到 program，不再需要) ──
        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)
        return program

    # ════════════════════════════════════════════════════════════
    # Uniform 辅助 — 接受 registered_shaders 为显式参数
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def get_uniform_location(
        registered_shaders: dict,
        shader_id: int,
        name: str
    ) -> int:
        """获取 uniform location (带缓存，支持懒查询)。

        Args:
            registered_shaders: 着色器注册表 (shader_id → shader_data_struct)
            shader_id: 着色器资源 ID
            name: uniform 名称

        Returns:
            uniform location，-1 表示不存在
        """
        shader_data = registered_shaders.get(shader_id)
        if shader_data is None:
            return -1
        if name not in shader_data.uniforms_loc:
            # 懒查询: 预枚举未覆盖的 uniform
            loc = gl.glGetUniformLocation(shader_data.program, name)
            shader_data.uniforms_loc[name] = loc
        return shader_data.uniforms_loc.get(name, -1)

    @staticmethod
    def set_uniform_mat4(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        matrix: np.ndarray
    ) -> None:
        """Set a mat4 uniform.

        Args:
            registered_shaders: 着色器注册表
            shader_id: Shader resource ID
            name: Uniform name
            matrix: 4x4 matrix (numpy ndarray)

        CONVENTION (see Core/Math/__init__.py for full documentation):
          - Row-vector matrices (Math.Transform, Math.Camera, camera classes):
            Translation in last row. Upload with GL_FALSE.
            ←  This is what set_uniform_mat4 assumes.
          - Column-vector matrices (standard math convention):
            Upload with GL_TRUE. ←  NOT handled here;
            use glUniformMatrix4fv(..., GL_TRUE, ...) directly for these.

        All engine camera matrices and entity model matrices use row-vector
        convention (pure numpy), so GL_FALSE is the universal convention
        for set_uniform_mat4.
        """
        loc = OpenGLUtils.get_uniform_location(registered_shaders, shader_id, name)
        if loc < 0:
            return
        # pyrr row-vector internal storage -> numpy C-contiguous flattening
        # produces column-vector byte order -> GL_FALSE is correct
        data = np.ascontiguousarray(matrix.astype('float32'))
        gl.glUniformMatrix4fv(loc, 1, gl.GL_FALSE, data)

    @staticmethod
    def set_uniform_float(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        value: float
    ) -> None:
        """设置 float uniform。"""
        loc = OpenGLUtils.get_uniform_location(registered_shaders, shader_id, name)
        if loc < 0:
            return
        gl.glUniform1f(loc, float(value))

    @staticmethod
    def set_uniform_int(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        value: int
    ) -> None:
        """设置 int / sampler2D uniform。"""
        loc = OpenGLUtils.get_uniform_location(registered_shaders, shader_id, name)
        if loc < 0:
            return
        gl.glUniform1i(loc, value)

    @staticmethod
    def set_uniform_vec4(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        value
    ) -> None:
        """设置 vec4 uniform (float32 数组)。"""
        loc = OpenGLUtils.get_uniform_location(registered_shaders, shader_id, name)
        if loc < 0:
            return
        data = np.ascontiguousarray(value, dtype=np.float32)
        gl.glUniform4fv(loc, 1, data)

    @staticmethod
    def set_uniform_vec3(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        value
    ) -> None:
        """设置 vec3 uniform (float32 数组)。"""
        loc = OpenGLUtils.get_uniform_location(registered_shaders, shader_id, name)
        if loc < 0:
            return
        data = np.ascontiguousarray(value, dtype=np.float32)
        gl.glUniform3fv(loc, 1, data)

    @staticmethod
    def set_uniform_value(
        registered_shaders: dict,
        shader_id: int,
        name: str,
        value
    ) -> None:
        """根据 shader 中声明的 GLSL 类型自动选择正确的 glUniform* 调用。

        与 isinstance 派发不同，此方法查询 shader_data_struct 中缓存的
        uniforms_type，避免 Python int 值被错误地当作 GLSL int uniform。

        Args:
            registered_shaders: 着色器注册表
            shader_id: 着色器资源 ID
            name: uniform 名称
            value: uniform 值 (numpy array / float / int)
        """
        shader_data = registered_shaders.get(shader_id)
        if shader_data is None:
            return

        glsl_type = shader_data.uniforms_type.get(name, None)

        if glsl_type == 'mat4' or (isinstance(value, np.ndarray) and value.ndim == 2):
            OpenGLUtils.set_uniform_mat4(registered_shaders, shader_id, name, value)
        elif glsl_type == 'vec4':
            OpenGLUtils.set_uniform_vec4(registered_shaders, shader_id, name, value)
        elif glsl_type == 'vec3':
            OpenGLUtils.set_uniform_vec3(registered_shaders, shader_id, name, value)
        elif glsl_type in ('float', 'double'):
            OpenGLUtils.set_uniform_float(registered_shaders, shader_id, name, float(value))
        elif glsl_type in ('int', 'sampler2D', 'sampler'):
            OpenGLUtils.set_uniform_int(registered_shaders, shader_id, name, int(value))
        elif glsl_type is None:
            # 回退: 未知 uniform 用 isinstance 猜测
            if isinstance(value, np.ndarray) and value.ndim == 2:
                OpenGLUtils.set_uniform_mat4(registered_shaders, shader_id, name, value)
            elif isinstance(value, (np.integer, int)):
                OpenGLUtils.set_uniform_int(registered_shaders, shader_id, name, int(value))
            else:
                OpenGLUtils.set_uniform_float(registered_shaders, shader_id, name, float(value))
        else:
            # 未知 GLSL 类型，用 float 兜底
            OpenGLUtils.set_uniform_float(registered_shaders, shader_id, name, float(value))
