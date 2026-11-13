"""Extension panel view state — menu checkbox <-> panel visibility, persisted.

Background (2026-11-13, reported by an external extension author)
--------------------------------------------------------------
Two independent state systems used to exist with no reconciliation:

* lifecycle:  ``ExtensionInfo.enabled``  (persisted in ``extensions.json``)
* view:       ``ExtensionPanel.visible`` (process memory only, always ``False``
              at startup because ImGui's ini file is disabled)

``scan()`` loaded state-enabled extensions but never called ``show_all()``,
so an enabled extension could have **zero visible panels** while the Extensions
menu checkbox (which read ``enabled``) showed it as checked.  On top of that
the checkbox meant *enable* for ``local``/``user`` extensions but *show panel*
(no checkbox at all) for built-ins -- the same affordance meaning two things.

Contract now locked by this test:

1. the menu checkbox reads ``ExtensionManager.has_visible_panel()`` only --
   checked  <=>  at least one panel visible;
2. ``ExtensionPanel.visible`` is the **single choke point**: every write
   persists ``panels[name]`` into the state file (no call site can forget);
3. panel visibility is restored on the next start (per window, so sub-windows
   like Device Manager come back too), and on a window's **first** appearance
   the registration's ``show_on_enable`` decides -- but only for non-bundled
   extensions (a built-in is always-on, so "just discovered" is
   indistinguishable from "the user closed it a year ago");
4. panel toggling never mutates ``enabled`` and never loses the other keys
   (``enabled`` / ``python`` / ``panels`` are independent sections).

TIER: core
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []

EXT_ID = "paneltest"


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _info(**kw) -> types.SimpleNamespace:
    """Minimal stand-in for ExtensionInfo (restore reads id/loaded/has_ui/bundled)."""
    base = dict(id=EXT_ID, loaded=True, has_ui=True, bundled=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _read_state(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _register(ui, name: str, *, visible: bool = False, show_on_enable: bool = True) -> None:
    ui.register_window(name, lambda: None, visible=visible,
                       show_on_enable=show_on_enable)


def main() -> int:
    print("=" * 60)
    print("Extension panel view state (menu <-> panel, persisted)")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
    from Application.Editor.Extensions.ExtensionUI import ExtensionPanel, ExtensionUI
    from Application.Editor.UI.UIManager import UIManager

    tmp = tempfile.mkdtemp(prefix="mge_panel_state_")
    state_path = os.path.join(tmp, "extensions.json")
    # ★ 必须带 `FVE_` 前缀（AppIdentity.env_get 只认 FVE_/MGE_）——否则测试会写到
    #   真实 %APPDATA% 状态文件里，把用户的扩展开关盖掉（2026-11-13 踩过）。
    old_env = os.environ.get("FVE_EXTENSIONS_STATE")
    old_data = os.environ.get("FVE_EXTENSIONS_DATA")
    os.environ["FVE_EXTENSIONS_STATE"] = state_path
    os.environ["FVE_EXTENSIONS_DATA"] = os.path.join(tmp, "ext_data")
    old_infos = dict(ExtensionManager._infos)
    if os.path.normcase(ExtensionManager._state_path()) != os.path.normcase(state_path):
        raise SystemExit(f"refusing to run: state path not sandboxed "
                         f"({ExtensionManager._state_path()!r})")
    names: list[str] = []
    try:
        ui = ExtensionUI(EXT_ID)
        main_win = "PanelTest Main"
        sub_win = "PanelTest Sub"
        _register(ui, main_win)
        _register(ui, sub_win, show_on_enable=False)
        names = [main_win, sub_win]
        ExtensionManager._infos = {EXT_ID: _info()}

        # ── 1. 注册即隐藏（首跑不弹窗）──
        check("fresh register: hidden", not ExtensionManager.has_visible_panel(EXT_ID))
        check("fresh register: no intent recorded",
              ExtensionManager.panel_intent(main_win) is None,
              str(ExtensionManager.panel_intent(main_win)))
        showed = ExtensionManager.show_panels(EXT_ID)
        check("show_panels opens main window only (sub has show_on_enable=False)",
              showed == 1 and ExtensionManager.has_visible_panel(EXT_ID), f"showed={showed}")
        check("show_panels leaves sub window hidden",
              UIManager.find(sub_win).visible is False)
        check("show_panels persists intent=True", ExtensionManager.panel_intent(main_win) is True)

        # ── 1b. 首次出现（无意图）: 非内置 + show_on_enable → 自动开一次 ──
        #     这条正是 2026-11-13 issue 的另一半: 用户装好扩展后重启，面板再也
        #     不出现（enable() 的弹出只发生在当次会话）。
        ExtensionManager._write_state({EXT_ID: True}, {}, {})     # 清空意图 = 首跑
        UIManager.find(main_win)._visible = False                 # 模拟新进程（不落盘）
        ExtensionManager._restore_panel_intents({EXT_ID: _info(bundled=False)})
        check("first run: non-bundled main window auto-shown",
              UIManager.find(main_win).visible is True)
        check("first run: intent recorded so next start is deterministic",
              ExtensionManager.panel_intent(main_win) is True,
              str(ExtensionManager.panel_intent(main_win)))
        check("first run: sub window (show_on_enable=False) stays hidden",
              UIManager.find(sub_win).visible is False)
        #     内置扩展恒激活 —— 「刚扫到」和「用户早先关掉了」无法区分，不乱弹。
        ExtensionManager._write_state({EXT_ID: True}, {}, {})
        UIManager.find(main_win)._visible = False
        ExtensionManager._restore_panel_intents({EXT_ID: _info(bundled=True)})
        check("first run: built-in stays hidden (cannot distinguish from user-closed)",
              ExtensionManager.has_visible_panel(EXT_ID) is False)
        check("first run: built-in records no intent",
              ExtensionManager.panel_intent(main_win) is None)
        ExtensionManager.show_panels(EXT_ID)                     # 回到 section 2 的前置

        # ── 2. 菜单数据源 == 面板事实 ──
        check("menu sees checked while panel visible",
              ExtensionManager.has_visible_panel(EXT_ID) is True)
        hidden = ExtensionManager.hide_panels(EXT_ID)
        check("hide_panels hides everything", hidden == 1, f"hidden={hidden}")
        check("menu sees unchecked after hide",
              ExtensionManager.has_visible_panel(EXT_ID) is False)
        check("hide_panels persists intent=False",
              ExtensionManager.panel_intent(main_win) is False)

        # ── 3. 用户点 X（visible 直接翻转）也要落盘 ──
        UIManager.find(main_win).visible = True
        check("direct visible=True is persisted (single choke point)",
              ExtensionManager.panel_intent(main_win) is True)
        UIManager.find(main_win).visible = False       # 模拟 ImGui X 按钮
        check("direct visible=False (user X) is persisted",
              ExtensionManager.panel_intent(main_win) is False)

        # ── 4. 重启恢复（按窗口恢复，含附属窗口）──
        UIManager.find(main_win).visible = True
        UIManager.find(sub_win).visible = True         # 用户也打开了附属窗口
        before_restart = ExtensionManager.panel_intent(sub_win)
        check("sub window intent recorded", before_restart is True, str(before_restart))
        for win in names:
            p = UIManager.find(win)
            if p is not None:
                UIManager.unregister(p)
        _register(ui, main_win)
        _register(ui, sub_win, show_on_enable=False)
        check("simulated restart starts hidden",
              not ExtensionManager.has_visible_panel(EXT_ID))
        ExtensionManager._restore_panel_intents({EXT_ID: _info()})
        check("restart restores main window",
              UIManager.find(main_win).visible is True)
        check("restart restores sub window too",
              UIManager.find(sub_win).visible is True)

        # ── 5. 面板操作不得动 enabled / python，且不得丢键 ──
        ExtensionManager._write_state({EXT_ID: True}, {EXT_ID: "/x/python.exe"},
                                      {main_win: True})
        ExtensionManager.hide_panels(EXT_ID)
        state = _read_state(state_path)
        check("panel write keeps enabled section",
              state.get("enabled", {}).get(EXT_ID) is True, str(state.get("enabled")))
        check("panel write keeps python section",
              state.get("python", {}).get(EXT_ID) == "/x/python.exe",
              str(state.get("python")))
        check("panel write updates panels section",
              state.get("panels", {}).get(main_win) is False,
              str(state.get("panels")))
        panels_snapshot = dict(state.get("panels") or {})
        ExtensionManager._write_state({EXT_ID: False})
        state = _read_state(state_path)
        check("enabled write keeps panels section",
              state.get("panels") == panels_snapshot,
              f"panels={state.get('panels')} expected={panels_snapshot}")

        # ── 6. toggle_panels 闭环（菜单点击）──
        ExtensionManager._infos = {EXT_ID: _info(loaded=True, loadable=True)}
        ExtensionManager.hide_panels(EXT_ID)
        now = ExtensionManager.toggle_panels(EXT_ID)
        check("toggle_panels on hidden -> visible", now is True)
        now = ExtensionManager.toggle_panels(EXT_ID)
        check("toggle_panels on visible -> hidden", now is False)
        state = _read_state(state_path)
        check("toggle_panels never touches enabled",
              state.get("enabled", {}).get(EXT_ID) is False,
              str(state.get("enabled")))
        check("toggle_panels leaves panels[name] = False",
              state.get("panels", {}).get(main_win) is False)

        # ── 7. 老状态文件（无 panels 段）可读 ──
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "enabled": {EXT_ID: True}, "python": {}}, fh)
        full = ExtensionManager._read_state_full()
        check("legacy state without panels reads as empty dict",
              full["panels"] == {} and full["enabled"].get(EXT_ID) is True, str(full))

        # ── 7b. 带 BOM 的状态文件也要读得出来（Windows 记事本默认这么存）──
        #      纯 utf-8 读会在 BOM 上抛 JSONDecodeError → 静默回落默认 = 开关全丢。
        with open(state_path, "w", encoding="utf-8-sig") as fh:
            json.dump({"version": 2, "enabled": {EXT_ID: True},
                       "panels": {main_win: True}}, fh)
        full = ExtensionManager._read_state_full()
        check("state file with UTF-8 BOM is still honoured",
              full["enabled"].get(EXT_ID) is True
              and full["panels"].get(main_win) is True, str(full))

        # ── 8. 诊断面：per-window 可见性 ──
        check("panel_state() reports per-window visibility",
              set(ExtensionManager.panel_state(EXT_ID)) == {main_win, sub_win},
              str(ExtensionManager.panel_state(EXT_ID)))
    finally:
        for win in names:
            p = UIManager.find(win)
            if p is not None:
                UIManager.unregister(p)
        ExtensionManager._infos = old_infos
        for key, saved in (("FVE_EXTENSIONS_STATE", old_env),
                           ("FVE_EXTENSIONS_DATA", old_data)):
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved

    print("-" * 60)
    print(f"  {_passed} passed, {len(_failed)} failed")
    if _failed:
        for label in _failed:
            print(f"  FAILED: {label}")
        return 1
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
