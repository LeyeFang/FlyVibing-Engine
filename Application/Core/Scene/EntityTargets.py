"""实体作用域解析 — one / tree / list 的单一实现（live ops 与工具共用）。

语义（写进 `Doc/Dev/node_editor_protocol.md` §2.2）:
  - one : 只操作目标实体本身；
  - tree: 目标实体 + 全部子孙（先序、去重）；
  - list: 只操作给定列表（去重、保序，不递归）。

运行时节点不直接使用编辑器场景 id：PIE/成品里实体由 EntitySpawn 重新创建，
这里的 id 解析只服务编辑器活场景（live ops / UI）。
"""

from __future__ import annotations

SCOPES = ("one", "tree", "list")


def _dedupe(values) -> list[int]:
    out: list[int] = []
    for value in values:
        eid = int(value)
        if eid not in out:
            out.append(eid)
    return out


def collect_descendants(scene, entity_id: int) -> list[int]:
    """先序遍历实体及其全部子孙（含自身）。"""
    out: list[int] = [int(entity_id)]
    try:
        children = scene.GetEntityChildren(int(entity_id))
    except Exception:  # noqa: BLE001 — 无层级 API 时退化为单实体
        return out
    for child in children or []:
        for eid in collect_descendants(scene, int(child)):
            if eid not in out:
                out.append(eid)
    return out


def resolve_scope(scene, roots, scope: str = "one") -> list[int]:
    """把根实体集合按 scope 展开成最终 eid 列表（保序去重）。"""
    scope = str(scope or "one").lower()
    if scope not in SCOPES:
        raise ValueError(f"invalid scope {scope!r} (expected one/tree/list)")

    roots = _dedupe(roots)
    if scope == "one":
        return [eid for eid in roots if _exists(scene, eid)]
    if scope == "tree":
        out: list[int] = []
        for root in roots:
            if not _exists(scene, root):
                continue
            for eid in collect_descendants(scene, root):
                if eid not in out:
                    out.append(eid)
        return out
    return [eid for eid in roots if _exists(scene, eid)]


def delete_scope(scene, roots, scope: str = "tree",
                 reparent_children: bool = True) -> dict:
    """按 scope 删除实体。

    - tree / list: 每个根按子树删除（`SceneManager.DeleteEntity` 语义）；
    - one: 只删目标本身；有子实体时必须 `reparent_children=True`（默认），
      子实体挂到目标的父级（无父级 → 变成根），不会产生孤儿。
    """
    scope = str(scope or "tree").lower()
    if scope not in SCOPES:
        raise ValueError(f"invalid scope {scope!r} (expected one/tree/list)")

    roots = _dedupe(roots)
    deleted: list[int] = []
    reparented = 0

    if scope == "one":
        for eid in roots:
            if not _exists(scene, eid):
                continue
            children = list(scene.GetEntityChildren(eid) or [])
            if children:
                if not reparent_children:
                    raise ValueError(
                        f"entity {eid} has {len(children)} child(ren); "
                        f"pass reparent_children=true or use scope=tree")
                parent = scene.GetEntityParent(eid)
                for child in children:
                    scene.SetEntityParent(child, parent)
                    reparented += 1
            if scene.DeleteEntity(eid):
                deleted.append(eid)
        return {"deleted": deleted, "scope": scope,
                "reparented_children": reparented}

    # tree / list: 删除每个根的子树；已随祖先删除的 id 自动跳过
    for eid in roots:
        if _exists(scene, eid) and scene.DeleteEntity(eid):
            deleted.append(eid)
    return {"deleted": deleted, "scope": scope, "reparented_children": 0}


def _exists(scene, eid: int) -> bool:
    try:
        return bool(scene.EntityExists(eid))
    except Exception:  # noqa: BLE001
        return True
