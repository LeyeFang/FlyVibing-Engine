"""Engine↔extension coupling inventory — a one-way ratchet.

背景（2026-11-14，O9 之后的复查）
--------------------------------
O9（`GameRuntime` 裸 import 串并口扩展）修完后，用户问"是不是还有别的主引擎
→ 扩展依赖"。审计结论：**还有，而且是四个扩展族**，但形态各不相同：

| 类别 | 形态 | 现状 |
|---|---|---|
| A. 运行时启动/收尾 | 硬 import 扩展 | **已清零**（`OptionalExtensions` 接缝 + 本测试 §1） |
| B. 核心实现归扩展的东西 | 183 行别名台账住在 core | **已迁移**（`Core/DeviceAliases` 只留能力凭据 + §2） |
| C. 核心/编辑器**知道扩展节点类型名** | 约束规则 / 编辑器控件 / 布局提示 | **仍有，逐个登记在下面（棘轮）** |
| D. 契约文档写死在 core | `graph_rules.py` 里 SPD/设备族/BCI 的说明 | 仍有（随 `.scene` 分发） |

C 类不能"一口气"搬走：pack 目前只能声明 pins/fields/evaluator/menu，**没有**声明
"我的引脚何时隐藏 / 我的 Init⇄Kill 配对规则 / 我的卡片有什么联动控件"的位置。
搬它需要先设计 pack 扩展点，再让四个扩展族各自迁移 —— 那是另一件工程，不是收尾。

所以这里把它做成**棘轮**：登记每个文件的引用数，只允许**减少**。任何新增
（新文件、或某文件计数变大）立即 FAIL 并给出处理指引。

TIER: core
"""

from __future__ import annotations

import ast
import json
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []

#: 唯一允许触碰 `Application.Functions` 的模块（运行时接缝）
_SEAM = os.path.join("Application", "Core", "Extension", "OptionalExtensions.py")

#: C 类棘轮基线 —— **只许减少**。搬走一处就把数字改小（或删掉整行）。
#: key = 相对仓库根的文件；value = 该文件引用"扩展自有节点类型名"的**代码**次数
#: （AST 统计，文档字符串/注释不算）。
COUPLING_BASELINE: dict[str, int] = {
    # 核心约束引擎：设备池 / SigGen / Epoch / BCI 的 Init⇄Kill / 引用配对
    # → 需要 pack 声明约束（约束规则归扩展）
    "Application/Core/NodeGraph/graph_constraints.py": 19,
    # 编辑器自动布局：给设备族节点留位置（纯观感，可延后）
    "Application/Editor/UI/panels/node_editor/group_layout.py": 7,
    # 扩展节点卡片控件（设备族 / Epoch / BCI）
    "Application/Editor/UI/panels/node_editor/widgets/device_siggen.py": 5,
    "Application/Editor/UI/panels/node_editor/widgets/epoch.py": 5,
    "Application/Editor/UI/panels/node_editor/widgets/algorithm.py": 4,
    "Application/Editor/UI/panels/node_editor/widgets/device_pool.py": 3,
    # 引脚可见性规则（ParallelSend 在 manual 模式隐藏 Value）
    "Application/Editor/UI/panels/node_editor/visible_pins.py": 1,
}

#: 扫描范围（引擎核心 / 运行时 / 编辑器 / 两个入口）
_SCAN_DIRS = ("Application/Core", "Application/Runtime", "Application/Editor")
_SCAN_FILES = ("Application/EntryPoint.py", "Application/PlayerEntry.py")


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


# ── 扩展自有节点类型（读 pack，不 import、不要求启用）────────────────

def _extension_types() -> set:
    """`{type_name}` — 由各扩展的 pack 文件声明（离线、可解析）。

    pack 文件名从 manifest 的 `nodes.module` 推导（加约定名 `node_pack.py`），
    所以这里不需要认识任何具体扩展的名字。
    """
    import re

    funcs = os.path.join(ROOT, "Application", "Functions")
    types: set = set()
    if not os.path.isdir(funcs):
        return types
    for name in sorted(os.listdir(funcs)):
        folder = os.path.join(funcs, name)
        if not os.path.isdir(folder):
            continue
        candidates = ["node_pack.py"]
        manifest = os.path.join(folder, "extension.json")
        try:
            spec = (json.load(open(manifest, encoding="utf-8")).get("nodes") or {})
            module = str(spec.get("module") or "").strip()
            if module:
                candidates.append(f"{module.split('.')[-1]}.py")
        except (OSError, ValueError):
            pass
        for fname in candidates:
            path = os.path.join(folder, fname)
            if not os.path.isfile(path):
                continue
            try:
                src = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            types |= set(re.findall(r'"type":\s*"([A-Za-z0-9_.]+)"', src))
            types |= set(re.findall(r'"(ext\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+)"', src))
            types |= set(re.findall(r'\("([A-Z][A-Za-z0-9_]+)",\s*"[A-Za-z0-9_.]+"\)', src))
    return {t for t in types if t and len(t) > 3}


# ── AST：区分代码引用与文档提及 ─────────────────────────────────────

def _docstring_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


def _code_string_counts(path: str, owned: set) -> dict:
    """{type_name: 次数} — 只看代码里的字符串常量（排除 docstring）。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return {}
    skip = _docstring_ids(tree)
    counts: dict = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        if node.value in owned:
            counts[node.value] = counts.get(node.value, 0) + 1
    return counts


def _iter_sources():
    for rel in _SCAN_DIRS:
        for cur, dirs, files in os.walk(os.path.join(ROOT, rel)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(cur, name)
    for rel in _SCAN_FILES:
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            yield path


def main() -> int:
    print("=" * 68)
    print("Engine <-> extension coupling inventory (one-way ratchet)")
    print("=" * 68)

    owned = _extension_types()
    check("extension packs declare node types (offline parse)",
          len(owned) >= 10, f"{len(owned)} type(s)")

    # ── 1. 运行时接缝之外不得有 Application.Functions **代码**引用 ────
    violations: list[str] = []
    for path in _iter_sources():
        rel = os.path.relpath(path, ROOT)
        if os.path.normcase(rel) == os.path.normcase(_SEAM):
            continue
        try:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
        except (OSError, SyntaxError):
            continue
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            hit = ""
            if isinstance(node, ast.Import):
                hit = next((a.name for a in node.names
                            if a.name.startswith("Application.Functions")), "")
            elif isinstance(node, ast.ImportFrom):
                if str(node.module or "").startswith("Application.Functions"):
                    hit = f"from {node.module} import ..."
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 允许**纯命名空间前缀** `"Application.Functions."`（能力发现用，拼包限定名）;
                # 具体的 `Application.Functions.<Ext>` 仍然禁止。
                if (id(node) not in skip
                        and node.value.startswith("Application.Functions.")
                        and len(node.value) > len("Application.Functions.")):
                    hit = f'"{node.value}"'
            if hit:
                violations.append(f"{rel}:{node.lineno} {hit}")
    check("no code-level Application.Functions reference outside the seam",
          not violations, "; ".join(violations[:3]))

    # ── 2. 核心不得再持有扩展实现（别名台账已迁走）───────────────────
    check("core no longer ships a device alias ledger implementation",
          not os.path.isfile(os.path.join(ROOT, "Application", "Core", "DeviceRegistry.py")))
    check("core offers the neutral alias capability instead",
          os.path.isfile(os.path.join(ROOT, "Application", "Core", "DeviceAliases.py")))
    from Application.Core import DeviceAliases

    check("alias capability degrades safely without any extension",
          isinstance(DeviceAliases.names(), list) and DeviceAliases.get("nobody") is None)

    # ── 2b. 能力提供者：按 manifest 声明发现，且与扩展自身 import 同一模块 ──
    #     这条锁的是"功能完备"——旧实现（Core.DeviceRegistry）直接读文件，
    #     所以离线校验器/扩展未启用的编辑器都能拿到别名。迁移后必须保持：
    #     - 有人声明 `device_aliases.module`（离线可读，核心不认识扩展名）
    #     - 发现到的 provider 与 `from Application.Functions.X import module` 是
    #       **同一个模块对象**（否则两份内存缓存 → 刚绑的别名看不到）
    declared = DeviceAliases._declared_providers()        # noqa: SLF001 — 端口用例
    check("at least one extension declares the device alias capability",
          bool(declared), str(declared))
    check("declared provider resolves to a package-qualified module",
          all(m.startswith("Application.Functions.") for m, _d in declared), str(declared))
    check("alias capability is available through lazy discovery (no manual import)",
          DeviceAliases.ensure() is True)
    import importlib

    for qualified, _directory in declared:
        module = importlib.import_module(qualified)
        check(f"discovered provider IS the normally imported module ({qualified})",
              DeviceAliases.provider() is module,
              f"{getattr(DeviceAliases.provider(), '__name__', '?')} vs {module.__name__}")
        break

    # ── 3. C 类棘轮：已有耦合只许减少 ────────────────────────────
    actual = {}
    for path in _iter_sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        counts = _code_string_counts(path, owned)
        if counts:
            actual[rel] = sum(counts.values())

    grew: list[str] = []
    appeared: list[str] = []
    for rel, total in sorted(actual.items()):
        allowed = COUPLING_BASELINE.get(rel)
        if allowed is None:
            appeared.append(f"{rel} ({total})")
        elif total > allowed:
            grew.append(f"{rel}: {allowed} -> {total}")
    check("no NEW file couples to extension-owned node types",
          not appeared, "; ".join(appeared[:3]))
    check("no file grew its coupling count", not grew, "; ".join(grew[:3]))

    shrank = [f"{rel}: {COUPLING_BASELINE[rel]} -> {actual.get(rel, 0)}"
              for rel in COUPLING_BASELINE if actual.get(rel, 0) < COUPLING_BASELINE[rel]]
    check("ratchet files are still present (baseline not stale)",
          all(os.path.isfile(os.path.join(ROOT, rel.replace("/", os.sep)))
              for rel in COUPLING_BASELINE),
          str([r for r in COUPLING_BASELINE
               if not os.path.isfile(os.path.join(ROOT, r.replace("/", os.sep)))][:2]))

    total_now = sum(actual.values())
    total_base = sum(COUPLING_BASELINE.values())
    print(f"\n  coupling: {total_now} code reference(s) in {len(actual)} file(s) "
          f"(baseline {total_base})")
    if shrank:
        print(f"  ↓ moved out — please lower COUPLING_BASELINE: {shrank}")
    if total_now > total_base:
        print(f"  ↑ grew by {total_now - total_base}")

    check("total coupling did not exceed the recorded baseline",
          total_now <= total_base, f"{total_base} -> {total_now}")

    print("-" * 68)
    print(f"  {_passed} passed, {len(_failed)} failed")
    if _failed:
        for label in _failed:
            print(f"  FAILED: {label}")
        print("\n  处理指引: 引擎不得新写依赖扩展节点名的代码。")
        print("  - 运行时/收尾 → Application.Core.Extension.OptionalExtensions")
        print("  - 别名等同机器侧能力 → Application.Core.DeviceAliases")
        print("  - 节点卡片/引脚/约束 → 等 pack 扩展点（roadmap），不要往 core 里加")
        return 1
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
