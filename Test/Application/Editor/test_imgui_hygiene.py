"""
imgui 卫生守卫 — 无头上下文唯一入口 / ini 永不落盘 / 防回归断言（无头）。

背景（2026-10-12 实测）：扩展自测里裸 `imgui.create_context()` → `destroy_context()`
把 `imgui.ini` 写到**当前工作目录**（仓库根）——我们在 ExtDev §12 鼓励作者写这种 GUI
回归测试，于是每个扩展都会污染应用根。另: `io.set_ini_filename(None)` 会让进程
**原生访问违例崩溃**（exit 0xC0000005，可复现），必须绝迹。

协议: `Doc/ExtDev/extension_dev_protocol.md` §12；`Doc/Dev/ui_protocol.md` §2。
唯一入口: `FlyVibing-User-And-Developer-Utils/packages/extension-kit/imgui_headless.py`。

锁定:
  1. `headless_imgui()` 功能: 连画 0x0/1x1 帧 → 退出后 CWD **无** imgui.ini; 有效文件名 = ""
  2. 静态: Test/** 无裸 `imgui.create_context()`（白名单两处必须自行禁用 ini）
  3. 静态: 全仓无 `set_ini_filename(None)`（会崩）
  4. 防回归: 引擎侧 `EditorImguiLayer` 仍以空串禁用 ini（被删则会重新落盘）

运行: python Utils/Dev/test_runner.py --only imgui_hygiene
"""
# TIER: core

from __future__ import annotations

import ast
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
_ROOT = _d or ""
if _ROOT:
    sys.path.insert(0, _ROOT)

from flyvibing_extension_kit.imgui_headless import headless_imgui  # noqa: E402
from imgui_bundle import imgui                                     # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}

# 允许自建长生命周期上下文的测试（各自必须显式禁用 ini —— 由检查 2b 校验）
_ALLOW_DIRECT_CONTEXT = {
    "Test/Application/Editor/_ui_boot.py": "完整编辑器引导（GL 后端 + 面板），需长生命周期",
    "Test/Application/Editor/test_node_runtime.py": "交互演示（manual 档），需长生命周期",
}
_SCAN_TREES = ("Application", "Test", "Utils")
# 剪枝: 产物/部署副本/运行时（不是源码 — 扫它们既慢又无意义）
_PRUNE_DIRS = {
    "__pycache__", "_runs", "dist", "build", "stage", "runtime", "Lib",
    "site-packages", "wheelhouse", "assets", "output", ".venv-py314t",
    ".venv", "tmp", "node_modules", "_gtec_archive_20261016",
}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _rel(path: str) -> str:
    return os.path.relpath(path, _ROOT).replace("\\", "/")


def _py_files(*trees: str):
    for tree in trees:
        base = os.path.join(_ROOT, *tree.split("/"))
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _PRUNE_DIRS]
            for fn in sorted(files):
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _call_attr(node: ast.AST) -> str:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def main() -> int:
    print("=" * 60)
    print("imgui hygiene guard — headless entry / no ini on disk / no None")
    print("=" * 60)

    # ── 1. 功能: 唯一入口不落盘 ─────────────────────────────────
    print("-- 1. headless_imgui() leaves no imgui.ini --")
    cwd = os.getcwd()
    before = os.path.exists(os.path.join(cwd, "imgui.ini"))

    def _draw() -> None:
        imgui.begin("HygieneProbe")
        imgui.text("x")
        imgui.end()

    try:
        with headless_imgui() as h:
            h.frames([(1280, 720), (0, 0), (1, 1), (1280, 720)], draw=_draw)
            eff = h.io.get_ini_filename()
        check("有效 ini 文件名为空 (禁用生效)", eff == "", repr(eff))
        check("无头会话结束后 CWD 无 imgui.ini",
              not os.path.exists(os.path.join(cwd, "imgui.ini")))
    except Exception as e:  # noqa: BLE001
        check("无头会话可完整绘制 4 帧（含 0x0）", False, repr(e))

    if before:
        print("       [note] 仓库根在本次运行前已存在 imgui.ini（历史残留/他人产物）— "
              "已由 .gitignore 忽略; 如非在用可删除")

    # ── 2. 静态: Test/** 无裸 create_context ────────────────────
    print("-- 2. no bare create_context in Test/** --")
    bare: list[str] = []
    for path in _py_files("Test"):
        rel = _rel(path)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                tree = ast.parse(fh.read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _call_attr(node) != "create_context":
                continue
            if rel in _ALLOW_DIRECT_CONTEXT:
                continue
            bare.append(f"{rel}:{node.lineno}")
    check("Test/** 无裸 imgui.create_context()（必须走 headless_imgui）", not bare,
          "; ".join(bare[:4]) + f" (+{max(0, len(bare) - 4)})")
    for rel in _ALLOW_DIRECT_CONTEXT:
        src = open(os.path.join(_ROOT, *rel.split("/")), encoding="utf-8-sig").read()
        check(f"白名单自行禁用 ini: {os.path.basename(rel)}", "disable_ini" in src)

    # ── 3. 静态: 全仓无 set_ini_filename(None) ─────────────────
    print("-- 3. no set_ini_filename(None) (crashes natively) --")
    bad_none: list[str] = []
    for path in _py_files(*_SCAN_TREES):
        rel = _rel(path)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                tree = ast.parse(fh.read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _call_attr(node) != "set_ini_filename" or not node.args:
                continue
            if isinstance(node.args[0], ast.Constant) and node.args[0].value is None:
                bad_none.append(f"{rel}:{node.lineno}")
    check("无 set_ini_filename(None)（原生崩溃写法）", not bad_none, "; ".join(bad_none[:4]))

    # ── 4. 防回归: 引擎仍禁用 ini ──────────────────────────────
    print("-- 4. engine still disables ini --")
    layer = os.path.join(_ROOT, "Application", "Editor", "EditorImguiLayer.py")
    found = False
    with open(layer, encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if _call_attr(node) != "set_ini_filename" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and arg.value == "":
            found = True
    check("EditorImguiLayer 仍以空串禁用 ini（删除会让 imgui.ini 复活）", found)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
