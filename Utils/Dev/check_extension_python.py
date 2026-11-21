"""check_extension_python — 扩展依赖契约（`python.runtime`）离线自查 / CI 闸门。

规范唯一来源: `Application/Core/Extension/ExtensionRuntimeDeps.py`（与导出器、成品
`PlayerBootstrap` 共用同一份解析与校验）。本脚本只负责"跑一遍并讲清楚"。

用法::

    # 扫仓库内全部 Application/Functions/*/extension.json
    .venv-py314t\\Scripts\\python.exe Utils/Dev/check_extension_python.py --all

    # 只看某几个扩展目录
    ... check_extension_python.py Application/Functions/Gtec

    # 机器可读（CI / agent）
    ... check_extension_python.py --all --json
    ... check_extension_python.py --all --strict   # WARN 也算失败（发布前用）

    # 顺带用引擎解释器实跑一次 import 自检（更慢，但能抓"装了却 import 不了"）
    ... check_extension_python.py --all --probe

退出码: 0 = 通过（无 FAIL）; 1 = 存在 FAIL; 2 = 用法错误。

检查项::

    D1  manifest 是合法 JSON 对象
    D2  python.runtime 结构合法（mode/requires/probe/optional/path/env/note，未知键报错）
    D3  随产物分发的扩展**必须**显式声明 python.runtime（缺失 = FAIL）
    D4  bundle 模式的环境目录存在且含可执行解释器
    D5  engine 模式的每个 require 能在 wheelhouse / 引擎 venv 里找到来源
    D6  --probe 时用引擎解释器实跑 import（开发期环境的真相）
    D7  源码里 import 的三方模块是否都进了 runtime.probe（漏掉的只在成品节点里炸）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Application.Core.Extension import ExtensionRuntimeDeps as deps  # noqa: E402


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, level: str, ext_id: str, code: str, message: str) -> None:
        self.rows.append({"level": level, "id": ext_id, "code": code, "message": message})

    def fail(self, ext_id: str, code: str, message: str) -> None:
        self.add("FAIL", ext_id, code, message)

    def warn(self, ext_id: str, code: str, message: str) -> None:
        self.add("WARN", ext_id, code, message)

    def ok(self, ext_id: str, code: str, message: str) -> None:
        self.add("OK", ext_id, code, message)

    @property
    def failed(self) -> int:
        return len([r for r in self.rows if r["level"] == "FAIL"])

    @property
    def warned(self) -> int:
        return len([r for r in self.rows if r["level"] == "WARN"])


def _iter_extension_dirs(targets: list[str]) -> list[str]:
    """扩展目录列表（目录本身，或含 `extension.json` 的父目录）。"""
    out: list[str] = []
    for target in targets:
        path = os.path.abspath(target)
        if os.path.isfile(os.path.join(path, "extension.json")):
            out.append(path)
            continue
        if os.path.isfile(path) and os.path.basename(path) == "extension.json":
            out.append(os.path.dirname(path))
            continue
        funcs = os.path.join(path, "Application", "Functions")
        base = funcs if os.path.isdir(funcs) else path
        for name in sorted(os.listdir(base)):
            candidate = os.path.join(base, name)
            if os.path.isfile(os.path.join(candidate, "extension.json")):
                out.append(candidate)
    return out


def _wheel_available(requirement: str) -> str:
    """wheelhouse / 引擎 venv 里能否找到该需求 → 来源描述（空 = 找不到）。"""
    from Application.Editor.Extensions import ExtensionPythonDist as dist

    wheel = dist.find_wheel(requirement, [os.path.join(ROOT, "Resource", "wheels")])
    if wheel:
        return os.path.basename(wheel)
    module = (deps.import_names([requirement]) or [""])[0]
    if module:
        try:
            if importlib.util.find_spec(module) is not None:
                return f"engine venv ({module})"
        except (ImportError, AttributeError, ValueError):
            pass
    return ""


def check_dir(ext_dir: str, report: Report, *, probe: bool = False) -> dict | None:
    ext_id = os.path.basename(ext_dir)
    manifest_path = os.path.join(ext_dir, "extension.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        report.fail(ext_id, "D1", f"extension.json 读取失败: {exc}")
        return None
    if not isinstance(manifest, dict):
        report.fail(ext_id, "D1", "extension.json 必须是 JSON 对象")
        return None
    ext_id = str(manifest.get("id") or ext_id)

    contract = deps.parse(
        manifest, ext_id=ext_id, ext_dir=ext_dir,
        data_dir=_data_dir(ext_id), engine_root=ROOT,
    )
    if contract.problems:
        for problem in contract.problems:
            report.fail(ext_id, "D2", problem)
    else:
        report.ok(ext_id, "D2", contract.summary())

    # D3: 是否随产物分发 → 必须显式声明
    ships = bool(manifest.get("entry")) and (
        "nodes" in (manifest.get("capabilities") or ())
        or isinstance(manifest.get("nodes"), dict)
        or "python" in manifest
    )
    if deps.export_problems(contract, ships_code=ships):
        for problem in deps.export_problems(contract, ships_code=ships):
            if problem in contract.problems:
                continue          # 已在 D2 报过
            report.fail(ext_id, "D3", problem)
            report.warn(ext_id, "D3", "抄这个: " + deps.snippet_for(ext_id).replace("\n", " "))
    elif ships:
        report.ok(ext_id, "D3", "契约已声明（可导出）")

    # D4: bundle 环境
    if contract.mode == "bundle":
        if os.path.isdir(contract.path):
            from Application.Core.Extension.ExtensionPython import _venv_exe

            exe = _venv_exe(contract.path)
            if os.path.isfile(exe):
                report.ok(ext_id, "D4", f"bundle env ok → {exe}")
            else:
                report.fail(ext_id, "D4", f"bundle env 里没有解释器: {contract.path}")
        else:
            report.fail(ext_id, "D4", f"bundle env 目录不存在: {contract.path}")

    # D5: engine 依赖来源
    if contract.mode == "engine":
        for requirement in contract.requires:
            source = _wheel_available(requirement)
            if source:
                report.ok(ext_id, "D5", f"{requirement} ← {source}")
            else:
                report.fail(
                    ext_id, "D5",
                    f"{requirement}: wheelhouse 与引擎 venv 都拿不到 —— "
                    f"跑 Utils/Dev/collect_wheels.py，或把 wheel 放进 "
                    f"{ext_id}/wheels/")

    # D6: 开发期解释器实跑
    if probe and contract.mode == "engine":
        for module in contract.imports:
            ok, detail = deps.probe_module(module)
            if ok:
                report.ok(ext_id, "D6", f"import {module} ok")
            else:
                report.fail(ext_id, "D6", f"import {module} 失败: {detail}")

    # D7: 源码里 import 的三方包，是否都在 runtime.probe 里声明过
    _check_probe_coverage(ext_dir, ext_id, contract, report)

    return contract.to_dict()


#: 扫描时**不进入**的目录（第三方 / 工具生成 — 与引擎同一判定）
def _is_vendor_dir(name: str) -> bool:
    try:
        from Application.Core.FileSystem.VendorDirs import is_vendor_dir as _impl
        return bool(_impl(name))
    except Exception:  # noqa: BLE001 — 引擎包不可用时的兜底
        low = str(name or "").lower()
        return low.startswith(".venv") or low.startswith("venv") or low in {
            "__pycache__", "site-packages", "node_modules", ".git"}


def _third_party_imports(ext_dir: str) -> dict[str, str]:
    """扩展源码里出现的**非 stdlib / 非本地**顶层 import → {模块: 首个相对路径}。

    只取 `import X` / `from X import ...` 的第一段；相对导入（`from . import`）忽略。
    """
    import ast

    local = set()
    try:
        for name in os.listdir(ext_dir):
            stem = name[:-3] if name.endswith(".py") else name
            local.add(stem)
    except OSError:
        pass
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    builtin_skip = {"__future__", "typing", "typing_extensions"}
    #: 只在**编辑器**里存在的包（成品运行时镜像不含它们）—— 不该出现在 probe 里
    editor_only = {"imgui_bundle", "mcp"}
    found: dict[str, str] = {}
    for cur, dirs, files in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if not _is_vendor_dir(d)]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(cur, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError):
                continue
            rel = os.path.relpath(path, ext_dir).replace("\\", "/")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".", 1)[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:            # 相对导入 — 本地模块
                        continue
                    names = [(node.module or "").split(".", 1)[0]]
                else:
                    continue
                for mod in names:
                    if (not mod or mod in found or mod in local or mod in stdlib
                            or mod in builtin_skip or mod in editor_only
                            or mod.startswith("_")):
                        continue
                    if mod in ("Application", "Test", "Utils"):
                        continue          # 引擎/测试侧模块，不属于第三方
                    found[mod] = rel
    return found


def _check_probe_coverage(ext_dir: str, ext_id: str, contract, report: Report) -> None:
    """D7: 用了却没在 `runtime.probe` 里声明的三方模块 → WARN。

    为什么重要（2026-11-17）：成品启动只按 `probe` 列表逐个 `import`。**依赖基础镜像
    的包最容易漏**——作者以为"numpy 肯定有"，镜像一变就 `ModuleNotFoundError`，而且
    报错点在节点求值里（第一次落盘/第一次画图），启动 probe 却全绿。
    """
    if contract.mode == "none":
        return
    declared = {str(m).split(".", 1)[0] for m in contract.imports}
    used = _third_party_imports(ext_dir)
    missing = sorted(m for m in used if m not in declared)
    if not missing:
        report.ok(ext_id, "D7", f"probe 覆盖源码 import（{len(used)} 个三方模块）")
        return
    preview = ", ".join(f"{m}（{used[m]}）" for m in missing[:4])
    report.warn(
        ext_id, "D7",
        f"这些三方模块在源码里用了，但没进 runtime.probe: {preview}"
        + (" …" if len(missing) > 4 else "")
        + " — 成品启动只 probe 声明过的模块；若成品也要用它们，补进 probe，"
          "否则会在节点求值时才炸（硬件 SDK 之类只在编辑器用的可忽略）")


def _data_dir(ext_id: str) -> str:
    from Application.Core import AppIdentity

    base = (AppIdentity.env_get("EXTENSIONS_DATA")
            or AppIdentity.data_dir("extensions_data"))
    return os.path.join(base, ext_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_extension_python",
        description="校验扩展依赖契约（manifest python.runtime）")
    parser.add_argument("targets", nargs="*",
                        help="扩展目录（默认 --all = Application/Functions/*）")
    parser.add_argument("--all", action="store_true", help="扫仓库内全部扩展")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--strict", action="store_true", help="WARN 也视作失败")
    parser.add_argument("--probe", action="store_true",
                        help="用引擎解释器实跑 import 自检（慢）")
    args = parser.parse_args(argv)

    targets = list(args.targets)
    if args.all or not targets:
        targets = [os.path.join(ROOT, "Application", "Functions")]

    ext_dirs = _iter_extension_dirs(targets)
    if not ext_dirs:
        print(f"[check] 没有找到扩展目录: {targets}", file=sys.stderr)
        return 2

    report = Report()
    contracts: dict = {}
    for ext_dir in ext_dirs:
        result = check_dir(ext_dir, report, probe=args.probe)
        if result is not None:
            contracts[str(result.get("id") or os.path.basename(ext_dir))] = result

    if args.json:
        print(json.dumps({
            "root": ROOT,
            "extensions": contracts,
            "rows": report.rows,
            "failed": report.failed,
            "warned": report.warned,
        }, indent=2, ensure_ascii=False))
    else:
        print("=" * 72)
        print("扩展依赖契约检查 — manifest python.runtime")
        print("=" * 72)
        current = ""
        for row in report.rows:
            if row["id"] != current:
                current = row["id"]
                print(f"\n[{current}]")
            print(f"  {row['level']:4} {row['code']}  {row['message']}")
        print("\n" + "-" * 72)
        print(f"  {len(contracts)} extension(s) | FAIL {report.failed} | WARN {report.warned}")
        if not report.failed and not report.warned:
            print("  RESULT: PASS")

    if report.failed or (args.strict and report.warned):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
