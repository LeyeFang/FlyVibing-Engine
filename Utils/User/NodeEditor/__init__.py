"""
NodeEditor — 节点图 agent 通道与工具。

  mcp_server      — MCP 4 工具（get_rules 分节 / get_scene_entities / build_graph / apply_graph）
  cli             — 终端通道（python -m Utils.User.NodeEditor.cli rules|entities|build|apply）
  rule_sections   — rules.md 分节读取（渐进披露）
  spec_builder    — 实验 spec → 节点图 JSON（build_graph 实现）
  graph_builder   — 程序化构图器（GraphBuilder）
  node_graph_validator — 旧离线校验（已退场, 仅旧脚本/单元测试复用）
"""
