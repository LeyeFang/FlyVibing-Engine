"""
NodeEditor agent 通道离线测试（v0.2.0: 4 工具 + 分节规则 + CLI）。

覆盖:
  1. 工具集: 4 工具 / 无 validate_graph / schema 预算 < 2000 字符
  2. get_rules: 目录（默认）/ 单节 / 子标题 / all / 未知节提示
  3. build_graph(spec) → apply_graph → 临时 scene 往返
  4. CLI: rules / entities / build / apply（含 --out 落盘摘要与 stdin 模式）

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/NodeGraph/test_node_editor_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
ROOT = _d
if ROOT and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import flyvibing_node_editor.rule_sections as rule_sections  # noqa: E402
from flyvibing_node_editor import mcp_server  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _run_cli(args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "flyvibing_node_editor.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
    )
    return proc.returncode, proc.stdout, proc.stderr


MIN_SPEC = {
    "entities": ["Cross"],
    "init_delay": 0.1,
    "trials": 2,
    "timer": "t",
    "phases": [
        {"time": 0, "type": "action", "show": ["Cross"]},
        {"time": 1, "type": "trial_end"},
    ],
}

SCENE = {
    "scene": {
        "name": "T",
        "entities": {"1": {"name": "Cross", "components": {}, "parent_id": None}},
        "node_graph": {},
    }
}


def main() -> int:
    print("== NodeEditor MCP/CLI offline tests ==")
    tmp = tempfile.mkdtemp(prefix="nodeeditor_test_")
    try:
        # ── 1. 工具集与 schema 预算 ──
        tools = asyncio.run(mcp_server.mcp.list_tools())
        names = sorted(t.name for t in tools)
        check("4 tools", names == ["apply_graph", "build_graph", "get_rules", "get_scene_entities"], str(names))
        check("validate_graph removed", "validate_graph" not in names)
        payload = json.dumps(
            [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema} for t in tools],
            ensure_ascii=False,
        )
        check("schema budget < 2000 chars", len(payload) < 2000, f"now {len(payload)}")

        # ── 2. get_rules 分节 ──
        outline = mcp_server.get_rules()
        check(
            "outline default (目录)",
            "目录" in outline and "Connection Rules" in outline and "build_graph Spec" in outline,
        )
        full = rule_sections.load_rules()
        check("outline < 20% of full", len(outline) < len(full) * 0.2, f"{len(outline)} vs {len(full)}")
        sec = mcp_server.get_rules("Connection Rules")
        check("section fetch", "never cross" in sec and "Execution Model" not in sec, f"{len(sec)} chars")
        sig = mcp_server.get_rules("SigGen")
        check("subsection fetch", "InitSigGenDevice" in sig and "InitFBCSP" not in sig, f"{len(sig)} chars")
        spec_sec = mcp_server.get_rules("build_graph Spec")
        check("spec section", '"phases"' in spec_sec and "trial_end" in spec_sec, f"{len(spec_sec)} chars")
        check("all == full", mcp_server.get_rules("all") == full)
        unknown = mcp_server.get_rules("zzz")
        check("unknown section hint", "unknown section" in unknown and "SigGen" in unknown)

        # ── 3. build/apply 往返 ──
        r = mcp_server.build_graph(MIN_SPEC)
        check("build_graph counts", r.get("node_count", 0) > 0 and r.get("link_count", 0) > 0, str(r.get("node_count")))
        scene_path = os.path.join(tmp, "t.scene")
        with open(scene_path, "w", encoding="utf-8") as fh:
            json.dump(SCENE, fh)
        a = mcp_server.apply_graph(scene_path, r["graph"])
        check("apply_graph ok", a.get("success") is True, str(a))
        with open(scene_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        check("scene updated", len(saved["scene"]["node_graph"]["nodes"]) == r["node_count"])

        # ── 4. CLI ──
        code, out, err = _run_cli(["rules"])
        check("cli rules outline", code == 0 and "目录" in out, err or out[:200])
        code, out, err = _run_cli(["rules", "Connection Rules"])
        check("cli rules section", code == 0 and "never cross" in out, err or out[:200])
        full_md = os.path.join(tmp, "full.md")
        code, out, err = _run_cli(["rules", "--all", "--out", full_md])
        check(
            "cli rules --out summary", code == 0 and '"chars"' in out and os.path.isfile(full_md), err or out
        )
        code, out, err = _run_cli(["rules", "zzz"])
        check("cli unknown section exit 2", code == 2, f"code={code}")

        spec_path = os.path.join(tmp, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as fh:
            json.dump(MIN_SPEC, fh)
        graph_path = os.path.join(tmp, "graph.json")
        code, out, err = _run_cli(["build", "--spec", spec_path, "--out", graph_path])
        check(
            "cli build --out", code == 0 and '"node_count"' in out and os.path.isfile(graph_path), err or out
        )
        scene2 = os.path.join(tmp, "t2.scene")
        with open(scene2, "w", encoding="utf-8") as fh:
            json.dump(SCENE, fh)
        code, out, err = _run_cli(["apply", "--scene", scene2, "--graph", graph_path])
        check("cli apply", code == 0 and '"success": true' in out, err or out)
        code, out, err = _run_cli(["entities", scene2])
        check("cli entities", code == 0 and '"Cross"' in out and '"total": 1' in out, err or out)
        code, out, err = _run_cli(["build", "--spec", os.path.join(tmp, "nope.json"), "--out", graph_path])
        check("cli missing spec exit 2", code == 2, f"code={code}")
        code, out, err = _run_cli(["build", "--spec", "-"], stdin=json.dumps(MIN_SPEC))
        check("cli build stdin", code == 0 and '"graph"' in out, err or out[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("RESULT: OK (all checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
