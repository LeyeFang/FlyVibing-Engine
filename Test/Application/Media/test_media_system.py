"""
MediaSystem 测试 — 解码 + 播放推进（无头, 显式 advance 驱动; 无编辑器 tick）。

覆盖:
  1. load_media: GIF 多帧 / 静态图单帧（MGE_TEST_TMP 沙箱内生成）
  2. advance 懒初始化: 动态纹理注册 + 材质槽绑定（SetEntityTexture）
  3. 播放时钟: 换帧 / playing=False 冻结 / speed 倍速 / 循环稳定
  4. 引擎帧去重: 同一 stamp 多次 advance 只推进一次
  5. 错误遏制: 源文件缺失 → 单播放器报错, 不抛异常

运行: python Utils/Dev/test_runner.py --only media_system
"""
# TIER: core

from __future__ import annotations

import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

ROOT = os.path.dirname(_d)
GIF_PATH = os.path.join(ROOT, "Resource", "Textures", "demo_animation.gif")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _MediaTestApp:
    """最小引擎替身（无渲染器 — MediaSystem 无头路径）。"""
    renderer = None


class _TickApp:
    """带引擎帧时间戳的替身（advance 去重语义）。"""
    renderer = None
    scene = None
    stamp = -1.0

    @classmethod
    def get_elapsed_time(cls) -> float:
        return cls.stamp


def main() -> int:
    print("=" * 60)
    print("MediaSystem — decode / advance (headless, node-driven)")
    print("=" * 60)

    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_MediaTestApp)
    SceneManager.Init(_MediaTestApp)
    _MediaTestApp.scene = SceneManager._state_for(_MediaTestApp.__name__)

    import esper
    import numpy as np
    from Application.Core import Media as MediaSystem
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, MediaPlayer

    # ── 1. 解码 ──
    print("── decode ──")
    clip = MediaSystem.load_media(GIF_PATH)
    check("gif frames == 10", len(clip.frames) == 10, str(len(clip.frames)))
    check("gif size 128x128", clip.width == 128 and clip.height == 128,
          f"{clip.width}x{clip.height}")
    check("durations all > 0", all(d > 0 for d in clip.durations), str(clip.durations[:3]))
    f0 = clip.frames[0]
    check("frame RGBA uint8 (128,128,4)",
          f0.shape == (128, 128, 4) and f0.dtype == np.uint8, f"{f0.shape} {f0.dtype}")

    tmp = os.environ.get("MGE_TEST_TMP") or tempfile.mkdtemp(prefix="mge_media_")
    from PIL import Image
    png_path = os.path.join(tmp, "static_red.png")
    Image.new("RGBA", (8, 6), (255, 0, 0, 255)).save(png_path)
    clip2 = MediaSystem.load_media(png_path)
    check("static image 1 frame", len(clip2.frames) == 1, str(len(clip2.frames)))
    check("static size 8x6", (clip2.width, clip2.height) == (8, 6),
          f"{clip2.width}x{clip2.height}")
    check("static dtype uint8", clip2.frames[0].dtype == np.uint8)

    # ── 2. 首帧 advance: 纹理注册 + 材质绑定 ──
    print("── lazy init ──")
    eid = esper.create_entity()
    esper.add_component(eid, Transform())
    mr = MeshRenderer()
    esper.add_component(eid, mr)
    mp = MediaPlayer(source=GIF_PATH)
    esper.add_component(eid, mp)

    MediaSystem.advance(_MediaTestApp, eid, 0.0)
    snap = MediaSystem.snapshot(_MediaTestApp)
    players = [p for p in snap["players"] if p["entity"] == eid]
    check("player registered", len(players) == 1, str(snap))
    pl = players[0] if players else {}
    check("no error", pl.get("error") == "", str(pl.get("error")))
    check("frames = 10", pl.get("frames") == 10, str(pl.get("frames")))
    tid = pl.get("texture_id", 0)
    check("dynamic texture created", tid > 0, str(tid))
    entry = ResourceManager.loaded_texture.get(str(tid), {})
    check("texture named media:*", str(entry.get("name", "")).startswith("media:"),
          str(entry.get("name")))
    mr = esper.component_for_entity(eid, MeshRenderer)   # 可能已被 clone
    mat = ResourceManager.GetMaterial(mr.material_id)
    check("material slot0 bound", bool(mat.texture_id_list) and mat.texture_id_list[0] == tid,
          str(getattr(mat, "texture_id_list", None)))

    # ── 3. 播放时钟 ──
    print("── playback clock ──")
    dur0 = clip.durations[0]
    MediaSystem.advance(_MediaTestApp, eid, dur0 * 1.1)
    fr = MediaSystem.snapshot(_MediaTestApp)["players"][0]["frame"]
    check("advances to frame 1", fr == 1, str(fr))

    mp.playing = False
    fr_hold = MediaSystem.snapshot(_MediaTestApp)["players"][0]["frame"]
    MediaSystem.advance(_MediaTestApp, eid, 5.0)
    fr_hold2 = MediaSystem.snapshot(_MediaTestApp)["players"][0]["frame"]
    check("playing=False holds frame", fr_hold2 == fr_hold, f"{fr_hold}->{fr_hold2}")

    mp.playing = True
    mp.speed = 2.0
    before = fr_hold2
    MediaSystem.advance(_MediaTestApp, eid, dur0 * 1.2)
    after = MediaSystem.snapshot(_MediaTestApp)["players"][0]["frame"]
    check("speed=2 advances >= 2", (after - before) % 10 >= 2, f"{before}->{after}")

    for _ in range(40):
        MediaSystem.advance(_MediaTestApp, eid, 0.05)
    after2 = MediaSystem.snapshot(_MediaTestApp)["players"][0]["frame"]
    check("loop stays in range", 0 <= after2 < 10, str(after2))

    # ── 4. 引擎帧去重（多驱动者不加速）──
    print("── frame dedup ──")
    eid3 = esper.create_entity()
    esper.add_component(eid3, Transform())
    esper.add_component(eid3, MeshRenderer())
    esper.add_component(eid3, MediaPlayer(source=GIF_PATH))
    MediaSystem.advance(_TickApp, eid3, 0.0)          # stamp=-1: 初始化
    _TickApp.stamp = 0.0
    MediaSystem.advance(_TickApp, eid3, dur0 * 1.2)   # 帧内第一个驱动者
    fr_a = MediaSystem.snapshot(_TickApp)["players"][0]["frame"]
    MediaSystem.advance(_TickApp, eid3, dur0 * 1.2)   # 同 stamp 第二驱动者 → 去重
    fr_b = MediaSystem.snapshot(_TickApp)["players"][0]["frame"]
    check("same-stamp dedup (single step)", fr_a == 1 and fr_b == fr_a, f"{fr_a}->{fr_b}")
    _TickApp.stamp = 1.0
    MediaSystem.advance(_TickApp, eid3, dur0 * 1.2)   # 新帧 → 继续推进
    fr_c = MediaSystem.snapshot(_TickApp)["players"][0]["frame"]
    check("next stamp advances", fr_c == fr_a + 1, f"{fr_a}->{fr_c}")

    # ── 5. 错误遏制 ──
    print("── error containment ──")
    eid2 = esper.create_entity()
    esper.add_component(eid2, Transform())
    esper.add_component(eid2, MeshRenderer())
    esper.add_component(eid2, MediaPlayer(source="does/not/exist.gif"))
    MediaSystem.advance(_MediaTestApp, eid2, 0.0)   # 不得抛异常
    snap2 = MediaSystem.snapshot(_MediaTestApp)
    p2 = [p for p in snap2["players"] if p["entity"] == eid2]
    check("bad source: player has error", bool(p2) and p2[0]["error"] != "", str(p2))
    p1 = [p for p in snap2["players"] if p["entity"] == eid]
    check("good player unaffected", bool(p1) and p1[0]["error"] == "", str(p1))

    # ── 6. 清理 ──
    MediaSystem.reset()
    check("reset clears players",
          MediaSystem.snapshot(_MediaTestApp)["players"] == [],
          str(MediaSystem.snapshot(_MediaTestApp)))
    for e in (eid, eid2, eid3):
        try:
            esper.delete_entity(e)
        except Exception:  # noqa: BLE001
            pass

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
