"""
Test: NodeGraph Boundary — Core.NodeGraph 与编辑器 / imgui 的边界守卫
═══════════════════════════════════════════════════════════════

验证（可回归，每次改动节点图包后必跑）:
  1. 源码扫描: Application/Core/NodeGraph/** 不得出现对
     `Application.Editor` / `imgui_bundle` 的 import（含函数内惰性导入）
  2. 阻断 imgui + Editor 导入后, 节点图运行时 + 运行时链路仍可导入
  3. 反向: 编辑器面板在同样阻断下必须失败（证明阻断器生效）

运行: python Test/Application/Core/test_node_graph_boundary.py
"""

from __future__ import annotations

import os
import re
import sys

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

_PASS = 0
_FAIL = 0


def check(cond: bool, name: str) -> bool:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}")
    return cond


# ═══════════════════════════════════════════════════════════════
# 1. 源码扫描 — Core/NodeGraph 禁止 import 编辑器 / imgui
# ═══════════════════════════════════════════════════════════════

_FORBIDDEN_IMPORT = re.compile(
    r"^[ \t]*(?:from|import)[ \t]+(?:Application\.Editor|imgui_bundle)\b",
    re.MULTILINE,
)

# 编辑器专用包（运行时子集要求: 除 Editor 与 Vulkan(WIP) 外不得出现）
_EDITOR_ONLY_IMPORT = re.compile(
    r"^[ \t]*(?:from|import)[ \t]+(?:imgui_bundle|mcp)\b",
    re.MULTILINE,
)
_EDITOR_ONLY_SCAN_EXCLUDE = (
    os.path.join("Application", "Editor"),
    os.path.join("Application", "Core", "Renderer", "Vulkan"),
)

# Runtime 链路（去掉编辑器 UI 后必须能独立导入的模块面）
_RUNTIME_CHAIN = [
    "Application.Core.NodeGraph",
    "Application.Core.NodeGraph.canvas",
    "Application.Core.NodeGraph.graph_constraints",
    "Application.Core.NodeGraph.evaluator_engine",
    "Application.Core.NodeGraph.evaluators.gtec",
    "Application.Core.Engine",
    "Application.Core.Scene.SceneManager",
    "Application.Core.Scene.Scene",
    "Application.Resource.ResourceManager",
    "Application.Runtime.RuntimeWindow",
    "Application.Runtime.RuntimeNodeLayer",
    "Application.Runtime.GameRuntime",
    "Application.Runtime.StubWindow",
    "Application.Runtime.StubRenderer",
    "Application.Functions.SerialParallelDevice",
    "Application.Functions.EEGDevice",
    # 播放器链路（无编辑器运行 — P1b 起; 在上述阻断器下必须全部可导入）
    "Application.Core.Project",
    "Application.Core.Project.RuntimeProjectLoader",
    "Application.Runtime.PlayerBootstrap",
    "Application.PlayerEntry",
]


def test_source_scan() -> None:
    print("── Source scan (Core/NodeGraph) ──")
    root = os.path.join(_path_setup._project_root, "Application", "Core", "NodeGraph")
    offenders: list[str] = []
    for base, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(base, fn)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for m in _FORBIDDEN_IMPORT.finditer(text):
                rel = os.path.relpath(path, _path_setup._project_root)
                offenders.append(f"{rel}: {m.group(0).strip()}")
    check(not offenders, f"no forbidden imports ({offenders[:3]})")


def test_editor_only_scan() -> None:
    """运行时树不得 import 编辑器专用包（imgui_bundle / mcp）——
    保证导出运行时子集（requirements.runtime.txt）成立。
    Editor 与 Vulkan(WIP, 未被运行时引用) 目录除外。"""
    print("── Editor-only package scan (Application/** minus Editor/Vulkan) ──")
    root = os.path.join(_path_setup._project_root, "Application")
    offenders: list[str] = []
    for base, dirs, files in os.walk(root):
        rel_base = os.path.relpath(base, _path_setup._project_root)
        if any(
            rel_base == ex or rel_base.startswith(ex + os.sep)
            for ex in _EDITOR_ONLY_SCAN_EXCLUDE
        ):
            dirs[:] = []
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(base, fn)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for m in _EDITOR_ONLY_IMPORT.finditer(text):
                offenders.append(
                    f"{os.path.relpath(path, _path_setup._project_root)}: {m.group(0).strip()}"
                )
    check(not offenders, f"runtime tree free of imgui_bundle/mcp ({offenders[:3]})")


# ═══════════════════════════════════════════════════════════════
# 2/3. 导入阻断器 — 运行时必须活, 编辑器必须死
# ═══════════════════════════════════════════════════════════════

class _BoundaryBlocker:
    """阻断 imgui_bundle 与 Application.Editor 的一切导入。"""

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001
        if (name == "imgui_bundle" or name.startswith("imgui_bundle.")
                or name == "Application.Editor" or name.startswith("Application.Editor.")):
            raise ImportError(f"BLOCKED boundary import: {name}")
        return None


def test_runtime_imports_under_blockers() -> None:
    print("── Runtime chain under blockers (imgui + Editor blocked) ──")
    import importlib

    blocker = _BoundaryBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        ok = True
        for mod in _RUNTIME_CHAIN:
            try:
                importlib.import_module(mod)
            except Exception as e:  # noqa: BLE001
                ok = False
                check(False, f"import {mod} → {e}")
        check(ok, f"all {len(_RUNTIME_CHAIN)} runtime-chain modules import cleanly")
    finally:
        sys.meta_path.remove(blocker)


def test_editor_fails_under_blockers() -> None:
    print("── Editor UI must fail under blockers (sanity) ──")
    import importlib

    blocker = _BoundaryBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        failed = False
        try:
            importlib.import_module("Application.Editor.UI.panels")
        except ImportError as e:
            failed = "BLOCKED" in str(e)
        check(failed, "editor UI correctly blocked without imgui")
    finally:
        sys.meta_path.remove(blocker)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Core.NodeGraph Boundary — Tests")
    print("=" * 60)

    test_source_scan()
    test_editor_only_scan()
    test_runtime_imports_under_blockers()
    test_editor_fails_under_blockers()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
