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

# ═══════════════════════════════════════════════════════════════
# 设备 / 设备池 键规则 — 单点定义 (节点类型 / 评估器 / UI / 校验共用)
# ═══════════════════════════════════════════════════════════════

# Init 节点类型 → 会话键前缀 (回退键: <prefix>#<nid>)
DEVICE_INIT_PREFIX: dict[str, str] = {
    "InitGtecDevice": "gtec",
    "InitSigGenDevice": "siggen",
}

# 引用设备会话的节点类型 (Start/Stop/Kill/Get), 供 UI / 校验统一枚举
DEVICE_REF_TYPES: tuple[str, ...] = (
    "StartGtecRecord", "StopGtecRecord", "KillGtecDevice", "GetGtecData",
    "StartSigGenRecord", "StopSigGenRecord", "KillSigGenDevice", "GetSigGenData",
)

POOL_CREATE = "CreateDevicePool"
POOL_ADD = "AddToDevicePool"
POOL_KILL = "KillDevicePool"
GLOBAL_POOL = "global"

# 动态媒体驱动节点 (ShowMedia — 编辑器=模板; 图内接线才播放, PIE/独立运行生效)
SHOW_MEDIA = "ShowMedia"


def device_session_key(node_type: str, nid, props) -> str:
    """Init 节点的会话键 — device_name 或 <prefix>#<nid> 回退 (与评估器一致)。"""
    name = str((props or {}).get("device_name", "")).strip()
    if name:
        return name
    return f"{DEVICE_INIT_PREFIX.get(node_type, 'device')}#{nid}"


def pool_key(nid, props) -> str:
    """Create 节点的池键 — pool_name 或 pool#<nid> 回退。"""
    name = str((props or {}).get("pool_name", "")).strip()
    return name or f"pool#{nid}"


GTEC_INIT = "InitGtecDevice"
GTEC_KILL = "KillGtecDevice"


# ── 辅助 ─────────────────────────────────────────────────────

def _key(nid, props) -> str:
    """Init 的会话键 — device_name 或 gtec#<nid> 回退 (共用 device_session_key)。"""
    return device_session_key(GTEC_INIT, nid, props)


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
    """Init 的会话键 — device_name 或 siggen#<nid> 回退 (共用 device_session_key)。"""
    return device_session_key(SIGGEN_INIT, nid, props)


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
    """全部设备族 (Gtec + SigGen) + 设备池的删除级联并集（供编辑器面板使用）。"""
    return (gtec_cascade_deletes(canvas, node_ids)
            | siggen_cascade_deletes(canvas, node_ids)
            | pool_cascade_deletes(canvas, node_ids))


# ═══════════════════════════════════════════════════════════════
# 设备池 (Device Pool) — Create ⇄ Kill 配对 / 引用检查 / 级联 / 画布清单
# ═══════════════════════════════════════════════════════════════

def _pool_partition(nodes) -> tuple[list[tuple], list[tuple]]:
    """nodes: iterable[(nid, node_type, props)] → (creates[(nid, key)], kills[(nid, name)])."""
    creates: list[tuple] = []
    kills: list[tuple] = []
    for nid, ntype, props in nodes:
        if ntype == POOL_CREATE:
            creates.append((nid, pool_key(nid, props)))
        elif ntype == POOL_KILL:
            kills.append((nid, str((props or {}).get("pool_name", "")).strip()))
    return creates, kills


def pool_pairing_errors(nodes: dict) -> list[str]:
    """检查 CreateDevicePool / KillDevicePool 配对（同设备族规则）。"""
    creates, kills = _pool_partition(
        (nid, nd.get("node_type", ""), nd.get("props", {}))
        for nid, nd in (nodes or {}).items()
    )
    if not creates and not kills:
        return []

    errors: list[str] = []
    create_keys = [k for _, k in creates]

    if not creates:
        for nid, name in kills:
            bound = f"'{name}'" if name else "(unbound)"
            errors.append(
                f"Node {nid}<KillDevicePool>: requires a CreateDevicePool "
                f"with the same pool — none found for {bound}"
            )
        return errors

    if not kills:
        names = ", ".join(k for _, k in creates)
        errors.append(
            f"DevicePool: CreateDevicePool ({names}) requires a matching KillDevicePool — "
            f"Create/Kill must appear together"
        )
        return errors

    for nid, key in creates:
        if not any(_kill_binding(name, create_keys) == key for _, name in kills):
            errors.append(
                f"Node {nid}<CreateDevicePool>: no KillDevicePool bound to '{key}' — "
                f"Create/Kill must appear together"
            )

    for nid, name in kills:
        if _kill_binding(name, create_keys) is None:
            if not name:
                errors.append(
                    f"Node {nid}<KillDevicePool>: ambiguous binding — multiple pools "
                    f"created, set pool_name"
                )
            else:
                errors.append(
                    f"Node {nid}<KillDevicePool>: pool '{name}' has no CreateDevicePool"
                )
    return errors


def pool_reference_errors(nodes: dict) -> list[str]:
    """Add / 设备引用节点的池引用校验（纯节点数据, 不依赖 links）:
      - 重复 Create 池键 → error
      - AddToDevicePool.pool_name 必须命中已注册(画布)池; 空 → error
      - Start/Stop/Kill/Get 的 pool (非空且非 global) 必须命中
    """
    errors: list[str] = []
    creates: dict[str, str] = {}
    for nid, nd in (nodes or {}).items():
        if nd.get("node_type") == POOL_CREATE:
            k = pool_key(nid, nd.get("props", {}))
            if k in creates:
                errors.append(
                    f"Node {nid}<CreateDevicePool>: duplicate pool '{k}' "
                    f"(also node {creates[k]})"
                )
            else:
                creates[k] = nid

    for nid, nd in (nodes or {}).items():
        ntype = nd.get("node_type", "")
        props = nd.get("props", {}) or {}
        if ntype == POOL_ADD:
            name = str(props.get("pool_name", "")).strip()
            if not name:
                errors.append(
                    f"Node {nid}<AddToDevicePool>: pool_name is empty — select a created pool"
                )
            elif name not in creates:
                known = ", ".join(creates) or "(none)"
                errors.append(
                    f"Node {nid}<AddToDevicePool>: pool '{name}' has no "
                    f"CreateDevicePool node (known: {known})"
                )
        elif ntype in DEVICE_REF_TYPES:
            pool = str(props.get("pool", "")).strip()
            if pool and pool != GLOBAL_POOL and pool not in creates:
                known = ", ".join(creates) or "(none)"
                errors.append(
                    f"Node {nid}<{ntype}>: pool '{pool}' has no "
                    f"CreateDevicePool node (known: {known})"
                )
    return errors


def pool_cascade_deletes(canvas, node_ids: Iterable[int]) -> set[int]:
    """返回删除 node_ids 时需一并删除的池节点集合（Create ⇄ Kill 配对）。"""
    result = {nid for nid in node_ids if nid in canvas.nodes}
    changed = True
    while changed:
        changed = False
        creates, kills = _pool_partition(
            (nid, inst.node_type, inst.props)
            for nid, inst in canvas.nodes.items()
        )
        create_keys = [k for _, k in creates]
        create_by_key = {k: nid for nid, k in creates}
        kill_by_nid = {nid: name for nid, name in kills}

        for nid in list(result):
            if nid in kill_by_nid:
                bound = _kill_binding(kill_by_nid[nid], create_keys)
                if bound is not None:
                    c_nid = create_by_key.get(bound)
                    if c_nid is not None and c_nid not in result:
                        result.add(c_nid)
                        changed = True
            else:
                key = next((k for c_nid, k in creates if c_nid == nid), None)
                if key is not None:
                    for kill_nid, name in kills:
                        if kill_nid not in result and _kill_binding(name, create_keys) == key:
                            result.add(kill_nid)
                            changed = True
    return result


def device_inventory(canvas) -> dict:
    """画布级设备/池清单（UI 下拉数据源）:

    Returns:
        {
          "pools": {pool_key: {"members": [session_key, ...], "node": create_nid}},
          "global": [session_key, ...],            # 未入显式池的设备
          "inits": {init_nid: session_key},
          "assignments": {init_nid: {"pool": pool_key, "add": add_nid}},
          "issues": [str, ...],                    # 重复键 / 多池连线等
        }
    """
    issues: list[str] = []
    pools: dict[str, dict] = {}
    for nid, inst in canvas.nodes.items():
        if inst.node_type == POOL_CREATE:
            k = pool_key(nid, inst.props)
            if k in pools:
                issues.append(f"duplicate pool '{k}' (nodes {pools[k]['node']}, {nid})")
            else:
                pools[k] = {"members": [], "node": nid}

    inits: dict[int, str] = {}
    for nid, inst in canvas.nodes.items():
        if inst.node_type in DEVICE_INIT_PREFIX:
            inits[nid] = device_session_key(inst.node_type, nid, inst.props)

    assignments: dict[int, dict] = {}
    for nid, inst in canvas.nodes.items():
        if inst.node_type != POOL_ADD:
            continue
        dp = inst.pin_ids.get("device")
        src = None
        if dp is not None:
            for lk in canvas.links.values():
                if lk.to_pin == dp:
                    src = canvas.find_pin_node(lk.from_pin)
                    break
        if src is None or src not in inits:
            continue
        if src in assignments:
            issues.append(f"device '{inits[src]}' connected to multiple Add nodes")
            continue
        assignments[src] = {"pool": str(inst.props.get("pool_name", "")).strip(),
                            "add": nid}

    glob: list[str] = []
    for init_nid, key in inits.items():
        a = assignments.get(init_nid)
        if a and a["pool"] in pools:
            pools[a["pool"]]["members"].append(key)
        else:
            glob.append(key)

    return {"pools": pools, "global": sorted(glob), "inits": inits,
            "assignments": assignments, "issues": issues}


# ═══════════════════════════════════════════════════════════════
# Epoch 数据集 (BCIAlgorithm) — 键规则与引用校验
# ═══════════════════════════════════════════════════════════════

EPOCH_APPEND = "EpochAppend"
EPOCH_LOAD = "EpochLoad"
EPOCH_REF_TYPES = ("EpochCount", "EpochClear", "EpochSave")


def epoch_key(nid, props) -> str:
    """Append/Load 的数据集键 — epochs_name 或 epochs#<nid> 回退（与评估器一致）。"""
    name = str((props or {}).get("epochs_name", "")).strip()
    return name or f"epochs#{nid}"


def nodes_as_dicts(canvas) -> dict:
    """UI/求值器适配: NodeCanvas → {nid: {"node_type", "props"}}。

    校验体系（checks/epoch_*/model_*/bci_* 等）的入参是序列化 dict；
    UI 侧持有 NodeInstance — 一律经本函数转换（不要直接传 canvas.nodes）。
    """
    return {nid: {"node_type": o.node_type, "props": o.props}
            for nid, o in (canvas.nodes if canvas is not None else {}).items()}


def epoch_source_keys(nodes: dict) -> dict:
    """画布上的数据集源 {key: nid}（Append/Load; 同键 = 同一数据集）。"""
    sources: dict[str, str] = {}
    for nid, nd in (nodes or {}).items():
        if nd.get("node_type") in (EPOCH_APPEND, EPOCH_LOAD):
            sources[epoch_key(nid, nd.get("props", {}))] = nid
    return sources


def epoch_reference_errors(nodes: dict) -> list[str]:
    """Count/Clear/Save 的 epochs_name 引用校验（同设备族绑定规则）:
      - 显式名必须命中画布源（Append/Load）;
      - 空名: 画布源恰好 1 个 → 自动绑定；0 或 ≥2 个 → error。
    """
    sources = epoch_source_keys(nodes)
    source_names = sorted(sources)
    errors: list[str] = []
    for nid, nd in (nodes or {}).items():
        ntype = nd.get("node_type", "")
        if ntype not in EPOCH_REF_TYPES:
            continue
        name = str((nd.get("props", {}) or {}).get("epochs_name", "")).strip()
        if name:
            if name not in sources:
                known = ", ".join(source_names) or "(none)"
                errors.append(
                    f"Node {nid}<{ntype}>: dataset '{name}' has no EpochAppend/"
                    f"EpochLoad node (known: {known})")
        elif len(sources) != 1:
            known = ", ".join(source_names) or "(none)"
            errors.append(
                f"Node {nid}<{ntype}>: unbound dataset reference — set "
                f"epochs_name (canvas sources: {known})")
    return errors


# ═══════════════════════════════════════════════════════════════
# BCI 算法 (FBCSP / CCA) — 模型键规则与引用校验
# ═══════════════════════════════════════════════════════════════

ALGO_INIT = "InitFBCSP"
ALGO_TRAIN = "TrainFBCSP"
ALGO_TEST = "TestFBCSP"
ALGO_CCA_TEST = "TestCCA"


def model_key(nid, props) -> str:
    """Init/Train 的模型键 — model_name 或 model#<nid> 回退（与评估器一致）。"""
    name = str((props or {}).get("model_name", "")).strip()
    return name or f"model#{nid}"


def model_source_keys(nodes: dict) -> dict:
    """画布模型源: {"specs": {key: nid} (InitFBCSP), "models": {key: nid} (TrainFBCSP)}。"""
    specs: dict[str, str] = {}
    models: dict[str, str] = {}
    for nid, nd in (nodes or {}).items():
        t = nd.get("node_type")
        if t == ALGO_INIT:
            specs[model_key(nid, nd.get("props", {}))] = nid
        elif t == ALGO_TRAIN:
            models[model_key(nid, nd.get("props", {}))] = nid
    return {"specs": specs, "models": models}


def bci_reference_errors(nodes: dict) -> list[str]:
    """BCI 算法节点引用校验（同设备族绑定规则）:
      - TrainFBCSP(train): spec 需命中 InitFBCSP（空名+唯一源自动绑定）; dataset_name 需命中 epoch 源;
      - TrainFBCSP(load):  需 model_path; 不依赖 spec/数据集;
      - TestFBCSP:         需命中 TrainFBCSP 模型（空名+唯一源自动绑定）;
      - TestCCA:           freqs >= 2（不限上限）。
    """
    refs = model_source_keys(nodes)
    specs, models = refs["specs"], refs["models"]
    epochs = epoch_source_keys(nodes)
    errors: list[str] = []

    for nid, nd in (nodes or {}).items():
        t = nd.get("node_type", "")
        props = nd.get("props", {}) or {}

        if t == ALGO_TRAIN:
            mode = str(props.get("mode", "train")).strip().lower()
            if mode == "load":
                if not str(props.get("model_path", "")).strip():
                    errors.append(
                        f"Node {nid}<TrainFBCSP>: mode=load requires model_path")
                continue
            name = str(props.get("model_name", "")).strip()
            if name:
                if name not in specs:
                    known = ", ".join(sorted(specs)) or "(none)"
                    errors.append(
                        f"Node {nid}<TrainFBCSP>: spec '{name}' has no "
                        f"InitFBCSP node (known: {known})")
            elif len(specs) != 1:
                known = ", ".join(sorted(specs)) or "(none)"
                errors.append(
                    f"Node {nid}<TrainFBCSP>: unbound spec — set model_name "
                    f"(canvas InitFBCSP: {known})")
            ds = str(props.get("dataset_name", "")).strip()
            if ds:
                if ds not in epochs:
                    known = ", ".join(sorted(epochs)) or "(none)"
                    errors.append(
                        f"Node {nid}<TrainFBCSP>: dataset '{ds}' has no "
                        f"EpochAppend/EpochLoad node (known: {known})")
            elif len(epochs) != 1:
                known = ", ".join(sorted(epochs)) or "(none)"
                errors.append(
                    f"Node {nid}<TrainFBCSP>: unbound dataset — set "
                    f"dataset_name (canvas sources: {known})")

        elif t == ALGO_TEST:
            name = str(props.get("model_name", "")).strip()
            if name:
                if name not in models:
                    known = ", ".join(sorted(models)) or "(none)"
                    errors.append(
                        f"Node {nid}<TestFBCSP>: model '{name}' has no "
                        f"TrainFBCSP node (known: {known})")
            elif len(models) != 1:
                known = ", ".join(sorted(models)) or "(none)"
                errors.append(
                    f"Node {nid}<TestFBCSP>: unbound model — set model_name "
                    f"(canvas TrainFBCSP: {known})")

        elif t == ALGO_CCA_TEST:
            freqs = props.get("freqs") or []
            n = len(freqs) if isinstance(freqs, (list, tuple)) else 0
            if n < 2:
                errors.append(
                    f"Node {nid}<TestCCA>: needs at least 2 reference "
                    f"frequencies (got {n})")
    return errors
