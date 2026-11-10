"""Extensions 菜单 — 主菜单栏的**面板入口**（唯一实现, 多面板共用）。

使用方:
  - Application/Editor/UI/UIManager.py  _draw_menu_bar  (实际渲染路径)
  - Application/Editor/UI/panels/MenuBarPanel.py        (保留文件, 未注册)

分工（2026-11-10 调整）:
  - 主菜单 Extensions = **UI 面板入口**。只列 `has_ui` 的扩展（capabilities 含
    `ui`，或已注册 ExtensionPanel 窗口）；纯后台扩展（ops/nodes/examples/device）
    不在这里出现 —— 它们的开关/诊断在 设置 ▸ Extensions 页。
  - **builtin** 扩展（allowlist 内、随引擎分发）恒激活，菜单项不再带勾选框，
    点击 = 把它的面板叫回来（与 View 菜单同语义）; `local`（Functions 下的非白名单夹具）
    与 `user` 扩展保持 勾选 = 启停。
  - broken / planned 不在这里列（管理面在设置页），避免菜单被不可用项塞满;
    菜单底部常驻 "Extension Settings…" 直达管理页 + Rescan。

约束: 须在 imgui.begin_main_menu_bar() 块内调用; 任何扩展体系异常
      不得使菜单栏崩溃（内部全部捕获）。
"""

from imgui_bundle import imgui

from Application.Editor.I18n import t


def draw_extensions_menu() -> None:
    """绘制 'Extensions' 顶级菜单（须在 begin_main_menu_bar 块内调用）。"""
    if not imgui.begin_menu(t("extension.menu.title"), True):
        return
    try:
        from Application.Editor.Extensions.ExtensionManager import ExtensionManager
        infos = [i for i in ExtensionManager.list_infos() if i.get("has_ui")]
    except Exception as e:  # noqa: BLE001 — 菜单不得因扩展体系异常而崩
        infos = []
        imgui.text_disabled(t("extension.system_error", error=repr(e)))

    shown = 0
    for info in infos:
        if not info.get("loadable"):
            continue          # planned / 无 entry：管理面在设置页
        label = f"{info.get('name') or info.get('id')}"
        tooltip = t("extension.tooltip", id=info.get("id"), version=info.get("version"),
                    maturity=info.get("maturity"), dir=info.get("dir", ""))
        if info.get("always_on"):
            # 内置恒激活 → 菜单项 = 面板开关（不是启停）
            if imgui.menu_item(label, "", False, True)[0]:
                try:
                    ExtensionManager.show_panels(info["id"])
                except Exception as e:  # noqa: BLE001
                    print(f"[Extensions] show panel failed: {e!r}")
            if imgui.is_item_hovered():
                imgui.set_tooltip(t("extension.bundled_tip") + "\n" + tooltip)
            shown += 1
            continue
        changed, val = imgui.menu_item(label, "", bool(info.get("enabled")), True)
        if imgui.is_item_hovered():
            imgui.set_tooltip(tooltip)
        if changed:
            try:
                ExtensionManager.toggle(info["id"], val)
            except Exception as e:  # noqa: BLE001
                print(f"[Extensions] toggle failed: {e!r}")
        shown += 1

    if not shown:
        imgui.menu_item(t("extension.none_ui"), "", False, False)

    imgui.separator()
    if imgui.menu_item(t("extension.open_settings"), "", False, True)[0]:
        try:
            from Application.Editor.UI.panels.SettingsPanel import SettingsPanel
            SettingsPanel.open("extensions")
        except Exception as e:  # noqa: BLE001
            print(f"[Extensions] open settings failed: {e!r}")
    if imgui.menu_item(t("extension.rescan"), "", False, True)[0]:
        try:
            ExtensionManager.rescan()
        except Exception as e:  # noqa: BLE001
            print(f"[Extensions] rescan failed: {e!r}")
    imgui.end_menu()
