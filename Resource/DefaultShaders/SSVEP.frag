#version 440 core

const float pi = 3.141592653589793;

layout(location = 0) in vec2 TexCoord;

uniform float freq;
uniform float time;
uniform float phase_shift;

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