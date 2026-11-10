#version 440 core

layout(location = 0) in vec2 TexCoord;

layout(binding = 0) uniform sampler2D uTexture;
// ★ `//!` = 机读注解（GUI 控件 / 范围 / 默认值 / 归属）—— 语法见 Doc/Dev/shader_protocol.md §6.1
//! ui: color4 | label=mat.color | group=Surface | default=1,1,1,1
uniform vec4 uColor = vec4(1.0);

layout(location = 0) out vec4 FragColor;

void main()
{
    FragColor = texture(uTexture, TexCoord) * uColor;
}