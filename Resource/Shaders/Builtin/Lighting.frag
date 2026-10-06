#version 440 core

layout(location = 0) in vec2 TexCoord;
layout(location = 1) in vec3 NormalWorld;
layout(location = 2) in vec3 PosWorld;

layout(binding = 0) uniform sampler2D uTexture;
uniform vec4 uColor = vec4(1.0);

// ── 材质参数 (进材质 uniforms_data, 可经 UI/节点/材质文件编辑) ──
//   uShininess: 0 = 使用默认 32 (材质 float 默认 0 的哨兵约定 — shader_protocol.md)
uniform float uShininess = 0.0;

// ── 渲染器注入 (保留 uniform — 不进材质, 每帧由渲染管线写入) ──
//   uLightDir: 光线传播方向 (世界空间单位向量); uLightColor: 颜色 × 强度
uniform vec3 uAmbient = vec3(0.18);
uniform vec3 uCameraPos = vec3(0.0);
uniform int  uLightCount = 0;
uniform vec3 uLightDir[4];
uniform vec3 uLightColor[4];

layout(location = 0) out vec4 FragColor;

void main()
{
    vec4 texel = texture(uTexture, TexCoord);
    vec3 albedo = texel.rgb * uColor.rgb;
    vec3 N = normalize(NormalWorld);
    vec3 V = normalize(uCameraPos - PosWorld);

    float shininess = (uShininess > 0.0) ? uShininess : 32.0;

    vec3 accum = uAmbient;
    for (int i = 0; i < uLightCount && i < 4; ++i)
    {
        vec3 L = -normalize(uLightDir[i]);          // 指向光源
        float ndl = max(dot(N, L), 0.0);
        vec3 H = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), shininess) * 0.25 * step(0.0001, ndl);
        accum += uLightColor[i] * (ndl + spec);
    }

    FragColor = vec4(albedo * accum, texel.a * uColor.a);
}
