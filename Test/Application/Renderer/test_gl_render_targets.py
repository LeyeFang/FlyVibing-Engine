"""
GL 渲染目标测试 — RT (FBO) 创建/采样/销毁/恢复（真实 GL, 探针）。

锁定内容 (协议: Doc/Dev/rendering_protocol.md §7):
  1. create_render_target: FBO 完整 + rt_id 即纹理 ID
     (registered_textures + loaded_texture 条目 "rt:<id>")
  2. SetSceneTargetCommand: 实体渲染进入 RT; 屏幕帧不再被写入 (stale 保留)
  3. RT 内容朝向与屏幕一致 (GL 底左原点 — 与 read_pixel 的 Y 翻转互为镜像)
  4. 屏幕恢复: target 回 0 后实体重新上屏
  5. RT 纹理被材质直接采样 (texture_id_list = rt_id)
  6. DestroyRenderTargetCommand: GL 条目 + 两个注册表清理; 正被用作
     场景目标时自动回退屏幕
  7. with_depth=False 也完整; 同 id 重复创建 = 重建 (单条目)

运行: python Utils/Dev/test_runner.py --only gl_render_targets
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

BG = (13, 13, 20)
RED = (255, 0, 0)
RT_ID = 7201
RT2_ID = 7202
RT3_ID = 7203


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def read_rt(rt: dict, x: int, y: int) -> tuple[int, int, int, int]:
    """读 RT 颜色附件 (x,y 为 GL 底左坐标 — 不做屏幕式翻转)。"""
    from OpenGL import GL as gl
    import numpy as np
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, rt["fbo"])
    gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
    buf = np.empty((1, 1, 4), dtype=np.uint8)
    gl.glReadPixels(int(x), int(y), 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, buf)
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
    return tuple(int(v) for v in buf[0, 0])


def main() -> int:
    print("=" * 60)
    print("GL render targets — RT lifecycle + sampling + restore (probe)")
    print("=" * 60)

    probe = GlProbe(320, 240)
    try:
        from Application.Core.Renderer.RenderCommand import SetSceneTargetCommand
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.BasicComponents import MeshRenderer
        import esper

        probe.set_topdown(half_h=10.0)

        # ── 0. 基线: 空场景一帧 (屏幕 = 背景) ──
        probe.render()
        check("基线: 屏幕为背景",
              probe.color_near(probe.read_pixel(160, 120), BG, 4),
              str(probe.read_pixel(160, 120)))

        # ── 1. 创建 RT (128×96 ≈ 0.4 倍窗口) ──
        print("── create ──")
        probe.renderer.create_render_target(RT_ID, 128, 96)
        rt = probe.renderer._targets.get(RT_ID)
        ok_gl = rt is not None and rt["fbo"] > 0 and rt["tex"] > 0 and rt["depth_rb"] > 0
        check("RT 记录 + FBO/纹理/深度 均创建", ok_gl, str(rt))
        tex_entry = probe.renderer.registered_textures.get(RT_ID)
        check("rt_id 即纹理 ID (registered_textures.gl_handle)",
              tex_entry is not None and tex_entry.gl_handle == rt["tex"])
        res_entry = ResourceManager.loaded_texture.get(str(RT_ID))
        check("loaded_texture 条目 'rt:7201'",
              res_entry is not None and res_entry.get("name") == f"rt:{RT_ID}",
              str(res_entry))

        # ── 2. 场景目标 = RT: 实体进 RT, 屏幕保留 stale ──
        print("── scene target = RT ──")
        # 方块中心 GL z=-5 → 屏幕顶左 y=120+12·(-5)=60; RT 0.4 倍缩放:
        # GL 底左坐标 x=64, y=(240-60)·0.4=72
        e_pix = probe.make_entity("rtpix", color=(1, 0, 0), position=(0, 0, -5.0), scale=4.0)
        probe.enqueue(SetSceneTargetCommand(RT_ID))
        probe.render()
        px_in = read_rt(rt, 64, 72)
        check("实体进 RT (镜像点 (64,72)=红) — 朝向钉死", probe.color_near(px_in, RED, 10), str(px_in))
        px_mirror = read_rt(rt, 64, 24)
        check("RT 镜像点 (64,24) 为背景 (非上下颠倒)", probe.color_near(px_mirror, BG, 6), str(px_mirror))
        screen_px = probe.read_pixel(160, 60)
        check("RT 帧不写屏幕 (上一帧背景保留)", probe.color_near(screen_px, BG, 4), str(screen_px))

        # ── 3. 居中方块重渲 RT → RT 中心=红 (供采样) ──
        probe.st.SetEntityTransform(e_pix, position_xyz=(0, 0, 0))
        probe.render()
        px_center = read_rt(rt, 64, 48)
        check("RT 中心跟随实体 (64,48)=红", probe.color_near(px_center, RED, 10), str(px_center))

        # ── 4. 恢复屏幕 ──
        print("── restore screen ──")
        probe.enqueue(SetSceneTargetCommand(0))
        probe.render()
        check("target 回 0 ⇒ 实体现于屏幕 (160,120)=红",
              probe.color_near(probe.read_pixel(160, 120), RED), str(probe.read_pixel(160, 120)))

        # ── 5. RT 纹理被材质直接采样 ──
        print("── sample RT as texture ──")
        e_disp = probe.make_entity("rtdisp", color=(1, 1, 1), position=(4.0, 0, 0), scale=4.0)
        probe.st.SetEntityTexture(e_disp, RT_ID, slot=0)
        probe.render()
        px_s = probe.read_pixel(160 + 48, 120)
        check("材质 texture_id_list=[7201] ⇒ 屏上方块显示 RT 内容 (红)",
              probe.color_near(px_s, RED, 12), str(px_s))

        # ── 6. 销毁: 注册表清理 + 场景目标回退 ──
        print("── destroy ──")
        probe.enqueue(SetSceneTargetCommand(RT_ID))
        probe.render()
        probe.renderer.destroy_render_target(RT_ID)
        check("targets 条目已清", probe.renderer._targets.get(RT_ID) is None)
        check("registered_textures 条目已清", RT_ID not in probe.renderer.registered_textures)
        check("loaded_texture 条目已清", str(RT_ID) not in ResourceManager.loaded_texture)
        check("销毁活跃场景目标 ⇒ _scene_target_id 回退 0",
              probe.renderer._scene_target_id == 0, str(probe.renderer._scene_target_id))
        probe.render()
        check("回退后实体正常上屏", probe.color_near(probe.read_pixel(160, 120), RED))

        # ── 7. with_depth=False + 重建语义 ──
        print("── depth-less + recreate ──")
        probe.renderer.create_render_target(RT2_ID, 64, 64, with_depth=False)
        rt2 = probe.renderer._targets.get(RT2_ID)
        check("with_depth=False: depth_rb=0 且 FBO 完整", rt2 is not None and rt2["depth_rb"] == 0)
        probe.renderer.create_render_target(RT3_ID, 32, 32)
        first_record = probe.renderer._targets.get(RT3_ID)
        probe.renderer.create_render_target(RT3_ID, 32, 32)
        rt3 = probe.renderer._targets.get(RT3_ID)
        check("同 id 重复创建 = 重建 (单条目, 记录被替换)",
              len(probe.renderer._targets.targets) == 2
              and rt3 is not None and rt3 is not first_record
              and rt3["fbo"] > 0 and rt3["tex"] > 0)

        # ── 8. 非法目标 ──
        try:
            probe.renderer.set_scene_target(999999)
            invalid_ok = False
        except ValueError:
            invalid_ok = True
        check("set_scene_target(不存在 id) ⇒ ValueError", invalid_ok)

        # 清场
        probe.renderer.destroy_render_target(RT2_ID)
        probe.renderer.destroy_render_target(RT3_ID)
        probe.unregister(e_pix)
        probe.unregister(e_disp)
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
