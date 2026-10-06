"""ops.md 生成器 — 从 ops.py（单一事实源）生成 Skill 的完整 op 参考。

用法:
    python -m engine_editor_mcp.docgen          # 写入 skills/engine-editor/references/ops.md
    python -m engine_editor_mcp.docgen --check  # 与磁盘比对（不一致 → 退出码 1; 测试用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ops as op_registry


def ops_md_path() -> Path:
    return Path(__file__).resolve().parent / "skills" / "engine-editor" / "references" / "ops.md"


def render() -> str:
    lines = [
        "# Engine op 完整参考",
        "",
        "> 由 `python -m engine_editor_mcp.docgen` 从 `ops.py` 生成 — 勿手改。",
        "> CLI: `engine-editor-cli call <op> k=v ...`; MCP(lite): `engine_call(op, args)`。",
        "> 旧工具名可用（如 `editor_run_pie` → `sim.play`）。数组/对象值在终端里请加引号。",
        "",
    ]
    for cat, label in op_registry.CATEGORY_ORDER:
        items = [o for o in op_registry.OPS.values() if o.category == cat and not o.internal]
        if not items:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for spec in items:
            lines.append(f"### `{spec.name}`")
            lines.append("")
            lines.append(spec.summary)
            if spec.detail:
                lines.append("")
                lines.append(spec.detail)
            if spec.params:
                lines.append("")
                for p in spec.params:
                    req = "必填" if p.required else "可选"
                    extra = f" — {p.summary}" if p.summary else ""
                    lines.append(f"- `{p.name}` ({p.kind}, {req}){extra}")
            example = op_registry.example_args(spec)
            lines.append("")
            lines.append(f"- 示例: `engine-editor-cli call {spec.name}" + (f" {example}`" if example else "`"))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine_editor_mcp.docgen")
    ap.add_argument("--check", action="store_true", help="只校验 ops.md 是否与 ops.py 同步")
    ns = ap.parse_args(argv)
    content = render()
    path = ops_md_path()
    if ns.check:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if existing != content:
            print(f"[docgen] OUT OF DATE: {path}", file=sys.stderr)
            return 1
        print("[docgen] ok")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[docgen] wrote {path} ({len(content)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
