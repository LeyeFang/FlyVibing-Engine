"""
节点图静态检查 — L1 薄适配器（规则实现在工具仓库，单一事实源）。

唯一实现:
    FlyVibing-User-And-Developer-Utils/packages/node-editor/
        src/flyvibing_node_editor/node_graph_validator.py::check_graph

为什么规则放在那里:
  - 离线设计期（CLI / GraphBuilder / apply_graph）与在线校验
    （graph.validate.* / Node Editor Validate / PlayerEntry --dry-run）必须同源，
    否则同一张图会出现两套结论；
  - 规则随节点类型与图约束演进 —— 只维护一份，避免"搬迁内化"式复制再漂移。

本模块只负责:
  1. 惰性导入（缺包时给出可操作的安装提示，而不是裸 ImportError）
  2. 把结构化条目原样交给上层（service / PlayerBootstrap / 测试）
"""

from __future__ import annotations

_BACKEND_MODULE = "flyvibing_node_editor.node_graph_validator"

_INSTALL_HINT = (
    "节点图静态校验由离线工具包 flyvibing-node-editor 提供（与离线通道同一实现）。\n"
    "  安装: pip install -e <FlyVibing-User-And-Developer-Utils>/packages/node-editor\n"
    "  验证: python -c \"import flyvibing_node_editor.node_graph_validator\""
)


class ValidationBackendUnavailable(RuntimeError):
    """校验后端（离线工具包）不可导入 —— 携带安装指引。"""


def _backend():
    """惰性取后端模块（不在模块级导入，避免运行时镜像缺包时整包 import 失败）。"""
    try:
        from flyvibing_node_editor import node_graph_validator as backend
    except ImportError as exc:  # pragma: no cover — 环境缺失路径
        raise ValidationBackendUnavailable(
            f"{_INSTALL_HINT}\n  (import error: {exc})"
        ) from exc
    return backend


def extract_graph_data(scene_data: dict) -> dict:
    """从 scene JSON / 裸 graph / 旧格式 graph 中提取节点图数据（委托后端）。"""
    return _backend().extract_graph_data(scene_data)


def static_check_graph(scene_data: dict) -> list[dict]:
    """L1: 静态结构校验 — 结构化条目 [{level, code, message, node_id}]（委托后端）。"""
    return _backend().check_graph(scene_data)
