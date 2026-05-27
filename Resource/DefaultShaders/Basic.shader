#version 330 core

layout (location = 0) in vec3 aPos;     // 顶点位置
layout (location = 1) in vec2 aTexCoord; // 纹理坐标（虽然暂时不用，但 OBJ 有）
layout (location = 2) in vec3 aNormal;   // 法线（暂时不用）


uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
out vec2 TexCoord;       // 传递纹理坐标（备用）


void main()
{
    // 应用模型矩阵变换顶点位置
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}


#version 330 core

in vec2 TexCoord;

uniform sampler2D uTexture;

out vec4 FragColor;

void main()
{
    FragColor = texture(uTexture, TexCoord);
}
