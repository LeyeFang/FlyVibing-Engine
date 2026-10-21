"""
E2E: EditorMcp v0.4.0 实机验收（需引擎运行中 — 先启动 startup.bat）。

覆盖:
  1. lite MCP 工具函数（engine_call / engine_batch / engine_validate_graph / engine_capture）
     — 与 VS Code 中 MCP 客户端走完全相同的代码路径（FastMCP 装饰器返回原函数）。
  2. CLI 通道（engine-editor-cli call / exec / validate / capture）— 终端型 agent 路径。
  3. 旧工具名别名、_unknown_args 提醒、summary 瘦身。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_editor_mcp_v040_check.py [--keep]
    --keep: 结束后不关闭编辑器。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

_keep = "--keep" in sys.argv

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
ROOT = _d
SRC = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine_editor_mcp import server as srv  # noqa: E402
from engine_editor_mcp.client import send  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _run_cli(args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "engine_editor_mcp.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _tiny_graph() -> dict:
    from Application.Core.NodeGraph import _TYPES

    seq = [9000]

    def mk(t: str) -> dict:
        pids = {}
        for p in _TYPES[t].pins:
            seq[0] += 1
            pids[p.name] = seq[0]
        return {"node_type": t, "pos": [0, 0], "props": {}, "pin_ids": pids}

    n1, n2 = mk("OnGameStart"), mk("Print")
    return {
        "version": "0.1.0",
        "nodes": {"1": n1, "2": n2},
        "links": {"1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]}},
        "next_id": seq[0] + 1,
    }


def main() -> int:
    print("== EditorMcp v0.4.0 E2E check ==")
    print("frames dir:", srv.FRAMES_DIR)

    # ── 0. 引擎存活 ──
    st = send("sim.state")
    check("engine alive (sim.state)", "error" not in st, str(st))
    if "error" in st:
        print("RESULT: FAIL (engine not running)")
        return 1

    # ── 1. engine_call：新建/变换/别名/未知参数提醒/未知 op ──
    print("── engine_call ──")
    r = srv.engine_call("entity.add", {"name": "MCP040_A"})
    eid = r.get("entity_id")
    check("engine_call entity.add", isinstance(eid, int), str(r))
    if isinstance(eid, int):
        r = srv.engine_call("entity.transform", {"id": eid, "position": [1.5, 0, 0], "scale": 2})
        check("engine_call entity.transform", "error" not in r, str(r))
        r = srv.engine_call("editor_entity_get", {"id": eid})  # 旧工具名别名
        check("alias editor_entity_get -> entity.get", "error" not in r and r.get("name") == "MCP040_A", str(r))
        r = srv.engine_call("sim.state", {"bogus": 1})
        check("_unknown_args warning", r.get("_unknown_args") == ["bogus"], str(r))
        r = srv.engine_call("no.such.op")
        check("unknown op -> error+hint", "error" in r and "hint" in r, str(r))
        r = srv.engine_call("entity.delete", {"id": eid})
        check("engine_call entity.delete", "error" not in r, str(r))

    # ── 2. engine_batch ──
    print("── engine_batch ──")
    rb = srv.engine_batch([
        {"op": "entity.add", "args": {"name": "MCP040_B"}},
        {"op": "entity.transform", "args": {"name": "MCP040_B", "position": [1, 0, 0]}},
        {"op": "entity.delete", "args": {"name": "MCP040_B"}},
    ])
    check("batch 3/3 ok", rb.get("count") == 3 and all("error" not in x for x in rb.get("results", [])), str(rb))
    rb2 = srv.engine_batch([{"op": "no.such.op"}, {"op": "sim.state"}])
    check("batch stops on error", rb2.get("count") == 1, str(rb2))

    # ── 3. engine_validate_graph（source=graph, summary 默认）──
    print("── engine_validate_graph (summary) ──")
    rv = srv.engine_validate_graph(source="graph", graph=_tiny_graph(), frames=30)
    report = rv.get("report") or {}
    check("validate no error", "error" not in rv, str(rv))
    check("validate ok", report.get("ok") is True, str(report.get("counts")))
    check("summary shape (detail marker)", str(report.get("detail", "")).startswith("summary"), str(report.keys()))
    check("summary counts present", "counts" in report)

    rv_full = srv.engine_validate_graph(source="graph", graph=_tiny_graph(), frames=30, detail="full")
    rf = rv_full.get("report") or {}
    check("full report has log", isinstance(rf.get("log"), list) and len(rf["log"]) > 0, str(rf.keys()))

    # ── 4. engine_capture ──
    print("── engine_capture ──")
    cap = srv.engine_capture("editor")
    ok_cap = isinstance(cap, list) and len(cap) == 2 and "saved:" in str(cap[1])
    path = str(cap[1]).split("saved: ", 1)[-1].strip() if ok_cap else ""
    check("capture returns [image, path]", ok_cap, str(cap)[:200])
    check("capture file exists", bool(path) and os.path.isfile(path), path)

    # ── 5. CLI 通道 ──
    print("── CLI ──")
    code, out, err = _run_cli(["call", "sim.state"])
    check("cli call exit 0", code == 0, err or out)
    check("cli call returns state", '"state"' in out, out)

    script = (
        "r = engine.ok('entity.add', name='MCP040_CLI')\n"
        "eid = r['entity_id']\n"
        "engine.ok('entity.transform', id=eid, position=[2, 0, 0])\n"
        "engine.ok('entity.visible', id=eid, editor=False)\n"
        "engine.ok('entity.delete', id=eid)\n"
        "print('cli-script-ok', eid)\n"
    )
    code, out, err = _run_cli(["exec", "-"], stdin=script)
    check("cli exec exit 0", code == 0, err or out)
    check("cli exec output", "cli-script-ok" in out, out)

    tmp_graph = os.path.join(srv.FRAMES_DIR, "..", "e2e_tiny_graph.json")
    tmp_graph = os.path.abspath(tmp_graph)
    with open(tmp_graph, "w", encoding="utf-8") as fh:
        json.dump(_tiny_graph(), fh)
    code, out, err = _run_cli(["validate", "--source", "graph", "--graph", "@" + tmp_graph, "--frames", "20"])
    check("cli validate exit 0", code == 0, err or out)
    check("cli validate summary", '"detail": "summary' in out or '"detail":"summary' in out, out)
    try:
        os.remove(tmp_graph)
    except OSError:
        pass

    out_png = os.path.join(srv.FRAMES_DIR, "..", "e2e_cli_capture.png")
    out_png = os.path.abspath(out_png)
    code, out, err = _run_cli(["capture", "editor", "--out", out_png])
    check("cli capture exit 0", code == 0, err or out)
    check("cli capture file", os.path.isfile(out_png), out_png)
    for f in (out_png,):
        try:
            os.remove(f)
        except OSError:
            pass

    # ── 6. 收尾 ──
    if not _keep:
        print("── editor.quit ──")
        rq = srv.engine_call("editor.quit")
        check("quit requested", "error" not in rq, str(rq))
    else:
        print("--keep: 编辑器保持运行")

    print()
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("RESULT: OK (all checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
