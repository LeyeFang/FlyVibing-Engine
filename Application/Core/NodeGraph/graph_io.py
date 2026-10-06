"""节点图导入/导出共享实现 — GUI 面板与 LiveCommandServer ops 共用（消除双实现漂移）。

边界: 纯数据 + 可选静态校验（validation 懒导入）; 不打印、不弹窗、不依赖 imgui/Editor。
顺序契约: `prepare_import` 不触碰画布 — 调用方遵循"先读入/校验, 后取画布"
（回环测试 test_live_command_server 依赖该顺序: 无画布时输入错误优先）。
"""

from __future__ import annotations

import json
import os


def prepare_import(
    graph: dict | None = None,
    path: str | None = None,
    validate_first: bool = True,
) -> tuple[dict, dict | None]:
    """读取（graph 优先, 否则 path）→ 可选静态检查。**不触碰画布**。

    Returns:
        (data, None)      通过 — data 为 graph dict
        (data, refusal)   被静态检查拒绝 — refusal 为 agent ops 同形结果 dict
    Raises:
        ValueError: 输入非法（消息与 agent ops 文案一致）
        json.JSONDecodeError: 文件非合法 JSON（ValueError 子类, 调用方可细分提示）
    """
    if graph is None:
        if not path:
            raise ValueError("either 'graph' or 'path' is required")
        file_path = str(path)
        if not os.path.isfile(file_path):
            raise ValueError(f"file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as fh:
            graph = json.load(fh)
    if not isinstance(graph, dict) or "nodes" not in graph:
        raise ValueError("graph must be a dict with 'nodes'")

    if validate_first:
        from .validation import static_check_graph

        errors = [e for e in static_check_graph(graph) if e.get("level") == "error"]
        if errors:
            return graph, {
                "imported": False,
                "reason": "static validation failed — fix errors or pass validate_first=false",
                "static_errors": errors,
            }
    return graph, None


def apply_to_canvas(canvas, data: dict) -> dict:
    """把 graph dict 应用到画布（整体替换）。返回 {imported, nodes, links}。"""
    from .canvas import NodeCanvas

    new_canvas = NodeCanvas.from_dict(data)
    canvas.replace_from(new_canvas)
    return {"imported": True, "nodes": len(canvas.nodes), "links": len(canvas.links)}


def export_graph(
    canvas,
    path: str | None = None,
    include_rules: bool = True,
    inline: bool = True,
) -> dict:
    """画布 → graph dict（可选落盘, 自动补 .json）。返回 {nodes, links, saved_path(, graph)}。"""
    data = canvas.to_dict()
    if include_rules is False:
        data.pop("_rules", None)
    saved_path = ""
    if path:
        saved_path = str(path)
        if not saved_path.lower().endswith(".json"):
            saved_path += ".json"
        os.makedirs(os.path.dirname(os.path.abspath(saved_path)), exist_ok=True)
        with open(saved_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    result: dict = {"nodes": len(canvas.nodes), "links": len(canvas.links), "saved_path": saved_path}
    if inline:
        result["graph"] = data
    return result
