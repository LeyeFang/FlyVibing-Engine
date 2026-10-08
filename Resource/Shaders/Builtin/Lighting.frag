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
//   uLightDir: 平面光传播方向 (世界空间单位向量); uLightColor: 颜色 × 强度
uniform vec3 uAmbient = vec3(0.5);
uniform vec3 uCameraPos = vec3(0.0);
uniform int  uLightCount = 0;
uniform vec3 uLightDir[4];
uniform vec3 uLightColor[4];

// 点光 (Light.light_type = "point"): 世界坐标 + 衰减半径 (att = (1 - d/range)²)
uniform int   uPointCount = 0;
uniform vec3  uPointPos[4];
uniform vec3  uPointColor[4];
uniform float uPointRange[4];

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
        vec3 L = -normalize(uLightDir[i]);          // 指向光源 (平面光)
        float ndl = max(dot(N, L), 0.0);
        vec3 H = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), shininess) * 0.25 * step(0.0001, ndl);
        accum += uLightColor[i] * (ndl + spec);
    }
    for (int i = 0; i < uPointCount && i < 4; ++i)
    {
        vec3 toL = uPointPos[i] - PosWorld;          // 指向点光
        float dist = length(toL);
        float att = max(1.0 - dist / max(uPointRange[i], 1e-4), 0.0);
        att *= att;                                  // (1 - d/range)² — d ≥ range 时 0
        if (att <= 0.0 || dist < 1e-6) continue;
        vec3 L = toL / dist;
        float ndl = max(dot(N, L), 0.0);
        vec3 H = normalize(L + V);
        float spec = pow(max(dot(N, H), 0.0), shininess) * 0.25 * step(0.0001, ndl);
        accum += uPointColor[i] * (ndl + spec) * att;
    }

    FragColor = vec4(albedo * accum, texel.a * uColor.a);
}
