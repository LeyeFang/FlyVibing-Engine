"""Extensions 菜单 — 主菜单栏的扩展管理入口（唯一实现, 多面板共用）。

使用方:
  - Application/Editor/UI/UIManager.py  _draw_menu_bar  (实际渲染路径)
  - Application/Editor/UI/panels/MenuBarPanel.py        (保留文件, 未注册)

职责（对应 Doc/ExtDev/extension_dev_protocol.md §5/§9）:
  - 列出全部扩展（ExtensionManager.list_infos, 来源 = 内置 Application/Functions/** + 用户目录）
  - broken           → 红色禁用项 + 错误 tooltip
  - planned/未实现    → 灰色"计划中" + 目录/描述 tooltip
  - 可装载           → 复选菜单项, 点击 = ExtensionManager.toggle
                       （与 extension.enable/disable op 同路径）
  - Rescan           → ExtensionManager.rescan

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
        infos = ExtensionManager.list_infos()
    except Exception as e:  # noqa: BLE001 — 菜单不得因扩展体系异常而崩
        infos = []
        imgui.text_disabled(t("extension.system_error", error=repr(e)))
    if not infos:
        imgui.menu_item(t("extension.none"), "", False, False)
    for info in infos:
        label = f"{info.get('name') or info.get('id')}"
        status = info.get("status", "planned")
        if status == "broken":
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(0.85, 0.35, 0.30, 1.0))
            imgui.menu_item(t("extension.broken", name=label), "", False, False)
            imgui.pop_style_color(1)
            if imgui.is_item_hovered():
                imgui.set_tooltip(str(info.get("error", "")))
        elif not info.get("loadable"):
            imgui.menu_item(t("extension.planned", name=label,
                              maturity=info.get("maturity", "planned")), "", False, False)
            if imgui.is_item_hovered():
                imgui.set_tooltip(f"{info.get('dir', '')}\n{info.get('description', '')}")
        else:
            changed, val = imgui.menu_item(label, "", bool(info.get("enabled")), True)
            if imgui.is_item_hovered():
                imgui.set_tooltip(t(
                    "extension.tooltip", id=info.get("id"), version=info.get("version"),
                    maturity=info.get("maturity"), dir=info.get("dir", "")))
            if changed:
                try:
                    ExtensionManager.toggle(info["id"], val)
                except Exception as e:  # noqa: BLE001
                    print(f"[Extensions] toggle failed: {e!r}")
    imgui.separator()
    if imgui.menu_item(t("extension.rescan"), "", False, True)[0]:
        try:
            ExtensionManager.rescan()
        except Exception as e:  # noqa: BLE001
            print(f"[Extensions] rescan failed: {e!r}")
    imgui.end_menu()
