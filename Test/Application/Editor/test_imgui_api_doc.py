"""imgui 控件目录守卫 — 生成物新鲜 + 分组表完整 + CLI 可寻址。

守三件事（对应 `Doc/Dev/imgui_api.md` 与 `Utils/Dev/imgui_docgen.py`）：

  1. **产物新鲜**：工具仓 `docs_content/dev/imgui_api.md` == 现渲染内容。
     升级 `imgui_bundle` 或改了分组表却忘了重新生成 → 这里红。
  2. **分组表可信**：写的函数必须在当前库里存在、不重复收录。
  3. **引擎用到的都被归类**：仓库里调用过 `imgui.<fn>` 而 `<fn>` 不在分组表 → 报未归类，
     提醒补一行文档（避免控件用法长在代码里、文档里却查不到）。

另外验证 CLI 能按节取（`doc show dev/imgui_api#8` = 表格）—— 文档只有能被 CLI 定位才有意义。

TIER: core

Usage:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_imgui_api_doc.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
while ROOT and not (ROOT / "startup.bat").exists():
    parent = ROOT.parent
    if parent == ROOT:
        ROOT = None
        break
    ROOT = parent
assert ROOT is not None, "repo root not found (startup.bat)"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Utils" / "Dev"))

import imgui_docgen  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def main() -> int:
    print("=" * 60)
    print("imgui control catalog — freshness / grouping / CLI addressing")
    print("=" * 60)

    resolved = imgui_docgen.default_out_path()
    check("tools repo reachable (engine_editor_mcp importable)", bool(resolved),
          "工具仓不可用：本机没装 engine-editor-cli 时会跳过产物检查")
    out_path = Path(resolved) if resolved else Path(os.devnull)

    # ── 1. 产物存在且新鲜 ──
    print("-- 1. generated doc --")
    check("doc file exists", out_path.is_file(), str(out_path))
    rendered = imgui_docgen.render()
    current = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    check("doc is fresh (regenerate with Utils/Dev/imgui_docgen.py)",
          current == rendered,
          "run: python Utils/Dev/imgui_docgen.py")
    check("doc is generated (has header + footer marker)",
          "生成" in rendered.split("\n")[0] or "生成" in rendered[:600],
          rendered[:120].replace("\n", " "))
    check("doc has both language-neutral sections and appendix",
          rendered.count("\n## ") >= 16, str(rendered.count("\n## ")))

    # ── 2. 分组表可信 ──
    print("-- 2. group table --")
    unknown = imgui_docgen.unknown_group_names()
    check("every grouped function exists in imgui_bundle", not unknown, str(unknown[:8]))
    dup = imgui_docgen.duplicates()
    check("no function listed in two groups", not dup, str(dup))

    imgui = imgui_docgen._imgui()
    grouped = imgui_docgen.grouped_names()
    examples = ("begin_table", "table_next_row", "begin_popup_modal", "input_text",
                "drag_float", "selectable", "begin_child", "push_style_color")
    missing = [n for n in examples if n not in grouped]
    check("high-traffic controls are grouped", not missing, str(missing))

    # ── 3. 引擎用到的都被归类 ──
    print("-- 3. coverage --")
    loose = imgui_docgen.unclassified_used()
    check("every imgui function used in the repo is classified", not loose, str(loose[:10]))

    usage = imgui_docgen.usage_counts()
    check("the catalog covers the bulk of real call sites", len(usage) > 50, str(len(usage)))
    check("grouped surface is bigger than what we use today",
          len(grouped) > len([n for n in usage if callable(getattr(imgui, n, None))]),
          f"grouped={len(grouped)} used={len(usage)}")

    # ── 4. CLI 可寻址 ──
    print("-- 4. doc CLI addressing --")
    try:
        from engine_editor_mcp import doclib

        outline = doclib.outline("dev/imgui_api")
        check("doc outline lists the catalog sections",
              "表格" in outline and "flag 速查" in outline, outline[:160].replace("\n", " "))
        table_section = doclib.show("dev/imgui_api", "8")
        check("doc show #8 returns the table section",
              table_section.startswith("## 8. 表格"), table_section[:60].replace("\n", " "))
        hits = doclib.search("begin_table")
        check("doc search finds a control", "imgui_api" in hits, hits[:120].replace("\n", " "))
    except Exception as exc:  # 工具仓不可用时不阻塞引擎测试
        check("doc CLI readable (skipped: tools repo unavailable)", False, repr(exc))

    print()
    total = 12
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)}): {', '.join(_failures)}")
        return 1
    print(f"RESULT: OK ({total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
