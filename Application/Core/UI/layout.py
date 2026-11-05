"""运行时 UI 基础原语（Core 侧 — 纯数据/纯数学，不 import imgui、不碰 GL）。

设计口径（协议：`Doc/Dev/product_todo.md` §10）：
  - 组件只描述"长什么样"；绘制交给渲染器的独立 UI pass（`OpenGLUI`）；
  - 命中用**矩形数学**，不用 GPU pick（pick 只认网格轮廓，空格也会挡点击）；
  - 坐标先在参考分辨率（默认 1920×1080）里写，再按 `scale_mode` 缩放到视口。

本文件只有三件事：`UIQuad`（一条绘制指令）、`content_box/resolve_rect`（锚点/枢轴 → 像素）、
`rect_hit`（命中）。任何"布局引擎"都还谈不上 —— 这是 M0 的最小面。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ── 参考分辨率（所有 UI 数值都写在这个空间里）──────────────────
REFERENCE_W: int = 1920
REFERENCE_H: int = 1080

# 锚点/枢轴可取值（与 CSS 的 9 宫格同名，方便前端同学迁移心智）
ANCHORS: tuple[str, ...] = (
    "top_left", "top", "top_right",
    "left", "center", "right",
    "bottom_left", "bottom", "bottom_right",
)


@dataclass(frozen=True)
class UIQuad:
    """一条 UI 绘制指令（屏幕像素，左上原点）。

    - `image is None` → 纯色矩形（用 `color`）
    - `image` 为 (H, W, 4) uint8 → 纹理矩形，`color` 作为乘色
    - `key` 是纹理缓存键：同一 key 只上传一次（文本按内容哈希）
    """

    x: float
    y: float
    w: float
    h: float
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    image: np.ndarray | None = field(default=None, compare=False, repr=False)
    key: str = ""


# ════════════════════════════════════════════════════════════════
# 分辨率 → 内容框 + 缩放
# ════════════════════════════════════════════════════════════════

def content_box(viewport_w: int, viewport_h: int,
                scale_mode: str = "fit_height",
                reference: tuple[int, int] = (REFERENCE_W, REFERENCE_H)) -> tuple:
    """视口 → (内容框 x, y, w, h) + (scale_x, scale_y)。

    - `fit_height`（默认）：高度贴合，宽度居中（超宽屏两侧留边，UI 不变形）
    - `fit_width`：宽度贴合，高度居中
    - `contain`：按较小比例贴合（宽高都不超出视口）— 窄/矮窗口下整份 UI 仍然可见
      （编辑器视口常见 4:3 / 5:4，用 fit_height 会裁掉右侧）
    - `stretch`：直接拉满（会变形，谨慎）
    """
    rw, rh = max(1, int(reference[0])), max(1, int(reference[1]))
    vw, vh = max(1, int(viewport_w)), max(1, int(viewport_h))
    mode = str(scale_mode or "fit_height").strip().lower()
    if mode == "stretch":
        return (0.0, 0.0, float(vw), float(vh)), (vw / rw, vh / rh)
    if mode == "fit_width":
        scale = vw / rw
        box_h = rh * scale
        return (0.0, (vh - box_h) / 2.0, float(vw), box_h), (scale, scale)
    if mode == "contain":
        scale = min(vw / rw, vh / rh)
        box_w, box_h = rw * scale, rh * scale
        return ((vw - box_w) / 2.0, (vh - box_h) / 2.0, box_w, box_h), (scale, scale)
    scale = vh / rh
    box_w = rw * scale
    return ((vw - box_w) / 2.0, 0.0, box_w, float(vh)), (scale, scale)


def _anchor_offset(name: str, w: float, h: float) -> tuple[float, float]:
    """9 宫格名字 → 在 (w,h) 矩形内的相对位置。

    `left` / `right` 是**左边中/右边中**（垂直居中），不是左上/右上 —— 这是 9 宫格
    与 CSS 对齐语义的对齐点（垂直只在 top / center / bottom 三档）。
    """
    key = str(name or "top_left").strip().lower()
    hx = 0.0 if key in ("top_left", "left", "bottom_left") \
        else 1.0 if key in ("top_right", "right", "bottom_right") else 0.5
    hy = 0.0 if key.startswith("top") \
        else 1.0 if key.startswith("bottom") else 0.5
    return (w * hx, h * hy)


def resolve_rect(pos: tuple[float, float], size: tuple[float, float],
                 box: tuple[float, float, float, float],
                 scale: tuple[float, float],
                 anchor: str = "center", pivot: str | None = None) -> tuple:
    """参考分辨率里的 (pos, size) → 屏幕像素矩形 (x, y, w, h)。

    - `anchor`：相对**内容框**的 9 宫格位置
    - `pivot`：矩形自身对齐点（默认与 anchor 相同；`center` 就是居中）
    - `pos`：锚点处的像素偏移（参考分辨率单位，会乘 scale）
    """
    bx, by, bw, bh = box
    sx, sy = scale
    w = float(size[0]) * sx
    h = float(size[1]) * sy
    ax, ay = _anchor_offset(anchor, bw, bh)
    px, py = _anchor_offset(pivot or anchor, w, h)
    x = bx + ax - px + float(pos[0]) * sx
    y = by + ay - py + float(pos[1]) * sy
    return (x, y, w, h)


def rect_hit(rect: tuple, x: float, y: float) -> bool:
    """(x, y, w, h) 矩形命中判定（左上原点，边界含）。"""
    rx, ry, rw, rh = (float(v) for v in rect)
    return rx <= float(x) <= rx + rw and ry <= float(y) <= ry + rh


# ════════════════════════════════════════════════════════════════
# 字体（运行时没有 i18n 字体表；CJK 探测系统字体）
# ════════════════════════════════════════════════════════════════

_CJK_FONT_CANDIDATES: tuple[str, ...] = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
_LATIN_FONT: str = "Resource/Fonts/Roboto-Regular.ttf"


def needs_cjk(text: str) -> bool:
    """文本里是否有非 Latin 字符（粗略：> 0x2E80 视为 CJK/全角）。"""
    return any(ord(ch) > 0x2E80 for ch in str(text or ""))


def resolve_font(text: str) -> str:
    """按文本挑字体：含 CJK → 找系统 CJK 字体；否则用仓库内置 Roboto。"""
    import os

    if needs_cjk(text):
        for cand in _CJK_FONT_CANDIDATES:
            if os.path.isfile(cand):
                return cand
    return _LATIN_FONT if os.path.isfile(_LATIN_FONT) else ""


__all__ = [
    "REFERENCE_W", "REFERENCE_H", "ANCHORS", "UIQuad",
    "content_box", "resolve_rect", "rect_hit",
    "needs_cjk", "resolve_font",
]
