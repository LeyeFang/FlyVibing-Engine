"""节点组内部起点/终点节点 — 纯数据，无 UI 依赖。

``imgui-node-editor`` 的 Group 节点不能直接挂 Pin。这里为每个组创建
两个真实节点：

    GroupStart  — 只有 exec_out
    GroupEnd    — 只有 exec_in

它们作为组的普通成员参与布局、连线、求值和序列化，生命周期与组绑定：
组创建/加载时补齐，Ungroup/Delete/Destroy 时移除。因为它们是普通节点，
组的 exec 接口可以自由拖到组内任意成员，不需要隐藏或改写成员 Pin。
"""

from __future__ import annotations

from .group_geometry import (
    GROUP_LAYOUT_VERSION,
    children_of,
    ensure_box,
    fit_group,
    get_box,
    group_depth,
)

START_TYPE = "GroupStart"
END_TYPE = "GroupEnd"
IO_TYPES = frozenset({START_TYPE, END_TYPE})
IO_KEY = "io_nodes"


def _groups(canvas) -> dict:
    groups = getattr(canvas, "node_groups", None)
    if groups is None:
        groups = {}
        try:
            canvas.node_groups = groups
        except Exception:  # noqa: BLE001 — duck-typed canvas
            pass
    return groups


def _nodes(canvas) -> dict:
    return getattr(canvas, "nodes", {}) or {}


def _to_nid(raw) -> int | None:
    try:
        nid = int(raw)
    except (TypeError, ValueError):
        return None
    return nid if nid >= 0 else None


def _raw_io(grp: dict) -> dict:
    raw = grp.get(IO_KEY)
    return raw if isinstance(raw, dict) else {}


def io_node_ids(canvas, gid: str) -> dict[str, int]:
    """返回组内仍有效的 ``{start, end}`` 节点 ID；缺失项不出现。"""
    grp = _groups(canvas).get(str(gid))
    if not isinstance(grp, dict):
        return {}
    nodes = _nodes(canvas)
    raw = _raw_io(grp)
    out: dict[str, int] = {}
    for key, want_type in (("start", START_TYPE), ("end", END_TYPE)):
        nid = _to_nid(raw.get(key))
        if nid is None:
            continue
        inst = nodes.get(nid)
        if inst is not None and str(getattr(inst, "node_type", "")) == want_type:
            out[key] = nid
    return out


def group_io_owner(canvas, nid: int) -> str | None:
    """节点是某个组的 GroupStart/GroupEnd 时返回组 id。"""
    target = int(nid)
    for gid, grp in _groups(canvas).items():
        if not isinstance(grp, dict):
            continue
        if target in io_node_ids(canvas, str(gid)).values():
            return str(gid)
    return None


def all_io_node_ids(canvas, gid: str) -> set[int]:
    """组自身 + 全部后代组内部 GroupStart/GroupEnd 的节点 ID。"""
    out = set(io_node_ids(canvas, gid).values())
    pending = list(children_of(canvas, str(gid)))
    seen: set[str] = set()
    while pending:
        child = str(pending.pop(0))
        if child in seen:
            continue
        seen.add(child)
        out.update(io_node_ids(canvas, child).values())
        pending.extend(children_of(canvas, child))
    return out


def io_pin_ids(canvas, gid: str) -> dict:
    """组入口/出口节点的真实 PinId 快照（诊断/测试用）。"""
    nodes = _nodes(canvas)
    ids = io_node_ids(canvas, gid)
    start = nodes.get(ids.get("start", -1))
    end = nodes.get(ids.get("end", -1))
    return {
        "start_node": ids.get("start"),
        "end_node": ids.get("end"),
        "out_pin": (start.pin_ids.get("exec_out")
                    if start is not None else None),
        "in_pin": (end.pin_ids.get("exec_in")
                   if end is not None else None),
        "start_type": str(getattr(start, "node_type", "") or "") or None,
        "end_type": str(getattr(end, "node_type", "") or "") or None,
    }


def _members(grp: dict) -> list[int]:
    out: list[int] = []
    for raw in grp.get("members") or []:
        nid = _to_nid(raw)
        if nid is not None and nid not in out:
            out.append(nid)
    return out


def _io_layout(box: tuple[float, float, float, float]
               ) -> tuple[tuple[float, float], tuple[float, float]]:
    """组框边缘的入口/出口锚点（实际位置由 panel 每帧贴边绘制）。"""
    x, y, w, h = (float(v) for v in box)
    start = (x + 8.0, y + 58.0)
    end = (x + max(8.0, w - 112.0), y + max(58.0, h - 42.0))
    return start, end


def ensure_group_io_nodes(canvas, gid: str, size_of=None,
                          update_min: bool = True) -> dict:
    """确保组拥有 GroupStart/GroupEnd，并保持它们属于该组。

    ``size_of`` 与 group_geometry 的回调一致：``(nid, inst) -> (w, h)``。
    返回更新后的 ``{start, end}``。节点创建失败（类型未注册/假 canvas）
    时静默跳过，不破坏组元数据。
    """
    gid = str(gid)
    groups = _groups(canvas)
    grp = groups.get(gid)
    if not isinstance(grp, dict):
        return {}
    if not hasattr(canvas, "add_node"):
        return io_node_ids(canvas, gid)

    existing = io_node_ids(canvas, gid)
    members = _members(grp)
    if (len(existing) == 2
            and all(nid in members for nid in existing.values())):
        # 旧组框使用 56px 顶部 margin，边缘接口会压到成员卡片；升级时
        # 一次性扩展到新的 header 高度，然后让真实尺寸在下一帧校正。
        if int(grp.get("layout_version") or 0) < GROUP_LAYOUT_VERSION:
            box = fit_group(canvas, gid, size_of, shrink=False,
                            update_min=False)
            if box is not None:
                grp["layout_version"] = GROUP_LAYOUT_VERSION
        return dict(existing)

    nodes = _nodes(canvas)
    had_box = get_box(canvas, gid) is not None
    box = ensure_box(canvas, gid, size_of) or (0.0, 0.0, 240.0, 120.0)
    start_xy, end_xy = _io_layout(box)
    missing = [key for key in ("start", "end") if key not in existing]
    changed = bool(missing)
    if missing:
        for key in missing:
            node_type = START_TYPE if key == "start" else END_TYPE
            pos = start_xy if key == "start" else end_xy
            nid = canvas.add_node(node_type, pos)
            if nid is None or int(nid) < 0:
                continue
            existing[key] = int(nid)
            inst = nodes.get(int(nid))
            if inst is not None:
                # Group IO nodes are internal; keep them out of alias lookup.
                inst.alias = ""

    if not existing:
        return {}

    for nid in existing.values():
        if nid not in members:
            members.append(nid)
            changed = True
    if changed:
        grp["members"] = sorted(members)
        grp[IO_KEY] = {key: int(nid) for key, nid in existing.items()}
        fit_group(canvas, gid, size_of, shrink=False, update_min=update_min)
        grp["layout_version"] = GROUP_LAYOUT_VERSION
        if not had_box:
            grp["box_auto"] = True
    return dict(existing)


def ensure_all_group_io_nodes(canvas, size_of=None) -> dict[str, dict]:
    """为所有组补齐内部节点；子组先算，父组后算。"""
    groups = _groups(canvas)
    out: dict[str, dict] = {}
    for gid in sorted(groups, key=lambda g: group_depth(canvas, g),
                      reverse=True):
        info = ensure_group_io_nodes(canvas, str(gid), size_of)
        if info:
            out[str(gid)] = info
    return out


def remove_group_io_nodes(canvas, gid: str) -> list[int]:
    """移除组的内部起点/终点节点及其连线（成员关系随组元数据一起消失）。"""
    gid = str(gid)
    groups = _groups(canvas)
    grp = groups.get(gid)
    if not isinstance(grp, dict):
        return []
    ids = io_node_ids(canvas, gid)
    removed: list[int] = []
    for nid in ids.values():
        remove_node = getattr(canvas, "remove_node", None)
        if callable(remove_node):
            remove_node(int(nid))
        if int(nid) not in removed:
            removed.append(int(nid))
    if ids:
        keep = [nid for nid in _members(grp) if nid not in ids.values()]
        grp["members"] = keep
    grp.pop(IO_KEY, None)
    return removed
