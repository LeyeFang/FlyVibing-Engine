#version 440 core

const float pi = 3.141592653589793;

layout(location = 0) in vec2 TexCoord;

// ★ `//!` = 机读注解: GUI 控件 / 范围 / 单位 / 默认值 / 归属（Doc/Dev/shader_protocol.md §6.1）
//! ui: float | label=mat.freq | group=Stimulus | range=1..60 | step=0.1 | unit=Hz | default=10
uniform float freq;
//! ui: float | label=mat.phase | group=Stimulus | range=0..6.283 | step=0.01 | unit=rad | default=0
uniform float phase_shift;
//! ui: readonly | owner=runtime | label=mat.time | group=Stimulus
uniform float time;

layout(location = 0) out vec4 FragColor;

void main()
{
    float lightness = sin(2.0 * pi * freq * time + phase_shift);
    if (lightness > 0) {
        FragColor = vec4(1.0, 1.0, 1.0, 1.0);
    } else {
        FragColor = vec4(0.0, 0.0, 0.0, 1.0);
    }
}