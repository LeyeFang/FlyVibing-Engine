#version 440 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec2 aTexCoord;

//! ui: readonly | owner=engine | label=mat.model
uniform mat4 model;
//! ui: readonly | owner=engine | label=mat.view
uniform mat4 view;
//! ui: readonly | owner=engine | label=mat.projection
uniform mat4 projection;

layout(location = 0) out vec2 TexCoord;

void main()
{
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}