"""节点组元数据操作 — 合并 / 拆分 / 删除 / 销毁（纯数据，无 UI 依赖）。

组的唯一事实源是 ``NodeCanvas.node_groups``。GUI、Live CLI 与离线工具复用
同一语义；除 ``destroy_group`` 外，本模块不移动/删除用户成员节点。

约定:
  - 组 id: ``g<N>``（与 tools 的 node_groups 一致）
  - ``members``: 直接成员节点 id（整数），含内部 GroupStart/GroupEnd
  - ``children``: 直接子组 id
  - ``parent``: 父组 id（根组无此字段）
  - ``description``: 组标题下方的说明文本
  - ``io_nodes``: ``{start, end}`` → 组内部 GroupStart/GroupEnd 节点 id
  - ``ungroup`` / ``delete_group`` 只拆框，用户成员节点保留；
    ``destroy_group`` 全删组框、子组与全部成员节点
"""

from __future__ import annotations

import re
from typing import Iterable

from .group_nodes import remove_group_io_nodes

_GROUP_ID_RE = re.compile(r"^g(\d+)$")


def _groups(canvas) -> dict:
    groups = getattr(canvas, "node_groups", None)
    if groups is None:
        groups = {}
        try:
            canvas.node_groups = groups
        except Exception:  # noqa: BLE001 - duck-typed canvas in tests
            pass
    return groups


def _nodes(canvas) -> dict:
    return getattr(canvas, "nodes", {}) or {}


def _resolve_node_ref(canvas, ref) -> int | None:
    """节点引用 → id（支持 id / #id / @alias / 唯一类型名）。"""
    nodes = _nodes(canvas)
    if isinstance(ref, int):
        return ref if ref in nodes else None
    raw = str(ref or "").strip()
    if not raw:
        return None
    if raw.startswith("#"):
        raw = raw[1:]
    if raw.isdigit():
        nid = int(raw)
        return nid if nid in nodes else None
    name = raw.lstrip("@").lower()
    alias_hits = [nid for nid, inst in nodes.items()
                  if str(getattr(inst, "alias", "") or "").lower() == name]
    if len(alias_hits) == 1:
        return int(alias_hits[0])
    type_hits = [nid for nid, inst in nodes.items()
                 if str(getattr(inst, "node_type", "") or "") == raw]
    return int(type_hits[0]) if len(type_hits) == 1 else None


def _int_members(grp: dict) -> list[int]:
    out: list[int] = []
    for raw in grp.get("members") or []:
        try:
            nid = int(raw)
        except (TypeError, ValueError):
            continue
        if nid not in out:
            out.append(nid)
    return out


def _children(groups: dict, gid: str) -> list[str]:
    """直接子组（children 列表 + parent 反向引用，去重）。"""
    grp = groups.get(gid) or {}
    out: list[str] = []
    for raw in grp.get("children") or []:
        cgid = str(raw)
        if cgid in groups and cgid != gid and cgid not in out:
            out.append(cgid)
    for cgid, child in groups.items():
        if cgid != gid and str((child or {}).get("parent") or "") == gid \
                and cgid not in out:
            out.append(cgid)
    return out


def _member_ids(groups: dict, gid: str, seen: set[str] | None = None) -> list[int]:
    """组内节点（直接成员 + 子组递归），保持稳定顺序。"""
    if seen is None:
        seen = set()
    if gid in seen:
        return []
    seen.add(gid)
    grp = groups.get(gid) or {}
    out = _int_members(grp)
    for cgid in _children(groups, gid):
        for nid in _member_ids(groups, cgid, seen):
            if nid not in out:
                out.append(nid)
    return out


def _ancestors(groups: dict, gid: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    cur = str((groups.get(gid) or {}).get("parent") or "")
    while cur and cur in groups and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = str((groups.get(cur) or {}).get("parent") or "")
    return out


def resolve_group(canvas, ref) -> str | None:
    """按 gid 或 alias 查找组（alias 大小写不敏感，可带 @）。"""
    groups = _groups(canvas)
    if ref is None:
        return None
    raw = str(ref).strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if raw in groups:
        return raw
    low = raw.lower()
    for gid, grp in groups.items():
        if str((grp or {}).get("alias") or "").lower() == low:
            return gid
    return None


def group_for_node(canvas, nid: int) -> str | None:
    """节点所在的最近（最深）组；不在组内返回 None。"""
    groups = _groups(canvas)
    nid = int(nid)
    candidates = [gid for gid in groups if nid in _member_ids(groups, gid)]
    if not candidates:
        return None
    return max(candidates, key=lambda gid: len(_ancestors(groups, gid)))


def next_group_id(canvas) -> str:
    best = 0
    for gid in _groups(canvas):
        match = _GROUP_ID_RE.match(str(gid))
        if match:
            best = max(best, int(match.group(1)))
    return f"g{best + 1}"


def _unique_alias(canvas, requested: str | None, gid: str) -> tuple[str, str | None]:
    groups = _groups(canvas)
    taken = {str((grp or {}).get("alias") or "").lower()
             for grp in groups.values() if str((grp or {}).get("alias") or "")}
    if requested is not None:
        alias = str(requested).strip()
        if alias and alias.lower() in taken:
            return "", f"duplicate group alias {alias!r}"
        return alias, None
    base = f"group_{gid[1:]}" if _GROUP_ID_RE.match(gid) else "group"
    alias = base
    n = 2
    while alias.lower() in taken:
        alias = f"{base}_{n}"
        n += 1
    return alias, None


def _fail(message: str) -> dict:
    return {"ok": False, "errors": [message], "gid": None, "nodes": 0}


def merge_nodes(canvas, nids: Iterable[int], alias: str | None = None) -> dict:
    """把选中节点合并成一个新的 container 组。

    - 选择必须完整覆盖它碰到的每个已有组；部分覆盖会被拒绝，避免出现
      “一个节点同时属于两个同级组”的歧义。
    - 完整选中的顶层组作为新组的 children，并重挂 parent。
    - 只改组元数据，节点位置不变。
    """
    groups = _groups(canvas)
    selected: list[int] = []
    for raw in nids or []:
        nid = _resolve_node_ref(canvas, raw)
        if nid is not None and nid not in selected:
            selected.append(int(nid))
    if len(selected) < 2:
        return _fail("select at least two nodes to merge")

    selected_set = set(selected)
    touched: dict[str, set[int]] = {}
    for gid in groups:
        members = set(_member_ids(groups, gid))
        hit = members & selected_set
        if hit:
            touched[gid] = hit

    partial = {gid: hit for gid, hit in touched.items()
               if hit and hit != set(_member_ids(groups, gid))}
    if partial:
        detail = ", ".join(f"{gid}({len(hit)}/{len(_member_ids(groups, gid))})"
                           for gid, hit in sorted(partial.items()))
        return _fail("selection partially covers existing group(s): " + detail
                     + "; select whole groups or nodes outside groups")

    fully = {gid for gid, hit in touched.items()
             if hit and hit == set(_member_ids(groups, gid))}
    # 只把最外层完整组作为 children；嵌套子组由父组递归覆盖。
    child_gids = [gid for gid in groups
                  if gid in fully
                  and not any(anc in fully for anc in _ancestors(groups, gid))]
    if len(child_gids) == 1 and not (selected_set - set(_member_ids(groups, child_gids[0]))):
        return _fail(f"selection is already group {child_gids[0]}")

    gid = next_group_id(canvas)
    alias, err = _unique_alias(canvas, alias, gid)
    if err:
        return _fail(err)

    for child_gid in child_gids:
        child = groups.get(child_gid) or {}
        old_parent = str(child.get("parent") or "")
        if old_parent and old_parent in groups and old_parent != gid:
            siblings = groups[old_parent].get("children") or []
            groups[old_parent]["children"] = [
                c for c in siblings if str(c) != child_gid
            ]
        child["parent"] = gid

    groups[gid] = {
        "type": "container",
        "version": 1,
        "alias": alias,
        "description": "",
        "params": {"children": list(child_gids), "entry": None, "done": None},
        "members": sorted(selected),
        "children": list(child_gids),
        "slots": {},
    }
    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "alias": alias,
        "nodes": len(selected),
        "children": list(child_gids),
    }


def ungroup(canvas, ref) -> dict:
    """拆掉一个组框；子组上移到它的父级（根级则成为根组），节点保留。"""
    groups = _groups(canvas)
    gid = resolve_group(canvas, ref)
    if gid is None:
        return _fail(f"unknown group {ref!r}")

    # 组内起点/终点只服务于这个组；拆组时随组生命周期一起移除。
    removed_io = remove_group_io_nodes(canvas, gid)
    grp = groups.pop(gid)
    parent = str(grp.get("parent") or "")
    parent_grp = groups.get(parent) if parent else None
    child_gids = _children(groups, gid)

    for child_gid in child_gids:
        child = groups.get(child_gid)
        if child is None:
            continue
        if parent_grp is not None:
            child["parent"] = parent
            siblings = parent_grp.get("children") or []
            if child_gid not in [str(c) for c in siblings]:
                parent_grp["children"] = [*siblings, child_gid]
        else:
            child.pop("parent", None)

    if parent_grp is not None:
        parent_grp["children"] = [
            c for c in (parent_grp.get("children") or []) if str(c) != gid
        ]

    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "alias": str(grp.get("alias") or ""),
        "nodes": len(_member_ids(groups | {gid: grp}, gid)),
        "children": child_gids,
        "removed_io_nodes": removed_io,
    }


def rename_group(canvas, ref, alias: str) -> dict:
    """重命名组（同步 UI 标题与 node_groups[gid].alias）。

    空名/重复名拒绝；只改元数据，不动节点与 box。
    """
    groups = _groups(canvas)
    gid = resolve_group(canvas, ref)
    if gid is None:
        return _fail(f"unknown group {ref!r}")
    new_alias = str(alias or "").strip()
    if new_alias.startswith("@"):
        new_alias = new_alias[1:].strip()
    if not new_alias:
        return _fail("group alias cannot be empty")
    low = new_alias.lower()
    for other_gid, grp in groups.items():
        if other_gid == gid:
            continue
        if str((grp or {}).get("alias") or "").lower() == low:
            return _fail(f"duplicate group alias {new_alias!r}")
    old_alias = str((groups.get(gid) or {}).get("alias") or "")
    groups[gid]["alias"] = new_alias
    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "old_alias": old_alias,
        "alias": new_alias,
    }


def set_group_description(canvas, ref, description: str) -> dict:
    """设置组描述（显示在组标题下方；组在编辑器里也是一个节点）。"""
    groups = _groups(canvas)
    gid = resolve_group(canvas, ref)
    if gid is None:
        return _fail(f"unknown group {ref!r}")
    text = str(description or "").replace("\r\n", "\n").replace("\r", "\n")
    groups[gid]["description"] = text
    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "description": text,
    }


def delete_group(canvas, ref, recursive: bool = True) -> dict:
    """删除组框（默认连同子组），只删元数据，成员节点保留。"""
    groups = _groups(canvas)
    gid = resolve_group(canvas, ref)
    if gid is None:
        return _fail(f"unknown group {ref!r}")

    targets: list[str] = [gid]
    if recursive:
        pending = [gid]
        seen: set[str] = set()
        while pending:
            cur = pending.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur != gid:
                targets.append(cur)
            pending.extend(_children(groups, cur))

    # 先记录成员数量（删除后 groups 里不再有这些节点组）。
    node_count = len(_member_ids(groups, gid))
    removed_io: list[int] = []
    for target in reversed(targets):
        removed_io.extend(remove_group_io_nodes(canvas, target))
        groups.pop(target, None)

    target_set = set(targets)
    for other_gid, other in groups.items():
        children = [c for c in (other.get("children") or [])
                    if str(c) not in target_set]
        if children:
            other["children"] = children
        elif "children" in other:
            other["children"] = []
        if str((other or {}).get("parent") or "") in target_set:
            other.pop("parent", None)

    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "removed": targets,
        "nodes": node_count,
        "recursive": bool(recursive),
        "removed_io_nodes": removed_io,
    }


def destroy_group(canvas, ref, recursive: bool = True) -> dict:
    """销毁组：删除组框、子组，以及**全部成员节点**和它们的连线。

    与 ``ungroup`` 的区别：ungroup 只拆框保留节点；destroy 全删。
    """
    groups = _groups(canvas)
    gid = resolve_group(canvas, ref)
    if gid is None:
        return _fail(f"unknown group {ref!r}")

    targets: list[str] = [gid]
    if recursive:
        pending = [gid]
        seen: set[str] = set()
        while pending:
            cur = pending.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur != gid:
                targets.append(cur)
            pending.extend(_children(groups, cur))

    remove_node = getattr(canvas, "remove_node", None)
    if not callable(remove_node):
        return _fail("canvas does not support node removal")

    node_ids: set[int] = set()
    for target in targets:
        node_ids.update(_int_members(groups.get(target) or {}))

    removed_nodes: list[int] = []
    for nid in sorted(node_ids):
        if nid in _nodes(canvas):
            remove_node(int(nid))
            removed_nodes.append(int(nid))

    for target in reversed(targets):
        groups.pop(target, None)
    target_set = set(targets)
    for _other_gid, other in groups.items():
        children = [c for c in (other.get("children") or [])
                    if str(c) not in target_set]
        other["children"] = children
        if str((other or {}).get("parent") or "") in target_set:
            other.pop("parent", None)

    return {
        "ok": True,
        "errors": [],
        "gid": gid,
        "removed_groups": targets,
        "removed_nodes": removed_nodes,
        "nodes": len(removed_nodes),
        "recursive": bool(recursive),
    }
