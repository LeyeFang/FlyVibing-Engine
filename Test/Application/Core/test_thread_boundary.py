"""
线程边界守卫 — 静态扫描 (协议: Doc/Dev/threading_protocol.md §2/§6)。

规则:
  R1  应用层 `Thread(` 启动点只允许出现在接线清单文件（禁止名单外新线程）
  R2  wired 类文件必须含 ThreadRegistry（注册/心跳已接线）; delegated 类校验被委托目标
  R3  evaluators/ 与 graph_constraints.py 零 threading 依赖（纯逻辑层）

运行: python Utils/Dev/test_runner.py --only thread_boundary
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
APP = os.path.join(ROOT, "Application")

# 本地兼容夹具（git-ignored 本地资产, 非引擎内容 — 品牌独立进程内部线程,
# 不参与引擎线程边界; 与 extension boundary guard 同口径的夹具豁免）
_SKIP_PATHS = (os.path.join(APP, "Functions", "Gtec"),)

# 相对 Application/ 的路径 → 类型:
#   wired          — 启动点直在本文件, 必须已接 ThreadRegistry
#   delegated:<p>  — 本文件仅投递, 目标文件 <p> 必须已接 ThreadRegistry
#   process-local  — 品牌独立进程内部线程（进程隔离; 协议允许, 引擎快照不可见）
SPAWN_SITES = {
    "Core/Engine.py": "wired",
    "Editor/Services/LiveCommandServer.py": "wired",
    "Core/NodeGraph/validation/service.py": "wired",
    "Functions/BCIAlgorithm/Jobs.py": "wired",
    "Functions/VirtualDevice/ServiceClient.py": "wired",
    "Functions/SerialParallelDevice/api.py": "delegated:Functions/SerialParallelDevice/io_thread.py",
}

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        if any(os.path.normcase(dirpath) == os.path.normcase(p)
               or os.path.normcase(dirpath).startswith(os.path.normcase(p) + os.sep)
               for p in _SKIP_PATHS):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def main() -> int:
    print("=" * 60)
    print("Thread Boundary Guards (static scan)")
    print("=" * 60)

    # ── R1/R2: 扫描启动点 ──
    offenders: list[str] = []
    wired_missing: list[str] = []
    scanned = 0
    for path in _iter_py(APP):
        rel = os.path.relpath(path, APP).replace("\\", "/")
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "Thread(" not in text:
            continue
        scanned += 1
        kind = SPAWN_SITES.get(rel)
        if kind is None:
            offenders.append(rel)
            continue
        if kind == "wired" and "ThreadRegistry" not in text:
            wired_missing.append(rel)
        elif kind.startswith("delegated:"):
            target = os.path.join(APP, kind.split(":", 1)[1].replace("/", os.sep))
            target_text = ""
            if os.path.exists(target):
                target_text = open(target, encoding="utf-8", errors="replace").read()
            if "ThreadRegistry" not in target_text:
                wired_missing.append(f"{rel} -> {kind.split(':', 1)[1]}")

    check("R1: no unregistered thread spawn sites", not offenders, str(offenders))
    check("R2: wired spawn sites have ThreadRegistry",
          not wired_missing, str(wired_missing))
    check("scan coverage (spawn-like files >= 6)", scanned >= 6, str(scanned))

    # ── R3: 纯逻辑层零 threading ──
    pure_files = [os.path.join(APP, "Core", "NodeGraph", "graph_constraints.py")]
    for path in _iter_py(os.path.join(APP, "Core", "NodeGraph", "evaluators")):
        pure_files.append(path)
    pure_bad: list[str] = []
    for path in pure_files:
        text = open(path, encoding="utf-8", errors="replace").read()
        if "import threading" in text or "from threading" in text or "Thread(" in text:
            pure_bad.append(os.path.relpath(path, APP))
    check("R3: pure logic layer has no threading", not pure_bad, str(pure_bad))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
