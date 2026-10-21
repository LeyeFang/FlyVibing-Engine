"""
imgui 窗口栈配对齐守卫 — 反模式静态拦截（主应用 + 扩展示例）。

背景（2026-10-12 扩展面板实测）：宿主窗口最小化 → 后续帧 0x0 全裁剪 →
`BeginChild()` 返回 False → 广为流传的 `if (BeginChild()) { … EndChild(); }` 写法漏配对 →
窗口栈失衡 → **之后任意一次 `end()`** 抛 `Must call EndChild() and not End()` 断言，
异常杀掉整个渲染循环；跳过错配的那一帧当时**无任何报错**，定位成本极高。

协议: `Doc/Dev/ui_protocol.md` §2.13；扩展侧同规则 `Doc/ExtDev/extension_dev_protocol.md` §7.7。
规则单一权威 = `FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py`（C8/C9/C10）—— 本测试与其同源。

锁定:
  1. 规则自检（合成片段：反模式必被抓 / 正确写法必放行 / 早退模式不被误判）
  2. `Application/Editor/**` + `Application/Functions/**` 无 gated `begin_child`
  3. 文件级配对计数平衡（`begin_X` ≡ `end_X` − 早退式 end）— 覆盖 child/child、popup、combo 等
  4. 扩展入口无顶层 imgui 上下文/窗口/GL 创建（C10 — 纯导入允许）

运行: python Utils/Dev/test_runner.py --only imgui_stack_pairing
"""
# TIER: core

from __future__ import annotations

import ast
import importlib.util
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
_ROOT = _d or ""
if _ROOT:
    sys.path.insert(0, _ROOT)
    sys.path.insert(0, os.path.join(_ROOT, "Utils", "ExtDev", "ExtensionKit"))

import review_extension as kit  # noqa: E402  (规则同源)

_RESULTS = {"pass": 0, "fail": 0}

# 配对表（begin 侧前缀归一化 —— begin_popup 涵盖 begin_popup_context_*/_modal）
PAIRS = (("begin_child", "end_child"),
         ("begin_popup", "end_popup"),
         ("begin_combo", "end_combo"),
         ("begin_tab_item", "end_tab_item"),
         ("begin_menu", "end_menu"),
         ("begin_disabled", "end_disabled"),
         ("push_id", "pop_id"))

_SCAN_DIRS = ("Application/Editor", "Application/Functions")


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _imgui_counts(tree: ast.AST) -> dict:
    out: dict = {}
    for node in ast.walk(tree):
        _b, attr = kit._imgui_call(node)
        if not attr:
            continue
        for b, _e in PAIRS:                      # 前缀归一化
            if attr.startswith(b):
                attr = b
                break
        out[attr] = out.get(attr, 0) + 1
    return out


def _early_exit_ends(tree: ast.AST) -> dict:
    """`end_X(); return/continue/break/raise` —— 早退式关窗（合法，需补偿计数）。"""
    out: dict = {}
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, st in enumerate(stmts):
                if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)):
                    continue
                _b, attr = kit._imgui_call(st.value)
                if not attr or not attr.startswith("end_"):
                    continue
                nxt = stmts[i + 1] if i + 1 < len(stmts) else None
                if isinstance(nxt, (ast.Return, ast.Continue, ast.Break, ast.Raise)):
                    out[attr] = out.get(attr, 0) + 1
    return out


def pairing_imbalance(tree: ast.AST) -> list:
    """文件级配对平衡（含早退补偿）→ ["begin_child: begin=1 end=2 early=1", …]。"""
    counts = _imgui_counts(tree)
    early = _early_exit_ends(tree)
    bad = []
    for b, e in PAIRS:
        nb = counts.get(b, 0)
        ne = sum(v for k, v in counts.items() if k.startswith(e))
        nex = sum(v for k, v in early.items() if k.startswith(e))
        if nb != ne - nex:
            bad.append(f"{b}: begin={nb} end={ne} early_exit={nex}")
    return bad


def _scan(target: str):
    """(files, gated, imbalance) for a repo-relative directory."""
    base = os.path.join(_ROOT, *target.split("/"))
    files = gated = 0
    imbalance: list = []
    for dirpath, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "_runs")]
        for fn in sorted(names):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, _ROOT).replace("\\", "/")
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue
            files += 1
            for x in kit.gated_begin_child(tree):
                gated += 1
                print(f"       [gated] {rel}: {x}")
            for x in pairing_imbalance(tree):
                imbalance.append(f"{rel}: {x}")
    return files, gated, imbalance


def main() -> int:
    print("=" * 60)
    print("imgui stack pairing guard — gated begin_child / balance / top-level context")
    print("=" * 60)

    # ── 1. 规则自检（防规则退化） ────────────────────────────────
    print("-- 1. rule self-check (synthetic) --")
    bad_src = (
        "from imgui_bundle import imgui\n"
        "def draw():\n"
        "    imgui.begin('W')\n"
        "    if imgui.begin_child('C', (10, 10), True):\n"
        "        imgui.text('x')\n"
        "        imgui.end_child()\n"
        "    imgui.end()\n")
    good_src = (
        "from imgui_bundle import imgui\n"
        "def draw():\n"
        "    imgui.begin('W')\n"
        "    open_ = imgui.begin_child('C', (10, 10), True)\n"
        "    try:\n"
        "        if open_:\n"
        "            imgui.text('x')\n"
        "    finally:\n"
        "        imgui.end_child()\n"
        "    imgui.end()\n")
    early_src = (
        "from imgui_bundle import imgui\n"
        "def draw(items):\n"
        "    imgui.begin_child('C', (10, 10), True)\n"
        "    if not items:\n"
        "        imgui.end_child()\n"
        "        return\n"
        "    imgui.text('x')\n"
        "    imgui.end_child()\n")
    ctx_bad_src = "from imgui_bundle import imgui\nimgui.create_context()\n"
    ctx_ok_src = ("from imgui_bundle import imgui\n"
                  "def boot():\n    imgui.create_context()\n")

    bad_tree = ast.parse(bad_src)
    check("反模式被抓（if begin_child）", len(kit.gated_begin_child(bad_tree)) == 1,
          str(kit.gated_begin_child(bad_tree)))
    check("正确写法放行（try/finally 无条件配对）",
          not kit.gated_begin_child(ast.parse(good_src)))
    check("早退模式不误判（end_child + return 补偿后平衡）",
          not pairing_imbalance(ast.parse(early_src)),
          str(pairing_imbalance(ast.parse(early_src))))
    check("早退补偿确实是必需的（不补偿就不平衡）",
          pairing_imbalance(ast.parse(early_src)) == []
          and _imgui_counts(ast.parse(early_src)).get("end_child", 0) == 2)
    check("顶层建上下文被抓（C10）", bool(kit.toplevel_context_calls(ast.parse(ctx_bad_src))))
    check("函数内建上下文放行（C10）",
          not kit.toplevel_context_calls(ast.parse(ctx_ok_src)))

    # ── 2. 真实扫描: 主应用 + 扩展示例 ───────────────────────────
    for target in _SCAN_DIRS:
        print(f"-- 2. scan: {target} --")
        files, gated, imbalance = _scan(target)
        check(f"{target}: 无 gated begin_child（{files} 文件）", gated == 0,
              f"{gated} 处 — 全裁剪时会漏 end_child 杀掉渲染循环")
        check(f"{target}: 配对计数平衡（含早退补偿）", not imbalance, "; ".join(imbalance[:3]))

    # ── 3. 现状信息（begin_child 调用点 — 全裁剪回归的覆盖面） ──
    total_children = 0
    for target in _SCAN_DIRS:
        base = os.path.join(_ROOT, *target.split("/"))
        for dirpath, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "_runs")]
            for fn in names:
                if not fn.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dirpath, fn), encoding="utf-8-sig") as fh:
                        total_children += _imgui_counts(ast.parse(fh.read())).get("begin_child", 0)
                except (SyntaxError, OSError):
                    continue
    print(f"       begin_child 调用点合计: {total_children}（均无条件配对）")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
