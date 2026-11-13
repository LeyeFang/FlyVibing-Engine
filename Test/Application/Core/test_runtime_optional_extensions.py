"""Runtime must never hard-depend on an extension (O9).

事故（2026-11-14，外部扩展报告 O9）
----------------------------------
`Application/Runtime/GameRuntime.py` 在 `init` / `run` / `stop` 三处裸 import
`Application.Functions.SerialParallelDevice`。导出器按**场景实际用到的节点类型**
决定带哪些扩展目录，于是一个不用 SPD 节点的场景（纯采集 / 纯展示 / 纯核心）导出的
成品里没有该目录 → 启动直接:

    ModuleNotFoundError: No module named 'Application.Functions.SerialParallelDevice'
    [ERROR] Player exited with an unhandled exception

连窗口都起不来。之前一直没暴露，是因为所有"能跑"的示例都用 `ParallelSend` 打标，
SPD 恰好被带上。

本测试锁住修复后的不变量：

1. **接缝唯一** —— `Application/Core/**` 与 `Application/Runtime/**` 中，除
   `OptionalExtensions` 外**不得**出现 `Application.Functions` 引用（AST 扫描，
   模块级与函数级都算）；
2. **缺席不是错误** —— 扩展不可见时 `call()` 返回 `absent` 且不抛，
   `start_io()` 返回 False 且不抛（这就是成品形态）；
3. **存在但坏掉是硬错误** —— `required=True` 时上抛（设备 I/O 起不来还继续
   跑实验 = 静默丢刺激）；`required=False` 只告警，用于关闭/清理路径；
4. **可用性判据与导出器一致** —— 看的是**目录**，不是 import 成功与否。

TIER: core
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import types

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []

#: 唯一允许触碰 `Application.Functions` 的模块（接缝本身）
_SEAM = os.path.join("Application", "Core", "Extension", "OptionalExtensions.py")

#: 扫描范围：引擎核心 + 运行时（编辑器可以有扩展管理器，不在其列）
_SCAN_DIRS = (os.path.join("Application", "Core"),
              os.path.join("Application", "Runtime"))
_SCAN_FILES = (os.path.join("Application", "EntryPoint.py"),
               os.path.join("Application", "PlayerEntry.py"))


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _iter_sources():
    for rel in _SCAN_DIRS:
        base = os.path.join(ROOT, rel)
        for cur, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(cur, name)
    for rel in _SCAN_FILES:
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            yield path


def _functions_refs(path: str) -> list:
    """一个文件里所有 `Application.Functions...` 引用 → [(行号, 形式)]。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    hits: list = []
    for node in ast.walk(tree):
        # import Application.Functions.X / from Application.Functions.X import y
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("Application.Functions"):
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if str(node.module or "").startswith("Application.Functions"):
                hits.append((node.lineno, f"from {node.module} import ..."))
        # 字符串形式（importlib / find_spec / 延迟 import 拼装）
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("Application.Functions."):
                hits.append((node.lineno, f'"{node.value}"'))
    return hits


def main() -> int:
    print("=" * 64)
    print("Runtime must never hard-depend on an extension (O9)")
    print("=" * 64)

    from Application.Core.Extension import OptionalExtensions as Opt

    # ── 1. 接缝唯一（AST 扫描）────────────────────────────────
    violations: list[str] = []
    scanned = 0
    for path in _iter_sources():
        scanned += 1
        if os.path.normcase(os.path.relpath(path, ROOT)) == os.path.normcase(_SEAM):
            continue
        for lineno, form in _functions_refs(path):
            violations.append(f"{os.path.relpath(path, ROOT)}:{lineno} {form}")
    check("no Application.Functions reference outside the OptionalExtensions seam",
          not violations, "; ".join(violations[:3]))
    check("scan actually covered the runtime tree", scanned >= 10, f"scanned={scanned}")

    # ── 2. 缺席 = 正常（成品形态）────────────────────────────
    absent = "ZZNotAnExtension_%d" % os.getpid()
    check("available() is False for a missing extension", Opt.available(absent) is False)
    ok, detail = Opt.call(absent, "start", "runtime", required=True)
    check("call(required=True) does NOT raise when the extension is absent",
          ok is False and detail == "absent", f"{ok}/{detail}")
    started = Opt.start_io("runtime")
    check("start_io() mirrors availability (no raise either way)",
          started is Opt.available("SerialParallelDevice"),
          f"started={started} available={Opt.available('SerialParallelDevice')}")
    Opt.stop_io("runtime")       # 不应抛
    Opt.stop_all_io()            # 不应抛
    check("stop_io/stop_all_io are safe whichever way", True)

    # ── 3. 存在但坏掉 = 硬错误（start）/ 仅告警（清理）────────
    reg = "ZZFakeExt_%d" % os.getpid()
    pkg_parent = "Application.Functions"
    fake_dir = tempfile.mkdtemp(prefix="mge_o9_ext_")
    fake_pkg = types.ModuleType(pkg_parent)
    fake_pkg.__path__ = [fake_dir]          # `from Application.Functions import <reg>`
    fake_mod = types.ModuleType(f"{pkg_parent}.{reg}")

    def _boom(*_a, **_k):
        raise OSError("device busy")

    fake_mod.start = _boom
    fake_mod.stop = _boom
    real_dir_fn = Opt._extension_dir           # noqa: SLF001 — 端口用例
    saved = {k: sys.modules.get(k) for k in (pkg_parent, f"{pkg_parent}.{reg}")}
    try:
        # 让 available() 走"目录存在"分支：临时指向那个假目录
        Opt._extension_dir = lambda name: (          # noqa: SLF001
            fake_dir if name == reg else real_dir_fn(name))
        sys.modules[pkg_parent] = fake_pkg
        sys.modules[f"{pkg_parent}.{reg}"] = fake_mod
        check("available() sees an injected extension", Opt.available(reg) is True)

        raised = False
        try:
            Opt.call(reg, "start", "runtime", required=True)
        except OSError:
            raised = True
        check("call(required=True) propagates a real failure", raised)

        ok, detail = Opt.call(reg, "start", "runtime", required=False)
        check("call(required=False) only warns", ok is False and "device busy" in detail,
              f"{ok}/{detail}")

        missing_fn_raised = False
        try:
            Opt.call(reg, "no_such_function", required=True)
        except AttributeError:
            missing_fn_raised = True
        check("call(required=True) raises when the function is missing",
              missing_fn_raised)

        mod = Opt.module(reg)
        check("module() returns the injected module", mod is fake_mod)
        check("module() returns None for a missing extension",
              Opt.module(absent) is None)
    finally:
        Opt._extension_dir = real_dir_fn           # noqa: SLF001
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    # ── 4. 判据与导出器一致：目录存在即"可见" ────────────────
    real = "SerialParallelDevice"
    directory = Opt._extension_dir(real)            # noqa: SLF001 — 端口用例
    check("availability is decided by the extension DIRECTORY (same unit as export)",
          os.path.isdir(directory), directory)
    check("that directory resolves inside this engine tree",
          os.path.normcase(os.path.dirname(os.path.dirname(directory)))
          == os.path.normcase(os.path.join(ROOT, "Application")),
          directory)

    # ── 5. 状态快照能解释"为什么没有设备 I/O" ─────────────────
    snap = Opt.status()
    check("status() lists every registered integration",
          set(snap["integrations"]) == set(Opt.INTEGRATIONS), str(sorted(snap["integrations"])))
    check("status() reports availability per integration",
          all(isinstance(v.get("available"), bool)
              for v in snap["integrations"].values()))
    check("the I/O integration is registered (start_io has something to call)",
          "SerialParallelDevice" in Opt.INTEGRATIONS)

    # ── 6. GameRuntime / PlayerBootstrap 的调用点都在接缝内 ────
    for rel, needles in (
        (os.path.join("Application", "Runtime", "GameRuntime.py"),
         ("start_io(", "stop_io(")),
        (os.path.join("Application", "Runtime", "PlayerBootstrap.py"),
         ("stop_all_io(",)),
    ):
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
            src = fh.read()
        check(f"{os.path.basename(rel)} goes through the seam ({', '.join(needles)})",
              all(n in src for n in needles))

    print("-" * 64)
    print(f"  {_passed} passed, {len(_failed)} failed")
    if _failed:
        for label in _failed:
            print(f"  FAILED: {label}")
        return 1
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
