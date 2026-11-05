"""运行时 UI 编译器守卫：元素模型 → quad + 命中（纯数学，无 GL / 无 esper）。

锁定内容:
  1. `build_ui` 布局：画布缩放、父链锚点、width/height=0 撑满父级
  2. 可见性：父不可见 → 子树不画不命中；`visible_overrides` 可运行期显隐
  3. 面板：遮罩铺满视口、描边四条、带 alpha=0 底色不产生 quad
  4. 按钮：变体底色、hover/pressed 变化、disabled 不可点
  5. 模态：只认模态子树里的按钮；整屏 `captures`
  6. 文字：注入的 `text_fn` 被调用；left/center/right 对齐位置
  7. 绘制顺序：(画布 sort_order, 深度, order, eid)；命中取最上层
  8. `scene.collect_elements`：父链找画布、跳过非 UIRect 实体
  9. `theme.parse_color`：token / #hex / tuple / 非法值
"""

# TIER: core

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

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

from Application.Core.UI.scene import collect_elements, find_by_name, find_by_role  # noqa: E402
from Application.Core.UI.theme import DEFAULT_TOKENS, parse_color  # noqa: E402
from Application.Core.UI.tree import UIElement, build_ui, captures  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def rect(anchor="center", pos=(0.0, 0.0), size=(100.0, 50.0), *,
         visible=True, order=0):
    return SimpleNamespace(anchor=anchor, pivot=anchor, pos_x=float(pos[0]),
                           pos_y=float(pos[1]), width=float(size[0]),
                           height=float(size[1]), visible=visible, order=order)


def panel(bg="@color.surface", border="@color.border", border_w=1.0,
          scrim="", modal=False, role=""):
    return SimpleNamespace(bg_color=bg, border_color=border,
                           border_width=border_w, scrim_color=scrim,
                           modal=modal, role=role)


def label(text="L", size=0.0, color="@color.text", align="center", bold=False):
    return SimpleNamespace(text=text, size=float(size), color=color,
                           align=align, bold=bold)


def button(text="B", variant="secondary", action="", enabled=True, size=0.0):
    return SimpleNamespace(text=text, variant=variant, action=action,
                           enabled=enabled, size=float(size))


def canvas(scale_mode="fit_height", ref=(1920, 1080), sort_order=0, visible=True):
    return SimpleNamespace(scale_mode=scale_mode, reference_w=ref[0],
                           reference_h=ref[1], sort_order=int(sort_order),
                           visible=bool(visible))


FAKE_TEXT_CALLS: list = []


def fake_text(text, size, color, bold=False):
    FAKE_TEXT_CALLS.append((text, size, bool(bold)))
    w = max(1, len(text) * max(4, size // 2))
    return (w, max(1, size), None, f"fake:{text}:{size}")


def main() -> int:
    print("=" * 60)
    print("runtime UI — element tree compiler")
    print("=" * 60)

    # ── 1. 布局 ──
    print("-- 1. layout --")
    cv = canvas()
    els = [
        UIElement(eid=1, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (400, 200)), panel=panel()),
        UIElement(eid=2, parent_id=1, canvas=cv,
                  rect=rect("top_left", (20, 20), (100, 40)), label=label("hi")),
        UIElement(eid=3, parent_id=1, canvas=cv,
                  rect=rect("top_left", (0, 0), (0, 0)), label=label("fill")),
    ]
    r = build_ui(els, 1920, 1080, text_fn=fake_text)
    p = r.rects[1]
    check("面板居中 400x200", p == (760.0, 440.0, 400.0, 200.0), str(p))
    c = r.rects[2]
    check("子元素相对父矩形偏移", c == (780.0, 460.0, 100.0, 40.0), str(c))
    f = r.rects[3]
    check("width/height=0 → 撑满父级", f == (760.0, 440.0, 400.0, 200.0), str(f))
    rs = build_ui([UIElement(eid=4, parent_id=None, canvas=cv,
                             rect=rect("right", (0, 0), (200, 100)), label=label("R"))],
                  1920, 1080, text_fn=fake_text)
    check("anchor=right → 右边中（垂直居中，不是右上）",
          rs.rects[4] == (1720.0, 490.0, 200.0, 100.0), str(rs.rects[4]))
    ls = build_ui([UIElement(eid=5, parent_id=None, canvas=cv,
                             rect=rect("left", (0, 0), (200, 100)), label=label("L"))],
                  1920, 1080, text_fn=fake_text)
    check("anchor=left → 左边中", ls.rects[5] == (0.0, 490.0, 200.0, 100.0), str(ls.rects[5]))

    r2 = build_ui(els, 2560, 1080, text_fn=fake_text)
    p2 = r2.rects[1]
    check("2560 宽 fit_height → 内容框居中 (320 留边)",
          p2 == (1080.0, 440.0, 400.0, 200.0), str(p2))
    r3 = build_ui(els, 1920, 540, text_fn=fake_text)
    check("1920x540 → 尺寸等比 0.5", r3.rects[1] == (860.0, 220.0, 200.0, 100.0),
          str(r3.rects[1]))

    # ── 2. 可见性 ──
    print("-- 2. visibility --")
    hidden_panel = [
        UIElement(eid=10, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (400, 200), visible=False), panel=panel()),
        UIElement(eid=11, parent_id=10, canvas=cv,
                  rect=rect("top_left", (10, 10), (80, 30)), button=button("x")),
    ]
    rh = build_ui(hidden_panel, 1920, 1080, text_fn=fake_text)
    check("父不可见 → 子树无 quad", len(rh.quads) == 0, str(len(rh.quads)))
    check("父不可见 → 子树不可命中", rh.hit_at(800, 460) is None)
    rv = build_ui(hidden_panel, 1920, 1080, text_fn=fake_text,
                  visible_overrides={10: True})
    check("override 显示父级 → 子树可画", len(rv.quads) > 0, str(len(rv.quads)))
    check("override 显示父级 → 按钮可命中", rv.hit_at(775, 455) is not None)

    # ── 3. 面板 ──
    print("-- 3. panel --")
    scrim = [UIElement(eid=20, parent_id=None, canvas=cv,
                       rect=rect("center", (0, 0), (0, 0)),
                       panel=panel(bg="", border_w=0.0, scrim="@color.scrim",
                                   modal=True))]
    rs = build_ui(scrim, 1920, 1080, text_fn=fake_text)
    check("遮罩 = 整屏单 quad",
          len(rs.quads) == 1 and rs.quads[0].w == 1920 and rs.quads[0].h == 1080,
          str(len(rs.quads)))
    check("遮罩色 = token 值", rs.quads[0].color == DEFAULT_TOKENS["color.scrim"],
          str(rs.quads[0].color))
    check("modal 标记透出", rs.modal and rs.modal_eid == 20, str(rs.modal_eid))
    b = build_ui([UIElement(eid=21, parent_id=None, canvas=cv,
                            rect=rect("center", (0, 0), (100, 50)), panel=panel())],
                 1920, 1080, text_fn=fake_text)
    check("面板 = 底 + 4 边（共 5 quad）", len(b.quads) == 5, str(len(b.quads)))
    none_bg = build_ui([UIElement(eid=22, parent_id=None, canvas=cv,
                                  rect=rect("center", (0, 0), (100, 50)),
                                  panel=panel(bg="", border_w=0.0))],
                       1920, 1080, text_fn=fake_text)
    check("无底色 + 无描边 → 0 quad", len(none_bg.quads) == 0, str(len(none_bg.quads)))

    # ── 4. 按钮状态 ──
    print("-- 4. buttons --")
    btn = [UIElement(eid=30, parent_id=None, canvas=cv,
                     rect=rect("center", (0, 0), (200, 64)), button=button("Go"))]
    base = build_ui(btn, 1920, 1080, text_fn=fake_text)
    hover = build_ui(btn, 1920, 1080, hover_eid=30, text_fn=fake_text)
    press = build_ui(btn, 1920, 1080, hover_eid=30, pressed_eid=30, text_fn=fake_text)
    check("按钮 = 底 + 文字", len(base.quads) == 2, str(len(base.quads)))
    check("hover 底色变化",
          base.quads[0].color == DEFAULT_TOKENS["color.button"]
          and hover.quads[0].color == DEFAULT_TOKENS["color.button.hover"],
          f"{base.quads[0].color} / {hover.quads[0].color}")
    check("pressed 用 hover 底色",
          press.quads[0].color == DEFAULT_TOKENS["color.button.hover"])
    primary = [UIElement(eid=31, parent_id=None, canvas=cv,
                         rect=rect("center", (0, 0), (200, 64)),
                         button=button("Go", variant="primary"))]
    rb = build_ui(primary, 1920, 1080, text_fn=fake_text)
    check("primary 变体用主色",
          rb.quads[0].color == DEFAULT_TOKENS["color.button.primary"], str(rb.quads[0].color))
    off = [UIElement(eid=32, parent_id=None, canvas=cv,
                     rect=rect("center", (0, 0), (200, 64)),
                     button=button("Off", enabled=False))]
    roff = build_ui(off, 1920, 1080, text_fn=fake_text)
    check("disabled 用禁用底色",
          roff.quads[0].color == DEFAULT_TOKENS["color.button.disabled"])
    check("disabled 命中被拒绝",
          roff.hit_at(960, 540) is None and roff.hits[0].enabled is False)

    # ── 5. 模态命中 ──
    print("-- 5. modal hit --")
    modal = [
        UIElement(eid=40, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (400, 200)),
                  panel=panel(bg="", border_w=0.0, scrim="@color.scrim", modal=True)),
        UIElement(eid=41, parent_id=40, canvas=cv,
                  rect=rect("top_left", (20, 20), (120, 40)), button=button("In")),
        UIElement(eid=42, parent_id=None, canvas=cv,
                  rect=rect("top_left", (0, 0), (200, 60)), button=button("Out")),
    ]
    rm = build_ui(modal, 1920, 1080, text_fn=fake_text)
    check("模态时屏外按钮不可点", rm.hit_at(100, 30) is None)
    check("模态内部按钮可点", rm.hit_at(800, 470) is not None)
    check("模态 captures 任意位置", captures(rm, 5, 5) and captures(rm, 1915, 1075))
    rnom = build_ui([modal[2]], 1920, 1080, text_fn=fake_text)
    check("非模态空白处不捕获", not captures(rnom, 1200, 800) and captures(rnom, 100, 30))

    # ── 6. 文字对齐 ──
    print("-- 6. text alignment --")
    FAKE_TEXT_CALLS.clear()
    three = [
        UIElement(eid=50, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (300, 60)), label=label("AA", align="left")),
        UIElement(eid=51, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (300, 60)), label=label("AA", align="center")),
        UIElement(eid=52, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (300, 60)), label=label("AA", align="right")),
    ]
    rl = build_ui(three, 1920, 1080, text_fn=fake_text)
    left_x, center_x, right_x = (q.x for q in rl.quads)
    check("left / center / right 三个位置", left_x < center_x < right_x,
          f"{left_x} {center_x} {right_x}")
    check("left 贴矩形左边界", abs(left_x - 810.0) < 1e-6, str(left_x))
    check("text_fn 收到文字与字号", any(c[0] == "AA" and c[1] == 28 for c in FAKE_TEXT_CALLS),
          str(FAKE_TEXT_CALLS[:2]))
    check("label.size 覆盖主题字号",
          build_ui([UIElement(eid=53, parent_id=None, canvas=cv,
                              rect=rect("center", (0, 0), (300, 60)),
                              label=label("B", size=44))],
                   1920, 1080, text_fn=fake_text).quads[0].h == 44)

    # ── 7. 绘制顺序 ──
    print("-- 7. draw order --")
    order = [
        UIElement(eid=60, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (200, 200)), panel=panel()),
        UIElement(eid=61, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (200, 200), order=5),
                  button=button("Top", action="close")),
    ]
    ro = build_ui(order, 1920, 1080, text_fn=fake_text)
    check("order 大的画在上面（命中取它）",
          ro.hit_at(960, 540) is not None and ro.hit_at(960, 540).eid == 61)
    rev = build_ui(list(reversed(order)), 1920, 1080, text_fn=fake_text)
    check("元素输入顺序不影响结果",
          [q.color for q in rev.quads] == [q.color for q in ro.quads])
    cv2 = canvas(sort_order=-1)
    two_canvas = [
        UIElement(eid=70, parent_id=None, canvas=cv2,
                  rect=rect("center", (0, 0), (50, 50)), panel=panel(bg="#FF0000")),
        UIElement(eid=71, parent_id=None, canvas=cv,
                  rect=rect("center", (0, 0), (50, 50)), panel=panel(bg="#00FF00")),
    ]
    rc = build_ui(two_canvas, 1920, 1080, text_fn=fake_text)
    check("画布 sort_order 小的先画",
          rc.quads[0].color == (1.0, 0.0, 0.0, 1.0), str(rc.quads[0].color))

    # ── 8. 收集器 ──
    print("-- 8. collect --")
    from Application.Core.Scene.UIComponents import (  # noqa: E402
        UICanvas, UILabel, UIPanel, UIRect,
    )

    class FakeScene:
        def __init__(self):
            self.comps = {1: {UICanvas: UICanvas()},
                          2: {UIRect: UIRect(width=0, height=0), UIPanel: UIPanel(role="exit_confirm")},
                          3: {UIRect: UIRect()},
                          4: {UIRect: UIRect(), UILabel: UILabel(text="child")},
                          5: {}}
            self.parents = {2: 1, 3: 1, 4: 2, 5: 1}
            self.names = {1: "Canvas", 2: "Dialog", 3: "Free", 4: "Child", 5: "NoUI"}

        def GetAllEntitiesWithComponent(self, cls):
            return [(eid, comp[cls]) for eid, comp in self.comps.items() if cls in comp]

        def GetEntityParent(self, eid):
            return self.parents.get(eid)

        def GetEntityName(self, eid):
            return self.names.get(eid, "")

    fake = FakeScene()
    collected = collect_elements(fake)
    by_eid = {el.eid: el for el in collected}
    check("只收集带 UIRect 的实体", set(by_eid) == {2, 3, 4}, str(sorted(by_eid)))
    check("画布按父链归属",
          by_eid[2].canvas is not None and by_eid[4].canvas is not None)
    check("按角色找面板", find_by_role(collected, "exit_confirm") == 2)
    check("按名字找元素", find_by_name(collected, "Child") == 4)
    check("无 UI 组件的实体不收集", 5 not in by_eid)

    # ── 9. parse_color ──
    print("-- 9. colors --")
    check("token 解析", parse_color("@color.text") == DEFAULT_TOKENS["color.text"])
    check("#RRGGBB", parse_color("#FF8000") == (1.0, 128 / 255, 0.0, 1.0),
          str(parse_color("#FF8000")))
    check("#RRGGBBAA", abs(parse_color("#00000080")[3] - 128 / 255) < 1e-6)
    check("tuple 补 alpha", parse_color((0.1, 0.2, 0.3)) == (0.1, 0.2, 0.3, 1.0))
    check("非法值 → default", parse_color("nope", default=(0.0, 0.0, 0.0, 0.0))
          == (0.0, 0.0, 0.0, 0.0))
    check("空值 → default", parse_color("", default=(1.0, 0.0, 0.0, 1.0))
          == (1.0, 0.0, 0.0, 1.0))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
