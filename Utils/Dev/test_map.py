"""测试节点地图 CLI — 查询、生成、校验 Doc/Dev/test_nodes.json。

设计:
  - 一个 test_*.py = 一个 test node（与 test_runner 的一文件一子进程一致）；
  - 节点之间的边只表达静态关系，不建立执行顺序依赖；
  - Doc/Dev/test_nodes.json 是机器唯一事实源，Doc/Dev/test_nodes.md 由本工具生成；
  - 当前不依赖 PyYAML，保持仓库现有 venv 可直接运行。

用法:
    python Utils/Dev/test_map.py init [--force]
    python Utils/Dev/test_map.py list [--tier core] [--kind unit] [--owner core.scene]
    python Utils/Dev/test_map.py show <node-id>
    python Utils/Dev/test_map.py affected Application/Core/Scene/SceneManager.py
    python Utils/Dev/test_map.py render [--check]
    python Utils/Dev/test_map.py check [--json]
    python Utils/Dev/test_map.py ui tree|check|render|show|affected|tests
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

# ── 路径与常量 ────────────────────────────────────────────────

_ROOT = Path(__file__).resolve()
while _ROOT and not (_ROOT / "startup.bat").exists():
    _parent = _ROOT.parent
    if _parent == _ROOT:
        _ROOT = None
        break
    _ROOT = _parent
if _ROOT is None:
    raise SystemExit("cannot locate repo root (startup.bat)")

ROOT = _ROOT
TEST_ROOT = ROOT / "Test" / "Application"
# Test/ 采用局部白名单；地图属于开发文档，放 Doc/Dev 以便版本控制。
MAP_PATH = ROOT / "Doc" / "Dev" / "test_nodes.json"
DOC_PATH = ROOT / "Doc" / "Dev" / "test_nodes.md"
UI_MAP_PATH = ROOT / "Doc" / "Dev" / "ui_map.json"
UI_DOC_PATH = ROOT / "Doc" / "Dev" / "ui_map.md"
OPS_PATH = ROOT / "Utils" / ("Ext" + "Dev") / "EditorMcp" / "src" / "engine_editor_mcp" / "ops.py"
TIERS = ("core", "gui", "heavy", "live", "manual")
KINDS = (
    "unit",
    "contract",
    "integration",
    "ui-behavior",
    "ui-visual",
    "e2e",
    "stress",
    "manual",
)
SCHEMA_VERSION = 1


def _dev_path() -> None:
    """让直接执行和 test import 都能复用 test_runner 的 tier 分类。"""
    dev = str(ROOT / "Utils" / "Dev")
    if dev not in sys.path:
        sys.path.insert(0, dev)


def _tier(path: Path, rel: str) -> str:
    try:
        _dev_path()
        import test_runner  # type: ignore

        return test_runner._classify(path, rel)
    except Exception:
        # 离线兜底：与 test_runner 的主要规则保持一致，避免工具无法运行。
        head = "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[:60]
        )
        import re

        match = re.search(r"TIER\s*[:=]\s*['\"]?(core|gui|heavy|live|manual)", head, re.I)
        if match:
            return match.group(1).lower()
        name = path.name.lower()
        if "e2e_" in name:
            return "live"
        if any(h in name for h in ("live_ui", "node_runtime")):
            return "manual"
        if "export_game_bundle" in name:
            return "heavy"
        if any(h in name for h in ("gizmo", "grid", "outliner")):
            return "gui"
        if any(h in rel for h in ("Core/Renderer", "Core/Window")):
            return "gui"
        return "core"


def _kind(path: Path, tier: str) -> str:
    name = path.stem
    if tier == "manual":
        return "manual"
    if tier == "heavy" or "stress" in path.parts:
        return "stress"
    if any(
        token in name
        for token in (
            "action_contract",
            "mcp_package",
            "i18n_coverage",
            "imgui_hygiene",
            "imgui_stack_pairing",
            "ui_text_safety",
            "utils_layout",
            "node_graph_boundary",
            "thread_boundary",
            "extension_review",
            "test_map",
        )
    ):
        return "contract"
    if "scene_panel_interactions" in name or "extension_ui" in name or "virtual_panel" in name:
        return "ui-behavior"
    if "gl_" in name or "light_gizmo" in name:
        return "integration"
    if name in {
        "test_math",
        "test_canvas_metadata",
        "test_canvas_optional_pin_ids",
        "test_node_pack",
        "test_scalar_math_ops",
        "test_compare_timer_lazy",
    }:
        return "unit"
    return "integration"


def _owner(path: Path) -> str:
    parts = list(path.relative_to(TEST_ROOT).parts)
    if not parts:
        return "unknown"
    head = parts[0]
    if head == "Core":
        if len(parts) > 1 and (TEST_ROOT / parts[0] / parts[1]).is_dir():
            sub = parts[1].lower()
            if sub in ("scenegraph", "scene"):
                return "core.scene"
            if sub == "nodegraph":
                return "nodegraph"
            return f"core.{sub}"
        return "core"
    if head == "Editor":
        return "editor"
    if head == "Extensions":
        return "extensions"
    if head == "Functions":
        if len(parts) > 1 and (TEST_ROOT / parts[0] / parts[1]).is_dir():
            return f"functions.{parts[1].lower()}"
        return "functions"
    if head in ("NodeGraph",):
        return "nodegraph"
    if head in ("Renderer", "Media", "Text", "Runtime"):
        return head.lower()
    if head == "stress":
        return "stress"
    return head.lower()


def _imports(path: Path) -> list[str]:
    """从测试文件 AST 提取 Application 模块依赖（不含具体符号）。"""
    found: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("Application"):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("Application"):
                found.add(node.module)
    # `Application.Core` / `Application.Editor` 这类包根会匹配整个子树，
    # 不能作为精确的依赖线索；保留具体子模块（>=3 段）。
    return sorted(m for m in found if len(m.split(".")) >= 3)


def _requirements(tier: str, path: Path) -> list[str]:
    if tier == "live":
        return ["running editor"]
    if tier == "manual":
        return ["interactive session"]
    if tier == "gui":
        return ["GL window"]
    if tier == "heavy":
        return ["sandbox project fixture"]
    if "gl_" in path.stem or "light_gizmo" in path.stem:
        return ["OpenGL window"]
    return []


def _node_id(path: Path) -> str:
    rel = path.relative_to(TEST_ROOT).with_suffix("")
    parts = list(rel.parts)
    parts[-1] = parts[-1][5:] if parts[-1].startswith("test_") else parts[-1]
    return ".".join(p.lower() for p in parts)


def discover_tests() -> list[tuple[Path, str]]:
    if not TEST_ROOT.is_dir():
        return []
    return [
        (path, str(path.relative_to(ROOT)).replace("\\", "/"))
        for path in sorted(TEST_ROOT.rglob("test_*.py"))
    ]


def build_map() -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for path, rel in discover_tests():
        tier = _tier(path, rel)
        nodes.append(
            {
                "id": _node_id(path),
                "path": rel,
                "tier": tier,
                "kind": _kind(path, tier),
                "owner": _owner(path),
                "covers": _imports(path),
                "requires": _requirements(tier, path),
                "exercises": [],
                "visualizes": [],
            }
        )
    return {
        "schema": SCHEMA_VERSION,
        "source": "Test/Application/**/test_*.py",
        "map_path": "Doc/Dev/test_nodes.json",
        "nodes": nodes,
    }


def load_map() -> dict[str, Any]:
    if not MAP_PATH.is_file():
        raise SystemExit(f"map not found: {MAP_PATH} (run: test_map.py init)")
    try:
        data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot load {MAP_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{MAP_PATH}: top-level JSON must be an object")
    return data


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _module_file(module: str) -> Path | None:
    """把 Application.X.Y 解析到 .py、/__init__.py 或命名空间包目录。"""
    rel = Path(*module.split("."))
    candidates = (ROOT / rel.with_suffix(".py"), ROOT / rel / "__init__.py", ROOT / rel)
    return next((p for p in candidates if p.exists()), None)


def _cover_exists(cover: str) -> bool:
    if cover.endswith(".py") or "/" in cover or "\\" in cover:
        return (ROOT / cover).is_file()
    # 允许 covers 写成 module.symbol；逐级截断寻找可导入模块。
    parts = cover.split(".")
    for end in range(len(parts), 0, -1):
        if _module_file(".".join(parts[:end])) is not None:
            return True
    return False


def check_map(data: dict[str, Any] | None = None) -> list[str]:
    data = load_map() if data is None else data
    errors: list[str] = []
    if data.get("schema") != SCHEMA_VERSION:
        errors.append(f"schema must be {SCHEMA_VERSION}, got {data.get('schema')!r}")
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return errors + ["nodes must be a list"]

    expected = {rel for _path, rel in discover_tests()}
    mapped: set[str] = set()
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = str(node.get("id") or "").strip()
        path = str(node.get("path") or "").strip()
        tier = str(node.get("tier") or "").strip()
        kind = str(node.get("kind") or "").strip()
        owner = str(node.get("owner") or "").strip()
        label = node_id or f"nodes[{index}]"
        if not node_id:
            errors.append(f"{label}: id is required")
        elif node_id in ids:
            errors.append(f"{label}: duplicate id")
        ids.add(node_id)
        if not path:
            errors.append(f"{label}: path is required")
            continue
        if path in mapped:
            errors.append(f"{label}: duplicate path {path}")
        mapped.add(path)
        p = ROOT / path
        if not p.is_file():
            errors.append(f"{label}: test path not found: {path}")
        if not path.startswith("Test/Application/"):
            errors.append(f"{label}: test must live under Test/Application/: {path}")
        if tier not in TIERS:
            errors.append(f"{label}: invalid tier {tier!r}")
        if kind not in KINDS:
            errors.append(f"{label}: invalid kind {kind!r}")
        if not owner:
            errors.append(f"{label}: owner is required")
        for field in ("covers", "requires", "exercises", "visualizes"):
            if not isinstance(node.get(field), list):
                errors.append(f"{label}: {field} must be a list")
        for cover in _as_list(node.get("covers")):
            if not isinstance(cover, str) or not cover.strip():
                errors.append(f"{label}: covers entries must be non-empty strings")
            elif not _cover_exists(cover):
                errors.append(f"{label}: cover not found: {cover}")

    missing = sorted(expected - mapped)
    extra = sorted(mapped - expected)
    for path in missing:
        errors.append(f"unmapped test: {path}")
    for path in extra:
        errors.append(f"map points to non-test file: {path}")
    return errors


def _normalise_target(target: str) -> tuple[str, str]:
    """返回 (module, path-or-empty)。"""
    raw = target.strip().replace("\\", "/")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    if path.exists() and path.is_file():
        try:
            rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            rel = raw
        if rel.endswith(".py"):
            parts = rel[:-3].split("/")
            if parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts), rel
    if raw.endswith(".py"):
        parts = raw[:-3].split("/")
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts), raw
    return raw, ""


def _matches(cover: str, module: str) -> bool:
    # 只做精确匹配：包根（如 Application.Core.Scene）不能把整棵子树的
    # 测试都算成某文件的受影响测试；需要时在 covers 中写具体模块。
    return cover == module


def affected(targets: list[str], data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = load_map() if data is None else data
    wanted = [_normalise_target(t) for t in targets]
    hits: dict[str, dict[str, Any]] = {}
    for node in _as_list(data.get("nodes")):
        if not isinstance(node, dict):
            continue
        node_path = str(node.get("path") or "")
        covers = [str(c) for c in _as_list(node.get("covers"))]
        for module, path in wanted:
            if node_path == path:
                hits[str(node.get("id"))] = {**node, "_reason": f"path:{path}"}
                continue
            for cover in covers:
                if _matches(cover, module):
                    hits[str(node.get("id"))] = {**node, "_reason": f"covers:{cover}"}
                    break
    return sorted(hits.values(), key=lambda n: (TIERS.index(n["tier"]), n["id"]))


def _format_node(node: dict[str, Any]) -> str:
    lines = [
        f"{node.get('id')}  [{node.get('tier')}/{node.get('kind')}]  owner={node.get('owner')}",
        f"  path: {node.get('path')}",
    ]
    for field in ("covers", "requires", "exercises", "visualizes"):
        values = _as_list(node.get(field))
        if values:
            lines.append(f"  {field}:")
            lines.extend(f"    - {value}" for value in values)
    if node.get("_reason"):
        lines.append(f"  reason: {node['_reason']}")
    return "\n".join(lines)


def render_markdown(data: dict[str, Any] | None = None) -> str:
    data = load_map() if data is None else data
    nodes = [n for n in _as_list(data.get("nodes")) if isinstance(n, dict)]
    lines = [
        "# 测试节点速查（自动生成）",
        "",
        " > 源：`Doc/Dev/test_nodes.json`。请修改 JSON 后运行 `python Utils/Dev/test_map.py render`，不要手改本文件。",
        "> 测试节点之间不表示执行顺序；`covers` 是静态覆盖关系。",
        "",
        "## 概览",
        "",
        f"- 节点数：**{len(nodes)}**",
    ]
    for tier in TIERS:
        count = sum(1 for n in nodes if n.get("tier") == tier)
        if count:
            lines.append(f"- `{tier}`：{count}")
    lines.append("")
    lines.extend(
        [
            "## 全部节点",
            "",
            "| id | tier | kind | owner | test | covers |",
            "|---|---|---|---|---|---|",
        ]
    )
    for node in sorted(nodes, key=lambda n: str(n.get("id"))):
        covers = "<br>".join(str(c) for c in _as_list(node.get("covers"))) or "-"
        lines.append(
            f"| `{node.get('id')}` | `{node.get('tier')}` | `{node.get('kind')}` | "
            f"`{node.get('owner')}` | `{node.get('path')}` | {covers} |"
        )
    lines.append("")
    return "\n".join(lines)


# ── UI map ────────────────────────────────────────────────────


def load_ui_map() -> dict[str, Any]:
    if not UI_MAP_PATH.is_file():
        raise SystemExit(f"ui map not found: {UI_MAP_PATH}")
    try:
        data = json.loads(UI_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot load {UI_MAP_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{UI_MAP_PATH}: top-level JSON must be an object")
    return data


def _ui_controls(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in _as_list(data.get("controls")) if isinstance(c, dict)]


def known_ops() -> set[str] | None:
    """从 tools repo 的 ops.py 读取 public op 名称；未链接工具仓库时返回 None。"""
    if not OPS_PATH.is_file():
        return None
    try:
        tree = ast.parse(OPS_PATH.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    names: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "OpSpec" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.add(node.args[0].value)
    return names or None


def _ui_action_coverage(data: dict[str, Any]) -> dict[str, Any]:
    mapped = {str(action) for control in _ui_controls(data)
              for action in _as_list(control.get("actions"))}
    agent_only = {str(action) for action in _as_list(data.get("agent_only"))}
    known = known_ops()
    if known is None:
        return {"available": False, "mapped": mapped, "agent_only": agent_only,
                "missing": set(), "unknown": set()}
    # frame.* 是 engine_capture 的内部实现；仍记录在 agent_only，不要求 UI 控件。
    required = known - agent_only - {"frame.request", "frame.fetch"}
    return {
        "available": True,
        "known": known,
        "mapped": mapped,
        "agent_only": agent_only,
        "missing": required - mapped,
        "unknown": mapped - known,
    }


def check_ui_map(data: dict[str, Any] | None = None) -> list[str]:
    data = load_ui_map() if data is None else data
    errors: list[str] = []
    if data.get("schema") != SCHEMA_VERSION:
        errors.append(f"ui schema must be {SCHEMA_VERSION}, got {data.get('schema')!r}")

    states: dict[str, dict[str, Any]] = {}
    for index, state in enumerate(_as_list(data.get("states"))):
        if not isinstance(state, dict):
            errors.append(f"states[{index}] must be an object")
            continue
        sid = str(state.get("id") or "").strip()
        if not sid:
            errors.append(f"states[{index}]: id is required")
            continue
        if sid in states:
            errors.append(f"{sid}: duplicate state id")
        states[sid] = state

    for sid, state in states.items():
        for req in _as_list(state.get("requires")):
            if req not in states:
                errors.append(f"{sid}: unknown required state {req!r}")

    controls: dict[str, dict[str, Any]] = {}
    for index, control in enumerate(_ui_controls(data)):
        cid = str(control.get("id") or "").strip()
        if not cid:
            errors.append(f"controls[{index}]: id is required")
            continue
        if cid in controls:
            errors.append(f"{cid}: duplicate control id")
        controls[cid] = control
        for field in ("label", "kind", "owner", "source"):
            if not str(control.get(field) or "").strip():
                errors.append(f"{cid}: {field} is required")
        source = str(control.get("source") or "")
        if source and not (ROOT / source).exists():
            errors.append(f"{cid}: source not found: {source}")

    # Cross-references require the full control set; validate after collection.
    for cid, control in controls.items():
        parent = control.get("parent")
        if parent is not None and parent not in controls:
            errors.append(f"{cid}: parent control not found: {parent!r}")
        for state in _as_list(control.get("visible_when")):
            if state not in states:
                errors.append(f"{cid}: visible_when state not found: {state!r}")
        for opened in _as_list(control.get("opens")):
            if opened not in controls:
                errors.append(f"{cid}: opens control not found: {opened!r}")
        for field in ("actions", "tests", "scenarios"):
            if not isinstance(control.get(field), list):
                errors.append(f"{cid}: {field} must be a list")

    # UI map tests/scenarios must point at known nodes/files.
    try:
        node_data = load_map()
        node_ids = {str(n.get("id")) for n in _as_list(node_data.get("nodes")) if isinstance(n, dict)}
    except SystemExit:
        node_ids = set()
    for cid, control in controls.items():
        for test_id in _as_list(control.get("tests")):
            if node_ids and test_id not in node_ids:
                errors.append(f"{cid}: test node not found: {test_id!r}")
        for scenario in _as_list(control.get("scenarios")):
            path = TEST_ROOT / "Editor" / "scenarios" / f"{scenario}.py"
            if not path.is_file():
                errors.append(f"{cid}: scenario not found: {path.relative_to(ROOT)}")

    coverage = _ui_action_coverage(data)
    if coverage.get("available"):
        for action in sorted(coverage["unknown"]):
            errors.append(f"ui action not in ops.py: {action!r}")
        for action in sorted(coverage["missing"]):
            errors.append(f"public op has no UI/agent_only mapping: {action!r}")
    for action in sorted(_as_list(data.get("agent_only"))):
        if coverage.get("available") and action not in coverage["known"]:
            errors.append(f"agent_only op not found: {action!r}")

    # Parent/opening graph cycles are a data error, not an execution dependency.
    for cid in controls:
        seen: set[str] = set()
        current: Any = cid
        while current is not None:
            if current in seen:
                errors.append(f"{cid}: control parent cycle at {current!r}")
                break
            seen.add(current)
            parent = controls.get(current, {}).get("parent")
            current = parent
    return errors


def _ui_tree_lines(data: dict[str, Any]) -> list[str]:
    controls = _ui_controls(data)
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for control in controls:
        by_parent.setdefault(control.get("parent"), []).append(control)
    lines: list[str] = []

    def visit(control: dict[str, Any], depth: int) -> None:
        prefix = "  " * depth + ("- " if depth else "")
        flags = []
        if control.get("visible_when"):
            flags.append("when=" + ",".join(str(s) for s in control["visible_when"]))
        if control.get("actions"):
            flags.append("actions=" + ",".join(str(a) for a in control["actions"]))
        suffix = "  " + " ".join(flags) if flags else ""
        lines.append(f"{prefix}{control.get('id')} [{control.get('kind')}] "
                     f"owner={control.get('owner')}{suffix}")
        for child in by_parent.get(control.get("id"), []):
            visit(child, depth + 1)

    for root in by_parent.get(None, []):
        visit(root, 0)
    return lines


def _ui_affected(target: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = target.strip().replace("\\", "/")
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    rel = ""
    try:
        rel = p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        rel = raw
    hits = []
    for control in _ui_controls(data):
        source = str(control.get("source") or "").replace("\\", "/")
        if source == rel or source.startswith(rel.rstrip("/") + "/") or rel.startswith(source + "/"):
            hits.append(control)
    return hits


def _format_ui_control(control: dict[str, Any]) -> str:
    lines = [f"{control.get('id')} [{control.get('kind')}] owner={control.get('owner')}",
             f"  source: {control.get('source')}"]
    for field in ("parent", "visible_when", "actions", "opens", "tests", "scenarios"):
        value = control.get(field)
        if value:
            lines.append(f"  {field}: {value}")
    return "\n".join(lines)


def render_ui_markdown(data: dict[str, Any] | None = None) -> str:
    data = load_ui_map() if data is None else data
    controls = _ui_controls(data)
    lines = [
        "# UI 展开图速查（自动生成）",
        "",
        "> 源：`Doc/Dev/ui_map.json`。修改 JSON 后运行 `python Utils/Dev/test_map.py ui render`，不要手改本文件。",
        "",
        "## 控件树",
        "",
        "```text",
        *_ui_tree_lines(data),
        "```",
        "",
        "## 控件",
        "",
        "| id | kind | owner | visible_when | actions | tests | scenarios | source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for control in controls:
        def cell(field: str) -> str:
            value = control.get(field)
            if isinstance(value, list):
                return ", ".join(str(v) for v in value) or "-"
            return str(value or "-")
        lines.append(
            f"| `{control.get('id')}` | `{control.get('kind')}` | `{control.get('owner')}` | "
            f"{cell('visible_when')} | {cell('actions')} | {cell('tests')} | "
            f"{cell('scenarios')} | `{control.get('source')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _cmd_ui(args: argparse.Namespace) -> int:
    data = load_ui_map()
    if args.ui_action == "render":
        rendered = render_ui_markdown(data)
        if args.check:
            if not UI_DOC_PATH.is_file():
                print(f"[ui-map] missing generated doc: {UI_DOC_PATH}", file=sys.stderr)
                return 1
            if UI_DOC_PATH.read_text(encoding="utf-8") != rendered:
                print(f"[ui-map] generated doc is stale: {UI_DOC_PATH}", file=sys.stderr)
                return 1
            print(f"[ui-map] generated doc is current: {UI_DOC_PATH}")
            return 0
        UI_DOC_PATH.write_text(rendered, encoding="utf-8")
        print(f"[ui-map] wrote {UI_DOC_PATH}")
        return 0

    if args.ui_action == "check":
        errors = check_ui_map(data)
        if args.json:
            print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        elif errors:
            print(f"[ui-map] FAIL ({len(errors)} issue(s))")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[ui-map] OK ({len(_ui_controls(data))} controls)")
        return 0 if not errors else 1

    if args.ui_action == "coverage":
        cov = _ui_action_coverage(data)
        if args.json:
            print(json.dumps({k: sorted(v) if isinstance(v, set) else v
                              for k, v in cov.items()}, ensure_ascii=False, indent=2))
        elif not cov.get("available"):
            print("[ui-map] ops.py unavailable; link the tools repo to enable coverage")
        else:
            print(f"[ui-map] known={len(cov['known'])} mapped={len(cov['mapped'])} "
                  f"agent_only={len(cov['agent_only'])}")
            print(f"  missing: {sorted(cov['missing']) or '-'}")
            print(f"  unknown: {sorted(cov['unknown']) or '-'}")
        return 0 if not cov.get("missing") and not cov.get("unknown") else 1

    if args.ui_action == "tree":
        print("\n".join(_ui_tree_lines(data)))
        return 0

    if not args.target:
        print(f"[ui-map] {args.ui_action} requires a target", file=sys.stderr)
        return 2

    if args.ui_action == "affected":
        hits = _ui_affected(args.target, data)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        elif not hits:
            print("[ui-map] no matching control")
            return 1
        else:
            for control in hits:
                print(_format_ui_control(control))
                print()
        return 0 if hits else 1

    control = next((c for c in _ui_controls(data) if c.get("id") == args.target), None)
    if control is None:
        print(f"[ui-map] control not found: {args.target}", file=sys.stderr)
        return 2
    if args.ui_action == "show":
        print(_format_ui_control(control) if not args.json
              else json.dumps(control, ensure_ascii=False, indent=2))
        return 0
    if args.ui_action == "tests":
        tests = _as_list(control.get("tests"))
        print("\n".join(str(t) for t in tests) if tests else "[ui-map] no tests")
        return 0 if tests else 1
    return 2


def _cmd_init(args: argparse.Namespace) -> int:
    if MAP_PATH.exists() and not args.force:
        print(f"[test-map] {MAP_PATH} already exists; use --force to regenerate")
        return 2
    data = build_map()
    MAP_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[test-map] wrote {MAP_PATH} ({len(data['nodes'])} nodes)")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    data = load_map()
    nodes = [n for n in _as_list(data.get("nodes")) if isinstance(n, dict)]
    tier = (args.tier or "").lower()
    kind = (args.kind or "").lower()
    owner = (args.owner or "").lower()
    nodes = [
        n
        for n in nodes
        if (not tier or str(n.get("tier", "")).lower() == tier)
        and (not kind or str(n.get("kind", "")).lower() == kind)
        and (not owner or str(n.get("owner", "")).lower() == owner)
    ]
    nodes.sort(key=lambda n: (str(n.get("tier")), str(n.get("id"))))
    if args.json:
        print(json.dumps(nodes, ensure_ascii=False, indent=2))
    else:
        for node in nodes:
            print(f"[{node.get('tier'):6s}] {node.get('kind'):12s} {node.get('id')}")
        print(f"\n{len(nodes)} node(s)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    data = load_map()
    node = next(
        (n for n in _as_list(data.get("nodes")) if isinstance(n, dict) and n.get("id") == args.id),
        None,
    )
    if node is None:
        print(f"[test-map] node not found: {args.id}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(node, ensure_ascii=False, indent=2))
    else:
        print(_format_node(node))
    return 0


def _cmd_affected(args: argparse.Namespace) -> int:
    data = load_map()
    nodes = affected(args.targets, data)
    if args.json:
        print(json.dumps(nodes, ensure_ascii=False, indent=2))
        return 0
    if not nodes:
        print("[test-map] no matching test node")
        return 1
    print(f"[test-map] {len(nodes)} related node(s):")
    for node in nodes:
        print()
        print(_format_node(node))
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    data = load_map()
    rendered = render_markdown(data)
    if args.check:
        if not DOC_PATH.is_file():
            print(f"[test-map] missing generated doc: {DOC_PATH}", file=sys.stderr)
            return 1
        current = DOC_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(f"[test-map] generated doc is stale: {DOC_PATH}", file=sys.stderr)
            return 1
        print(f"[test-map] generated doc is current: {DOC_PATH}")
        return 0
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(rendered, encoding="utf-8")
    print(f"[test-map] wrote {DOC_PATH}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    data = load_map()
    errors = check_map(data)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "nodes": len(_as_list(data.get("nodes"))),
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif errors:
        print(f"[test-map] FAIL ({len(errors)} issue(s))")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"[test-map] OK ({len(_as_list(data.get('nodes')))} nodes)")
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test_map", description="测试节点地图 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="从 Test/Application/**/test_*.py 生成基线")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=_cmd_init)

    list_cmd = sub.add_parser("list", help="列出节点")
    list_cmd.add_argument("--tier", default="")
    list_cmd.add_argument("--kind", default="")
    list_cmd.add_argument("--owner", default="")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=_cmd_list)

    show = sub.add_parser("show", help="查看一个节点")
    show.add_argument("id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=_cmd_show)

    aff = sub.add_parser("affected", help="源码路径/模块 → 相关测试节点")
    aff.add_argument("targets", nargs="+")
    aff.add_argument("--json", action="store_true")
    aff.set_defaults(func=_cmd_affected)

    render = sub.add_parser("render", help="生成人读 Markdown 速查表")
    render.add_argument("--check", action="store_true")
    render.set_defaults(func=_cmd_render)

    check = sub.add_parser("check", help="校验地图完整性")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_cmd_check)

    ui = sub.add_parser("ui", help="UI 展开图查询/校验")
    ui.add_argument("ui_action", choices=("tree", "show", "affected", "tests", "check", "coverage", "render"))
    ui.add_argument("target", nargs="?")
    ui.add_argument("--json", action="store_true")
    ui.add_argument("--check", action="store_true", help="render: 只检查生成文档是否最新")
    ui.set_defaults(func=_cmd_ui)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
