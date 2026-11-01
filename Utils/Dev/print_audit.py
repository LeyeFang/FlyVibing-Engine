"""生成 `Doc/Dev/print_inventory.md` — 引擎侧裸 print（未走日志/事件系统）清单。

背景（2026-11-01）:
  我们逐步把调试信息迁到 `ctx.emit_log` / `LogBus` / `console.tail`。
  但在迁移完成前，`print(...)` 仍然散落在 Application/ 各处，最高频的（每帧节点求值）
  会把控制台和 `console.tail` 缓冲刷满。本脚本把现状固定成一张可 diff 的表，
  配合 `test_print_inventory` 保证"不新增裸 print 而不被看见"。

用法:
    .venv-py314t\\Scripts\\python.exe Utils/Dev/print_audit.py          # 重写 md
    .venv-py314t\\Scripts\\python.exe Utils/Dev/print_audit.py --check  # 只校验新鲜度
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP = os.path.join(ROOT, "Application")
OUT = os.path.join(ROOT, "Doc", "Dev", "print_inventory.md")

_PRINT_RE = re.compile(r"^\s*print\(")
_SKIP_DIRS = {"__pycache__", "Config", "runtime", "wheels"}

# 热路径判定：这些位置会在每个逻辑帧 / 每次节点执行时跑（最高优先级迁移）
_HOT_PREFIXES = (
    os.path.join("Application", "Core", "NodeGraph", "evaluators"),
)
_HOT_FILES = {
    "Application/Runtime/RuntimeNodeLayer.py",
    "Application/Runtime/RuntimeLayer.py",
    "Application/Runtime/GameRuntime.py",
    "Application/Runtime/RuntimeInputLayer.py",
    "Application/Runtime/RuntimeDebugLayer.py",
}

# 保留项：节点语义本身就是输出（Print / PrintString），不是调试遗留
_KEEP_FILES = {
    "Application/Core/NodeGraph/evaluators/debug.py",
}


def _scan() -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for base, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if _PRINT_RE.match(line):
                            rows.append((rel, lineno, line.strip()))
            except OSError:
                continue
    return rows


def _area(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) >= 2 and parts[1] in ("Core", "Editor", "Runtime", "Functions", "Resource"):
        return parts[1]
    return "other"


def _is_hot(rel: str) -> bool:
    if rel in _KEEP_FILES:
        return False
    return rel in _HOT_FILES or any(rel.startswith(p.replace("\\", "/")) for p in _HOT_PREFIXES)


def render() -> str:
    rows = _scan()
    by_file: dict[str, int] = {}
    for rel, _lineno, _text in rows:
        by_file[rel] = by_file.get(rel, 0) + 1
    by_area: dict[str, int] = {}
    for rel, count in by_file.items():
        area = _area(rel)
        by_area[area] = by_area.get(area, 0) + count

    hot = [(rel, n) for rel, n in by_file.items() if _is_hot(rel)]
    hot_total = sum(n for _rel, n in hot)

    lines: list[str] = []
    lines.append("# 引擎裸 print 清单（生成文件，勿手改）")
    lines.append("")
    lines.append("> 由 `Utils/Dev/print_audit.py` 生成；`test_print_inventory` 校验新鲜度。")
    lines.append("> 范围: `Application/**/*.py` 中行首为 `print(` 的语句（排除 `__pycache__` / `Config`）。")
    lines.append("")
    lines.append("## 1. 汇总")
    lines.append("")
    lines.append("| 区域 | print 条数 |")
    lines.append("|---|---:|")
    for area in sorted(by_area, key=lambda a: (-by_area[a], a)):
        lines.append(f"| {area} | {by_area[area]} |")
    lines.append(f"| **合计** | **{len(rows)}** |")
    lines.append("")
    lines.append(f"热路径（`Core/NodeGraph/evaluators` + 运行时循环层）: **{hot_total}** 条。")
    lines.append("")
    lines.append("保留项（不是调试遗留）: `Application/Core/NodeGraph/evaluators/debug.py`")
    lines.append("（`Print` / `PrintString` 节点的输出语义本身）。")
    lines.append("")
    lines.append("## 2. 热路径（每帧可能执行，优先迁移）")
    lines.append("")
    lines.append("| 文件 | 条数 |")
    lines.append("|---|---:|")
    for rel, n in sorted(hot, key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{rel}` | {n} |")
    lines.append("")
    ext_total = by_area.get("Functions", 0)
    lines.append("")
    lines.append("## 3. 全部文件（按条数降序；`Functions/**` 扩展自有，不计入明细）")
    lines.append("")
    lines.append(f"`Application/Functions/**` 共 **{ext_total}** 条，由各扩展自行治理，不列入本表。")
    lines.append("")
    lines.append("| 文件 | 条数 |")
    lines.append("|---|---:|")
    for rel, n in sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0])):
        if rel.startswith("Application/Functions/"):
            continue
        lines.append(f"| `{rel}` | {n} |")
    lines.append("")
    lines.append("## 4. 迁移约定（2026-11-01 立项）")
    lines.append("")
    lines.append("- **节点求值器（热路径）**: 不再 `print`；需要诊断时用 `ctx.emit_log`（结构化、")
    lines.append("  干跑进收集器；真实运行默认不输出）。错误由 `GraphEvaluator._report_node_error`")
    lines.append("  统一限流打印。")
    lines.append("- **引擎子系统**: 走 `LogBus`（stdout/stderr tee + 环形缓冲），agent 用")
    lines.append("  `console.tail` 读取；不新增行首裸 `print`。")
    lines.append("- **本条目的目标**: 热路径裸 print 归零；其余按区域逐步收敛，")
    lines.append("  新增 print 必须在本清单产生 diff（评审可见）。")
    lines.append("- **后续（未开始）**: Settings ▸ Debug —— 选择 Debug layer 隔离哪些事件类型")
    lines.append("  （已有先例: 键盘/鼠标事件已隔离，窗口 resize 未隔离）。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/check print inventory")
    parser.add_argument("--check", action="store_true", help="只校验文件是否最新")
    args = parser.parse_args()

    text = render()
    if args.check:
        try:
            with open(OUT, encoding="utf-8") as fh:
                current = fh.read()
        except OSError:
            print(f"[print-audit] missing {OUT}")
            return 1
        if current != text:
            print(f"[print-audit] stale: {OUT} — run Utils/Dev/print_audit.py")
            return 1
        print("[print-audit] up to date")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"[print-audit] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
