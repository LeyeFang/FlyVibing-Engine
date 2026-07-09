#version 440 core

layout(location = 0) in vec2 TexCoord;

layout(binding = 0) uniform sampler2D uTexture;
uniform vec4 uColor = vec4(1.0);

layout(location = 0) out vec4 FragColor;

void main()
{
    FragColor = texture(uTexture, TexCoord) * uColor;
}