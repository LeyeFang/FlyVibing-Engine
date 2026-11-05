#version 440 core

// ─────────────────────────────────────────────────────────────────────────
// Lighting.frag — 经典冯氏光照 + 面光源 / 点光源
//
// 光源两种 (协议: Doc/Dev/shader_protocol.md §7):
//   1. 面光源 (area): 一块发光平面。光照方向 = 平面法线 (uLightDir 传播方向 d)；
//      表面点必须在**发光面正面** (dot(P - lightPos, d) > 0) 才会被照亮，
//      面背后（射线负方向）无直射光 —— 位置是参与的，不是无穷远光源。
//   2. 点光源 (point): 有限半径内的局部光源，att = (1 - d/range)²。
//
// 反射模型（经典冯氏）:
//   I = ambient·ka + Σ (kd·max(N·L,0) + ks·pow(max(R·V,0), shininess))·Lcolor
//   R = reflect(-L, N)。uSpecularModel = 1 时切到 Blinn (H·N)。
// ─────────────────────────────────────────────────────────────────────────

layout(location = 0) in vec2 TexCoord;
layout(location = 1) in vec3 NormalWorld;
layout(location = 2) in vec3 PosWorld;

layout(binding = 0) uniform sampler2D uTexture;
uniform vec4 uColor = vec4(1.0);

// ── 材质参数 (进材质 uniforms_data, 可经 UI/节点/材质文件编辑) ──
//   哨兵约定: float 0 = 使用默认值 (与 uShininess 一致 — shader_protocol.md)
uniform float uShininess = 0.0;         // 高光指数      → 默认 32
uniform float uSpecularStrength = 0.0;  // 高光强度 ks   → 默认 0.25 (与旧版观感一致)
uniform float uDiffuseStrength = 0.0;   // 漫反射 kd     → 默认 1.0
uniform float uAmbientStrength = 0.0;   // 环境光 ka     → 默认 1.0
uniform int   uSpecularModel = 0;       // 0 = 经典冯氏 (R·V) / 1 = Blinn (H·N)

// ── 渲染器注入 (保留 uniform — 不进材质, 每帧由渲染管线写入) ──
//   uLight*: 面光源位置 / 传播方向 / 颜色×强度;  uPoint*: 点光源
uniform vec3 uAmbient = vec3(0.5);
uniform vec3 uCameraPos = vec3(0.0);
uniform int  uLightCount = 0;
uniform vec3 uLightPos[4];
uniform vec3 uLightDir[4];
uniform vec3 uLightColor[4];

uniform int   uPointCount = 0;
uniform vec3  uPointPos[4];
uniform vec3  uPointColor[4];
uniform float uPointRange[4];

layout(location = 0) out vec4 FragColor;

float specular_term(vec3 L, vec3 N, vec3 V, float shininess)
{
    if (uSpecularModel == 1)
    {
        vec3 H = normalize(L + V);                       // Blinn
        return pow(max(dot(N, H), 0.0), shininess);
    }
    vec3 R = reflect(-L, N);                             // 经典冯氏
    return pow(max(dot(R, V), 0.0), shininess);
}

void main()
{
    vec4 texel = texture(uTexture, TexCoord);
    vec3 albedo = texel.rgb * uColor.rgb;
    vec3 N = normalize(NormalWorld);
    vec3 V = normalize(uCameraPos - PosWorld);

    float shininess = (uShininess > 0.0)         ? uShininess         : 32.0;
    float ks        = (uSpecularStrength > 0.0)  ? uSpecularStrength  : 0.25;
    float kd        = (uDiffuseStrength > 0.0)   ? uDiffuseStrength   : 1.0;
    float ka        = (uAmbientStrength > 0.0)   ? uAmbientStrength   : 1.0;

    vec3 accum = uAmbient * ka;

    // ── 面光源: 只在发光面正面有直射光 (背面 = 射线负方向 → 跳过) ──
    //   EPS: 表面与发光面共面时按“正面”处理，避免浮点噪声导致闪烁
    const float SIDE_EPS = 1e-4;
    for (int i = 0; i < uLightCount && i < 4; ++i)
    {
        vec3 d = normalize(uLightDir[i]);                // 传播方向
        if (dot(PosWorld - uLightPos[i], d) < -SIDE_EPS) continue;
        vec3 L = -d;                                     // 指向光源
        float ndl = max(dot(N, L), 0.0);
        float spec = specular_term(L, N, V, shininess) * ks * step(0.0001, ndl);
        accum += uLightColor[i] * (ndl * kd + spec);
    }

    // ── 点光源: 有限半径衰减 ──
    for (int i = 0; i < uPointCount && i < 4; ++i)
    {
        vec3 toL = uPointPos[i] - PosWorld;              // 指向点光
        float dist = length(toL);
        float att = max(1.0 - dist / max(uPointRange[i], 1e-4), 0.0);
        att *= att;                                      // (1 - d/range)² — d ≥ range 时 0
        if (att <= 0.0 || dist < 1e-6) continue;
        vec3 L = toL / dist;
        float ndl = max(dot(N, L), 0.0);
        float spec = specular_term(L, N, V, shininess) * ks * step(0.0001, ndl);
        accum += uPointColor[i] * (ndl * kd + spec) * att;
    }

    FragColor = vec4(albedo * accum, texel.a * uColor.a);
}
