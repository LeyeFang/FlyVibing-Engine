"""
节点图静态检查 — L1 层（结构化条目输出）。

规则与 Utils/User/NodeEditor/node_graph_validator.validate_static 保持一致（搬迁内化）:
  1. 未知节点类型 / 缺失引脚 (optional 版本兼容 pin 除外) / Pin ID 冲突
  2. 连线端点存在性 / 方向（output→input）/ 重复连线
  3. 孤立节点（降级为 warning — 可能是刻意保留的模板/常量节点）
  4. 必连引脚（Branch.Condition）
  5. Gtec Init/Kill 强制配对（graph_constraints 同一规则）
  6. SigGen Init/Kill 强制配对（同一规则）
  7. 设备池: Create/Kill 配对 + Add/设备引用池校验
  8. 设备池: AddToDevicePool.device pin 连线检查（未连 / 来源 / 单池成员制）
  9. Epoch 数据集: Count/Clear/Save 引用校验
  10. Epoch 数据集: EpochAppend 必需数据引脚（Data / Label）
  11. BCI 算法: Init/Train/Test 模型与数据集引用校验 + TestCCA 频率组 ≥2

差异（相对离线版）:
  - 输出结构化条目 dict: {level, code, message, node_id}
  - "孤立节点" 从 error 降级为 warning
"""

from __future__ import annotations

import re

_EVENT_TYPES = {"OnGameStart", "OnFrameUpdate", "OnGameStop"}

# 必连输入引脚: {node_type: [pin_name, ...]}
_REQUIRED_CONNECTIONS = {
    "Branch": ["Condition"],
}

_NODE_ID_RE = re.compile(r"^Node (\d+)<")


def _entry(level: str, code: str, message: str, node_id: int | None = None) -> dict:
    return {"level": level, "code": code, "message": message, "node_id": node_id}


def extract_graph_data(scene_data: dict) -> dict:
    """从 scene JSON / 裸 graph / 旧格式 graph 中提取节点图数据。

    支持三种格式:
      1. { "scene": { "node_graph": {...} } }   ← 标准 .scene 文件
      2. { "nodes": ..., "links": ... }          ← 裸 graph JSON（NodeCanvas.to_dict）
      3. { "graph": { "nodes": ..., "links": ... } }  ← 旧格式
    """
    if not isinstance(scene_data, dict):
        return {}
    scene = scene_data.get("scene", {})
    if isinstance(scene, dict):
        ng = scene.get("node_graph")
        if isinstance(ng, dict) and "nodes" in ng:
            return ng
    graph = scene_data.get("graph")
    if isinstance(graph, dict) and "nodes" in graph:
        return graph
    if "nodes" in scene_data:
        return scene_data
    return {}


def static_check_graph(scene_data: dict) -> list[dict]:
    """L1: 静态结构校验 — 返回结构化条目列表（level: "error" | "warning"）。"""
    from ..node_types import _TYPES

    entries: list[dict] = []
    graph = extract_graph_data(scene_data)
    nodes: dict = graph.get("nodes", {}) or {}
    links: dict = graph.get("links", {}) or {}

    if not nodes:
        entries.append(_entry("error", "empty_graph", "No nodes found in graph data"))
        return entries

    # ── 收集所有 pin_id → (nid_str, pin_name, direction) 映射 ──
    pin_map: dict[int, tuple[str, str, str]] = {}
    all_pin_ids: set[int] = set()

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type not in _TYPES:
            entries.append(_entry(
                "error", "unknown_type",
                f"Node {nid_str}: unknown type '{node_type}'",
                _safe_int(nid_str),
            ))
            continue

        type_def = _TYPES[node_type]
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}

        # 1. 检查模板引脚是否齐全 (optional 标记的版本兼容 pin 缺失不报错)
        for pin_def in type_def.pins:
            if pin_def.name not in node_pin_ids:
                if getattr(pin_def, "optional", False):
                    continue
                entries.append(_entry(
                    "error", "missing_pin",
                    f"Node {nid_str}<{node_type}>: missing pin '{pin_def.name}' "
                    f"({pin_def.direction}, {pin_def.kind})",
                    _safe_int(nid_str),
                ))

        # 2. 收集 pin 映射 + 冲突检测
        for pin_name, pin_id in node_pin_ids.items():
            pid = int(pin_id)
            if pid in all_pin_ids:
                prev = pin_map.get(pid)
                prev_desc = f"Node {prev[0]}.{prev[1]}" if prev else "(unknown)"
                entries.append(_entry(
                    "error", "pin_collision",
                    f"Pin ID collision: {pid} used by "
                    f"Node {nid_str}.{pin_name} and {prev_desc}",
                    _safe_int(nid_str),
                ))
            all_pin_ids.add(pid)
            direction = "unknown"
            for pin_def in type_def.pins:
                if pin_def.name == pin_name:
                    direction = pin_def.direction
                    break
            pin_map[pid] = (nid_str, pin_name, direction)

    # 3. 连线检查
    link_set: set[tuple[int, int]] = set()
    for lid_str, ld in links.items():
        try:
            from_pin = int(ld["from_pin"])
            to_pin = int(ld["to_pin"])
        except (KeyError, TypeError, ValueError):
            entries.append(_entry("error", "malformed_link", f"Link {lid_str}: malformed (missing from_pin/to_pin)"))
            continue

        if from_pin not in pin_map:
            entries.append(_entry("error", "link_endpoint", f"Link {lid_str}: from_pin={from_pin} not found in any node"))
        if to_pin not in pin_map:
            entries.append(_entry("error", "link_endpoint", f"Link {lid_str}: to_pin={to_pin} not found in any node"))

        if from_pin in pin_map and to_pin in pin_map:
            _, _, from_dir = pin_map[from_pin]
            _, _, to_dir = pin_map[to_pin]
            if from_dir == "input":
                entries.append(_entry("error", "link_direction", f"Link {lid_str}: from_pin={from_pin} is input (should be output)"))
            if to_dir == "output":
                entries.append(_entry("error", "link_direction", f"Link {lid_str}: to_pin={to_pin} is output (should be input)"))

        pair = (from_pin, to_pin)
        if pair in link_set:
            entries.append(_entry("error", "duplicate_link", f"Link {lid_str}: duplicate connection {from_pin}→{to_pin}"))
        link_set.add(pair)

    # 4. 孤立节点（warning — 可能是刻意保留）
    connected_pins: set[int] = set()
    for ld in links.values():
        try:
            connected_pins.add(int(ld["from_pin"]))
            connected_pins.add(int(ld["to_pin"]))
        except (KeyError, TypeError, ValueError):
            continue

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type in _EVENT_TYPES:
            continue
        if node_type not in _TYPES:
            continue  # 未知类型已报错, 跳过
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}
        is_isolated = True
        for pin_id in node_pin_ids.values():
            if int(pin_id) in connected_pins:
                is_isolated = False
                break
        if is_isolated:
            entries.append(_entry(
                "warning", "isolated_node",
                f"Node {nid_str}<{node_type}>: isolated (no connections) — "
                f"may be dead code or missing links",
                _safe_int(nid_str),
            ))

    # 5. 必连引脚检查
    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        required = _REQUIRED_CONNECTIONS.get(node_type, [])
        if not required:
            continue
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}
        for rpin in required:
            rpid = node_pin_ids.get(rpin)
            if rpid is None:
                continue
            if int(rpid) not in connected_pins:
                entries.append(_entry(
                    "error", "required_pin_unconnected",
                    f"Node {nid_str}<{node_type}>: required pin '{rpin}' is not connected",
                    _safe_int(nid_str),
                ))

    # 6. Gtec Init/Kill 强制配对（与编辑器删除级联同一规则）
    try:
        from ..graph_constraints import gtec_pairing_errors

        for msg in gtec_pairing_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "gtec_pairing", msg, node_id))
    except Exception as e:  # noqa: BLE001 — 约束模块失败不应让整个检查崩溃
        entries.append(_entry("error", "gtec_pairing", f"gtec pairing check failed: {e}"))

    # 7. SigGen Init/Kill 强制配对（与 Gtec 同一规则）
    try:
        from ..graph_constraints import siggen_pairing_errors

        for msg in siggen_pairing_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "siggen_pairing", msg, node_id))
    except Exception as e:  # noqa: BLE001 — 约束模块失败不应让整个检查崩溃
        entries.append(_entry("error", "siggen_pairing", f"siggen pairing check failed: {e}"))

    # 8. 设备池: Create/Kill 配对 + Add/设备引用池校验
    try:
        from ..graph_constraints import pool_pairing_errors, pool_reference_errors

        for msg in pool_pairing_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "pool_pairing", msg, node_id))
        for msg in pool_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "pool_reference", msg, node_id))
    except Exception as e:  # noqa: BLE001 — 约束模块失败不应让整个检查崩溃
        entries.append(_entry("error", "pool_pairing", f"pool check failed: {e}"))

    # 9. 设备池: AddToDevicePool.device pin 连线检查 (需 links)
    try:
        from ..graph_constraints import DEVICE_INIT_PREFIX as _INIT_TYPES
        from ..graph_constraints import POOL_ADD as _POOL_ADD

        to_src: dict[int, int] = {}
        for ld in links.values():
            try:
                to_src[int(ld["to_pin"])] = int(ld["from_pin"])
            except (KeyError, TypeError, ValueError):
                continue

        reported_srcs: set[int] = set()
        for nid_str, nd in nodes.items():
            if nd.get("node_type") != _POOL_ADD:
                continue
            node_pin_ids = nd.get("pin_ids", {}) or {}
            dp = node_pin_ids.get("device")
            if dp is None:
                continue  # optional pin 尚未补齐 — 加载时自动 heal, 静态检查跳过
            src = to_src.get(int(dp))
            if src is None:
                entries.append(_entry(
                    "error", "device_pin_unconnected",
                    f"Node {nid_str}<AddToDevicePool>: 'device' pin is not connected "
                    f"(link Init*Device.device → AddToDevicePool.device)",
                    _safe_int(nid_str),
                ))
                continue
            src_info = pin_map.get(src)
            if src_info is None:
                continue  # 端点问题已由连线检查报告
            src_nid_str, src_pin_name, src_dir = src_info
            src_type = (nodes.get(src_nid_str) or {}).get("node_type", "")
            if src_dir != "output" or src_pin_name != "device" or src_type not in _INIT_TYPES:
                entries.append(_entry(
                    "error", "device_pin_source",
                    f"Node {nid_str}<AddToDevicePool>: 'device' pin must come from an "
                    f"Init*Device 'device' output (got {src_type}.{src_pin_name})",
                    _safe_int(nid_str),
                ))
                continue
            # 单池成员制: 同一 device pin 不能被多个 Add 消费
            add_consumers = 0
            for ld in links.values():
                try:
                    if int(ld["from_pin"]) != src:
                        continue
                    cinfo = pin_map.get(int(ld["to_pin"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if cinfo and (nodes.get(cinfo[0]) or {}).get("node_type") == _POOL_ADD:
                    add_consumers += 1
            if add_consumers > 1 and src not in reported_srcs:
                reported_srcs.add(src)
                entries.append(_entry(
                    "error", "device_multi_pool",
                    f"Node {src_nid_str}<{src_type}>: device pin feeds {add_consumers} "
                    f"AddToDevicePool nodes — a device belongs to ONE pool (exclusive)",
                    _safe_int(src_nid_str),
                ))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "device_pin", f"device pin check failed: {e}"))

    # 10. Epoch 数据集: 引用校验 + EpochAppend 必需数据引脚 (Data / Label)
    try:
        from ..graph_constraints import EPOCH_APPEND as _EPOCH_APPEND
        from ..graph_constraints import epoch_reference_errors

        for msg in epoch_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "epoch_reference", msg, node_id))

        for nid_str, nd in nodes.items():
            if nd.get("node_type") != _EPOCH_APPEND:
                continue
            node_pin_ids = nd.get("pin_ids", {}) or {}
            for rpin in ("Data", "Label"):
                rpid = node_pin_ids.get(rpin)
                if rpid is not None and int(rpid) not in connected_pins:
                    entries.append(_entry(
                        "error", "epoch_pin_unconnected",
                        f"Node {nid_str}<EpochAppend>: '{rpin}' pin is not "
                        f"connected (link Get*Data.{rpin} / a label source)",
                        _safe_int(nid_str),
                    ))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "epoch_reference",
                              f"epoch check failed: {e}"))

    # 11. BCI 算法: 模型/数据集引用 + TestCCA 频率组
    try:
        from ..graph_constraints import bci_reference_errors

        for msg in bci_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "bci_reference", msg, node_id))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "bci_reference",
                              f"bci check failed: {e}"))

    return entries


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
