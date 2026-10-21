"""场景: 主菜单冒烟 — View 菜单 Show Grid 网格开关。

特性: View ▸ Show Grid 网格开关
  业务: Grid.set_visible   菜单: toggle_grid_visible   agent: view.set_grid op
验证:
  1. 引导后网格默认可见 (Grid.visible=True)
  2. 菜单动作 (toggle_grid_visible — 与 imgui 点击同函数) 翻转状态
  3. 无渲染器时状态-only 翻转 (UI 场景可测; 实机由 e2e 截图验证)
  4. 幂等: set_visible 同值调用不变
  5. 快照: boot / grid_off / final

TIER: gui
运行: python Test/Application/Editor/ui_scenario.py Test/Application/Editor/scenarios/menu_smoke.py
"""

NAME = "menu_smoke"
TIER = "gui"


def run(ctx) -> None:
    from Application.Editor.Gizmos.Grid import Grid
    from Application.Editor.UI.panels.MenuBarPanel import toggle_grid_visible

    # ── 1. 引导 + 首帧快照 ──
    ctx.frames(3)
    s1 = ctx.snapshot("boot")
    ctx.expect(s1["bytes"] > 10000, f"boot snapshot non-trivial ({s1['bytes']} bytes)")

    # ── 2. 默认状态 ──
    ctx.expect(Grid.visible is True, "grid visible by default")

    # ── 3. 菜单动作 (唯一入口) 翻转 → 快照 ──
    state = toggle_grid_visible()
    ctx.expect(state is False, f"menu action hides grid (state={state})")
    ctx.expect(Grid.visible is False, "Grid.visible flipped by menu action")

    s2 = ctx.snapshot("grid_off")
    ctx.expect(s2["bytes"] > 10000, f"grid_off snapshot non-trivial ({s2['bytes']} bytes)")

    # ── 4. 再次翻转恢复 ──
    state = toggle_grid_visible()
    ctx.expect(state is True, f"menu action restores grid (state={state})")

    # ── 5. 幂等性: set_visible 同值调用不变 ──
    ctx.expect(Grid.set_visible(True) is True, "idempotent set_visible(True)")
    ctx.expect(Grid.set_visible(False) is False, "direct set_visible(False)")
    Grid.set_visible(True)  # 还原默认, 避免污染后续场景

    ctx.frames(1)
    s3 = ctx.snapshot("final")
    ctx.expect(s3["std"] > 2.0, f"final snapshot has UI variance (std={s3['std']})")
