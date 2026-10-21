"""
GL 像素测试 — 真实 GL 上下文端到端（探针 = 隐藏窗口 + OpenGLRenderer）。

锁定内容（rendering_protocol.md §验证体系）:
  1. 世界→像素映射金标准: 俯视相机 half_h=10, 320×240 ⇒ 1 单位 = 12px;
     x_px = 160 + 12·GLx, y_px = 120 + 12·GLz（GL -Z = 屏幕上方 = 编辑器 +Y 北向）
  2. 主色/材质 uColor → 像素（白纹理 × uColor）
  3. 深度测试（GL_LESS; 俯视时 GL +Y 更近）
  4. 可见性命令: EntityVisibilityCommand / EntityRenderVisibleCommand
  5. 纹理路径: Checkerboard 明暗块 + 动态纹理 (CreateTextureFromArray → TextureUpdateCommand 就地重传)
     —— 即媒体播放链的 GL 层回归
  6. SetClearColorCommand / ResizeCommand / 高亮后处理注册-注销 GL 冒烟
  7. 材质混合: Material.blend=alpha → 标准 alpha 混合 + 透明由远到近排序 (painter)

运行: python Utils/Dev/test_runner.py --only gl_pixels
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

BG = (13, 13, 20)       # 探针默认清屏色 0.05/0.05/0.08
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def px(x_gl: float, z_gl: float) -> tuple[int, int]:
    """金标准映射: half_h=10 / 320×240 ⇒ 12px/单位（见文件头）。"""
    return (int(round(160 + 12 * x_gl)), int(round(120 + 12 * z_gl)))


def main() -> int:
    print("=" * 60)
    print("GL pixels — probe end-to-end (mapping / depth / visibility / texture)")
    print("=" * 60)

    import numpy as np
    from Application.Core.Renderer.RenderCommand import (
        EntityRenderVisibleCommand, EntityVisibilityCommand, ResizeCommand,
        SetClearColorCommand, TextureUpdateCommand,
    )

    probe = GlProbe(320, 240)
    try:
        # ── 1. 映射 + 主色 ──
        print("── mapping & color ──")
        e_r = probe.make_entity("red", color=(1, 0, 0), position=(0, 0, 0), scale=4.0)
        e_g = probe.make_entity("green", color=(0, 1, 0), position=(0, 0, -4.0), scale=4.0)
        e_b = probe.make_entity("blue", color=(0, 0, 1), position=(4.0, 0, 0), scale=4.0)
        probe.set_topdown(half_h=10.0)
        probe.render()

        check("background corner", probe.color_near(probe.read_pixel(5, 5), BG, 4),
              str(probe.read_pixel(5, 5)))
        check("red at center (0,0)", probe.color_near(probe.read_pixel(*px(0, 0)), RED),
              str(probe.read_pixel(*px(0, 0))))
        # 注: 红块 (scale4, 跨 y 像素 72..168) 与绿/蓝块在等深重叠区由先绘者胜 —
        # 采样各块“无重叠可见区”的中心: 绿可见区 y≈24..70 → 取 (160,48); 蓝可见区 x≈208..256 → 取 (226,120)
        check("green at GL z=-4 (可见区) ⇒ 屏幕上方",
              probe.color_near(probe.read_pixel(160, 48), GREEN),
              str(probe.read_pixel(160, 48)))
        check("blue at GL x=+4 (可见区) ⇒ 屏幕右侧",
              probe.color_near(probe.read_pixel(226, 120), BLUE),
              str(probe.read_pixel(226, 120)))
        check("outside red footprint = bg",
              probe.color_near(probe.read_pixel(160 - 70, 120), BG, 4),
              str(probe.read_pixel(90, 120)))

        for e in (e_r, e_g, e_b):
            probe.unregister(e)
        probe.render()
        check("unregister ⇒ center 回背景", probe.color_near(probe.read_pixel(160, 120), BG, 4),
              str(probe.read_pixel(160, 120)))

        # ── 2. 深度测试（俯视: GL +Y 更近） ──
        print("── depth ──")
        e_front = probe.make_entity("front", color=(1, 0, 0), position=(0, 0.3, 0), scale=4.0)
        e_back = probe.make_entity("back", color=(0, 0, 1), position=(0, -0.3, 0), scale=4.0)
        probe.render()
        check("nearer (y=+0.3) wins", probe.color_near(probe.read_pixel(160, 120), RED),
              str(probe.read_pixel(160, 120)))

        probe.st.SetEntityTransform(e_front, position_xyz=(0, -0.3, 0))
        probe.st.SetEntityTransform(e_back, position_xyz=(0, 0.3, 0))
        probe.render()
        check("swap heights ⇒ blue wins (即时生效, 无需重注册)",
              probe.color_near(probe.read_pixel(160, 120), BLUE),
              str(probe.read_pixel(160, 120)))
        probe.unregister(e_front)
        probe.unregister(e_back)
        probe.render()

        # ── 3. 可见性命令 ──
        print("── visibility commands ──")
        e_v = probe.make_entity("vis", color=(1, 0, 0), position=(0, 0, 0), scale=4.0)
        probe.render()
        check("visible by default", probe.color_near(probe.read_pixel(160, 120), RED))

        probe.enqueue(EntityVisibilityCommand(e_v, False))
        probe.render()
        check("EntityVisibilityCommand(False) hides", probe.color_near(probe.read_pixel(160, 120), BG, 4))
        probe.enqueue(EntityVisibilityCommand(e_v, True))
        probe.render()
        check("EntityVisibilityCommand(True) shows", probe.color_near(probe.read_pixel(160, 120), RED))

        probe.enqueue(EntityRenderVisibleCommand(e_v, False))
        probe.render()
        check("EntityRenderVisibleCommand(False) hides", probe.color_near(probe.read_pixel(160, 120), BG, 4))
        probe.enqueue(EntityRenderVisibleCommand(e_v, True))
        probe.render()
        check("EntityRenderVisibleCommand(True) shows", probe.color_near(probe.read_pixel(160, 120), RED))
        probe.unregister(e_v)
        probe.render()

        # ── 4. 纹理: Checkerboard 明暗块 ──
        print("── texture (checkerboard) ──")
        e_tex = probe.make_entity("checker", texture_name="Checkerboard",
                                  position=(0, 0, 0), scale=4.0)
        probe.render()
        vals = [probe.read_pixel(x, 120)[0] for x in range(116, 206, 2)]
        has_light = any(v > 150 for v in vals)
        has_dark = any(v < 100 for v in vals)
        check("checkerboard shows light+dark blocks", has_light and has_dark,
              f"light={has_light} dark={has_dark} sample={vals[:8]}")
        probe.unregister(e_tex)
        probe.render()

        # ── 5. 动态纹理（媒体链 GL 回归） ──
        print("── dynamic texture (media chain) ──")
        from Application.Resource.ResourceManager import ResourceManager

        red_img = np.full((4, 4, 4), (255, 0, 0, 255), dtype=np.uint8)
        tid = ResourceManager.CreateTextureFromArray("probe:dynamic_red", red_img)
        e_dyn = probe.make_entity("dynamic", color=(1, 1, 1), texture_name=None,
                                  position=(0, 0, 0), scale=4.0)
        from Application.Core.Scene.BasicComponents import MeshRenderer
        import esper
        mr = esper.component_for_entity(e_dyn, MeshRenderer)
        mat = ResourceManager.GetMaterial(mr.material_id)
        mat.texture_id_list[0] = tid
        mat.mark_modified()
        probe.render()
        check("dynamic texture initial frame = red",
              probe.color_near(probe.read_pixel(160, 120), RED),
              str(probe.read_pixel(160, 120)))
        check("texture registered in GL context",
              (tid in probe.renderer.registered_textures
               and probe.renderer.registered_textures[tid].gl_handle is not None))

        green_img = np.full((4, 4, 4), (0, 255, 0, 255), dtype=np.uint8)
        probe.enqueue(TextureUpdateCommand(tid, green_img, 4, 4, 4))
        probe.render()
        check("TextureUpdateCommand 就地重传 ⇒ green（媒体回归）",
              probe.color_near(probe.read_pixel(160, 120), GREEN),
              str(probe.read_pixel(160, 120)))
        probe.unregister(e_dyn)
        probe.render()

        # ── 6. 清屏色命令 ──
        print("── clear color ──")
        probe.enqueue(SetClearColorCommand(0.3, 0.2, 0.1, 1.0))
        probe.render()
        expect = (int(0.3 * 255), int(0.2 * 255), int(0.1 * 255))
        check("SetClearColorCommand → 背景像素", probe.color_near(probe.read_pixel(5, 5), expect, 4),
              f"{probe.read_pixel(5, 5)} vs {expect}")
        probe.set_clear_color(0.05, 0.05, 0.08, 1.0)
        probe.render()

        # ── 7. 高亮后处理 GL 冒烟 ──
        print("── highlight postprocess smoke ──")
        from Application.Core.Renderer.RenderCommand import (
            RegisterHighlightEffectCommand, UnregisterHighlightEffectCommand,
            UpdateHighlightConfigCommand, UpdateHighlightSelectionCommand,
        )
        from Application.Core.Renderer.PostProcess import HighlightEffectConfig

        smoke_ok = True
        try:
            probe.enqueue(RegisterHighlightEffectCommand(HighlightEffectConfig()))
            probe.render()
            probe.enqueue(UpdateHighlightSelectionCommand({1}))
            probe.enqueue(UpdateHighlightConfigCommand(color=(1.0, 0.5, 0.0), width=4, xray=True))
            probe.render()
            probe.enqueue(UnregisterHighlightEffectCommand())
            probe.render()
        except Exception as e:  # noqa: BLE001
            smoke_ok = False
            print(f"    highlight smoke exception: {type(e).__name__}: {e}")
        check("highlight register/update/unregister 无异常", smoke_ok)

        # ── 8. ResizeCommand ──
        print("── resize ──")
        probe.enqueue(ResizeCommand(160, 120))
        probe.render()
        check("resize ⇒ viewport 160x120",
              (probe.renderer.viewport_width, probe.renderer.viewport_height) == (160, 120),
              f"{probe.renderer.viewport_width}x{probe.renderer.viewport_height}")
        probe.enqueue(ResizeCommand(320, 240))
        probe.render()
        check("resize back ⇒ 320x240",
              (probe.renderer.viewport_width, probe.renderer.viewport_height) == (320, 240))

        # ── 9. 材质混合 (Material.blend: opaque / alpha) ──
        print("── material blend ──")
        from Application.Resource.ResourceManager import ResourceManager as _RM

        def _set_blend(eid, mode):
            import esper as _esper
            from Application.Core.Scene.BasicComponents import MeshRenderer as _MR
            _mr = _esper.component_for_entity(eid, _MR)
            _RM.GetMaterial(_mr.material_id).blend = mode

        # ① alpha(0.5 绿) 叠在不透明红上 → 0.5·G + 0.5·R = (127,127,0)
        #    俯视 GL +Y 更近 — 绿在 y=1.0 位于红(y=0)前方, 由透明阶段后绘
        e_base = probe.make_entity("mbase", color=(1, 0, 0), position=(0, 0, 0), scale=4.0)
        e_over = probe.make_entity("mover", color=(0, 1, 0, 0.5), position=(0, 1.0, 0), scale=4.0)
        _set_blend(e_over, "alpha")
        probe.render()
        px_c = probe.read_pixel(160, 120)
        check("alpha 0.5 green over opaque red ⇒ (127,127,0)",
              probe.color_near(px_c, (127, 127, 0), 8), str(px_c))

        # ② alpha(0.5 绿) 叠在背景上 → 0.5·G + 0.5·bg = (7,134,10)
        probe.st.SetEntityTransform(e_over, position_xyz=(4.0, 1.0, 0))
        probe.render()
        px_c = probe.read_pixel(*px(4, 0))
        check("alpha 0.5 green over background ⇒ (7,134,10)",
              probe.color_near(px_c, (7, 134, 10), 8), str(px_c))
        # ★ e_over 左边缘恰好压在 x=160 (中心列) — 排序用例前必须离场
        probe.unregister(e_over)
        probe.render()

        # ③ 透明由远到近: 底=不透明红(y=0), 中=绿 alpha(y=0.5), 顶=红 alpha(y=1.0)
        #    正确顺序(远→近: 绿,红): 0.5R + 0.5·(0.5G + 0.5R) = (191,64,0)
        #    若顺序颠倒(近者先画): (64,191,0)
        e_mid = probe.make_entity("mmid", color=(0, 1, 0, 0.5), position=(0, 0.5, 0), scale=4.0)
        e_top = probe.make_entity("mtop", color=(1, 0, 0, 0.5), position=(0, 1.0, 0), scale=4.0)
        _set_blend(e_mid, "alpha")
        _set_blend(e_top, "alpha")
        probe.render()
        px_c = probe.read_pixel(160, 120)
        ok_order = probe.color_near(px_c, (191, 64, 0), 8)
        wrong_order = probe.color_near(px_c, (64, 191, 0), 8)
        check("透明由远到近 (近红最后混合) ⇒ (191,64,0)", ok_order and not wrong_order, str(px_c))

        # ④ 状态恢复: 全部移除后, 不透明方块仍为纯色 (混合状态不泄漏到下一帧)
        for _e in (e_base, e_mid, e_top):
            probe.unregister(_e)
        probe.render()
        e_pure = probe.make_entity("mpure", color=(1, 0, 0), position=(0, 0, 0), scale=4.0)
        probe.render()
        check("混合实体移除后 不透明纯色无损",
              probe.color_near(probe.read_pixel(160, 120), RED), str(probe.read_pixel(160, 120)))
        probe.unregister(e_pure)
        probe.render()

    finally:
        probe.close()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
