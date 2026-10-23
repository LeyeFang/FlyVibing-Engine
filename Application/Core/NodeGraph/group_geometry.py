"""节点组框几何 — 持久化 box / 自适应 / 成员进入离开 / 比例缩放。

纯数据（无 imgui/Editor 依赖）。组框几何是 ``node_groups[gid]`` 的一部分：

    "box":     {"x": float, "y": float, "w": float, "h": float}
    "min_box": {"w": float, "h": float}   # 缩放手柄的下限

坐标系为画布坐标（与 ``NodeInstance.pos`` 一致）。

设计约束
--------
- **不要每帧从成员包围盒推导组框**：用户手工 resize 会被下一帧覆盖。
- 成员进入/离开、组内重排时显式调用 ``fit_group`` / ``expand_group_to_rect``。
- 手工缩放调用 ``scale_group_to_box``，成员 position 按比例移动。
- 父组包含子组时，父组内容矩形使用子组 **box**，不再递归节点。
"""

from __future__ import annotations

from typing import Callable, Iterable

Rect = tuple[float, float, float, float]  # x, y, w, h
SizeOf = Callable[[int, object], tuple[float, float]]

# 组入口/出口节点由编辑器绘制在组框边缘，不作为内容包围盒的一部分；
# 否则每次新建组都会为了容纳接口卡片而额外扩框。
GROUP_IO_TYPES = frozenset({"GroupStart", "GroupEnd"})

# 与编辑器 group_layout.PAD_* 保持一致：Rearrange 用这些 padding 生成
# 组内位置，fit 时再用同一组 margin 反推组框，组框才不会每次重排漂移。
MARGIN_LEFT = 100.0
# 组标题 + 描述 + 组入口接口占用顶部 header 带，成员卡片从 MARGIN_TOP 下方开始。
MARGIN_TOP = 96.0
MARGIN_RIGHT = 100.0
MARGIN_BOTTOM = 48.0
GROUP_LAYOUT_VERSION = 3

DEFAULT_W = 240.0
DEFAULT_H = 120.0


# ── 基础矩形 ─────────────────────────────────────────────


def rect_right(rect: Rect) -> float:
    return float(rect[0]) + float(rect[2])


def rect_bottom(rect: Rect) -> float:
    return float(rect[1]) + float(rect[3])


def rect_union(a: Rect | None, b: Rect | None) -> Rect | None:
    if a is None:
        return b
    if b is None:
        return a
    x0 = min(float(a[0]), float(b[0]))
    y0 = min(float(a[1]), float(b[1]))
    x1 = max(rect_right(a), rect_right(b))
    y1 = max(rect_bottom(a), rect_bottom(b))
    return (x0, y0, x1 - x0, y1 - y0)


def fit_rect(rect: Rect | None) -> Rect | None:
    """内容矩形 → 组框矩形（加 margin）。"""
    if rect is None:
        return None
    x, y, w, h = rect
    return (x - MARGIN_LEFT, y - MARGIN_TOP,
            max(1.0, w + MARGIN_LEFT + MARGIN_RIGHT),
            max(1.0, h + MARGIN_TOP + MARGIN_BOTTOM))


def point_in_rect(rect: Rect | None, point: tuple[float, float]) -> bool:
    if rect is None:
        return False
    return (rect[0] <= point[0] <= rect_right(rect)
            and rect[1] <= point[1] <= rect_bottom(rect))


# ── 组数据访问 ───────────────────────────────────────────


def groups_of(canvas) -> dict:
    groups = getattr(canvas, "node_groups", None)
    if groups is None:
        groups = {}
        try:
            canvas.node_groups = groups
        except Exception:  # noqa: BLE001 — duck-typed canvas
            pass
    return groups


def children_of(canvas, gid: str) -> list[str]:
    groups = groups_of(canvas)
    grp = groups.get(gid) or {}
    out: list[str] = []
    for raw in grp.get("children") or []:
        cgid = str(raw)
        if cgid in groups and cgid != gid and cgid not in out:
            out.append(cgid)
    for cgid, child in groups.items():
        if cgid == gid:
            continue
        if str((child or {}).get("parent") or "") == gid and cgid not in out:
            out.append(cgid)
    return out


def direct_members(canvas, gid: str) -> list[int]:
    grp = groups_of(canvas).get(gid) or {}
    nodes = getattr(canvas, "nodes", {}) or {}
    out: list[int] = []
    for raw in grp.get("members") or []:
        try:
            nid = int(raw)
        except (TypeError, ValueError):
            continue
        if nid in nodes and nid not in out:
            out.append(nid)
    return out


def all_member_ids(canvas, gid: str, _seen: set[str] | None = None) -> list[int]:
    groups = groups_of(canvas)
    if _seen is None:
        _seen = set()
    if gid in _seen:
        return []
    _seen.add(gid)
    out = direct_members(canvas, gid)
    for cgid in children_of(canvas, gid):
        for nid in all_member_ids(canvas, cgid, _seen):
            if nid not in out:
                out.append(nid)
    return out


def group_depth(canvas, gid: str) -> int:
    groups = groups_of(canvas)
    depth = 0
    seen: set[str] = set()
    cur = gid
    while cur and cur not in seen:
        seen.add(cur)
        parent = str((groups.get(cur) or {}).get("parent") or "")
        if not parent or parent not in groups:
            break
        depth += 1
        cur = parent
    return depth


def group_chain(canvas, gid: str) -> list[str]:
    """gid + 所有祖先（由深到浅）。"""
    groups = groups_of(canvas)
    out = [gid]
    seen = {gid}
    cur = gid
    while True:
        parent = str((groups.get(cur) or {}).get("parent") or "")
        if not parent or parent not in groups or parent in seen:
            break
        out.append(parent)
        seen.add(parent)
        cur = parent
    return out


def descendant_groups(canvas, gid: str) -> list[str]:
    """所有后代组（不含自身）。"""
    out: list[str] = []
    seen: set[str] = set()
    pending = list(children_of(canvas, gid))
    while pending:
        cur = pending.pop(0)
        if cur in seen or cur == gid:
            continue
        seen.add(cur)
        out.append(cur)
        pending.extend(children_of(canvas, cur))
    return out


# ── box 读写 ─────────────────────────────────────────────


def _coerce_box(raw) -> Rect | None:
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x", 0.0))
        y = float(raw.get("y", 0.0))
        w = float(raw.get("w", 0.0))
        h = float(raw.get("h", 0.0))
    except (TypeError, ValueError):
        return None
    if w <= 0.0 or h <= 0.0:
        return None
    return (x, y, w, h)


def get_box(canvas, gid: str) -> Rect | None:
    grp = groups_of(canvas).get(gid) or {}
    return _coerce_box(grp.get("box"))


def get_min_box(canvas, gid: str) -> tuple[float, float] | None:
    grp = groups_of(canvas).get(gid) or {}
    raw = grp.get("min_box")
    if not isinstance(raw, dict):
        return None
    try:
        w = float(raw.get("w", 0.0))
        h = float(raw.get("h", 0.0))
    except (TypeError, ValueError):
        return None
    if w <= 0.0 or h <= 0.0:
        return None
    return (w, h)


def set_box(canvas, gid: str, box: Rect,
            min_box: tuple[float, float] | None = None) -> None:
    grp = groups_of(canvas).get(gid)
    if grp is None:
        return
    x, y, w, h = box
    grp.pop("box_auto", None)
    grp["box"] = {
        "x": round(float(x), 2),
        "y": round(float(y), 2),
        "w": round(max(1.0, float(w)), 2),
        "h": round(max(1.0, float(h)), 2),
    }
    if min_box is not None:
        grp["min_box"] = {
            "w": round(max(1.0, float(min_box[0])), 2),
            "h": round(max(1.0, float(min_box[1])), 2),
        }


def _fallback_size(inst) -> tuple[float, float]:
    # 保守估计；Editor 侧会传入真实节点尺寸回调。
    return (160.0, 96.0)


def node_rect(canvas, nid: int, size_of: SizeOf | None = None) -> Rect | None:
    inst = (getattr(canvas, "nodes", {}) or {}).get(int(nid))
    if inst is None:
        return None
    w, h = _fallback_size(inst)
    if size_of is not None:
        try:
            got = size_of(int(nid), inst)
            if got is not None:
                w, h = float(got[0]), float(got[1])
        except Exception:  # noqa: BLE001 — 回调失败退回估计值
            pass
    try:
        x, y = float(inst.pos[0]), float(inst.pos[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (x, y, max(1.0, w), max(1.0, h))


def content_rect(canvas, gid: str, size_of: SizeOf | None = None,
                 _seen: set[str] | None = None) -> Rect | None:
    """组内内容（直接/递归节点 + 子组 box）的包围盒。"""
    groups = groups_of(canvas)
    if gid not in groups:
        return None
    if _seen is None:
        _seen = set()
    if gid in _seen:
        return None
    _seen.add(gid)

    rect: Rect | None = None
    nodes = getattr(canvas, "nodes", {}) or {}
    for nid in all_member_ids(canvas, gid):
        inst = nodes.get(int(nid))
        if inst is not None and str(getattr(inst, "node_type", "")) in GROUP_IO_TYPES:
            continue
        rect = rect_union(rect, node_rect(canvas, nid, size_of))
    for cgid in children_of(canvas, gid):
        child_box = ensure_box(canvas, cgid, size_of, _seen)
        rect = rect_union(rect, child_box)
    return rect


def ensure_box(canvas, gid: str, size_of: SizeOf | None = None,
               _seen: set[str] | None = None) -> Rect | None:
    """取组框；缺失时按内容初始化并持久化。"""
    box = get_box(canvas, gid)
    grp = groups_of(canvas).get(gid) or {}
    if box is not None:
        # 首次用估计尺寸初始化；拿到真实节点尺寸后校正一次。
        if grp.get("box_auto") and size_of is not None:
            content = content_rect(canvas, gid, size_of, _seen)
            fitted = fit_rect(content)
            if fitted is not None:
                set_box(canvas, gid, fitted, (fitted[2], fitted[3]))
                return fitted
        return box
    content = content_rect(canvas, gid, size_of, _seen)
    fitted = fit_rect(content)
    if fitted is None:
        fitted = (0.0, 0.0, DEFAULT_W, DEFAULT_H)
    set_box(canvas, gid, fitted, (fitted[2], fitted[3]))
    grp = groups_of(canvas).get(gid)
    if grp is not None:
        grp["layout_version"] = GROUP_LAYOUT_VERSION
        if size_of is None:
            grp["box_auto"] = True
    return fitted


def _upgrade_box_layout(canvas, gid: str,
                        size_of: SizeOf | None = None) -> None:
    """旧布局升级：只向四周扩容，不覆盖用户手工放大的组框。"""
    grp = groups_of(canvas).get(gid) or {}
    box = get_box(canvas, gid)
    if box is None:
        return
    try:
        version = int(grp.get("layout_version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= GROUP_LAYOUT_VERSION:
        return
    required = fit_rect(content_rect(canvas, gid, size_of))
    if required is not None:
        x0 = min(float(box[0]), float(required[0]))
        y0 = min(float(box[1]), float(required[1]))
        x1 = max(rect_right(box), rect_right(required))
        y1 = max(rect_bottom(box), rect_bottom(required))
        set_box(canvas, gid, (x0, y0, x1 - x0, y1 - y0),
                (required[2], required[3]))
    grp["layout_version"] = GROUP_LAYOUT_VERSION


def init_boxes(canvas, size_of: SizeOf | None = None) -> None:
    """为所有缺 box 的组初始化；子组先算，父组后算。"""
    groups = groups_of(canvas)
    for gid in sorted(groups, key=lambda g: -group_depth(canvas, g)):
        _upgrade_box_layout(canvas, gid, size_of)
        ensure_box(canvas, gid, size_of)


# ── 自适应 / 成员进入离开 ───────────────────────────────


def fit_group(canvas, gid: str, size_of: SizeOf | None = None,
              *, shrink: bool = True,
              extra_rect: Rect | None = None,
              update_min: bool = True) -> Rect | None:
    """按内容重算组框。

    shrink=True  ：成员离开后收紧到内容 + margin。
    shrink=False ：成员进入/内部移动时只扩不缩。
    """
    if gid not in groups_of(canvas):
        return None
    content = content_rect(canvas, gid, size_of)
    required = fit_rect(content)
    if extra_rect is not None:
        required = rect_union(required, fit_rect(extra_rect))
    if required is None:
        required = get_box(canvas, gid)
    if required is None:
        return None

    current = get_box(canvas, gid)
    if not shrink and current is not None:
        new_box = rect_union(current, required) or required
    else:
        new_box = required
    set_box(canvas, gid, new_box,
            (required[2], required[3]) if update_min else get_min_box(canvas, gid))
    for parent in group_chain(canvas, gid)[1:]:
        fit_group(canvas, parent, size_of, shrink=False, update_min=False)
    return new_box


def expand_group_to_rect(canvas, gid: str, rect: Rect,
                         size_of: SizeOf | None = None) -> Rect | None:
    """成员被拖入：组框只增不减，确保覆盖目标节点 + margin。"""
    return fit_group(canvas, gid, size_of, shrink=False,
                     extra_rect=rect, update_min=True)


def set_member(canvas, nid: int, target_gid: str | None) -> list[str]:
    """把节点从所有组的直接 members 里摘除，再加入目标组。

    Returns: 受影响的组 id（摘除的旧组 + 目标组）。
    """
    groups = groups_of(canvas)
    nid = int(nid)
    affected: list[str] = []
    for gid, grp in groups.items():
        raw = grp.get("members") or []
        members: list[int] = []
        removed = False
        for item in raw:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value == nid:
                removed = True
                continue
            if value not in members:
                members.append(value)
        if removed:
            grp["members"] = members
            affected.append(gid)
    if target_gid and target_gid in groups:
        grp = groups[target_gid]
        members = []
        for item in grp.get("members") or []:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value not in members:
                members.append(value)
        if nid not in members:
            members.append(nid)
        grp["members"] = sorted(members)
        if target_gid not in affected:
            affected.append(target_gid)
    return affected


def group_at_point(canvas, point: tuple[float, float],
                   size_of: SizeOf | None = None) -> str | None:
    """鼠标点落入的最深组框。"""
    hits = []
    for gid in groups_of(canvas):
        box = ensure_box(canvas, gid, size_of)
        if point_in_rect(box, point):
            hits.append(gid)
    if not hits:
        return None
    return max(hits, key=lambda g: (group_depth(canvas, g), g))


# ── 平移 / 比例缩放 ──────────────────────────────────────


def translate_group(canvas, gid: str, dx: float, dy: float) -> int:
    """平移组框 + 全部成员节点 + 子组 box。返回移动节点数。"""
    moved = 0
    seen: set[int] = set()
    for nid in all_member_ids(canvas, gid):
        inst = (getattr(canvas, "nodes", {}) or {}).get(nid)
        if inst is None or nid in seen:
            continue
        seen.add(nid)
        inst.pos = (float(inst.pos[0]) + float(dx),
                    float(inst.pos[1]) + float(dy))
        moved += 1
    for child in [gid, *descendant_groups(canvas, gid)]:
        box = get_box(canvas, child)
        if box is not None:
            set_box(canvas, child, (box[0] + dx, box[1] + dy, box[2], box[3]),
                    get_min_box(canvas, child))
    for parent in group_chain(canvas, gid)[1:]:
        fit_group(canvas, parent, shrink=False, update_min=True)
    return moved


def scale_group_to_box(canvas, gid: str, new_box: Rect,
                       size_of: SizeOf | None = None) -> Rect | None:
    """手工 resize：组框改为 new_box，成员 position 按比例移动。

    缩放下限 = ``min_box``（成员内容 + margin）。返回实际应用的 box。
    """
    old = get_box(canvas, gid)
    if old is None:
        old = ensure_box(canvas, gid, size_of)
    if old is None:
        return None
    min_box = get_min_box(canvas, gid)
    nx, ny, nw, nh = (float(new_box[0]), float(new_box[1]),
                      float(new_box[2]), float(new_box[3]))
    if min_box is not None:
        nw = max(nw, float(min_box[0]))
        nh = max(nh, float(min_box[1]))
    nw = max(1.0, nw)
    nh = max(1.0, nh)
    old_x, old_y, old_w, old_h = old
    sx = nw / old_w if old_w > 0.0 else 1.0
    sy = nh / old_h if old_h > 0.0 else 1.0

    for nid in all_member_ids(canvas, gid):
        inst = (getattr(canvas, "nodes", {}) or {}).get(nid)
        if inst is None:
            continue
        px, py = float(inst.pos[0]), float(inst.pos[1])
        inst.pos = (nx + (px - old_x) * sx, ny + (py - old_y) * sy)

    # 子组 box 同步比例缩放（成员节点已单独移动）。
    for child in descendant_groups(canvas, gid):
        cbox = get_box(canvas, child)
        if cbox is None:
            continue
        cx = nx + (cbox[0] - old_x) * sx
        cy = ny + (cbox[1] - old_y) * sy
        set_box(canvas, child, (cx, cy, cbox[2] * sx, cbox[3] * sy),
                get_min_box(canvas, child))

    set_box(canvas, gid, (nx, ny, nw, nh), min_box)
    for parent in group_chain(canvas, gid)[1:]:
        fit_group(canvas, parent, size_of, shrink=False, update_min=False)
    return (nx, ny, nw, nh)
