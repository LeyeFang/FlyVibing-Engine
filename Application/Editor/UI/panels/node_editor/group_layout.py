"""Group-aware node layout — pure data, no imgui.

The editor stores node groups as opaque metadata on ``NodeCanvas.node_groups``.
This module turns that metadata into layout blocks so Rearrange can:

  * keep every top-level group together (a group is one unit in the outer graph);
  * recursively lay out nested groups (a child group is one unit in its parent);
  * expose deterministic group bounds for the background frames and drag code.

Only the editor layer uses this module.  The runtime/validator must not import it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from Application.Core.NodeGraph.group_geometry import GROUP_IO_TYPES
from Application.Core.NodeGraph.node_types import _TYPES

# Card geometry estimates.  Keep these in sync with the node-editor card renderer;
# exact pixel widths are not needed for non-overlap, only a stable upper bound.
NODE_WIDTH = 300.0
NODE_HEADER = 44.0
NODE_PER_PIN = 24.0
WIDGET_EXTRA = 44.0
H_GAP = 90.0
V_GAP = 40.0

# Background group frame padding around its member cards / child group frames.
# 左侧 100px 给 group exec out，右侧 100px 给 group exec in，
# 端口与成员卡片之间留出可视线槽；否则入口连线会从卡片上方穿过。
PAD_LEFT = 100.0
PAD_TOP = 96.0
PAD_RIGHT = 100.0
PAD_BOTTOM = 48.0

EVENT_TYPES = frozenset({"OnGameStart", "OnFrameUpdate", "OnGameStop"})
WIDGET_TYPES = frozenset({
    "VarGet", "VarSet", "Constant", "StringConst",
    "EntitySpawn", "EntityGet", "EntitySetRenderVisible", "EntityGroupSetVisible",
    "ComponentAdd", "SetComponent", "GetComponent", "ComponentRemove",
    "ParallelSend", "SerialSend", "PathVar", "TextFileWrite",
    "TimeGetDate",
    "InitSigGenDevice", "StartSigGenRecord", "StopSigGenRecord",
    "KillSigGenDevice", "GetSigGenData",
    "ShowMedia", "SetText",
})


# ── public geometry helpers ─────────────────────────────────


def node_size(inst) -> tuple[float, float]:
    """Conservative card size estimate used for layout and group bounds."""
    if inst.node_type in ("GroupStart", "GroupEnd"):
        # 内部 exec 接口节点只有一行 pin + 标题，比普通卡片窄得多。
        return (150.0, 68.0)
    ndef = _TYPES.get(inst.node_type)
    pins = len(ndef.pins) if ndef else 2
    title = ndef.label if ndef else inst.node_type
    longest_pin = max(
        (len(p.name) for p in (ndef.pins if ndef else [])),
        default=0,
    )
    width = max(NODE_WIDTH, 8.0 * max(len(title), longest_pin + 4) + 80.0)
    height = NODE_HEADER + pins * NODE_PER_PIN
    if inst.node_type in WIDGET_TYPES:
        height += WIDGET_EXTRA
    return width, height


def group_member_ids(canvas, gid: str) -> list[int]:
    """All existing node ids directly or transitively owned by ``gid``."""
    groups = getattr(canvas, "node_groups", None) or {}
    nodes = getattr(canvas, "nodes", {}) or {}
    seen: set[str] = set()

    def collect(group_id: str) -> list[int]:
        if group_id in seen:
            return []
        seen.add(group_id)
        group = groups.get(group_id) or {}
        out: list[int] = []
        for raw in group.get("members") or []:
            try:
                nid = int(raw)
            except (TypeError, ValueError):
                continue
            if nid in nodes and nid not in out:
                out.append(nid)
        for cgid in children_of(canvas, group_id):
            for nid in collect(cgid):
                if nid not in out:
                    out.append(nid)
        return out

    return collect(gid)


def children_of(canvas, gid: str) -> list[str]:
    groups = getattr(canvas, "node_groups", None) or {}
    group = groups.get(gid) or {}
    out: list[str] = []
    for raw in group.get("children") or []:
        cgid = str(raw)
        if cgid in groups and cgid != gid and cgid not in out:
            out.append(cgid)
    for cgid, child in groups.items():
        if str((child or {}).get("parent") or "") == gid and cgid not in out:
            out.append(cgid)
    return out


def group_depth(canvas, gid: str) -> int:
    groups = getattr(canvas, "node_groups", None) or {}
    depth = 0
    seen: set[str] = set()
    current = gid
    while current and current not in seen:
        seen.add(current)
        parent = str((groups.get(current) or {}).get("parent") or "")
        if not parent or parent not in groups:
            break
        depth += 1
        current = parent
    return depth


def group_order(canvas) -> list[str]:
    """Top-level groups first, then children (parents paint behind children)."""
    groups = getattr(canvas, "node_groups", None) or {}
    return sorted(groups, key=lambda gid: (group_depth(canvas, gid), gid))


def group_bounds(canvas, gid: str) -> tuple[float, float, float, float] | None:
    """Return ``(x, y, width, height)`` for a group frame, or None if empty.

    自 2026-10-22 起优先使用持久化的 ``node_groups[gid]["box"]``；
    只有旧数据缺少 box 时才按成员包围盒初始化一次并写回。这样用户
    手工 resize 的组框不会被下一帧重新推导覆盖。
    """
    from Application.Core.NodeGraph.group_geometry import ensure_box

    box = ensure_box(canvas, gid)
    return box


def descendant_group_ids(canvas, gid: str) -> set[str]:
    groups = getattr(canvas, "node_groups", None) or {}
    out: set[str] = set()
    queue = deque(children_of(canvas, gid))
    while queue:
        cgid = queue.popleft()
        if cgid in out or cgid not in groups:
            continue
        out.add(cgid)
        queue.extend(children_of(canvas, cgid))
    return out


# ── layout engine ────────────────────────────────────────────


@dataclass
class _Unit:
    key: str
    width: float = 0.0
    height: float = 0.0
    gid: str | None = None
    node_id: int | None = None
    # Node positions relative to this unit's top-left (groups include padding).
    local: dict[int, tuple[float, float]] = field(default_factory=dict)
    nodes: list[int] = field(default_factory=list)


class GroupLayoutEngine:
    """Recursive cluster layout over ``canvas.node_groups``."""

    def __init__(self, canvas) -> None:
        self.canvas = canvas
        self.nodes = getattr(canvas, "nodes", {}) or {}
        self.links = getattr(canvas, "links", {}) or {}
        self.groups: dict[str, dict] = getattr(canvas, "node_groups", None) or {}
        self.pin_node: dict[int, int] = {}
        self.pin_kind: dict[int, str] = {}
        self._member_cache: dict[str, list[int]] = {}
        self._build_pin_index()

    # ── building blocks ─────────────────────────────────────

    def _build_pin_index(self) -> None:
        for nid, inst in self.nodes.items():
            ndef = _TYPES.get(inst.node_type)
            if ndef is None:
                continue
            for pin in ndef.pins:
                pid = inst.pin_ids.get(pin.name)
                if pid is not None:
                    self.pin_node[int(pid)] = nid
                    self.pin_kind[int(pid)] = pin.kind

    def _members(self, gid: str) -> list[int]:
        if gid not in self._member_cache:
            self._member_cache[gid] = group_member_ids(self.canvas, gid)
        return self._member_cache[gid]

    def _direct_nodes(self, gid: str) -> list[int]:
        child_nodes: set[int] = set()
        for cgid in children_of(self.canvas, gid):
            child_nodes.update(self._members(cgid))
        out: list[int] = []
        for nid in self._members(gid):
            if nid in child_nodes:
                continue
            inst = self.nodes.get(nid)
            if inst is not None and inst.node_type in GROUP_IO_TYPES:
                continue
            out.append(nid)
        return out

    def _node_unit(self, nid: int) -> _Unit:
        inst = self.nodes[nid]
        width, height = node_size(inst)
        return _Unit(
            key=f"n:{nid}", width=width, height=height,
            node_id=nid, local={nid: (0.0, 0.0)}, nodes=[nid],
        )

    def _group_unit(self, gid: str, visiting: set[str]) -> _Unit | None:
        if gid in visiting:
            return None
        children = [c for c in children_of(self.canvas, gid) if c in self.groups]
        units: list[_Unit] = [self._node_unit(nid) for nid in self._direct_nodes(gid)]
        child_units: list[_Unit] = []
        next_visiting = set(visiting)
        next_visiting.add(gid)
        for cgid in children:
            unit = self._group_unit(cgid, next_visiting)
            if unit is not None:
                child_units.append(unit)
        units.extend(child_units)
        if not units:
            return _Unit(key=f"g:{gid}", gid=gid, width=200.0, height=80.0,
                         local={}, nodes=[])
        owner: dict[int, str] = {}
        for unit in units:
            for nid in unit.nodes:
                owner[nid] = unit.key
        placements = self._layout_units(units, owner)
        positions: dict[int, tuple[float, float]] = {}
        max_x = 0.0
        max_y = 0.0
        for unit in units:
            x, y = placements.get(unit.key, (0.0, 0.0))
            for nid, (lx, ly) in unit.local.items():
                positions[nid] = (PAD_LEFT + x + lx, PAD_TOP + y + ly)
            max_x = max(max_x, x + unit.width)
            max_y = max(max_y, y + unit.height)
        width = PAD_LEFT + max_x + PAD_RIGHT
        height = PAD_TOP + max_y + PAD_BOTTOM
        return _Unit(
            key=f"g:{gid}", gid=gid, width=width, height=height,
            local=positions, nodes=list(positions),
        )

    def _root_units(self) -> list[_Unit]:
        child_gids = {cgid for gid in self.groups
                      for cgid in children_of(self.canvas, gid)}
        top_gids = [
            gid for gid in self.groups
            if gid not in child_gids
            and str((self.groups.get(gid) or {}).get("parent") or "") not in self.groups
        ]
        units: list[_Unit] = []
        grouped: set[int] = set()
        for gid in top_gids:
            unit = self._group_unit(gid, set())
            if unit is None:
                continue
            units.append(unit)
            grouped.update(unit.nodes)
        for nid in sorted(self.nodes):
            inst = self.nodes.get(nid)
            if inst is not None and inst.node_type in GROUP_IO_TYPES:
                continue
            if nid not in grouped:
                units.append(self._node_unit(nid))
        return units

    # ── outer layout ─────────────────────────────────────────

    def _layout_units(self, units: list[_Unit],
                      owner: dict[int, str]) -> dict[str, tuple[float, float]]:
        if not units:
            return {}
        by_key = {u.key: u for u in units}
        exec_succ: dict[str, list[str]] = defaultdict(list)
        succ: dict[str, list[str]] = defaultdict(list)
        pred: dict[str, list[str]] = defaultdict(list)
        for link in self.links.values():
            sn = self.pin_node.get(int(link.from_pin))
            tn = self.pin_node.get(int(link.to_pin))
            if sn is None or tn is None:
                continue
            su = owner.get(sn)
            tu = owner.get(tn)
            if not su or not tu or su == tu:
                continue
            if tu not in succ[su]:
                succ[su].append(tu)
            if su not in pred[tu]:
                pred[tu].append(su)
            if self.pin_kind.get(int(link.from_pin)) == "exec":
                if tu not in exec_succ[su]:
                    exec_succ[su].append(tu)

        # Event roots carry the graph; a group containing an event is a root.
        roots = [
            u.key for u in units
            if any(self.nodes.get(nid) is not None
                   and self.nodes[nid].node_type in EVENT_TYPES for nid in u.nodes)
        ]
        if not roots:
            roots = [u.key for u in units if not pred.get(u.key)]
        layer: dict[str, int] = {}
        queue: deque[str] = deque()
        for key in roots:
            if key in by_key and key not in layer:
                layer[key] = 0
                queue.append(key)
        while queue:
            key = queue.popleft()
            for nxt in exec_succ.get(key, []):
                if nxt in by_key and nxt not in layer:
                    layer[nxt] = layer[key] + 1
                    queue.append(nxt)
        # Disconnected/cycles: derive from any known predecessor, then fall back.
        for unit in units:
            if unit.key in layer:
                continue
            pred_layers = [layer[p] for p in pred.get(unit.key, []) if p in layer]
            layer[unit.key] = (max(pred_layers) + 1) if pred_layers else 0

        layers: dict[int, list[str]] = defaultdict(list)
        for unit in units:
            layers[layer.get(unit.key, 0)].append(unit.key)
        # Stable initial order; then two barycenter sweeps reduce crossings.
        y_order: dict[str, float] = {}
        for lyr in sorted(layers):
            for i, key in enumerate(layers[lyr]):
                y_order[key] = float(i)
        for _ in range(2):
            for lyr in sorted(layers):
                def left_key(key: str) -> tuple[float, str]:
                    ps = pred.get(key, [])
                    if ps:
                        return (sum(y_order.get(p, 0.0) for p in ps) / len(ps), key)
                    return (float(int(by_key[key].node_id or 0) % 1000), key)
                layers[lyr].sort(key=left_key)
                for i, key in enumerate(layers[lyr]):
                    y_order[key] = float(i)
            for lyr in sorted(layers, reverse=True):
                def right_key(key: str) -> tuple[float, str]:
                    ss = succ.get(key, [])
                    if ss:
                        return (sum(y_order.get(s, 0.0) for s in ss) / len(ss), key)
                    return (float(int(by_key[key].node_id or 0) % 1000), key)
                layers[lyr].sort(key=right_key)
                for i, key in enumerate(layers[lyr]):
                    y_order[key] = float(i)

        placements: dict[str, tuple[float, float]] = {}
        cursor_x = 0.0
        for lyr in sorted(layers):
            keys = layers[lyr]
            col_width = max(by_key[k].width for k in keys)
            cursor_y = 0.0
            for key in keys:
                unit = by_key[key]
                placements[key] = (
                    cursor_x + (col_width - unit.width) * 0.5,
                    cursor_y,
                )
                cursor_y += unit.height + V_GAP
            cursor_x += col_width + H_GAP
        return placements

    # ── public result ────────────────────────────────────────

    def layout_all(self) -> dict[int, tuple[float, float]]:
        units = self._root_units()
        owner = {nid: unit.key for unit in units for nid in unit.nodes}
        placements = self._layout_units(units, owner)
        out: dict[int, tuple[float, float]] = {}
        for unit in units:
            ux, uy = placements.get(unit.key, (0.0, 0.0))
            for nid, (lx, ly) in unit.local.items():
                out[nid] = (80.0 + ux + lx, 80.0 + uy + ly)
        return out

    def layout_group(self, gid: str) -> dict[int, tuple[float, float]]:
        unit = self._group_unit(gid, set())
        return dict(unit.local) if unit is not None else {}

    def group_size(self, gid: str) -> tuple[float, float]:
        unit = self._group_unit(gid, set())
        return (unit.width, unit.height) if unit is not None else (0.0, 0.0)
