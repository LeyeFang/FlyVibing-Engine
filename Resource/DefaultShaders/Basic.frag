#version 450

layout(location = 0) in vec2 TexCoord;

layout(binding = 0) uniform sampler2D uTexture;

layout(location = 0) out vec4 FragColor;

void main()
{
    FragColor = texture(uTexture, TexCoord);
}