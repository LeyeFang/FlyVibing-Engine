"""
MCP Server — Node Graph Validation Tools.
Exposes: validate_graph
"""
import sys, os

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Node Graph Validate", version="0.1.0")


@mcp.tool()
def validate_graph(graph: dict, max_frames: int = 0, verbose: bool = False) -> dict:
    """验证节点图 (静态检查 + 可选干跑)。

    Args:
        graph: 节点图 dict (build_graph 的输出)
        max_frames: 干跑帧数 (0 = 仅静态检查)
        verbose: 详细输出

    Returns:
        {passed: bool, static_errors: [...], dry_run: {...} | null}
    """
    from Utils.NodeEditor.node_graph_validator import (
        validate_static, dry_run_simulation,
    )

    errors = validate_static(graph)
    static_errors = [{"message": e} for e in errors]

    dry_run_result = None
    if max_frames > 0 and not static_errors:
        try:
            result = dry_run_simulation(
                graph, max_frames=max_frames, verbose=verbose)
            dr_errors = result.get("errors", [])
            dry_run_result = {
                "frames_simulated": result.get("frames_simulated", 0),
                "total_events": result.get("total_events", 0),
                "events_by_type": result.get("events_by_type", {}),
                "errors": dr_errors,
            }
            passed = len(dr_errors) == 0
        except Exception as e:
            dry_run_result = {"errors": [str(e)]}
            passed = False
    else:
        passed = len(static_errors) == 0

    return {
        "passed": passed,
        "static_errors": static_errors,
        "dry_run": dry_run_result,
    }


if __name__ == "__main__":
    mcp.run()
