"""UI 文本字形安全守卫 — imgui 字面量不得含字体图集外字符（渲染为 '?'）。

根因: UI 字体经 `hello_imgui.load_font_ttf_with_font_awesome_icons` 以默认字形范围加载
（ASCII + Latin-1 + General Punctuation 子集 + FontAwesome 私有区）→ 图集外的
CJK / 箭头(←→) / 几何(▶■●) / Dingbats(✓✗★) 等一律渲染为 `?`。

规范（两侧文档同源）:
  - 主应用: `Doc/Dev/ui_protocol.md` §12（文本与字形安全）
  - 扩展:   `Doc/ExtDev/extension_dev_protocol.md` §7（文本安全）

本测试锁定:
  1. `Application/Editor/**` 中全部 `imgui.*() / hello_imgui.*()` 调用的字符串常量
     （含 f-string 文本段）均只含安全字符;
  2. `ComponentRegistry.FIELD_CHOICES` 的显示标签均安全（其值会直接进检查器 Combo）。

运行: python Utils/Dev/test_runner.py --only ui_text_safety
"""
# TIER: core

from __future__ import annotations

import ast
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
_ROOT = _d
while _ROOT and not os.path.exists(os.path.join(_ROOT, "_path_setup.py")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT:
    sys.path.insert(0, _ROOT)
    import _path_setup  # noqa: E402
_REPO = os.path.dirname(_ROOT) if _ROOT else ""

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


# ── 安全字符集（与字体图集一致 — 协议 §12 单一权威定义） ──────
_SAFE_RANGES = [
    (0x0020, 0x007E),   # ASCII 可打印
    (0x00A0, 0x00FF),   # Latin-1（× ÷ ° · 等）
    (0x2013, 0x2014),   # – —
    (0x2018, 0x201D),   # ' ' " "
    (0x2022, 0x2022),   # •
    (0x2026, 0x2026),   # …
    (0xF000, 0xFFFF),   # FontAwesome 图标私有区（ICON_FA_*）
]
_IMGUI_ROOTS = {"imgui", "hello_imgui"}


def unsafe_chars(text: str) -> list[str]:
    """返回图集外字符（去重排序）— 换行/制表符为 imgui 合法多行文本, 放行。"""
    bad = set()
    for ch in text:
        if ch in "\n\t":
            continue
        cp = ord(ch)
        if not any(a <= cp <= b for a, b in _SAFE_RANGES):
            bad.add(ch)
    return sorted(bad)


def _fmt(chars: list[str]) -> str:
    return " ".join(f"U+{ord(c):04X}({c})" for c in chars)


def _imgui_string_nodes(tree: ast.AST):
    """产出 imgui.*()/hello_imgui.*() 参数中的 str 常量节点。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        base = node.func.value
        if not (isinstance(base, ast.Name) and base.id in _IMGUI_ROOTS):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    yield sub


def _scan_imgui_literals(path: str, violations: list) -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError):
        return
    for node in _imgui_string_nodes(tree):
        bad = unsafe_chars(node.value)
        if bad:
            violations.append(f"{os.path.relpath(path, _REPO)}:{node.lineno}: "
                              f"{_fmt(bad)}  in {node.value[:60]!r}")


def _scan_field_choices(violations: list) -> None:
    """FIELD_CHOICES 显示标签（进检查器 Combo）。"""
    path = os.path.join(_REPO, "Application", "Core", "Scene", "ComponentRegistry.py")
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "FIELD_CHOICES":
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        bad = unsafe_chars(sub.value)
                        if bad:
                            violations.append(f"ComponentRegistry.py:{sub.lineno}: "
                                              f"{_fmt(bad)}  in {sub.value[:60]!r}")


def main() -> int:
    print("=" * 60)
    print("UI text glyph-safety guard (imgui literals)")
    print("=" * 60)

    violations: list = []
    editor_root = os.path.join(_REPO, "Application", "Editor")
    for dirpath, dirnames, filenames in os.walk(editor_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                _scan_imgui_literals(os.path.join(dirpath, fn), violations)
    _scan_field_choices(violations)

    if violations:
        print("  违规（图集外字符 → 渲染为 '?'）:")
        for v in violations:
            print(f"    {v}")
    check("imgui 字面量 + FIELD_CHOICES 全部字形安全", not violations,
          f"{len(violations)} 处违规")

    # 自检: 守卫规则本身（确保规则集不会退化放行）
    check("规则自检: CJK 被拦", set(unsafe_chars("平面光")) == {"平", "面", "光"})
    check("规则自检: 箭头被拦", bool(unsafe_chars("a → b")))
    check("规则自检: em dash/×/·/…/换行 放行",
          not unsafe_chars("a — b × c · d …\n\te") and not unsafe_chars("a -> b <- c"))
    check("规则自检: FA 私有区放行", not unsafe_chars("\uf013"))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
