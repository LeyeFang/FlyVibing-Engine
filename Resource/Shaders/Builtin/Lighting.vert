#version 440 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec2 aTexCoord;
layout(location = 2) in vec3 aNormal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

layout(location = 0) out vec2 TexCoord;
layout(location = 1) out vec3 NormalWorld;
layout(location = 2) out vec3 PosWorld;

void main()
{
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
    // ★ 矩阵约定: 上传为 GL_FALSE + numpy C 序 → GLSL 中 (model * v) 即引擎世界坐标
    //   法线: mat3(model) 对旋转有效 (世界空间与引擎坐标一致; 见 shader_protocol.md)
    NormalWorld = mat3(model) * aNormal;
    PosWorld = (model * vec4(aPos, 1.0)).xyz;
}
