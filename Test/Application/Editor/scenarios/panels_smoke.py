"""场景: 面板冒烟 — 引导 / 快照 / 实体创建 / 选中 / 数据一致性。

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/panels_smoke.py
"""

NAME = "panels_smoke"
TIER = "gui"


def run(ctx) -> None:
    # ── 1. 引导 + 首帧快照（应包含完整 ImGui UI）──
    ctx.frames(3)
    s1 = ctx.snapshot("boot")
    ctx.expect(s1["width"] >= 800 and s1["height"] >= 600, f"framebuffer size {s1['width']}x{s1['height']}")
    ctx.expect(s1["bytes"] > 10000, f"boot snapshot non-trivial ({s1['bytes']} bytes)")
    ctx.expect(s1["std"] > 2.0, f"boot snapshot has UI variance (std={s1['std']})")

    # ── 2. 面板注册 ──
    for pname in ("Scene", "Node Editor", "Resources", "Settings"):
        ctx.expect(ctx.panel(pname) is not None, f"panel registered: {pname}")

    # ── 3. 实体创建（Controller = 面板按钮同一路径）→ 快照 ──
    browser = ctx.ctrl("SceneBrowser")
    ctx.expect(browser is not None, "SceneBrowser controller resolved")
    eid = browser.add_entity("UITest_A")
    ctx.expect(isinstance(eid, int), f"add_entity returned id ({eid})")
    browser.select(eid)
    ctx.frames(2)

    s2 = ctx.snapshot("entity_added")
    ctx.expect(s2["bytes"] > 10000, f"entity snapshot non-trivial ({s2['bytes']} bytes)")

    info = browser.get_entity_info(eid)
    ctx.expect(bool(info) and info.get("name") == "UITest_A", f"entity visible to panel data ({info})")
    ctx.expect(browser.get_selected() == eid, "selection persisted")
