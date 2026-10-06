"""NodeEditor CLI — 终端通道（与 MCP 同一实现; 零常驻上下文成本）。

用法:
  python -m Utils.User.NodeEditor.cli rules [section] [--all] [--out FILE]
  python -m Utils.User.NodeEditor.cli entities <scene.scene>
  python -m Utils.User.NodeEditor.cli build --spec spec.json [--out graph.json]
  python -m Utils.User.NodeEditor.cli apply --scene scene.scene --graph graph.json   # --graph - = stdin

- `rules` 无 section → 目录（outline）; 有 section → 单节文本; `--all` → 全文;
  `--out` 落盘时只回摘要 JSON（不把全文/大图塞进上下文）。
- `build` 无 `--out` → 打印完整结果（含内联 graph）; 有 `--out` → 写入 graph JSON 只回摘要。
- 图校验请用引擎内服务（engine-editor MCP / CLI validate; 见 rules.md 的 Validation 节）。

退出码: 0 成功 / 1 运行时错误 / 2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from Utils.User.NodeEditor import rule_sections  # noqa: E402


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_project_root, path)


def _out(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _fail(message: str, code: int = 1) -> int:
    sys.stderr.write(message.rstrip() + "\n")
    return code


def _read_json_arg(raw: str):
    if raw == "-":
        return json.load(sys.stdin)
    with open(_resolve(raw), "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_rules(ns) -> int:
    if ns.all:
        text = rule_sections.load_rules()
    elif ns.section:
        text = rule_sections.section(ns.section)
        if text is None:
            titles = ", ".join(f'"{t}"' for t in rule_sections.section_titles())
            return _fail(f"unknown section: {ns.section!r} — 可用: {titles}", 2)
    else:
        text = rule_sections.outline()
    if ns.out:
        out_path = os.path.abspath(_resolve(ns.out))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        _out({"saved": out_path, "chars": len(text)})
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def cmd_entities(ns) -> int:
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    with open(scene_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    scene = data.get("scene", data)
    entities = []
    for eid_str, ed in (scene.get("entities") or {}).items():
        entities.append({
            "id": int(eid_str),
            "name": ed.get("name", ""),
            "components": list((ed.get("components") or {}).keys()),
            "parent_id": ed.get("parent_id"),
        })
    _out({"entities": entities, "total": len(entities)})
    return 0


def cmd_build(ns) -> int:
    try:
        spec = _read_json_arg(ns.spec)
    except (OSError, ValueError) as e:
        return _fail(f"spec 读取失败: {e}", 2)
    from Utils.User.NodeEditor.spec_builder import build_experiment_graph

    result = build_experiment_graph(spec)
    if ns.out:
        out_path = os.path.abspath(_resolve(ns.out))
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result["graph"], fh, indent=2, ensure_ascii=False)
        _out({"saved": out_path, "node_count": result["node_count"], "link_count": result["link_count"]})
    else:
        _out(result)
    return 0


def cmd_apply(ns) -> int:
    try:
        graph = _read_json_arg(ns.graph)
    except (OSError, ValueError) as e:
        return _fail(f"graph 读取失败: {e}", 2)
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["scene"]["node_graph"] = graph
        with open(scene_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except (OSError, KeyError, ValueError) as e:
        return _fail(f"apply 失败: {e}", 1)
    _out({
        "success": True,
        "path": scene_path,
        "node_count": len(graph.get("nodes", {})),
        "link_count": len(graph.get("links", {})),
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m Utils.User.NodeEditor.cli",
        description="NodeEditor 终端通道（rules 分节 / build spec / apply 到 scene）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("rules", help="参考文档: 无参=目录; section=单节; --all=全文")
    p.add_argument("section", nargs="?", default="", help='节标题（如 "Gtec" / "build_graph Spec"）')
    p.add_argument("--all", action="store_true", help="输出全文（谨慎: 约 1 万字符）")
    p.add_argument("--out", help="写入文件（只回摘要 JSON）")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("entities", help="读取 .scene 实体列表")
    p.add_argument("scene")
    p.set_defaults(func=cmd_entities)

    p = sub.add_parser("build", help="实验 spec → 节点图 JSON")
    p.add_argument("--spec", required=True, help="spec JSON 文件路径（- = stdin）")
    p.add_argument("--out", help="写入 graph JSON（只回摘要; 供 apply 复用）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("apply", help="将节点图 JSON 注入 .scene 文件")
    p.add_argument("--scene", required=True)
    p.add_argument("--graph", required=True, help="graph JSON 文件路径（- = stdin）")
    p.set_defaults(func=cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
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
