"""
MediaSystem — 动态媒体播放库（GIF/图像; 协议: `Doc/Dev/media_protocol.md`）。

架构（v2, 2026-10-06 — 用户决议）:
  - **无独立循环**: 本模块不自我推进; 由节点 `ShowMedia` 在运行时 (PIE 的
    GameRuntime → RuntimeNodeLayer 逻辑线程) 逐帧调用 `advance(engine, eid, dt)`。
  - **编辑器侧 = 模板**: MediaPlayer 组件只是参数声明; 不在图里接 ShowMedia → 不播放。
  - **PIE 由 GameRuntime 唯一控制**: 纹理创建/上传目标 = engine.scene / engine.renderer
    (即 GameRuntime 自己的场景视图与渲染器)。

职责边界:
  - `MediaPlayer` 组件: 可序列化参数 (source/playing/loop/speed/fit);
  - 本模块: 帧解码缓存 + 播放时钟 + 动态纹理协调; 错误遏制（单源失败不炸帧循环）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_MIN_FRAME_DT = 0.02  # 最小帧时长（防 GIF 元数据 0 时长死循环）
_NO_COMP = "no MediaPlayer component"

# ═══════════════════════════════════════════════════════════════
# 解码（Pillow — GIF 全帧 / 静态图单帧; (path, mtime) 缓存）
# ═══════════════════════════════════════════════════════════════

@dataclass
class MediaClip:
    """预解码媒体片段: RGBA 帧 + 每帧时长（秒）。静态图 = 单帧。"""
    width: int
    height: int
    frames: list = field(default_factory=list)
    durations: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.durations) or 1e-6


_clip_cache: dict[tuple, MediaClip] = {}


def load_media(path: str) -> MediaClip:
    """Pillow 解码 GIF（多帧 seek）/ 静态图（单帧）→ MediaClip。"""
    from PIL import Image
    import numpy as np

    key = (os.path.abspath(path), os.stat(path).st_mtime)
    clip = _clip_cache.get(key)
    if clip is not None:
        return clip

    im = Image.open(path)
    frames: list = []
    durations: list = []
    if int(getattr(im, "n_frames", 1) or 1) > 1:
        try:
            while True:
                frames.append(np.array(im.convert("RGBA"), dtype=np.uint8))
                durations.append(max(_MIN_FRAME_DT,
                                     float(im.info.get("duration", 100)) / 1000.0))
                im.seek(im.tell() + 1)
        except EOFError:
            pass
    else:
        frames.append(np.array(im.convert("RGBA"), dtype=np.uint8))
        durations.append(1.0)  # 静态图: 恒定单帧, 时钟不推进
    if not frames:
        raise ValueError(f"媒体无有效帧: {path}")

    clip = MediaClip(width=frames[0].shape[1], height=frames[0].shape[0],
                     frames=frames, durations=durations)
    _clip_cache[key] = clip
    return clip


# ═══════════════════════════════════════════════════════════════
# 播放器状态（运行期; 不序列化）
# ═══════════════════════════════════════════════════════════════

@dataclass
class _Player:
    source: str = ""
    clip: "MediaClip | None" = None
    texture_id: int = 0
    slot: int = 0
    frame: int = 0
    acc: float = 0.0
    error: str = ""
    stamp: float | None = None   # 引擎帧时间戳（多驱动去重）


_players: dict[tuple, _Player] = {}


def _engine_key(engine) -> str:
    return getattr(engine, "__name__", type(engine).__name__)


def _resolve_source(source: str) -> str:
    """CWD 相对/绝对路径解析（builtin 资源约定: 相对仓库根）。"""
    if os.path.isabs(source) or os.path.exists(source):
        return source
    return os.path.join(os.getcwd(), source)


def _engine_stamp(engine):
    """引擎帧时间戳（可缺省 — 测试替身无 get_elapsed_time 时返回 None 表示不去重）。"""
    fn = getattr(engine, "get_elapsed_time", None)
    if not callable(fn):
        return None
    try:
        return float(fn())
    except Exception:  # noqa: BLE001
        return None


# ═══════════════════════════════════════════════════════════════
# 核心: 单实体推进（节点 ShowMedia 每帧调用; 无渲染器时仅推进 CPU 侧）
# ═══════════════════════════════════════════════════════════════

def advance(engine, eid: int, dt: float) -> None:
    """推进实体 eid 的媒体播放（懒加载 → 时钟换帧 → 上传）。

    幂等去重: 同一引擎帧内多次调用只推进一次（多个 ShowMedia 驱动同一实体不加速）。
    """
    if engine is None:
        return
    key = (_engine_key(engine), int(eid))

    try:
        import esper
        from Application.Core.Scene.BasicComponents import MediaPlayer
        comp = esper.component_for_entity(eid, MediaPlayer)
    except KeyError:
        pl = _players.get(key)
        if pl is None or pl.error != _NO_COMP:
            _players[key] = _Player(error=_NO_COMP)
            print(f"[Media] entity #{eid} 无 MediaPlayer 组件（或实体不存在） — skipped")
        return
    except Exception:  # noqa: BLE001
        return

    pl = _players.get(key)
    if pl is not None and pl.error == _NO_COMP:
        pl = None  # 组件后补 → 重新初始化
    if pl is None or pl.source != comp.source:
        pl = _Player(source=str(comp.source or ""))
        _players[key] = pl

    # ── 引擎帧内去重（stamp 相同 = 同一帧的第二个驱动者）──
    stamp = _engine_stamp(engine)
    if stamp is not None and pl.stamp is not None and stamp == pl.stamp:
        return
    pl.stamp = stamp

    # ── 懒初始化: 解码 → 动态纹理 → 材质绑定（错误遏制: 报一次, 停该播放器）──
    if pl.clip is None and not pl.error and pl.source:
        try:
            pl.clip = load_media(_resolve_source(pl.source))
            if pl.texture_id == 0:
                from Application.Resource.ResourceManager import ResourceManager
                pl.texture_id = ResourceManager.CreateTextureFromArray(
                    f"media:{os.path.basename(pl.source)}",
                    pl.clip.frames[0], file_path=pl.source)
            scene = getattr(engine, "scene", None)
            if scene is not None:
                scene.SetEntityTexture(eid, pl.texture_id, slot=pl.slot)
            _push_frame(engine, pl)     # 首帧上传（绑定/注册在同一引擎帧内先于绘制）
            print(f"[Media] '{os.path.basename(pl.source)}' → texture#{pl.texture_id} "
                  f"({len(pl.clip.frames)} frames, {pl.clip.width}x{pl.clip.height})")
        except Exception as e:  # noqa: BLE001 — 媒体错误不炸帧循环
            pl.error = f"{type(e).__name__}: {e}"
            print(f"[Media] '{pl.source}' load failed: {pl.error}")
    if not pl.source and not pl.error:
        pl.error = "empty source"
    if pl.error or pl.clip is None:
        return

    # ── 播放时钟: 累积换帧 (speed 倍速; loop 绕回; 静态图不推进) ──
    if bool(getattr(comp, "playing", True)) and len(pl.clip.frames) > 1:
        speed = max(0.0, float(getattr(comp, "speed", 1.0) or 1.0))
        pl.acc += max(0.0, float(dt)) * speed
        advanced = False
        n_frames = len(pl.clip.frames)
        while True:
            dur = pl.clip.durations[pl.frame % len(pl.clip.durations)]
            if pl.acc < dur:
                break
            pl.acc -= dur
            nxt = pl.frame + 1
            if nxt >= n_frames:
                if bool(getattr(comp, "loop", True)):
                    nxt = 0
                else:
                    nxt = n_frames - 1   # 停在末帧
                    pl.acc = 0.0
                    advanced = True
                    break
            pl.frame = nxt
            advanced = True
        if advanced:
            _push_frame(engine, pl)


def _push_frame(engine, pl: _Player) -> None:
    """enqueue 整帧上传（宿主渲染线程执行; 无渲染器=无头时跳过）。"""
    renderer = getattr(engine, "renderer", None)
    if renderer is None:
        return
    from Application.Core.Renderer.RenderCommand import TextureUpdateCommand
    img = pl.clip.frames[pl.frame % len(pl.clip.frames)]
    try:
        renderer.enqueue(TextureUpdateCommand(
            texture_id=pl.texture_id, image_data=img,
            width=pl.clip.width, height=pl.clip.height, channels=4))
    except Exception as e:  # noqa: BLE001
        pl.error = f"enqueue failed: {type(e).__name__}: {e}"
        print(f"[Media] texture update enqueue failed: {pl.error}")


# ═══════════════════════════════════════════════════════════════
# 诊断 / 测试辅助
# ═══════════════════════════════════════════════════════════════

def snapshot(engine=None) -> dict:
    """播放器状态快照（测试/调试）。"""
    out = []
    for (ekey, eid), pl in _players.items():
        if engine is not None and ekey != _engine_key(engine):
            continue
        out.append({
            "engine": ekey, "entity": eid, "source": pl.source,
            "frame": pl.frame, "texture_id": pl.texture_id,
            "frames": 0 if pl.clip is None else len(pl.clip.frames),
            "error": pl.error,
        })
    return {"players": out}


def reset(engine=None) -> None:
    """清空播放器状态（测试隔离 / 引擎停止安全网）。省略 engine = 清全部。"""
    if engine is None:
        _players.clear()
        return
    ekey = _engine_key(engine)
    for k in [k for k in _players if k[0] == ekey]:
        _players.pop(k, None)
