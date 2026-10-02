"""
节点编辑器 — 图约束 (跨节点联动规则, 不依赖 imgui)。

规则: Gtec Init ⇄ Kill 强制成对
  - KillGtecDevice 必须与同一绑定的 InitGtecDevice 共同出现
  - 编辑器删除任一侧 → 级联删除另一侧 (gtec_cascade_deletes)
  - 静态校验 (MCP validate_graph) 检查配对 (gtec_pairing_errors)

绑定规则:
  - 会话键 = props.device_name (非空) 或 gtec#<node_id> (回退)
  - Kill 的 device_name 为空且画布恰好 1 个 Init → 绑定该 Init
  - 其余未绑定 / 歧义 (多设备且未指定) 情况 → 校验错误

本模块纯数据操作 — 可被 UI (panel 删除), 校验器 (node_graph_validator) 与测试复用。
"""

from __future__ import annotations

from typing import Iterable, Optional

GTEC_INIT = "InitGtecDevice"
GTEC_KILL = "KillGtecDevice"


# ── 辅助 ─────────────────────────────────────────────────────

def _key(nid, props) -> str:
    """Init 的会话键 — device_name 或 gtec#<nid> 回退。"""
    name = str((props or {}).get("device_name", "")).strip()
    return name or f"gtec#{nid}"


def _partition(nodes) -> tuple[list[tuple], list[tuple]]:
    """nodes: iterable[(nid, node_type, props)] → (inits[(nid, key)], kills[(nid, name)])."""
    inits: list[tuple] = []
    kills: list[tuple] = []
    for nid, ntype, props in nodes:
        if ntype == GTEC_INIT:
            inits.append((nid, _key(nid, props)))
        elif ntype == GTEC_KILL:
            kills.append((nid, str((props or {}).get("device_name", "")).strip()))
    return inits, kills


def _kill_binding(kill_name: str, init_keys: list[str]) -> Optional[str]:
    """Kill 的绑定键: 显式名匹配 → 该键; 空名 + 仅 1 个 Init → 该键; 否则 None。"""
    if kill_name:
        return kill_name if kill_name in init_keys else None
    if len(init_keys) == 1:
        return init_keys[0]
    return None


# ═══════════════════════════════════════════════════════════════
# 静态校验 (供 node_graph_validator)
# ═══════════════════════════════════════════════════════════════

def gtec_pairing_errors(nodes: dict) -> list[str]:
    """检查 Init/Kill 配对。nodes = {nid_str: {node_type, props, ...}} → 错误列表。"""
    inits, kills = _partition(
        (nid, nd.get("node_type", ""), nd.get("props", {}))
        for nid, nd in (nodes or {}).items()
    )
    if not inits and not kills:
        return []

    errors: list[str] = []
    init_keys = [k for _, k in inits]

    if not inits:
        for nid, name in kills:
            bound = f"'{name}'" if name else "(unbound)"
            errors.append(
                f"Node {nid}<KillGtecDevice>: requires an InitGtecDevice "
                f"with the same device — none found for {bound}"
            )
        return errors

    if not kills:
        names = ", ".join(k for _, k in inits)
        errors.append(
            f"Gtec: InitGtecDevice ({names}) requires a matching KillGtecDevice — "
            f"Init/Kill must appear together"
        )
        return errors

    for nid, key in inits:
        if not any(_kill_binding(name, init_keys) == key for _, name in kills):
            errors.append(
                f"Node {nid}<InitGtecDevice>: no KillGtecDevice bound to '{key}' — "
                f"Init/Kill must appear together"
            )

    for nid, name in kills:
        if _kill_binding(name, init_keys) is None:
            if not name:
                errors.append(
                    f"Node {nid}<KillGtecDevice>: ambiguous binding — multiple Gtec devices "
                    f"registered, set device_name"
                )
            else:
                errors.append(
                    f"Node {nid}<KillGtecDevice>: device '{name}' has no matching InitGtecDevice"
                )
    return errors


# ═══════════════════════════════════════════════════════════════
# 删除级联 (供 NodeEditorPanel)
# ═══════════════════════════════════════════════════════════════

def gtec_cascade_deletes(canvas, node_ids: Iterable[int]) -> set[int]:
    """返回删除 node_ids 时需一并删除的节点集合（含自身）。

    删除 Init → 所有绑定到它的 Kill；删除 Kill → 其绑定的 Init（继而其余 Kill）。
    """
    result = {nid for nid in node_ids if nid in canvas.nodes}
    changed = True
    while changed:
        changed = False
        inits, kills = _partition(
            (nid, inst.node_type, inst.props)
            for nid, inst in canvas.nodes.items()
        )
        init_keys = [k for _, k in inits]
        init_by_key = {k: nid for nid, k in inits}
        kill_by_nid = {nid: name for nid, name in kills}

        for nid in list(result):
            if nid in kill_by_nid:
                # Kill → 其绑定的 Init
                bound = _kill_binding(kill_by_nid[nid], init_keys)
                if bound is not None:
                    init_nid = init_by_key.get(bound)
                    if init_nid is not None and init_nid not in result:
                        result.add(init_nid)
                        changed = True
            else:
                # Init → 所有绑定到它的 Kill
                key = next((k for i_nid, k in inits if i_nid == nid), None)
                if key is not None:
                    for kill_nid, name in kills:
                        if kill_nid not in result and _kill_binding(name, init_keys) == key:
                            result.add(kill_nid)
                            changed = True
    return result


# ═══════════════════════════════════════════════════════════════
# SigGen (虚拟信号发生器) — 与 Gtec 同一配对规则
# ═══════════════════════════════════════════════════════════════

SIGGEN_INIT = "InitSigGenDevice"
SIGGEN_KILL = "KillSigGenDevice"


def _siggen_key(nid, props) -> str:
    """Init 的会话键 — device_name 或 siggen#<nid> 回退。"""
    name = str((props or {}).get("device_name", "")).strip()
    return name or f"siggen#{nid}"


def _siggen_partition(nodes) -> tuple[list[tuple], list[tuple]]:
    """nodes: iterable[(nid, node_type, props)] → (inits[(nid, key)], kills[(nid, name)])."""
    inits: list[tuple] = []
    kills: list[tuple] = []
    for nid, ntype, props in nodes:
        if ntype == SIGGEN_INIT:
            inits.append((nid, _siggen_key(nid, props)))
        elif ntype == SIGGEN_KILL:
            kills.append((nid, str((props or {}).get("device_name", "")).strip()))
    return inits, kills


def siggen_pairing_errors(nodes: dict) -> list[str]:
    """检查 SigGen Init/Kill 配对。nodes = {nid_str: {node_type, props, ...}} → 错误列表。"""
    inits, kills = _siggen_partition(
        (nid, nd.get("node_type", ""), nd.get("props", {}))
        for nid, nd in (nodes or {}).items()
    )
    if not inits and not kills:
        return []

    errors: list[str] = []
    init_keys = [k for _, k in inits]

    if not inits:
        for nid, name in kills:
            bound = f"'{name}'" if name else "(unbound)"
            errors.append(
                f"Node {nid}<KillSigGenDevice>: requires an InitSigGenDevice "
                f"with the same device — none found for {bound}"
            )
        return errors

    if not kills:
        names = ", ".join(k for _, k in inits)
        errors.append(
            f"SigGen: InitSigGenDevice ({names}) requires a matching KillSigGenDevice — "
            f"Init/Kill must appear together"
        )
        return errors

    for nid, key in inits:
        if not any(_kill_binding(name, init_keys) == key for _, name in kills):
            errors.append(
                f"Node {nid}<InitSigGenDevice>: no KillSigGenDevice bound to '{key}' — "
                f"Init/Kill must appear together"
            )

    for nid, name in kills:
        if _kill_binding(name, init_keys) is None:
            if not name:
                errors.append(
                    f"Node {nid}<KillSigGenDevice>: ambiguous binding — multiple SigGen devices "
                    f"registered, set device_name"
                )
            else:
                errors.append(
                    f"Node {nid}<KillSigGenDevice>: device '{name}' has no matching InitSigGenDevice"
                )
    return errors


def siggen_cascade_deletes(canvas, node_ids: Iterable[int]) -> set[int]:
    """返回删除 node_ids 时需一并删除的 SigGen 节点集合（含自身）。"""
    result = {nid for nid in node_ids if nid in canvas.nodes}
    changed = True
    while changed:
        changed = False
        inits, kills = _siggen_partition(
            (nid, inst.node_type, inst.props)
            for nid, inst in canvas.nodes.items()
        )
        init_keys = [k for _, k in inits]
        init_by_key = {k: nid for nid, k in inits}
        kill_by_nid = {nid: name for nid, name in kills}

        for nid in list(result):
            if nid in kill_by_nid:
                # Kill → 其绑定的 Init
                bound = _kill_binding(kill_by_nid[nid], init_keys)
                if bound is not None:
                    init_nid = init_by_key.get(bound)
                    if init_nid is not None and init_nid not in result:
                        result.add(init_nid)
                        changed = True
            else:
                # Init → 所有绑定到它的 Kill
                key = next((k for i_nid, k in inits if i_nid == nid), None)
                if key is not None:
                    for kill_nid, name in kills:
                        if kill_nid not in result and _kill_binding(name, init_keys) == key:
                            result.add(kill_nid)
                            changed = True
    return result


def device_cascade_deletes(canvas, node_ids: Iterable[int]) -> set[int]:
    """全部设备族 (Gtec + SigGen) 的删除级联并集（供编辑器面板使用）。"""
    return (gtec_cascade_deletes(canvas, node_ids)
            | siggen_cascade_deletes(canvas, node_ids))
