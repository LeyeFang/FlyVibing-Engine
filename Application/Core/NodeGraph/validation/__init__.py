"""
节点图校验服务 — 静态检查 + 干跑（引擎内单一事实源）。

设计（详见 Doc/Dev/graph_validation_protocol.md）:
  - L1 静态检查 (checks.static_check_graph): 结构化条目 {level, code, message, node_id}
  - L2 干跑    (dry_run.run_dry_run):       fake-time 确定性模拟 + 结构化事件日志
  - 任务服务   (service.ValidationService): 单活动任务 / worker 线程 / 报告留存

入口:
  - UI:   Node Editor 面板 "Validate" 按钮
  - MCP:  graph.validate.start / state / report / cancel（LiveCommandServer）
  - 程序: run_validation()（PlayerBootstrap 干跑 / 无头测试 / 算法验证复用）

L1 规则实现在工具仓库 `flyvibing_node_editor.node_graph_validator.check_graph`
（离线设计期与在线校验同源）；本包的 `checks` 只是薄适配器。
"""

from .checks import (
    ValidationBackendUnavailable,
    extract_graph_data,
    static_check_graph,
)
from .dry_run import DRY_RUN_SESSION_PREFIX, DEFAULT_DT, DEFAULT_FRAMES, run_dry_run
from .service import ValidationService, get_service, run_validation

__all__ = [
    "ValidationBackendUnavailable",
    "extract_graph_data",
    "static_check_graph",
    "run_dry_run",
    "run_validation",
    "ValidationService",
    "get_service",
    "DRY_RUN_SESSION_PREFIX",
    "DEFAULT_FRAMES",
    "DEFAULT_DT",
]
