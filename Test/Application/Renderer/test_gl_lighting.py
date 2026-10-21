"""
GL 光照测试 — Lighting shader + 平面光/点光/环境光（真实 GL, 探针）。

锁定内容 (协议: Doc/Dev/shader_protocol.md / rendering_protocol.md §光照):
  1. 环境光单独生效: 输出 = albedo × ambient
  2. 平面光注入: 光线方向 = 实体 Transform 局部 -Z; Rx=+90° ⇒ 垂直向下 → 顶面全亮
  3. 斜射 (60°) 含 Blinn-Phong 高光 → 数值钉死
  4. 侧向/背向 (N·L ≤ 0) ⇒ 仅环境光 (step 拍死高光 — 背面不漏光)
  5. 颜色 × 强度 合并 + 双光源叠加 (逐通道)
  6. 材质 uShininess 进 uniforms_data; 渲染器保留 uniform 不进材质
  7. 点光 (Light.light_type="point"): att=(1-d/range)² — 0.25 / 0.0625 / 超距截断 三档
  8. 无灯回退: fallback=ON 无任何光源 ⇒ 环境光强制满亮; OFF ⇒ 恢复环境光值

夹具: 俯视相机 (Square 法线 +Y 朝上)、uColor=(0.8,0.8,0.8)、
      ambient 用 SetAmbientColor(0.2, 0.1, 0.05) 钉死、fallback 钉死 OFF (用例 8 单独开关)、
      无默认灯光 (非 EditorHost)。
      V=(0,1,0) (相机在正上方), H 与数值推导见各用例注释。

运行: python Utils/Dev/test_runner.py --only gl_lighting
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _gl_probe import GlProbe  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}

AMB = (0.2, 0.1, 0.05)          # 测试钉死的环境光
AMBIENT_ONLY = (41, 20, 10)     # 0.8 × AMB → 8bit


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("GL lighting — Lighting shader + directional/point/ambient (probe)")
    print("=" * 60)

    probe = GlProbe(320, 240)
    try:
        import esper
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.BasicComponents import (
            Transform, Light, MeshRenderer,
        )

        # ── Lighting shader id ──
        lighting_sid = None
        for sid_str, entry in ResourceManager.loaded_shader.items():
            if entry.get('name') == 'Lighting':
                lighting_sid = int(sid_str)
                break
        check("Lighting shader 已注册 (builtin)", lighting_sid is not None,
              str([e.get('name') for e in ResourceManager.loaded_shader.values()]))

        # ── 场景: 白纹理方块 (uColor 0.8) + 俯视相机 + 钉死环境光 ──
        # 注: SetEntityShader 会按新 shader 的 uniform 表重建材质 (set_new_shader),
        #     因此 uColor 必须在切 shader 之后重设 (协议: shader_protocol.md)
        probe.st.SetAmbientColor(*AMB)
        probe.st.SetLightingFallback(False)  # 数值钉死依赖 ambient; 回退开关单测见用例 7
        e_sq = probe.make_entity("lit", color=(0.8, 0.8, 0.8),
                                 position=(0, 0, 0), scale=4.0)
        probe.st.SetEntityShader(e_sq, lighting_sid)
        _mr0 = esper.component_for_entity(e_sq, MeshRenderer)
        ResourceManager.SetMaterialColor(_mr0.material_id, 0.8, 0.8, 0.8, 1.0)
        probe.set_topdown(half_h=10.0)
        probe.render()

        # ── 1. 环境光单独: 输出 = 0.8 × (0.2,0.1,0.05) ──
        print("── ambient only ──")
        px = probe.read_pixel(160, 120)
        check("ambient-only ⇒ (41,20,10)", probe.color_near(px, AMBIENT_ONLY, 5), str(px))

        # ── 材质参数: uShininess 进材质; 保留 uniform 不进材质 ──
        mr = esper.component_for_entity(e_sq, MeshRenderer)
        ud = ResourceManager.GetMaterial(mr.material_id).uniforms_data
        reserved_leak = [k for k in ('uAmbient', 'uCameraPos', 'uLightCount',
                                     'uLightDir', 'uLightColor',
                                     'uPointCount', 'uPointPos',
                                     'uPointColor', 'uPointRange') if k in ud]
        check("uShininess ∈ 材质; 保留 uniform 不进材质",
              ('uShininess' in ud) and not reserved_leak,
              f"shininess={'uShininess' in ud} leak={reserved_leak}")

        # ── 2. 平面光垂直向下 (Rx=+90°): 顶面 N·L=1, 镜面重合 → 饱和全亮 ──
        print("── directional light straight down ──")
        dl = Light(color_r=1.0, color_g=1.0, color_b=1.0, intensity=1.0)
        e_light = probe.st.AddEntity("sun", Transform(), dl)
        probe.st.SetEntityTransform(e_light, rotation_xyz=(1.5707963267948966, 0.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("垂直向下 → 全亮饱和 (ndl=1 + 镜面 0.25)", all(v >= 250 for v in px[:3]), str(px))

        # ── 3. 斜射 60° (Rx=π/3): ndl=0.866, H=(0,0.966,0.259) spec≈0.083 ──
        #    accum ≈ (0.2,0.1,0.05)+0.949 → 0.8× ⇒ (234,214,204)
        print("── light tilted 60° ──")
        probe.st.SetEntityTransform(e_light, rotation_xyz=(1.0471975511965976, 0.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("斜射 60° ⇒ (234,214,204) [含 Blinn-Phong 高光]",
              probe.color_near(px, (234, 214, 204), 10), str(px))

        # ── 4. 侧向 (Rx=0 → 光沿 -Z) 与背向 (Rx=-90° → 光向上): N·L=0 ⇒ 仅环境光 ──
        print("── side / back facing ──")
        probe.st.SetEntityTransform(e_light, rotation_xyz=(0.0, 0.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("侧向 (光沿 -Z) ⇒ 仅环境光 (高光被 step 拍死)",
              probe.color_near(px, AMBIENT_ONLY, 5), str(px))
        probe.st.SetEntityTransform(e_light, rotation_xyz=(-1.5707963267948966, 0.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("背向 (光向上, N·L<0) ⇒ 仅环境光",
              probe.color_near(px, AMBIENT_ONLY, 5), str(px))

        # ── 5. 颜色×强度: 白 ×0.5 向下 ⇒ 0.8×((0.2,0.1,0.05)+0.625) = (168,148,138) ──
        print("── intensity ──")
        probe.st.SetEntityTransform(e_light, rotation_xyz=(1.5707963267948966, 0.0, 0.0))
        dl.intensity = 0.5
        probe.render()
        px = probe.read_pixel(160, 120)
        check("白 光×0.5 向下 ⇒ (168,148,138)",
              probe.color_near(px, (168, 148, 138), 8), str(px))

        # ── 6. 双光源叠加: +红×0.5 向下 ⇒ r 饱和, g/b 不变 (255,148,138) ──
        print("── two lights ──")
        dl2 = Light(color_r=1.0, color_g=0.0, color_b=0.0, intensity=0.5)
        e_light2 = probe.st.AddEntity("red_sun", Transform(), dl2)
        probe.st.SetEntityTransform(e_light2, rotation_xyz=(1.5707963267948966, 0.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("红×0.5 叠加 ⇒ (255,148,138) [逐通道]", probe.color_near(px, (255, 148, 138), 8), str(px))
        check("场景含 2 盏平面光 (世界查询)",
              len(list(probe.st.GetAllEntitiesWithComponent(Light))) == 2)

        # ── 7. 点光 (Light.light_type="point"): att = (1 - d/range)² 三档 ──
        #    V=(0,1,0), 光源正上方: L=(0,1,0), ndl=1, H=(0,1,0)→spec=0.25
        #    accum = ambient + color·(1+0.25)·att; 输出 = 0.8 × accum
        print("── point light (attenuation) ──")
        probe.st.DeleteEntity(e_light)
        probe.st.DeleteEntity(e_light2)
        e_pt = probe.st.AddEntity(
            "bulb", Transform(),
            Light(light_type="point", color_r=1.0, color_g=1.0, color_b=1.0,
                  intensity=1.0, range=10.0))
        # d=5, range=10 → att=0.25: (0.2,0.1,0.05)+1.25×0.25 → ×0.8 = (105,84,74)
        probe.st.SetEntityTransform(e_pt, position_xyz=(0.0, 5.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("点光 d=5/r=10 (att=0.25) ⇒ (105,84,74)",
              probe.color_near(px, (105, 84, 74), 10), str(px))
        # d=7.5, range=10 → att=0.0625: (0.2,0.1,0.05)+1.25×0.0625 → ×0.8 = (57,36,26)
        probe.st.SetEntityTransform(e_pt, position_xyz=(0.0, 7.5, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("点光 d=7.5/r=10 (att=0.0625) ⇒ (57,36,26)",
              probe.color_near(px, (57, 36, 26), 8), str(px))
        # d=15 ≥ range=10 → att=0 ⇒ 仅环境光
        probe.st.SetEntityTransform(e_pt, position_xyz=(0.0, 15.0, 0.0))
        probe.render()
        px = probe.read_pixel(160, 120)
        check("点光 d=15 > r=10 (att=0) ⇒ 仅环境光 (41,20,10)",
              probe.color_near(px, AMBIENT_ONLY, 5), str(px))
        probe.st.DeleteEntity(e_pt)

        # ── 8. 无灯回退: fallback=ON 无任何光源 ⇒ 环境光强制满亮 0.8×1.0=204 ──
        print("── no-light fallback ──")
        probe.st.SetLightingFallback(True)
        probe.render()
        px = probe.read_pixel(160, 120)
        check("fallback=ON 无光源 ⇒ 满亮 (204,204,204)",
              probe.color_near(px, (204, 204, 204), 5), str(px))
        probe.st.SetLightingFallback(False)
        probe.render()
        px = probe.read_pixel(160, 120)
        check("fallback=OFF 无光源 ⇒ 回环境光 (41,20,10)",
              probe.color_near(px, AMBIENT_ONLY, 5), str(px))

        # ── 清场 ──
        probe.unregister(e_sq)
        probe.render()
        px = probe.read_pixel(160, 120)
        check("清场后回背景", probe.color_near(px, (13, 13, 20), 5), str(px))

    finally:
        probe.close()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
