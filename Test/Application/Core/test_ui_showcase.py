"""`Examples/UIShowcase` 守卫：场景可加载 / 控件齐全 / token 全部可解析 / 能编译出 quad。

四重身份里的"② core 守卫"（协议：`Doc/Dev/product_todo.md` §10.8）：
新增控件时必须同步 Example（相当于 UI 的验收清单），这个测试就是清单的执行者。

锁定内容:
  1. 工程元数据（`.myproj` name / startup_scene / provider / 背景色）
  2. 场景可加载；UI 实体都有 UIRect；父子链完整；实体名唯一
  3. 控件齐全：Canvas / 4 个面板 / 8 个按钮（含 4 个变体 + disabled）/ 8 个标签
  4. 退出确认面板：role=exit_confirm + modal + 遮罩 + 默认隐藏 + exit/close 按钮
  5. 颜色/字号只写 token（不留死 hex RGB）；token 全部能在主题里解析
  6. 编译：1920×1080 有 quad、对话框默认不出遮罩；打开后有整屏遮罩且按钮可命中
  7. 参考分辨率缩放：2560×1080 下内容框居中偏移 320
"""

# TIER: core

from __future__ import annotations

import json
import os
import re
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.Scene.Scene import Scene  # noqa: E402
from Application.Core.Scene.UIComponents import (  # noqa: E402
    ANCHORS,
    BUTTON_VARIANTS,
    SCALE_MODES,
    SELECT_SKINS,
    UICanvas,
    UIButton,
    UILabel,
    UIPanel,
    UIRect,
    UISelect,
)
from Application.Core.UI.layout import rect_hit  # noqa: E402
from Application.Core.UI.scene import collect_elements, find_by_role  # noqa: E402
from Application.Core.UI.theme import DEFAULT_TOKENS  # noqa: E402
from Application.Core.UI.tree import build_ui, captures  # noqa: E402
import Application.Core.NodeGraph  # noqa: E402,F401 — 注册 NodeCanvas 契约（.scene 图反序列化）

ROOT = os.path.dirname(_d)
EXAMPLE_DIR = os.path.join(ROOT, "Examples", "UIShowcase")
PROJECT_PATH = os.path.join(EXAMPLE_DIR, "UIShowcase.myproj")
SCENE_PATH = os.path.join(EXAMPLE_DIR, "scenes", "UIShowcase.scene")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def fake_text(text, size, color, bold=False):
    return (max(1, len(str(text)) * max(4, int(size) // 2)), max(1, int(size)),
            None, f"t:{text}:{int(size)}")


class SceneAdapter:
    """把 `Scene`（纯数据）包装成 `collect_elements` 需要的查询面（不起 esper）。"""

    def __init__(self, scene: Scene):
        self._scene = scene
        self._by_type: dict = {}
        for eid, ed in scene.entities.items():
            for name, comp in ed.components.items():
                self._by_type.setdefault(name, []).append((eid, comp))

    def GetAllEntitiesWithComponent(self, cls):
        return list(self._by_type.get(cls.__name__, ()))

    def GetEntityParent(self, eid):
        ed = self._scene.entities.get(int(eid))
        return ed.parent_id if ed is not None else None

    def GetEntityName(self, eid):
        ed = self._scene.entities.get(int(eid))
        return ed.name if ed is not None else ""


def _iter_ui(scene: Scene):
    for eid, ed in scene.entities.items():
        comps = ed.components
        if any(isinstance(c, (UICanvas, UIRect, UIPanel, UILabel, UIButton))
               for c in comps.values()):
            yield eid, ed


def main() -> int:
    print("=" * 60)
    print("UIShowcase — example guard")
    print("=" * 60)

    # ── 1. 工程 ──
    print("-- 1. project --")
    check("project exists", os.path.isfile(PROJECT_PATH), PROJECT_PATH)
    with open(PROJECT_PATH, encoding="utf-8") as fh:
        project = json.load(fh)
    check("project metadata",
          project.get("name") == "UIShowcase"
          and project.get("provider") == "@Official"
          and project.get("startup_scene") == "scenes\\UIShowcase.scene",
          str(project.get("name")))
    check("project has dark background",
          isinstance(project.get("background_color"), list)
          and len(project["background_color"]) == 3)
    check("project ships builtin cameras",
          any(p.get("path") == "builtin://DefaultCamera3D"
              for p in project.get("resources", {}).get("prefabs", [])))

    # ── 2. 场景结构 ──
    print("-- 2. scene --")
    check("scene exists", os.path.isfile(SCENE_PATH), SCENE_PATH)
    scene = Scene.load_from_file(SCENE_PATH)
    check("scene loads with typed components",
          all(any(isinstance(c, (UIRect, UICanvas)) for c in ed.components.values())
              for _, ed in _iter_ui(scene)))
    names = [ed.name for ed in scene.entities.values()]
    check("entity names unique", len(names) == len(set(names)),
          str([n for n in names if names.count(n) > 1][:3]))
    dangling = [ed.name for ed in scene.entities.values()
                if ed.parent_id is not None and ed.parent_id not in scene.entities]
    check("parent chain intact", not dangling, str(dangling[:3]))
    missing_rect = [ed.name for _, ed in _iter_ui(scene) if "UIRect" not in ed.components]
    check("every UI entity has UIRect (canvas itself may be root-only)",
          not [n for n in missing_rect if n != "UIHUD"], str(missing_rect[:3]))

    canvases = [(eid, ed) for eid, ed in _iter_ui(scene) if "UICanvas" in ed.components]
    check("exactly one canvas", len(canvases) == 1, str(len(canvases)))
    cv_comp = canvases[0][1].components["UICanvas"]
    check("canvas scale mode valid", cv_comp.scale_mode in SCALE_MODES, cv_comp.scale_mode)
    check("canvas reference 1920x1080",
          (cv_comp.reference_w, cv_comp.reference_h) == (1920, 1080))

    # ── 3. 控件齐全 ──
    print("-- 3. controls --")
    panels = [(eid, ed) for eid, ed in _iter_ui(scene) if "UIPanel" in ed.components]
    labels = [(eid, ed) for eid, ed in _iter_ui(scene) if "UILabel" in ed.components]
    buttons = [(eid, ed) for eid, ed in _iter_ui(scene) if "UIButton" in ed.components]
    toggles = [(eid, ed) for eid, ed in _iter_ui(scene) if "UIToggle" in ed.components]
    sliders = [(eid, ed) for eid, ed in _iter_ui(scene) if "UISlider" in ed.components]
    selects = [(eid, ed) for eid, ed in _iter_ui(scene) if "UISelect" in ed.components]
    check("5 panels (bar/controls/settings/detail/exit)", len(panels) == 5, str(len(panels)))
    check("11 labels", len(labels) == 11, str(len(labels)))
    check("8 buttons", len(buttons) == 8, str(len(buttons)))
    check("1 toggle / 1 slider / 3 selects", (len(toggles), len(sliders), len(selects)) == (1, 1, 3),
          f"{len(toggles)}/{len(sliders)}/{len(selects)}")
    skins = sorted(ed.components["UISelect"].skin for _, ed in selects)
    check("all three select skins present", skins == sorted(SELECT_SKINS), str(skins))
    check("slider has a stepped range",
          sliders[0][1].components["UISlider"].step > 0
          and sliders[0][1].components["UISlider"].max_value
          > sliders[0][1].components["UISlider"].min_value)
    check("every select has options + valid index",
          all(ed.components["UISelect"].options
              and 0 <= ed.components["UISelect"].index < len(ed.components["UISelect"].options)
              for _, ed in selects))
    variants = {ed.components["UIButton"].variant for _, ed in buttons}
    check("covers every button variant",
          variants >= set(BUTTON_VARIANTS), str(sorted(variants)))
    check("has a disabled button example",
          any(not ed.components["UIButton"].enabled for _, ed in buttons))
    check("labels have text", all(ed.components["UILabel"].text for _, ed in labels))
    check("buttons have text", all(ed.components["UIButton"].text for _, ed in buttons))
    check("all anchors are legal",
          all(ed.components["UIRect"].anchor in ANCHORS
              for _, ed in _iter_ui(scene) if "UIRect" in ed.components))

    # ── 4. 退出确认面板 ──
    print("-- 4. exit dialog --")
    adapter = SceneAdapter(scene)
    elements = collect_elements(adapter)
    rect_entities = [eid for eid, ed in _iter_ui(scene) if "UIRect" in ed.components]
    check("collector sees every entity with UIRect",
          len(elements) == len(rect_entities),
          f"{len(elements)} vs {len(rect_entities)}")
    exit_eid = find_by_role(elements, "exit_confirm")
    check("exit_confirm panel exists", exit_eid != 0)
    exit_ed = scene.entities[exit_eid]
    exit_panel = exit_ed.components["UIPanel"]
    exit_rect = exit_ed.components["UIRect"]
    check("exit panel modal + scrim",
          exit_panel.modal and exit_panel.scrim_color == "@color.scrim",
          f"modal={exit_panel.modal} scrim={exit_panel.scrim_color!r}")
    check("exit panel hidden by default", exit_rect.visible is False)

    def _descendants(eid: int) -> list:
        out = []
        for cid, ed in scene.entities.items():
            if ed.parent_id == eid:
                out.append(cid)
                out.extend(_descendants(cid))
        return out

    child_ids = _descendants(exit_eid)
    actions = {scene.entities[c].components["UIButton"].action
               for c in child_ids if "UIButton" in scene.entities[c].components}
    check("dialog has exit + close buttons", {"exit", "close"} <= actions, str(sorted(actions)))
    check("dialog title mentions exit",
          any("exit" in scene.entities[c].components["UILabel"].text.lower()
              for c in child_ids if "UILabel" in scene.entities[c].components))

    # ── 5. token / 颜色 ──
    print("-- 5. theme tokens --")
    colors = []
    for _, ed in _iter_ui(scene):
        for comp in ed.components.values():
            for field in ("bg_color", "border_color", "scrim_color", "color"):
                val = getattr(comp, field, None)
                if isinstance(val, str) and val:
                    colors.append(val)
    check("colors are tokens only", all(c.startswith("@") for c in colors), str(colors[:3]))
    unresolved = [c for c in colors if c.startswith("@") and c[1:] not in DEFAULT_TOKENS]
    check("every token resolves", not unresolved, str(unresolved[:3]))
    hexlike = [ed.name for _, ed in _iter_ui(scene)
               if re.search(r"#[0-9a-fA-F]{6}", json.dumps(
                   {k: str(getattr(v, '__dict__', v)) for k, v in ed.components.items()}))]
    check("no hardcoded hex colors in scene", not hexlike, str(hexlike[:3]))

    # ── 6. 编译 ──
    print("-- 6. compile --")
    hidden = build_ui(elements, 1920, 1080, text_fn=fake_text)
    check("hidden dialog produces no scrim",
          not any(q.w == 1920 and q.h == 1080 for q in hidden.quads))
    check("HUD compiles to quads", len(hidden.quads) > 20, str(len(hidden.quads)))
    check("14 visible hits (6 buttons + toggle/slider/3 segments/2 steps/dropdown)",
          len(hidden.hits) == 14, str([(h.kind, h.index) for h in hidden.hits]))
    check("hidden dialog buttons not hittable",
          not any(h.eid in child_ids for h in hidden.hits))
    detail_eid = next(eid for eid, ed in scene.entities.items()
                      if ed.name == "DetailPanel")
    extra_hits = [h for h in hidden.hits if h.action.startswith("toggle:")]
    check("toggle action preserved",
          extra_hits and extra_hits[0].action == "toggle:DetailPanel",
          str([h.action for h in extra_hits]))

    shown = build_ui(elements, 1920, 1080, visible_overrides={exit_eid: True},
                     text_fn=fake_text)
    scrims = [q for q in shown.quads if q.w == 1920 and q.h == 1080]
    check("open dialog draws full-screen scrim", len(scrims) == 1, str(len(scrims)))
    check("open dialog is modal", shown.modal and shown.modal_eid == exit_eid)
    check("modal captures outside the panel too", captures(shown, 10, 10))
    dialog_hits = [h for h in shown.hits if h.eid in child_ids]
    check("dialog buttons are the only hittable ones",
          len(dialog_hits) == 2 and all(h.in_modal for h in dialog_hits),
          str([(h.eid, h.action) for h in dialog_hits]))
    cx = 1920 / 2.0
    cy = 1080 / 2.0
    hit = shown.hit_at(cx - 112, cy + 88)
    check("click at Stay position hits a close button",
          hit is not None and hit.action == "close", str(hit))
    hit2 = shown.hit_at(cx + 112, cy + 88)
    check("click at Exit position hits exit", hit2 is not None and hit2.action == "exit",
          str(hit2))
    check("click outside dialog panel is not a button", shown.hit_at(30, 900) is None)

    # ── 6b. UI 节点图（SetUIVisible / SetUIText / OnUIClick）──
    print("-- 6b. node graph --")
    graph = scene.node_graph
    check("scene ships a node graph", graph is not None)
    types = sorted(inst.node_type for inst in graph.nodes.values())
    check("graph uses UI nodes",
          types == ["OnGameStart", "OnUIClick", "SetUIText",
                    "SetUIVisible", "SetUIVisible"], str(types))
    targets = sorted(inst.props.get("target", "") for inst in graph.nodes.values()
                     if inst.node_type == "SetUIVisible")
    check("graph targets the NodeHint label", targets == ["NodeHint", "NodeHint"], str(targets))
    visible_props = sorted(bool(inst.props.get("visible", True))
                           for inst in graph.nodes.values()
                           if inst.node_type == "SetUIVisible")
    check("graph hides at start + shows on click", visible_props == [False, True],
          str(visible_props))
    click = next(inst for inst in graph.nodes.values() if inst.node_type == "OnUIClick")
    check("OnUIClick filters the Primary action",
          click.props.get("action") == "show:DetailPanel", str(click.props))
    retitle = next(inst for inst in graph.nodes.values() if inst.node_type == "SetUIText")
    check("SetUIText retitles DetailTitle",
          retitle.props.get("target") == "DetailTitle"
          and retitle.props.get("text") == "Trial 1 / 12", str(retitle.props))
    check("graph is wired (3 links)", len(graph.links) == 3, str(len(graph.links)))
    from Application.Core.NodeGraph import _TYPES  # noqa: E402
    unknown = [inst.node_type for inst in graph.nodes.values()
               if inst.node_type not in _TYPES]
    check("every graph node type is registered", not unknown, str(unknown))

    # ── 7. 参考分辨率缩放 ──
    print("-- 7. scaling --")
    wide = build_ui(elements, 2560, 1080, text_fn=fake_text)
    small = build_ui(elements, 1920, 1080, text_fn=fake_text)
    check("2560 → 内容框居中（+320px）",
          abs(wide.rects[detail_eid][0] - small.rects[detail_eid][0] - 320.0) < 1e-6,
          f"{wide.rects[detail_eid][0]} vs {small.rects[detail_eid][0]}")
    scaled = build_ui(elements, 1280, 720, text_fn=fake_text)
    detail_w = scene.entities[detail_eid].components["UIRect"].width
    check("1280x720 → 尺寸按 2/3 缩放",
          abs(scaled.rects[detail_eid][2] - detail_w * 2 / 3) < 1e-6,
          str(scaled.rects[detail_eid][2]))
    inside = all(0 <= r[0] <= 1920 and 0 <= r[1] <= 1080
                 for r in small.rects.values())
    check("all rects inside the 1920x1080 content box", inside)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
