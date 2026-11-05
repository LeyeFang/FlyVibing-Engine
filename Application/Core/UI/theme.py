"""UI 主题 token（默认值 — 后续由工程根 `ui_theme.json` 覆盖，见 product_todo §10.8）。

规则（**不是 CSS**）：
  - 组件只引用 token 名（`@color.accent`）或 variant 名（`primary/danger`）；
  - hover/pressed/disabled 由控件自动派生，用户不写伪类；
  - token 只放"值"，不放选择器/布局规则。
"""

from __future__ import annotations

# ── 颜色（RGBA 0..1）────────────────────────────────────────────
DEFAULT_TOKENS: dict[str, tuple | float | int | str] = {
    # 遮罩 / 面板
    "color.scrim": (0.0, 0.0, 0.0, 0.55),
    "color.surface": (0.105, 0.110, 0.125, 0.98),
    "color.border": (1.0, 1.0, 1.0, 0.14),
    # 文本
    "color.text": (0.93, 0.93, 0.94, 1.0),
    "color.text.muted": (0.70, 0.72, 0.76, 1.0),
    # 按钮（默认 / 悬停 / 主操作 / 危险 / 幽灵）
    "color.button": (0.20, 0.22, 0.26, 1.0),
    "color.button.hover": (0.27, 0.30, 0.36, 1.0),
    "color.button.primary": (0.24, 0.52, 0.98, 1.0),
    "color.button.primary.hover": (0.32, 0.60, 1.0, 1.0),
    "color.danger": (0.78, 0.235, 0.235, 1.0),
    "color.danger.hover": (0.88, 0.31, 0.31, 1.0),
    "color.ghost": (0.0, 0.0, 0.0, 0.0),          # 无底（只有文字）
    "color.ghost.hover": (1.0, 1.0, 1.0, 0.10),
    "color.button.disabled": (0.16, 0.17, 0.20, 1.0),
    "color.text.disabled": (0.55, 0.56, 0.62, 1.0),
    # 字号（参考分辨率像素）
    "font.size.title": 42,
    "font.size.body": 28,
    "font.size.button": 30,
    # 间距 / 尺寸
    "space.pad": 28,
    "space.gap": 18,
    "radius.panel": 0,          # M0 只画直角（圆角等 SDF 版）
}


def resolve(value, tokens: dict | None = None):
    """`"@color.text"` → 实际值；非 token 原样返回。"""
    if not isinstance(value, str) or not value.startswith("@"):
        return value
    table = DEFAULT_TOKENS if tokens is None else tokens
    return table.get(value[1:], value)


def parse_color(value, tokens: dict | None = None,
                default: tuple = (1.0, 1.0, 1.0, 1.0)) -> tuple:
    """任意颜色写法 → RGBA float tuple(4)。

    接受: `"@color.surface"`（token）/ `"#RRGGBB"` / `"#RRGGBBAA"` /
    `(r,g,b)` / `(r,g,b,a)` / 空值（→ `default`）。
    解析不到 → `default`（渲染宁可用兜底色，也不抛异常打断帧）。
    """
    if value is None or value == "":
        return tuple(default)
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("@"):
            return parse_color(resolve(raw, tokens), tokens, default)
        if raw.startswith("#"):
            hexpart = raw[1:]
            try:
                if len(hexpart) == 3:
                    hexpart = "".join(ch * 2 for ch in hexpart)
                if len(hexpart) == 6:
                    r, g, b = (int(hexpart[i:i + 2], 16) for i in (0, 2, 4))
                    return (r / 255.0, g / 255.0, b / 255.0, 1.0)
                if len(hexpart) == 8:
                    r, g, b, a = (int(hexpart[i:i + 2], 16) for i in (0, 2, 4, 6))
                    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
            except ValueError:
                return tuple(default)
        return tuple(default)
    if isinstance(value, (tuple, list)):
        vals = [float(v) for v in value]
        if len(vals) == 3:
            return (vals[0], vals[1], vals[2], 1.0)
        if len(vals) >= 4:
            return (vals[0], vals[1], vals[2], vals[3])
        if len(vals) == 1:
            return (vals[0], vals[0], vals[0], 1.0)
    return tuple(default)


def with_alpha(color: tuple, alpha: float) -> tuple:
    """RGBA → 替换 alpha（0..1）。"""
    r, g, b = (float(color[0]), float(color[1]), float(color[2]))
    return (r, g, b, max(0.0, min(1.0, float(alpha))))


# ════════════════════════════════════════════════════════════════
# 控件变体 → token（用户在场景里只写语义名）
# ════════════════════════════════════════════════════════════════

# variant → (底色, 悬停底色)
BUTTON_VARIANTS: dict[str, tuple[str, str]] = {
    "secondary": ("color.button", "color.button.hover"),
    "primary": ("color.button.primary", "color.button.primary.hover"),
    "danger": ("color.danger", "color.danger.hover"),
    "ghost": ("color.ghost", "color.ghost.hover"),
}


def button_colors(variant: str, hover: bool = False,
                  enabled: bool = True, tokens: dict | None = None) -> tuple:
    """按钮变体 → (背景 RGBA, 文字 RGBA)。"""
    table = DEFAULT_TOKENS if tokens is None else tokens
    key = str(variant or "secondary").strip().lower()
    base, hover_key = BUTTON_VARIANTS.get(key, BUTTON_VARIANTS["secondary"])
    if not enabled:
        return (parse_color("@" + "color.button.disabled", table),
                parse_color("@color.text.disabled", table))
    bg = parse_color("@" + (hover_key if hover else base), table)
    return (bg, parse_color("@color.text", table))


def text_font_size(size_token: str | int, tokens: dict | None = None) -> int:
    return int(resolve(size_token, tokens))
