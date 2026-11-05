"""场景 → UI 元素快照（运行期 / 编辑器预览共用）。

只在**逻辑线程**调用一次（`RuntimeUILayer.OnUpdate`）：读 esper 世界是可变操作，
渲染线程不碰 ECS —— 渲染只用这里产出的不可变 `UIElement` 元组。

依赖面很小（鸭子类型，方便测试用假场景）:
    GetAllEntitiesWithComponent(cls) -> [(eid, comp), ...]
    GetEntityParent(eid) -> int | None
    GetEntityName(eid) -> str
"""

from __future__ import annotations

from Application.Core.UI.tree import UIElement

_MAX_DEPTH = 64


def collect_elements(scene_mgr) -> tuple[UIElement, ...]:
    """收集场景里所有 UI 元素（带 `UIRect` 的实体）。

    - 画布按父链归属；没有 `UICanvas` 祖先 → 默认画布（1920×1080, fit_height）。
    - 没有 `UIRect` 的实体不参与（容器请显式加 `UIRect`，width/height=0 即撑满父级）。
    - 产出的顺序不保证 —— 绘制顺序由 `tree.build_ui` 决定。
    """
    if scene_mgr is None:
        return ()
    try:
        from Application.Core.Scene.UIComponents import (
            UICanvas,
            UILabel,
            UIPanel,
            UIRect,
            UIButton,
            UISelect,
            UISlider,
            UIToggle,
        )
    except Exception:  # noqa: BLE001 — Core 未装 UI 组件（裁剪发行版）
        return ()

    try:
        canvases = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UICanvas)}
        rects = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UIRect)}
    except Exception:  # noqa: BLE001 — 无 esper 世界（无头测试）
        return ()
    if not rects:
        return ()

    try:
        panels = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UIPanel)}
        labels = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UILabel)}
        buttons = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UIButton)}
        toggles = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UIToggle)}
        sliders = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UISlider)}
        selects = {int(e): c for e, c in scene_mgr.GetAllEntitiesWithComponent(UISelect)}
    except Exception:  # noqa: BLE001 — 组件未注册（旧工程）
        panels = labels = buttons = toggles = sliders = selects = {}

    parent_cache: dict[int, int | None] = {}

    def _parent(eid: int) -> int | None:
        if eid not in parent_cache:
            try:
                p = scene_mgr.GetEntityParent(eid)
            except Exception:  # noqa: BLE001
                p = None
            parent_cache[eid] = int(p) if p else None
        return parent_cache[eid]

    def _canvas_of(eid: int):
        cur, guard = eid, 0
        while cur is not None and guard < _MAX_DEPTH:
            if cur in canvases:
                return canvases[cur]
            cur = _parent(cur)
            guard += 1
        return None

    result: list[UIElement] = []
    for eid, rect in rects.items():
        try:
            name = scene_mgr.GetEntityName(eid)
        except Exception:  # noqa: BLE001
            name = ""
        result.append(UIElement(
            eid=eid,
            parent_id=_parent(eid),
            canvas=_canvas_of(eid),
            rect=rect,
            panel=panels.get(eid),
            label=labels.get(eid),
            button=buttons.get(eid),
            toggle=toggles.get(eid),
            slider=sliders.get(eid),
            select=selects.get(eid),
            name=str(name or ""),
        ))
    return tuple(result)


def find_by_role(elements, role: str) -> int:
    """按 `UIPanel.role` 找面板实体 id（0 = 没有）。"""
    want = str(role or "").strip().lower()
    if not want:
        return 0
    for el in elements or ():
        if el.panel is not None and str(getattr(el.panel, "role", "") or "").strip().lower() == want:
            return int(el.eid)
    return 0


def find_by_name(elements, name: str) -> int:
    """按实体名找 UI 元素 id（0 = 没有）。"""
    want = str(name or "").strip()
    if not want:
        return 0
    for el in elements or ():
        if el.name == want:
            return int(el.eid)
    return 0


__all__ = ["collect_elements", "find_by_role", "find_by_name"]
