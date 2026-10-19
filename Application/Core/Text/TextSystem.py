"""TextSystem — 文本 → 动态纹理光栅化 (协议: Doc/Dev/text_protocol.md)。

职责:
  - `refresh(engine, eid)` — 按需光栅化 TextDisplay → CPU 纹理 → 材质槽绑定
    (同尺寸 → TextureUpdateCommand 热更; 换尺寸 → 新纹理 id + SetEntityTexture);
  - `tick(engine)` — 脏扫描 (编辑器预览; 仅处理本引擎注册表中实体);
  - `rasterize(display)` — 纯函数光栅化 (Pillow, 零新增依赖):
    自动画布 / 透明底(浮空文字)或实底(有色画布) / 合成加粗(描边) / 合成斜体(斜切)。

形态矩阵 (text_protocol.md):
  ┌ bg_color alpha=1 → 有色画布: 文字写在实心背景上
  └ bg_color alpha=0 → 浮空文字: 画布透明, 仅字形可见 (依赖 Material.blend="alpha")

拉普天则: 组件 = 状态载体; 节点 SetText = 控制面; 编辑器编辑即预览。
"""

from __future__ import annotations

import os

import numpy as np

_states: dict[tuple, dict] = {}
_font_cache: dict[tuple, object] = {}


# ═══════════════════════════════════════════════════════════════
# 字体 / 颜色 / 折行 助手
# ═══════════════════════════════════════════════════════════════

def _resolve_font_path(spec: str) -> str:
    spec = str(spec or "").strip()
    if spec and os.path.isfile(spec):
        return spec
    fonts_dir = os.path.join("Resource", "Fonts")
    for cand in ([f"{spec}.ttf", f"{spec}.ttc", spec] if spec else []):
        p = os.path.join(fonts_dir, cand)
        if os.path.isfile(p):
            return p
    fallback = os.path.join(fonts_dir, "Roboto-Regular.ttf")
    return fallback if os.path.isfile(fallback) else ""


def _load_font(path: str, size: int):
    key = (path, int(size))
    font = _font_cache.get(key)
    if font is None:
        from PIL import ImageFont
        if path:
            try:
                font = ImageFont.truetype(path, int(size))
            except Exception:  # noqa: BLE001
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
        _font_cache[key] = font
    return font


def _rgba255(v, fallback=(255, 255, 255, 255)) -> tuple:
    try:
        vals = list(v)
    except TypeError:
        return fallback
    if len(vals) == 3:
        vals.append(1.0)
    if len(vals) != 4:
        return fallback
    out = []
    for c in vals:
        try:
            out.append(max(0, min(255, int(round(float(c) * 255)))))
        except (TypeError, ValueError):
            return fallback
    return tuple(out)


def _wrap_line(raw: str, font, max_px: float) -> list[str]:
    if not raw:
        return [""]
    out: list[str] = []
    cur = ""
    for ch in raw:
        trial = cur + ch
        if cur and font.getlength(trial) > max_px:
            out.append(cur)
            cur = ch
        else:
            cur = trial
    out.append(cur)
    return out


# ═══════════════════════════════════════════════════════════════
# 光栅化 (纯函数)
# ═══════════════════════════════════════════════════════════════

def rasterize(display) -> np.ndarray:
    """TextDisplay → (H, W, 4) uint8 RGBA 数组 (自动画布)。"""
    text = str(getattr(display, 'text', '') or '')
    size = max(4, int(getattr(display, 'size', 64) or 64))
    bold = bool(getattr(display, 'bold', False))
    italic = bool(getattr(display, 'italic', False))
    fg = _rgba255(getattr(display, 'color', (1.0, 1.0, 1.0, 1.0)), (255, 255, 255, 255))
    bg = _rgba255(getattr(display, 'bg_color', (0.0, 0.0, 0.0, 0.0)), (0, 0, 0, 0))
    align = str(getattr(display, 'align', 'center') or 'center').lower()
    if align not in ('left', 'center', 'right'):
        align = 'center'
    spacing = max(0.8, float(getattr(display, 'line_spacing', 1.15) or 1.15))
    padding = max(0, int(getattr(display, 'padding', 8) or 0))
    wrap = int(getattr(display, 'wrap_width', 0) or 0)

    font = _load_font(_resolve_font_path(getattr(display, 'font', 'segoeui')), size)

    lines: list[str] = []
    for raw in text.split("\n"):
        if wrap > 0:
            lines.extend(_wrap_line(raw, font, float(wrap)))
        else:
            lines.append(raw)
    if not lines:
        lines = [""]

    line_h = max(1, int(round(size * spacing)))
    widths = [float(font.getlength(ln)) for ln in lines]
    stroke = max(1, int(round(size * 0.04))) if bold else 0
    canvas_w = max(1, int(round(max(widths))) + 2 * padding + stroke)
    canvas_h = max(1, line_h * len(lines) + 2 * padding + stroke)

    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (canvas_w, canvas_h), bg)
    draw = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        x = float(padding)
        if align == 'center':
            x = (canvas_w - widths[i]) / 2.0
        elif align == 'right':
            x = canvas_w - padding - widths[i]
        y = float(padding + i * line_h)
        kwargs = {}
        if bold:
            kwargs["stroke_width"] = stroke
            kwargs["stroke_fill"] = fg
        draw.text((x, y), ln, font=font, fill=fg, **kwargs)

    if italic:
        # 顶部右移 / 底部固定 = 标准斜体斜切; 右侧扩宽防裁切
        shear = 0.22
        shift = shear * canvas_h
        new_w = canvas_w + int(shift) + 2
        img = img.transform(
            (new_w, canvas_h), Image.AFFINE,
            (1, shear, -shift, 0, 1, 0),
            resample=Image.BILINEAR,
        )
    return np.asarray(img, dtype=np.uint8).copy()


# ═══════════════════════════════════════════════════════════════
# 应用 (refresh / tick)
# ═══════════════════════════════════════════════════════════════

def _signature(display) -> tuple:
    """影响光栅/缩放的字段签名 — 变化才重做。"""
    return (
        str(getattr(display, 'text', '') or ''),
        str(getattr(display, 'font', '') or ''),
        int(getattr(display, 'size', 0) or 0),
        bool(getattr(display, 'bold', False)),
        bool(getattr(display, 'italic', False)),
        _rgba255(getattr(display, 'color', None)),
        _rgba255(getattr(display, 'bg_color', None), (0, 0, 0, 0)),
        str(getattr(display, 'align', '') or ''),
        float(getattr(display, 'line_spacing', 0.0) or 0.0),
        int(getattr(display, 'padding', 0) or 0),
        int(getattr(display, 'wrap_width', 0) or 0),
        float(getattr(display, 'world_height', 0.0) or 0.0),
        bool(getattr(display, 'auto_scale', True)),
    )


def refresh(engine, eid: int, force: bool = False) -> bool:
    """光栅化实体 TextDisplay 并绑定材质槽; 返回是否执行了更新。"""
    import esper
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import TextDisplay
    from Application.Resource.ResourceManager import ResourceManager

    try:
        display = esper.component_for_entity(int(eid), TextDisplay)
    except KeyError:
        return False

    engine_key = getattr(engine, '__name__', type(engine).__name__)
    key = (engine_key, int(eid))
    sig = _signature(display)
    state = _states.get(key)
    if state is not None and state.get('sig') == sig and not force:
        return False

    st = SceneManager._state_for(engine_key)
    arr = rasterize(display)
    h, w = int(arr.shape[0]), int(arr.shape[1])
    renderer = getattr(engine, 'renderer', None)

    prev_tid = int(state.get('texture_id', 0)) if state else 0
    tid = 0
    reused = False
    if prev_tid:
        entry = ResourceManager.loaded_texture.get(str(prev_tid))
        tex = entry.get('data') if entry else None
        if tex is not None and tex.width == w and tex.height == h:
            tex.image_data = arr
            tid = prev_tid
            reused = True
    if not reused:
        tid = ResourceManager.CreateTextureFromArray(f"text:{int(eid)}", arr)

    if renderer is not None and reused:
        from Application.Core.Renderer.RenderCommand import TextureUpdateCommand
        renderer.enqueue(TextureUpdateCommand(tid, arr, w, h, 4))

    if st is not None:
        if not reused:
            st.SetEntityTexture(int(eid), tid, 0)
        if bool(getattr(display, 'auto_scale', True)):
            sz = max(1e-4, float(getattr(display, 'world_height', 1.0) or 1.0)) / 2.0
            sx = sz * (w / max(1, h))
            st.SetEntityTransform(int(eid), scale_xyz=(sx, 1.0, sz))

    _states[key] = {'sig': sig, 'texture_id': tid, 'size': (w, h)}
    return True


def tick(engine) -> int:
    """脏扫描 — 仅处理本引擎注册表内的实体 (编辑器预览路径)。"""
    import esper
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import TextDisplay

    engine_key = getattr(engine, '__name__', type(engine).__name__)
    try:
        st = SceneManager._state_for(engine_key)
        own = set(st.entities.keys())
    except KeyError:
        own = set()

    updated = 0
    live: set[tuple] = set()
    try:
        pairs = list(esper.get_component(TextDisplay))
    except Exception:  # noqa: BLE001
        pairs = []
    for eid, _display in pairs:
        if str(eid) not in own:
            continue   # 其他引擎 (如 PIE 运行时实例) 的实体 — 各自驱动
        live.add((engine_key, int(eid)))
        if refresh(engine, eid):
            updated += 1

    for k in [k for k in _states if k[0] == engine_key and k not in live]:
        _states.pop(k, None)
    return updated


def snapshot(engine) -> dict:
    """调试/测试快照。"""
    engine_key = getattr(engine, '__name__', type(engine).__name__)
    items = [
        {"entity": k[1], "texture_id": v.get("texture_id"),
         "size": list(v.get("size", ()))}
        for k, v in _states.items() if k[0] == engine_key
    ]
    return {"engine": engine_key, "texts": items, "count": len(items)}


def reset() -> None:
    """清空状态 (纹理登记保留 — 与媒体一致)。"""
    _states.clear()
