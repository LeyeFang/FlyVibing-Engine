"""Extensions 菜单 — 主菜单栏的**面板入口**（唯一实现, 多面板共用）。

使用方:
  - Application/Editor/UI/UIManager.py  _draw_menu_bar  (实际渲染路径)
  - Application/Editor/UI/panels/MenuBarPanel.py        (保留文件, 未注册)

分工（2026-11-13 调整 —— 状态同步）:
  - 主菜单 Extensions = **UI 面板入口**。只列 `has_ui` 的扩展（capabilities 含
    `ui`，或已注册 ExtensionPanel 窗口）；纯后台扩展（ops/nodes/examples/device）
    不在这里出现 —— 它们的开关/诊断在 设置 ▸ Extensions 页。
  - **勾选框只表达一件事: 这个扩展的面板当前是否可见**（`panel_visible`），
    与扩展生命周期（enabled）**解耦** —— 启停是 设置 ▸ Extensions 页 / `extension.enable`。
    点勾选 = 打开/关闭面板（打开时若未装载先装载），所以永远不可能出现
    “勾着但没面板”。
    （旧实现: builtin 无勾选框、local/user 勾选框 = enabled，同一位置两种含义;
    加上启动时从不恢复面板可见性 → 某个 local 扩展“勾着却没面板”。）
  - 面板可见性作为**独立持久意图**（`extensions.json` 的 `panels` 段）跨会话恢复;
    broken / planned 不在这里列（管理面在设置页），避免菜单被不可用项塞满;
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
        ext_id = info.get("id")
        # ★ 勾选 = 面板可见（唯一数据源: ExtensionPanel.visible）—— 所有 scope 同一语义。
        #   已启用但被关掉 → 不勾; 未启用 → 不勾（点一下 = 装载 + 打开）。
        try:
            visible = ExtensionManager.has_visible_panel(ext_id)
        except Exception:  # noqa: BLE001 — 无 UI 环境
            visible = False
        label = f"{info.get('name') or ext_id}"
        tooltip = t("extension.tooltip", id=ext_id, version=info.get("version"),
                    maturity=info.get("maturity"), dir=info.get("dir", ""))
        changed, _val = imgui.menu_item(label, "", visible, True)
        if imgui.is_item_hovered():
            hint = t("extension.bundled_tip") if info.get("always_on") \
                else t("extension.panel_tip")
            imgui.set_tooltip(hint + "\n" + tooltip)
        if changed:
            try:
                ExtensionManager.toggle_panels(ext_id)
            except Exception as e:  # noqa: BLE001
                print(f"[Extensions] toggle panel failed: {e!r}")
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
