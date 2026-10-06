"""
MCP Server — Node Graph 工具（v0.2.0: 精简 4 工具 + 渐进披露, 省 token）。

Tools:
  - get_rules(section="")   → 参考文档目录 / 单节 / 全文（默认只回目录 ~1.4k 字符）
  - get_scene_entities      → 读取 .scene 实体列表
  - build_graph(spec)       → 实验 spec → 节点图 JSON（spec 见 get_rules("build_graph Spec")）
  - apply_graph             → 将节点图注入 .scene 文件

CLI（等价的终端通道, 零常驻上下文成本）:
  python -m Utils.User.NodeEditor.cli rules|entities|build|apply ...

校验: 图校验已内化为引擎服务 — 引擎运行中: engine-editor MCP `engine_validate_graph` /
`engine-editor-cli validate`; 无头环境: PlayerEntry --dry-run。
旧 `validate_graph` 工具已于 2026-10-05 移除（曾仅返回弃用指针）。

启动方式:
  python -m Utils.User.NodeEditor.mcp_server
"""

import json
import os
import sys

# ── 确保项目根在 sys.path ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

from Utils.User.NodeEditor import rule_sections
from Utils.User.NodeEditor.spec_builder import build_experiment_graph

mcp = FastMCP("Node Graph Editor", version="0.2.0")


# ═══════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def get_rules(section: str = "") -> str:
    """节点图参考（渐进披露, 默认只回目录 — 省 token）。

    无参 = 目录（各节标题与规模）; section="<标题>" 取该节（子标题可单独取, 如 "Gtec"）;
    section="all" = 全文。CLI: python -m Utils.User.NodeEditor.cli rules
    """
    try:
        if not section or section.strip().lower() in ("outline", "list"):
            return rule_sections.outline()
        if section.strip().lower() in ("all", "full"):
            return rule_sections.load_rules()
        body = rule_sections.section(section)
    except OSError as e:
        return f"ERROR: rules.md not readable: {e}"
    if body is None:
        titles = ", ".join(f'"{t}"' for t in rule_sections.section_titles())
        return f"unknown section: {section!r} — 可用: {titles}\n（无参调用 get_rules() 看目录）"
    return body


@mcp.tool()
def get_scene_entities(scene_path: str) -> dict:
    """读取 .scene 文件 → 实体列表 [{id, name, components, parent_id}]（相对路径基于仓库根）。"""
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)
    if not os.path.exists(scene_path):
        return {"error": f"Scene not found: {scene_path}"}

    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": f"Failed to read: {e}"}

    scene = data.get("scene", data)
    entities = []
    for eid_str, ed in scene.get("entities", {}).items():
        entities.append({
            "id": int(eid_str),
            "name": ed.get("name", ""),
            "components": list(ed.get("components", {}).keys()),
            "parent_id": ed.get("parent_id"),
        })
    return {"entities": entities, "total": len(entities)}


@mcp.tool()
def build_graph(experiment_spec: dict) -> dict:
    """实验 spec → 节点图 JSON（构建前读 get_rules(section="build_graph Spec")）。

    Returns: {graph, node_count, link_count}。v0.2.0: 移除未使用的 scene_path 参数（历史遗留）。
    """
    return build_experiment_graph(experiment_spec)


@mcp.tool()
def apply_graph(scene_path: str, graph: dict) -> dict:
    """将节点图注入 .scene 文件的 node_graph 字段（相对路径基于仓库根）。返回 {success, path, node_count, link_count}。"""
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)

    if not os.path.exists(scene_path):
        return {"success": False, "error": f"Scene not found: {scene_path}"}

    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["scene"]["node_graph"] = graph
        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {
            "success": True,
            "path": scene_path,
            "node_count": len(graph.get("nodes", {})),
            "link_count": len(graph.get("links", {})),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
