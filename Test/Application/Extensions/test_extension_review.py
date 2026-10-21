"""ExtensionKit 静态审查器测试（无引擎 — 纯静态扫描）。

锁定:
  1. 官方示例 (device) 全 PASS（含 C1/C2/C3 UI 完备性三项）
  2. 既有扩展（sigproc/bci）无 FAIL（planned 允许无 entry）
  3. 坏 manifest → M2/M3/M5 FAIL + main 退出码 1
  4. capabilities ui 但缺 UIExtensionBase → C1/C2 FAIL
  5. 官方示例 main 退出码 0

运行: python Utils/Dev/test_runner.py --only extension_review
"""
# TIER: core

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
_ROOT = _d
while _ROOT and not os.path.exists(os.path.join(_ROOT, "_path_setup.py")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT:
    sys.path.insert(0, _ROOT)
    import _path_setup  # noqa: E402
_REPO = os.path.dirname(_ROOT) if _ROOT else ""   # _ROOT = Test/ → 仓库根再向上一级

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _load_tool():
    path = os.path.join(_REPO, "Utils", "ExtDev", "ExtensionKit", "review_extension.py")
    spec = importlib.util.spec_from_file_location("ext_review_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _joined(rep) -> str:
    return "\n".join(rep.lines)


def main() -> int:
    print("=" * 60)
    print("ExtensionKit reviewer — static rule scan (headless)")
    print("=" * 60)
    tool = _load_tool()
    fn_root = os.path.join(_REPO, "Application", "Functions")

    # ── 1. 官方示例: device ──────────────────────────────────────
    print("── official example ──")
    rep = tool.review_extension(os.path.join(fn_root, "SerialParallelDevice"))
    text = _joined(rep)
    check("device: 无 FAIL", rep.fails == 0, text)
    check("device: C1 UIExtensionBase PASS", "[PASS] C1" in text)
    check("device: C2 on_ui_event PASS", "[PASS] C2" in text)
    check("device: C3 close_policy PASS", "[PASS] C3" in text)

    # ── 2. 既有扩展无 FAIL ───────────────────────────────────────
    print("── existing extensions ──")
    for name in ("SignalProcess", "BCIAlgorithm", "VirtualDevice"):
        rep = tool.review_extension(os.path.join(fn_root, *name.split("/")))
        check(f"{name}: 无 FAIL", rep.fails == 0, _joined(rep))

    # ── 3. 坏 manifest ───────────────────────────────────────────
    print("── bad manifest ──")
    tmp = tempfile.mkdtemp(prefix="extreview_")
    bad = os.path.join(tmp, "bad_manifest")
    _write(os.path.join(bad, "extension.json"), json.dumps({
        "id": "Bad-ID!", "name": "X", "version": "1", "api_version": "2",
        "capabilities": ["warp"], "description": ""}))
    rep = tool.review_extension(bad)
    text = _joined(rep)
    check("坏 manifest: M2 FAIL", "[FAIL] M2" in text)
    check("坏 manifest: M3 FAIL", "[FAIL] M3" in text)
    check("坏 manifest: M5 FAIL (非法 capability)", "[FAIL] M5" in text)
    check("坏 manifest: main 退出码 1", tool.main(["review_extension.py", bad]) == 1)

    # ── 4. ui 缺 UIExtensionBase ─────────────────────────────────
    print("── ui missing base ──")
    bad_ui = os.path.join(tmp, "bad_ui")
    _write(os.path.join(bad_ui, "extension.json"), json.dumps({
        "id": "bad_ui", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ui"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(bad_ui, "extension.py"),
           "from Application.Core.Extension.ExtensionBase import ExtensionBase\n\n"
           "class BadUiExtension(ExtensionBase):\n"
           "    id = 'bad_ui'\n\n"
           "def create_extension():\n"
           "    return BadUiExtension()\n")
    rep = tool.review_extension(bad_ui)
    text = _joined(rep)
    check("ui 缺基类: C1 FAIL", "[FAIL] C1" in text)
    check("ui 缺基类: C2 FAIL", "[FAIL] C2" in text)

    # ── 5. 官方示例 main 退出码 0 ────────────────────────────────
    rc = tool.main(["review_extension.py", os.path.join(fn_root, "SerialParallelDevice")])
    check("device: main 退出码 0", rc == 0)

    # ── 6. imgui 窗口栈纪律 C8/C9/C10（2026-10-12 新增 — 与 ui_protocol §2.13 同源） ──
    print("── imgui stack discipline (C8/C9/C10) ──")
    text = _joined(tool.review_extension(os.path.join(fn_root, "SerialParallelDevice")))
    check("device: C8 配对纪律 PASS", "[PASS] C8" in text)
    check("device: C9 combo 反向规则 PASS", "[PASS] C9" in text)
    check("device: C10 无顶层上下文创建 PASS", "[PASS] C10" in text)

    stack_bad = os.path.join(tmp, "stack_bad")
    _write(os.path.join(stack_bad, "extension.json"), json.dumps({
        "id": "stack_bad", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ops"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(stack_bad, "extension.py"),
           "from imgui_bundle import imgui\n\n"
           "def draw():\n"
           "    if imgui.begin_child('c', (100, 100), True):\n"
           "        imgui.text('x')\n"
           "        imgui.end_child()\n")
    check("gated begin_child: C8 FAIL", "[FAIL] C8" in _joined(tool.review_extension(stack_bad)))

    ctx_bad = os.path.join(tmp, "ctx_bad")
    _write(os.path.join(ctx_bad, "extension.json"), json.dumps({
        "id": "ctx_bad", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ops"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(ctx_bad, "extension.py"),
           "from imgui_bundle import imgui\n\n"
           "imgui.create_context()\n\n"
           "def create_extension():\n"
           "    return None\n")
    check("顶层 create_context: C10 FAIL", "[FAIL] C10" in _joined(tool.review_extension(ctx_bad)))

    global_bad = os.path.join(tmp, "global_bad")
    _write(os.path.join(global_bad, "extension.json"), json.dumps({
        "id": "global_bad", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ops"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(global_bad, "extension.py"),
           "from imgui_bundle import imgui\n\n"
           "def create_extension():\n"
           "    imgui.get_io().set_ini_filename('custom.ini')\n"
           "    return None\n")
    check("全局 imgui 状态写入（链式）: C11 FAIL",
          "[FAIL] C11" in _joined(tool.review_extension(global_bad)))

    global_alias = os.path.join(tmp, "global_alias")
    _write(os.path.join(global_alias, "extension.json"), json.dumps({
        "id": "global_alias", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ops"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(global_alias, "extension.py"),
           "from imgui_bundle import imgui\n\n"
           "def create_extension():\n"
           "    io = imgui.get_io()\n"
           "    io.font_global_scale = 1.2\n"
           "    return None\n")
    check("全局 io 别名写入: C11 FAIL",
          "[FAIL] C11" in _joined(tool.review_extension(global_alias)))

    global_read = os.path.join(tmp, "global_read")
    _write(os.path.join(global_read, "extension.json"), json.dumps({
        "id": "global_read", "name": "X", "version": "1", "api_version": "1",
        "capabilities": ["ops"], "entry": "extension.py:create_extension",
        "description": "x"}))
    _write(os.path.join(global_read, "extension.py"),
           "from imgui_bundle import imgui\n\n"
           "def create_extension():\n"
           "    io = imgui.get_io()\n"
           "    return io.delta_time\n")
    check("只读 get_io 不误报: C11 PASS",
          "[PASS] C11" in _joined(tool.review_extension(global_read)))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
