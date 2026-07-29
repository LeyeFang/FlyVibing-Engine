"""
MCP Server — Node Graph Build & Apply Tools.
Exposes: build_graph, apply_graph
"""
import sys, os

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Node Graph Build", version="0.1.0")

# ── 复用原有实现 ──
from Utils.NodeEditor.mcp_server import build_graph as _build_graph
from Utils.NodeEditor.mcp_server import apply_graph as _apply_graph


@mcp.tool()
def build_graph(scene_path: str, experiment_spec: dict) -> dict:
    """从实验描述 spec 构建完整节点图 JSON。调用前必须先 get_rules 了解节点类型。

    spec 结构:
    {
        "seed_dir": "Test/.../seed", "seed_prefix": "MI-Seed",
        "init_delay": 5.0, "trials": 60, "timer": "trial_phase",
        "phases": [
            {"time": 0, "type": "cue_pick",
             "random": {"min": 1, "max": 2},
             "branches": [
                 {"value": 1, "show": ["L_arrow_body","L_arrow_head"], "parallel": 11},
                 {"value": 2, "show": ["R_arrow_head","R_arrow_body"], "parallel": 12}
             ]},
            {"time": 2, "show": ["TaskCue"]},
            {"time": 6, "hide": ["L_arrow_body","L_arrow_head","R_arrow_head","R_arrow_body","TaskCue"]},
            {"time": 10, "type": "trial_end"}
        ],
        "entities": ["Cross","LeftCue","RightCue","TaskCue"],
        "pulse": null
    }
    """
    return _build_graph(scene_path, experiment_spec)


@mcp.tool()
def apply_graph(scene_path: str, graph: dict) -> dict:
    """将节点图注入到 .scene 文件。

    Args:
        scene_path: 目标 .scene 文件路径
        graph: 节点图 dict (build_graph 的输出.graph)
    """
    return _apply_graph(scene_path, graph)


if __name__ == "__main__":
    mcp.run()
