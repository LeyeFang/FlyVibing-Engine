"""engine-editor-cli — 编辑器实时控制的终端入口（零常驻上下文成本）。

任意终端型 agent 平台（Codex / Copilot / Claude Code / Cursor ...）均可直接调用;
与 MCP 同一 wheel、同一 op 注册表（ops.py）与 socket 客户端（client.py）。

用法:
    engine-editor-cli ops                        # op 目录（按需获取，不常驻）
    engine-editor-cli help <op|topic>            # 单 op 详情 / 主题（cli, mcp, skill, capture）
    engine-editor-cli call <op> k=v ...          # 单 op（值先按 JSON 解析，失败按字符串）
    engine-editor-cli call <op> --json '{...}'   # 完整 args（或 @file.json）
    engine-editor-cli batch ops.json             # 顺序批处理（- = stdin）
    engine-editor-cli exec script.py             # 脚本模式（注入全局 engine 客户端）
    engine-editor-cli validate [--detail full]   # 图干跑校验（阻塞编排）
    engine-editor-cli capture [editor|pie]       # 抓帧落盘（只回路径）
    engine-editor-cli probe [editor|pie] --points 160:120;200:240
                                                 # 像素采样（裸帧 → 指定点 RGBA; 顶左坐标）
    engine-editor-cli setup [--workspace DIR]    # 向任意工作区安装 skill + mcp.json

退出码: 0 成功 / 1 引擎或运行时错误 / 2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from . import ops as op_registry
from .client import (
    EngineClient,
    EngineError,
    capture_png,
    execute_calls,
    fetch_raw_frame,
    send_raw,
    validate_graph_orchestrate,
)

_SKILL_DIR_NAME = "engine-editor"
_SKILL_TARGETS = {
    "github": ".github/skills",
    "claude": ".claude/skills",
    "agents": ".agents/skills",
}


# ── 输出 / 解析小工具 ──


def _out(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _fail(message: str, code: int = 1) -> int:
    sys.stderr.write(message.rstrip() + "\n")
    return code


def _coerce(value: str):
    """值解析: 先尝试 JSON（数字/bool/数组/对象/引号字符串），失败按纯字符串。"""
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _parse_kv(pairs: list[str]) -> dict:
    args: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"参数应为 k=v 形式: {pair!r}")
        key, _, raw = pair.partition("=")
        args[key.strip()] = _coerce(raw)
    return args


def _load_json_arg(raw: str) -> dict:
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(raw)


def _send_checked(name: str, args: dict) -> dict:
    """发送 op（含 prepare_args 适配；返回结果或 {"error"}）。"""
    result, _payload = send_raw(name, op_registry.prepare_args(name, args), timeout=op_registry.call_timeout(name))
    return result


# ── 子命令 ──


def cmd_ops(_ns) -> int:
    print(op_registry.format_ops_list())
    return 0


def cmd_help(ns) -> int:
    topic = (ns.topic or "").strip()
    if topic in op_registry.TOPIC_HELP:
        print(op_registry.TOPIC_HELP[topic])
    else:
        print(op_registry.format_op_help(topic))
    return 0


def cmd_call(ns) -> int:
    name, defaults = op_registry.resolve(ns.op)
    if not name:
        print(op_registry.format_op_help(ns.op), file=sys.stderr)
        return 2
    try:
        kv = _parse_kv(ns.kv)
        if ns.json:
            kv = {**_load_json_arg(ns.json), **kv}
    except (OSError, ValueError) as e:
        return _fail(f"参数解析失败: {e}", 2)
    args = dict(defaults)
    args.update(kv)
    result = _send_checked(name, args)
    unknown = op_registry.unknown_args(name, args)
    if unknown and "error" not in result:
        result = dict(result)
        result["_unknown_args"] = unknown
    result = op_registry.trim_result(name, result, ns.detail)
    _out(result)
    return 1 if "error" in result else 0


def cmd_batch(ns) -> int:
    try:
        if ns.file == "-":
            payload = json.load(sys.stdin)
        else:
            with open(ns.file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
    except (OSError, ValueError) as e:
        return _fail(f"batch 输入读取失败: {e}", 2)
    if isinstance(payload, dict):
        payload = payload.get("calls")
    if not isinstance(payload, list) or not payload:
        return _fail("batch 输入应为 [{op, args}, ...]（或 {\"calls\": [...]}）", 2)
    results = execute_calls(payload, ns.continue_)
    _out({"count": len(results), "results": results})
    return 1 if any("error" in r for r in results) else 0


def cmd_exec(ns) -> int:
    script = ns.script
    if script != "-" and not os.path.isfile(script):
        return _fail(f"script not found: {script}", 2)
    client = EngineClient(timeout=ns.timeout)
    init_globals = {
        "engine": client,
        "EngineError": EngineError,
        "json": json,
        "time": time,
        "ops": op_registry,
    }
    old_argv = sys.argv
    sys.argv = [str(script)] + list(ns.args or [])
    try:
        if script == "-":
            code = sys.stdin.read()
            exec(compile(code, "<stdin>", "exec"), {"__name__": "__main__", **init_globals})
        else:
            runpy.run_path(str(script), run_name="__main__", init_globals=init_globals)
        return 0
    except EngineError as e:
        return _fail(f"engine error: {e}", 1)
    except SystemExit as e:
        return int(e.code or 0)
    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    finally:
        sys.argv = old_argv


def cmd_validate(ns) -> int:
    graph = None
    if ns.graph:
        try:
            graph = _load_json_arg(ns.graph)
        except (OSError, ValueError) as e:
            return _fail(f"--graph 解析失败: {e}", 2)
    result = validate_graph_orchestrate(
        source=ns.source,
        graph=graph,
        frames=ns.frames,
        verbose=bool(ns.verbose),
        seed=ns.seed,
        save_path=ns.save,
        timeout_s=ns.timeout,
    )
    report = result.get("report")
    if isinstance(report, dict):
        result = dict(result)
        result["report"] = op_registry.summarize_report(report) if ns.detail == "summary" else report
    _out(result)
    return 1 if "error" in result else 0


def cmd_capture(ns) -> int:
    try:
        path, png_bytes = capture_png(ns.target, ns.timeout)
    except EngineError as e:
        return _fail(f"capture failed: {e}", 1)
    out_path = path
    if ns.out:
        abs_out = os.path.abspath(ns.out)
        os.makedirs(os.path.dirname(abs_out), exist_ok=True)
        shutil.copyfile(path, abs_out)
        out_path = abs_out
    _out({"saved": out_path, "bytes": len(png_bytes), "frames_dir": str(Path(path).parent)})
    return 0


def cmd_probe(ns) -> int:
    """像素采样 — 裸帧（零 PNG 编码）→ 指定点 RGBA（顶左坐标系）。

    用途: agent 端无图像通道时的像素级断言（配合 renderer.snapshot）。
    """
    try:
        frame = fetch_raw_frame(ns.target, ns.timeout)
    except EngineError as e:
        return _fail(f"probe failed: {e}", 1)
    width, height, payload = frame["width"], frame["height"], frame["payload"]
    points: list[tuple[int, int]] = []
    for chunk in ns.points.replace(";", " ").split():
        try:
            x_str, y_str = chunk.split(":")
            points.append((int(x_str), int(y_str)))
        except ValueError:
            return _fail(f"--points 格式错误: {chunk!r}（应为 x:y;x:y, 顶左坐标系）", 2)
    if not points:
        return _fail("--points 为空（示例: --points 160:120;200:240）", 2)
    out_pixels = []
    for x, y in points:
        if not (0 <= x < width and 0 <= y < height):
            out_pixels.append({"x": x, "y": y, "rgba": None, "error": "out of bounds"})
            continue
        idx = ((height - 1 - y) * width + x) * 4   # 裸帧 bottom-up → 顶左坐标换算
        r, g, b, a = payload[idx], payload[idx + 1], payload[idx + 2], payload[idx + 3]
        out_pixels.append({"x": x, "y": y, "rgba": [r, g, b, a]})
    _out({"frame": {"target": ns.target, "width": width, "height": height},
          "pixels": out_pixels})
    return 0


def _skill_source() -> Path:
    return Path(__file__).resolve().parent / "skills" / _SKILL_DIR_NAME


def _update_mcp_json(path: Path, python_cmd: str, profile: str, uninstall: bool) -> None:
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    servers = data.setdefault("servers", {})
    if uninstall:
        servers.pop("engine-editor-live", None)
    else:
        servers["engine-editor-live"] = {
            "type": "stdio",
            "command": python_cmd,
            "args": ["-m", "engine_editor_mcp", "--profile", profile],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[mcp] {path}")
    if not uninstall:
        print(f"[mcp] command: {python_cmd} -m engine_editor_mcp --profile {profile}")


def cmd_setup(ns) -> int:
    ws = Path(ns.workspace or os.getcwd()).expanduser().resolve()
    src = _skill_source()
    if not ns.uninstall and not src.is_dir():
        return _fail(f"skill payload missing in package: {src}", 1)
    targets = list(_SKILL_TARGETS) if ns.skills == "all" else ([] if ns.skills == "none" else [ns.skills])
    python_cmd = ns.python or sys.executable
    mcp_path = ws / ".vscode" / "mcp.json"

    if ns.dry_run:
        for name in targets:
            print(f"[dry-run] skill -> {ws / _SKILL_TARGETS[name] / _SKILL_DIR_NAME}")
        print(f"[dry-run] mcp   -> {mcp_path} (profile={ns.profile}, python={python_cmd})")
        return 0

    print(f"[workspace] {ws}")
    if ns.uninstall:
        for name in targets:
            dest = ws / _SKILL_TARGETS[name] / _SKILL_DIR_NAME
            shutil.rmtree(dest, ignore_errors=True)
            print(f"[remove] {dest}")
        _update_mcp_json(mcp_path, python_cmd, ns.profile, uninstall=True)
    else:
        for name in targets:
            dest = ws / _SKILL_TARGETS[name] / _SKILL_DIR_NAME
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            print(f"[skill] {dest}")
        _update_mcp_json(mcp_path, python_cmd, ns.profile, uninstall=False)
    print("[note] 重载 IDE 窗口（或 MCP: List Servers 重启）后生效")
    return 0


# ── 入口 ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine-editor-cli",
        description="MyGameEngine 编辑器实时控制 CLI（需编辑器运行中; 默认 127.0.0.1:8977）",
    )
    parser.add_argument("--version", action="version", version=f"engine-editor-cli {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ops", help="op 目录（一行一个）")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("help", help="单 op 详情 / 主题（cli, mcp, skill, capture）")
    p.add_argument("topic", nargs="?", default="")
    p.set_defaults(func=cmd_help)

    p = sub.add_parser("call", help="执行一个 op")
    p.add_argument("op")
    p.add_argument("kv", nargs="*", metavar="k=v", help="参数（值先按 JSON 解析，失败按字符串; 数组/对象请加引号）")
    p.add_argument("--json", help="完整 args JSON（或 @file.json）")
    p.add_argument("--detail", choices=("auto", "full"), default="auto")
    p.set_defaults(func=cmd_call)

    p = sub.add_parser("batch", help="顺序执行多个 op（JSON 文件 / stdin）")
    p.add_argument("file", help="JSON 文件路径或 -（stdin）")
    p.add_argument("--continue", dest="continue_", action="store_true", help="出错继续")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("exec", help="运行脚本（注入全局 engine 客户端）")
    p.add_argument("script", help="脚本路径或 -（stdin）")
    p.add_argument("args", nargs="*", help="传给脚本的 argv")
    p.add_argument("--timeout", type=float, default=15.0)
    p.set_defaults(func=cmd_exec)

    p = sub.add_parser("validate", help="图干跑校验（阻塞编排; 默认 summary）")
    p.add_argument("--source", choices=("canvas", "graph"), default="canvas")
    p.add_argument("--graph", help="graph dict JSON（或 @file.json; source=graph 用）")
    p.add_argument("--frames", type=int, default=360)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--detail", choices=("summary", "full"), default="summary")
    p.add_argument("--save", help="报告落盘（.json/.txt）")
    p.add_argument("--timeout", type=float, default=120.0)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("capture", help="抓帧落盘（只回路径）")
    p.add_argument("target", nargs="?", choices=("editor", "pie"), default="editor")
    p.add_argument("--out", help="另存到指定路径")
    p.add_argument("--timeout", type=float, default=6.0)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("probe", help="像素采样（裸帧 → 指定点 RGBA; 顶左坐标系）")
    p.add_argument("target", nargs="?", choices=("editor", "pie"), default="editor")
    p.add_argument("--points", required=True, help="采样点: x:y[;x:y...]（顶左坐标系）")
    p.add_argument("--timeout", type=float, default=6.0)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("setup", help="向工作区安装 skill + mcp.json（独立分发）")
    p.add_argument("--workspace", default=".", help="目标工作区（默认当前目录）")
    p.add_argument("--profile", choices=("lite", "full"), default="lite", help="MCP 档位（默认 lite）")
    p.add_argument("--python", default="", help="MCP 启动用的 Python 解释器（默认当前解释器）")
    p.add_argument("--skills", choices=("github", "claude", "agents", "all", "none"), default="github")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    p.set_defaults(func=cmd_setup)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:  # GBK 控制台下不可映射字符 → 替换而非崩溃
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ns = build_parser().parse_args(argv)
    try:
        return int(ns.func(ns) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
