"""Hot Keys 面板 — 只读热键总表（Help ▸ Hot Keys…）。

数据源 = `Application/Core/Input/Hotkeys.py` 注册表（**不是**这里写死的文案）：
改键位/加绑定只改注册表，本面板与 CLI `hotkeys.list` 自动跟随。

只读：面板里没有任何编辑控件（键位是代码里声明的，改键属于改代码）。
"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Core.Input.Hotkeys import SCOPE_ORDER, SCOPES, snapshot
from Application.Editor.I18n import t, t_optional
from Application.Editor.UI.BasePanel import BasePanel


class HotkeysPanel(BasePanel):
    """热键一览（分组只读表）。"""

    name = "Hot Keys"
    title_key = "hotkeys.title"
    flags = imgui.WindowFlags_.none
    first_use_size = (660.0, 460.0)

    def __init__(self) -> None:
        super().__init__()
        self.visible = False          # 默认隐藏，由 Help 菜单打开
        self._filter: str = ""
        self._show_mouse: bool = True

    # ── 数据 ────────────────────────────────────────────────

    @staticmethod
    def _rows() -> list[dict]:
        from Application.Editor.HotkeyActions import register_editor_hotkeys
        register_editor_hotkeys()      # 面板先打开（注册表还没初始化）时的保险
        return snapshot(t_optional)

    # ── 绘制 ────────────────────────────────────────────────

    def draw(self) -> None:
        rows = self._rows()
        imgui.text_disabled(t("hotkeys.source_hint"))
        imgui.separator()

        imgui.text_disabled(t("hotkeys.search"))
        imgui.same_line()
        imgui.set_next_item_width(200.0)
        _changed, self._filter = imgui.input_text("##hotkeys_filter", self._filter)
        imgui.same_line()
        _changed, self._show_mouse = imgui.checkbox(
            f"{t('hotkeys.show_mouse')}##hotkeys_mouse", self._show_mouse)

        needle = self._filter.strip().lower()

        def _visible(row: dict) -> bool:
            if row["kind"] == "mouse" and not self._show_mouse:
                return False
            if not needle:
                return True
            return needle in (f"{row['keys']} {row['description']} {row['action']} "
                              f"{row['scope']}").lower()

        shown = [r for r in rows if _visible(r)]
        if not shown:
            imgui.text_disabled(t("hotkeys.empty"))
            return

        for scope in SCOPE_ORDER:
            group = [r for r in shown if r["scope"] == scope]
            if not group:
                continue
            if imgui.collapsing_header(f"{t_optional(SCOPES[scope], scope)}##hotkeys_scope_{scope}",
                                       imgui.TreeNodeFlags_.default_open):
                self._draw_table(group, scope)

    @staticmethod
    def _draw_table(group: list[dict], scope: str) -> None:
        flags = (imgui.TableFlags_.row_bg
                 | imgui.TableFlags_.borders_inner_h
                 | imgui.TableFlags_.sizing_stretch_prop)
        table_id = f"##hotkeys_table_{scope}"
        if not imgui.begin_table(table_id, 2, flags):
            return
        try:
            imgui.table_setup_column(t("hotkeys.col.keys"),
                                     imgui.TableColumnFlags_.width_fixed, 150.0)
            imgui.table_setup_column(t("hotkeys.col.action"),
                                     imgui.TableColumnFlags_.width_stretch)
            imgui.table_headers_row()
            for row in group:
                imgui.table_next_row()
                imgui.table_set_column_index(0)
                imgui.text(row["keys"])
                imgui.table_set_column_index(1)
                imgui.text(row["description"])
                if row["kind"] == "mouse":
                    imgui.same_line()
                    imgui.text_disabled(t("hotkeys.mouse_tag"))
        finally:
            imgui.end_table()


# ── 打开入口（Help 菜单 / 未来的 op 同路径）──────────────────
def open_hotkeys_panel() -> bool:
    """显示 Hot Keys 面板。返回是否找到面板。"""
    from Application.Editor.UI.UIManager import UIManager

    panel = UIManager.find(HotkeysPanel.name)
    if panel is None:
        return False
    panel.visible = True
    return True


__all__ = ["HotkeysPanel", "open_hotkeys_panel"]
