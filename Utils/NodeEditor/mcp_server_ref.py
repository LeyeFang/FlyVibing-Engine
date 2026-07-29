"""
MCP Server — Node Graph Reference Tools.
Exposes: get_rules, get_scene_entities
"""
import json, os, sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Node Graph Reference", version="0.1.0")


@mcp.tool()
def get_rules() -> str:
    """获取节点图完整参考文档（节点类型、连接规则、执行模型、常见模式）。

    Agent 在构建节点图之前必须调用此工具，了解所有可用节点类型及其引脚定义。
    """
    rules_path = os.path.join(os.path.dirname(__file__), "rules.md")
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            return f.read()
    return "ERROR: rules.md not found"


@mcp.tool()
def get_scene_entities(scene_path: str) -> dict:
    """读取 .scene 文件，返回实体名列表和 entity ID 映射。

    Args:
        scene_path: .scene 文件路径 (相对或绝对)

    Returns:
        {entities: [{id, name, components, parent_id}, ...], total: N}
    """
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


if __name__ == "__main__":
    mcp.run()
