"""
EditorMcp 独立包离线测试（无引擎、无 GUI）:

  1. op 注册表 vs 引擎 LiveCommandServer 完整性（70 ops）
  2. MCP 档位: lite 6 工具 / schema 预算; full 恢复旧 45 工具 + engine_launch
  3. 兼容符号（dev shim / E2E 脚本契约）: _send/_send_raw/_capture_png/...
  4. CLI: ops / help / call（离线友好错误）/ batch / exec / 未知 op
  5. setup: 向任意工作区安装 skill + mcp.json（dry-run / 安装 / 卸载）
  6. docgen 新鲜度（references/ops.md 与 ops.py 同步）
  7. wheel 构建内容（skills 数据 + engine-editor-cli console script）

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_editor_mcp_package.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        ROOT = ""
        break
    ROOT = parent
assert ROOT, "repo root not found"
SRC = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine_editor_mcp import __version__, docgen, ops  # noqa: E402
from engine_editor_mcp import server  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _run_cli(args: list[str], stdin: str | None = None,
             env_extra: dict[str, str] | None = None) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
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


def test_registry() -> None:
    print("-- 1. op 注册表完整性 --")
    src = os.path.join(ROOT, "Application", "Editor", "Services", "LiveCommandServer.py")
    with open(src, encoding="utf-8") as fh:
        engine_ops = set(re.findall(r'"([a-z_]+\.[a-z_.]+)":\s*cls\._op_', fh.read()))
    check("engine ops found (70)", len(engine_ops) == 70, str(sorted(engine_ops)))
    check("registry covers engine ops", engine_ops <= set(ops.OPS), str(engine_ops - set(ops.OPS)))
    check("no extra registry ops", set(ops.OPS) <= engine_ops, str(set(ops.OPS) - engine_ops))
    check("aliases resolve", ops.resolve("editor_run_pie") == ("sim.play", {}), str(ops.resolve("editor_run_pie")))
    check("alias with defaults", ops.resolve("editor_switch_2d") == ("view.set_mode", {"mode": "2d"}))
    check("unknown alias", ops.resolve("nope") == ("", {}))
    check("internal ops hidden", set(ops.op_names()) == set(ops.OPS) - {"frame.request", "frame.fetch"})

    # 扩展节点包: 内置 Serial pack 自动发现 + 运行期注册/反注册
    from Application.Core.NodeGraph import _TYPES
    from Application.Core.NodeGraph.node_packs import NodePackRegistry

    catalog = {item["type"]: item for item in NodePackRegistry.catalog()}
    check("SerialSend discovered from device pack",
          catalog.get("SerialSend", {}).get("owner") == "device", str(catalog.get("SerialSend")))
    check("SerialSend has pin metadata",
          any(p["name"] == "exec_in" for p in catalog.get("SerialSend", {}).get("pins", [])))
    check("graph.types op registered", "graph.types" in ops.OPS)
    probe = {
        "id": "probe_pack", "owner": "probe_owner",
        "nodes": [{
            "type": "ext.probe.Node", "label": "Probe", "category": "Probe",
            "pins": [{"name": "exec_in", "kind": "exec", "direction": "input"}],
            "fields": [{"key": "gain", "label": "Gain", "kind": "float"}],
        }],
        "menu": [("Probe", [("Probe", "ext.probe.Node")])],
    }
    NodePackRegistry.register(probe)
    check("runtime pack registered", "ext.probe.Node" in _TYPES
          and NodePackRegistry.owner_of("ext.probe.Node") == "probe_owner")
    check("runtime pack fields",
          NodePackRegistry.fields_for("ext.probe.Node"),
          str(NodePackRegistry.fields_for("ext.probe.Node")))
    again = NodePackRegistry.register(probe)
    check("runtime pack re-register is idempotent",
          again.get("types") == ["ext.probe.Node"] and "ext.probe.Node" in _TYPES,
          str(again))
    removed = NodePackRegistry.unregister_owner("probe_owner")
    check("runtime pack unregistered", removed == ["ext.probe.Node"] and "ext.probe.Node" not in _TYPES,
          str(removed))


def test_profiles() -> None:
    print("-- 2. MCP 档位与 schema 预算 --")

    async def tool_sizes() -> dict[str, int]:
        tools = await server.mcp.list_tools()
        return {
            t.name: len(
                json.dumps(
                    {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema},
                    ensure_ascii=False,
                )
            )
            for t in tools
        }

    raw = asyncio.run(tool_sizes())
    check("raw import has both sets (45+6=51)", len(raw) == 51, str(len(raw)))
    check("legacy tools present", {"editor_run_pie", "editor_graph_validate", "editor_capture"} <= set(raw))

    server.apply_profile("lite")
    lite = asyncio.run(tool_sizes())
    check("lite = 6 tools", set(lite) == set(server.LITE_TOOL_NAMES), str(sorted(lite)))
    check("lite includes engine_launch", "engine_launch" in lite, str(sorted(lite)))
    total = sum(lite.values())
    check(f"lite schema budget < 4000 chars (now {total})", total < 4000, str(total))

    server.apply_profile("full")
    full = asyncio.run(tool_sizes())
    lite_only = set(server.LITE_TOOL_NAMES) - set(server._SHARED_TOOL_NAMES)
    check("full drops lite-only tools", not (set(full) & lite_only), str(sorted(set(full) & lite_only)))
    check("full keeps engine_launch (shared)", "engine_launch" in full)
    check("full keeps 45 legacy + launch", len(full) == 46, str(len(full)))

    check("profile parse --profile=full", server._requested_profile(["--profile=full"]) == "full")
    check("profile parse --profile lite", server._requested_profile(["--profile", "lite"]) == "lite")
    os.environ["MGE_MCP_PROFILE"] = "lite"
    try:
        check("profile env when no arg", server._requested_profile([]) == "lite")
        check("arg beats env", server._requested_profile(["--profile", "full"]) == "full")
    finally:
        os.environ.pop("MGE_MCP_PROFILE", None)


def test_compat() -> None:
    print("-- 3. 兼容符号（dev shim / E2E 契约）--")
    for name in (
        "mcp",
        "FRAMES_DIR",
        "DEFAULT_PORT",
        "_send",
        "_send_raw",
        "_port",
        "_capture_png",
        "_encode_and_save",
        "_wipe_frames_dir",
        "apply_profile",
        "main",
    ):
        check(f"server.{name}", hasattr(server, name))
    check("version 0.5.0", __version__ == "0.5.0", __version__)
    check("default port 8977", server.DEFAULT_PORT == 8977)
    os.environ["MGE_EDITOR_MCP_PORT"] = "9123"
    try:
        check("port env override", server._port() == 9123)
    finally:
        os.environ.pop("MGE_EDITOR_MCP_PORT", None)


def test_cli() -> None:
    print("-- 4. CLI --")
    # offline 段强制指向空闲端口 — 真引擎在 8977 运行时也能稳定测"未连接"路径
    import socket
    with socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        _offline_port = str(_s.getsockname()[1])
    offline_env = {"MGE_EDITOR_MCP_PORT": _offline_port}

    code, out, err = _run_cli(["ops"])
    check("ops exit 0", code == 0, err)
    check("ops lists sim.play", "sim.play" in out)

    code, out, err = _run_cli(["help", "entity.add"])
    check("help entity.add exit 0", code == 0, err)
    check("help shows params", "parent" in out and "new_name" not in out)

    code, out, err = _run_cli(["help", "editor_run_pie"])
    check("help alias -> sim.play", code == 0 and "sim.play" in out, out)

    code, out, err = _run_cli(["call", "sim.state"], env_extra=offline_env)
    check("call offline exit 1", code == 1, str(code))
    check("call offline friendly error", "编辑器未运行" in out, out)

    code, out, err = _run_cli(["call", "bogus.op"])
    check("unknown op exit 2", code == 2, str(code))

    code, out, err = _run_cli(["batch", "-"], stdin='[{"op": "sim.state"}]', env_extra=offline_env)
    check("batch runs (offline -> error result)", code == 1 and '"results"' in out, out)

    code, out, err = _run_cli(["batch", "-"], stdin="not json")
    check("batch bad json exit 2", code == 2, str(code))

    code, out, err = _run_cli(["exec", "-"], stdin='print("engine ok:", hasattr(engine, "ok"))')
    check("exec stdin exit 0", code == 0, err)
    check("exec injects engine client", "engine ok: True" in out, out)

    code, out, err = _run_cli(["doc"])
    check("doc list exit 0", code == 0, err)
    check("doc list shows Dev topic", "dev/project_export_protocol" in out, out[:160])
    check("doc index shows secondary headings", "路径规则" in out, out[:300])

    code, out, err = _run_cli(["doc", "dev"])
    check("doc dev area index exit 0", code == 0, err)
    check("doc dev lists pilot topic", "dev/project_export_protocol" in out, out[:160])

    code, out, err = _run_cli(["doc", "show", "dev/project_export_protocol#3"])
    check("doc show #section exit 0", code == 0, err)
    check("doc show #section content", "Save As" in out, out[:160])

    code, out, err = _run_cli(["doc", "show", "bogus/topic"])
    check("doc unknown topic exit 2", code == 2 and "doc:" in err, err[:120])

    code, out, err = _run_cli(["doc", "tools"])
    check("doc tools exit 0", code == 0, err)
    check("doc tools lists dev tools",
          all(n in out for n in ("test_runner", "thread_probe", "i18n_tool", "setup_env")), out[:220])

    code, out, err = _run_cli(["doc", "tool", "test_runner"])
    check("doc tool test_runner exit 0", code == 0, err)
    check("doc tool shows usage", "--tier" in out, out[:200])

    code, out, err = _run_cli(["doc", "tool", "no_such_tool"])
    check("doc tool unknown exit 2", code == 2 and "doc:" in err, err[:120])

    code, out, err = _run_cli(["engines", "--start", "65000", "--end", "65001"])
    check("engines scan exit 0", code == 0, err)
    check("engines scan returns count", '"count": 0' in out, out[:160])

    code, out, err = _run_cli(["launch", "--port", "80", "--timeout", "1"])
    check("launch invalid port exit 1", code == 1, str(code))
    check("launch invalid port error", "1024..65535" in out, out[:240])


def test_setup() -> None:
    print("-- 5. setup（skill + mcp.json）--")
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = _run_cli(["setup", "--workspace", tmp, "--dry-run"])
        check("setup dry-run exit 0", code == 0, err)
        check("dry-run mentions skill", "[dry-run] skill" in out, out)

        code, out, err = _run_cli(["setup", "--workspace", tmp])
        check("setup exit 0", code == 0, err)
        skill_md = os.path.join(tmp, ".github", "skills", "engine-editor", "SKILL.md")
        ops_md = os.path.join(tmp, ".github", "skills", "engine-editor", "references", "ops.md")
        wf_md = os.path.join(tmp, ".github", "skills", "engine-editor", "references", "workflows.md")
        check("skill copied", os.path.isfile(skill_md))
        check("references copied", os.path.isfile(ops_md) and os.path.isfile(wf_md))
        mcp_path = os.path.join(tmp, ".vscode", "mcp.json")
        check("mcp.json written", os.path.isfile(mcp_path))
        if os.path.isfile(mcp_path):
            with open(mcp_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            entry = cfg.get("servers", {}).get("engine-editor-live", {})
            check(
                "mcp entry lite profile",
                list(entry.get("args", []))[-2:] == ["--profile", "lite"],
                json.dumps(entry, ensure_ascii=False),
            )

        code, out, err = _run_cli(["setup", "--workspace", tmp, "--port", "8988",
                                   "--engine-root", ROOT])
        check("setup --port exit 0", code == 0, err)
        if os.path.isfile(mcp_path):
            with open(mcp_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            entry = cfg.get("servers", {}).get("engine-editor-live", {})
            check("mcp entry includes --port",
                  list(entry.get("args", []))[-2:] == ["--port", "8988"],
                  json.dumps(entry, ensure_ascii=False))
            check("mcp entry includes engine root",
                  entry.get("env", {}).get("MGE_ENGINE_ROOT") == ROOT,
                  json.dumps(entry, ensure_ascii=False))

        code, out, err = _run_cli(["setup", "--workspace", tmp, "--uninstall"])
        check("uninstall exit 0", code == 0, err)
        check("skill removed", not os.path.exists(skill_md))
        if os.path.isfile(mcp_path):
            with open(mcp_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            check("mcp entry removed", "engine-editor-live" not in cfg.get("servers", {}))


def test_docgen() -> None:
    print("-- 6. docgen 新鲜度 --")
    path = docgen.ops_md_path()
    check("ops.md exists", path.is_file(), str(path))
    if path.is_file():
        check("ops.md fresh (regenerate with docgen)", path.read_text(encoding="utf-8") == docgen.render())


def test_doc() -> None:
    print("-- 7. doc CLI + 指针 stub 守卫 --")
    from engine_editor_mcp import doclib

    topics = doclib.list_all()
    check("doc list has pilot topic", "dev/project_export_protocol" in topics, topics[:200])
    check("index has purpose line", "面向:" in topics, topics[:300])
    check("index has secondary headings",
          "职责与文件地图" in topics and "路径规则" in topics, topics[:300])
    ol = doclib.outline("dev/project_export_protocol")
    check("outline has previews", "—" in ol and "面向:" in ol, ol[:300])
    section = doclib.show("dev/project_export_protocol", "3")
    check("doc show #3 returns section", "Save As" in section, section[:120])
    hits = doclib.search("提交点")
    check("doc search finds hits", "dev/project_export_protocol" in hits, hits[:160])

    tools = doclib.list_tools()
    check("tool index lists core dev tools",
          all(n in tools for n in ("test_runner", "thread_probe", "i18n_tool", "setup_env")), tools[:220])
    usage = doclib.tool_help("thread_probe")
    check("tool help has usage", "--assert-alive" in usage, usage[:200])
    try:
        doclib.tool_help("no_such_tool")
        check("tool unknown raises ValueError", False)
    except ValueError as e:
        check("tool unknown raises ValueError", "未知工具" in str(e), str(e))

    # 迁移约束: 内容在 CLI (docs_content), 引擎仓 Doc/** 只留指针 stub — 一一对应
    area_dirs = {"dev": "Doc/Dev", "extdev": "Doc/ExtDev"}
    missing: list[str] = []
    for topic, _path in doclib._iter_topics():
        area, name = topic.split("/", 1)
        stub = os.path.join(ROOT, *area_dirs[area].split("/"), f"{name}.md")
        if not os.path.isfile(stub):
            missing.append(topic)
            continue
        text = open(stub, encoding="utf-8").read()
        if f"doc show {topic}" not in text:
            missing.append(topic)
    check("engine Doc stubs point at CLI", not missing, str(missing))


def test_wheel() -> None:
    print("-- 8. wheel 构建 --")
    builder = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "build_wheel.py")
    proc = subprocess.run(
        [sys.executable, builder],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    check("build exit 0", proc.returncode == 0, proc.stderr or proc.stdout)
    wheel = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "dist", f"engine_editor_mcp-{__version__}-py3-none-any.whl")
    check("wheel exists", os.path.isfile(wheel), wheel)
    if os.path.isfile(wheel):
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
            ep = zf.read(f"engine_editor_mcp-{__version__}.dist-info/entry_points.txt").decode("utf-8")
        check("wheel has skill payload", "engine_editor_mcp/skills/engine-editor/SKILL.md" in names)
        check("wheel has ops.md", any(n.endswith("references/ops.md") for n in names))
        check("wheel has docs payload (doc CLI)",
              "engine_editor_mcp/docs_content/dev/project_export_protocol.md" in names)
        check("wheel has cli.py", "engine_editor_mcp/cli.py" in names)
        check("wheel cli console script", "engine-editor-cli" in ep)


def main() -> int:
    print("== EditorMcp 独立包离线测试 ==")
    test_registry()
    test_profiles()
    test_compat()
    test_cli()
    test_setup()
    test_docgen()
    test_doc()
    test_wheel()
    print()
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("RESULT: OK (all checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
