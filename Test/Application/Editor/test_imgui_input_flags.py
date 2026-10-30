"""imgui 输入控件 flags 守卫 — `input_text` 第三参数是 flags，不是缓冲区长度。

背景（2026-10-30 实机缺陷）: `imgui.input_text(label, text, 1024)` 在 imgui_bundle 里
第三个**位置参数是 `flags`**，1024 = `Password` → 面板里的发送文本框把内容显示成 `**`；
128 = `NoCursorBlink`、96 = `AllowTabInput|CtrlEnterForNewLine`（Tab 无法离开字段）、
256 = `NoUndoRedo`。旧写法来自 imgui-python（第三参数是 buffer_length），迁移后静默变形。

规则:
  1. `imgui.input_text(...)` 第 3 个位置参数只能是 0 或用 `flags=` 关键字；
  2. `imgui.input_text_multiline(...)` 第 4 个位置参数（flags）同理
     （第 3 个 `size` 允许是 ImVec2）；
  3. 规则自检: 合成片段必须被规则拦下，合规写法必须放行。

运行: python Utils/Dev/test_runner.py --only imgui_input_flags
"""
# TIER: core

from __future__ import annotations

import ast
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
ROOT = _d or ""
if ROOT:
    sys.path.insert(0, ROOT)

_RESULTS = {"pass": 0, "fail": 0}
SCAN_ROOT = os.path.join(ROOT, "Application")
SKIP_DIRS = {"__pycache__", "dist", "build"}   # 产物目录不参与规则检查


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _int_const(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return int(node.value)
    return None


def find_violations(source: str, filename: str = "<synth>") -> list[str]:
    """Return human-readable violations found in one Python source string."""
    issues: list[str] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:  # noqa: BLE001 — 语法错误由别的守卫负责
        return [f"{filename}: syntax error: {e}"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name not in ("input_text", "input_text_multiline"):
            continue
        keywords = {kw.arg for kw in node.keywords}
        if name == "input_text":
            if len(node.args) >= 3:
                value = _int_const(node.args[2])
                if value is not None and value != 0:
                    issues.append(
                        f"{filename}:{node.lineno}: input_text flags={value} "
                        f"(第三参数是 flags，不是缓冲区长度 — 1024=Password 会显示成 **)")
            continue
        # input_text_multiline(label, text, size, flags)
        if len(node.args) >= 4:
            value = _int_const(node.args[3])
            if value is not None and value != 0:
                issues.append(
                    f"{filename}:{node.lineno}: input_text_multiline flags={value}")
        elif "flags" in keywords and len(node.args) < 3:
            issues.append(f"{filename}:{node.lineno}: input_text_multiline 缺少 size")
    return issues


def scan_tree(root: str) -> tuple[list[str], int]:
    issues: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "dist", "build")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    source = fh.read()
            except OSError as e:  # noqa: BLE001
                issues.append(f"{rel}: cannot read: {e}")
                continue
            count += 1
            skip = any(part in SKIP_DIRS for part in rel.split("/"))
            found = find_violations(source, rel)
            if found and not skip:
                issues.extend(found)
    return issues, count


_SELF_TEST_BAD = '''
from imgui_bundle import imgui
changed, val = imgui.input_text("##send", text, 1024)      # Password -> **
changed, val = imgui.input_text("##port", text, 128)      # NoCursorBlink
changed, val = imgui.input_text_multiline("##ml", text, (0, 0), 96)
'''

_SELF_TEST_GOOD = '''
from imgui_bundle import imgui
changed, val = imgui.input_text("##send", text, 0)
changed, val = imgui.input_text("##send", text)
changed, val = imgui.input_text("##send", text, flags=imgui.InputTextFlags_.password)
changed, val = imgui.input_text_multiline("##ml", text, (0, 0), 0)
'''


def main() -> int:
    print("=" * 60)
    print("imgui input_text flags guard")
    print("=" * 60)

    bad = find_violations(_SELF_TEST_BAD)
    check("规则自检: 长度当 flags → 抓到 3 处", len(bad) == 3, str(bad))
    good = find_violations(_SELF_TEST_GOOD)
    check("规则自检: 合规写法放行", not good, str(good))

    issues, scanned = scan_tree(SCAN_ROOT)
    check(f"扫描 Application/** ({scanned} files) 无 flags 误用", not issues,
          "; ".join(issues[:6]))

    # 发送框必须走带左标签的封装（回归: 曾经直接写 input_text(..., 1024)）
    panel = os.path.join(SCAN_ROOT, "Functions", "SerialParallelDevice", "extension.py")
    source = open(panel, encoding="utf-8").read() if os.path.isfile(panel) else ""
    check("SerialParallelDevice 面板: input_text 第三参数全为 0",
          "input_text(" in source and not find_violations(source, "spd/extension.py"))
    check("SerialParallelDevice 面板: 提供左置标签表单 helper",
          "_form_label" in source and "_labeled_input" in source)

    print("-" * 60)
    ok = _RESULTS["fail"] == 0
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
