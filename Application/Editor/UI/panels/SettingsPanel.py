"""SettingsPanel — 编辑器设置面板（Edit ▸ Preferences…；面板名 `Settings`）。

协议: `Doc/Dev/ui_protocol.md` §13（Settings 面板与设置体系）。

结构（MATLAB / Blender 风格）: **左侧页面列表 + 右侧当前页内容**。

页面注册表:
  - core 内置页: `Common`（外观: 字号/语言）/ `Export`（PIE 启动窗口设置 —
    由 ScenePanel 的 ⚙ Settings 弹层迁移, 2026-10-12）;
  - **extension 贡献页与 core 页同级展示**（规划 M1: `ctx.settings(schema)` 自动生成
    并注册到此面板; 见 Doc/ExtDev/extension_dev_protocol.md §6）— `owner` 标注来源;
  - `register_page` 重名 → `ValueError`（不静默改写 — 与窗口命名红线同则）。

文本与自由度（ui_protocol §11/§12）:
  - 文案一律经 `I18n.t()`（中文显示依赖已合并的 CJK 字体 msyh）;
  - 控件自由度标注见各控件处 `[自由度: Lx]` 注释; 数值变更经 `EditorSettings`（钳制 + 落盘）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from imgui_bundle import imgui

from Application.Editor.EditorSettings import EditorSettings
from Application.Editor.I18n import t
from Application.Editor.Services.ControllerRegistry import NAME_SIMULATION, get_ctrl
from Application.Editor.UI.BasePanel import BasePanel


@dataclass
class SettingsPage:
    """设置页（core 或 extension 贡献 — 同级展示）。

    title_key: I18n 键（语言切换后即时更新; I18n 无词条时回退显示键原文,
               因此扩展页可直接用自有文案作为键）。
    """
    id: str
    title_key: str
    draw_fn: Callable[[], None]
    order: int = 100           # 排序（小者靠前; 同序按 id）
    owner: str = "core"        # "core" | 扩展 id


class SettingsPanel(BasePanel):
    """设置面板 — 页面注册表 + 左列表/右内容布局。"""

    name = "Settings"
    title_key = "panel.settings"      # 窗口标题可翻译（imgui ID 仍由 ###name 固定）

    _pages: dict = {}                 # id → SettingsPage
    _active_id: str = ""

    # ════════════════════════════════════════════════════════════
    # 页面注册表（core + 未来 extension 共用）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_page(cls, page: "SettingsPage") -> str:
        """注册设置页（重名 → ValueError — 不静默改写）。"""
        if not page.id:
            raise ValueError("settings page id must not be empty")
        if page.id in cls._pages:
            raise ValueError(f"settings page already registered: {page.id!r}")
        cls._pages[page.id] = page
        return page.id

    @classmethod
    def unregister_page(cls, page_id: str) -> bool:
        return cls._pages.pop(page_id, None) is not None

    @classmethod
    def unregister_pages_by_owner(cls, owner: str) -> int:
        """移除某来源的全部页（扩展卸载保险丝 — 与 purge_ui 对称）。"""
        ids = [pid for pid, page in cls._pages.items() if page.owner == owner]
        for pid in ids:
            cls._pages.pop(pid, None)
        if cls._active_id in ids:
            cls._active_id = ""
        return len(ids)

    @classmethod
    def pages(cls) -> list:
        """已注册页（排序: order → id）。"""
        return sorted(cls._pages.values(), key=lambda p: (p.order, p.id))

    # ════════════════════════════════════════════════════════════
    # 打开入口（菜单 / 未来的 settings.* op 同路径）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def open(cls, page_id: str = "") -> bool:
        """显示面板并选中指定页（空 = 保持/首个）。返回是否成功。"""
        from Application.Editor.UI.UIManager import UIManager
        panel = UIManager.find(cls.name)
        if panel is None:
            return False
        if page_id and page_id in cls._pages:
            cls._active_id = page_id
        panel.visible = True
        return True

    # ════════════════════════════════════════════════════════════
    # 绘制（渲染线程帧内 — UIManager.draw_all 调用）
    # ════════════════════════════════════════════════════════════

    def begin_panel(self) -> bool:
        """首次出现给定尺寸。

        左列表/右内容双列布局在 imgui 自适应尺寸下会塌缩成一条
        （子窗口高度 0 — 实测 2026-10-12 截图），故首次强制一个可用尺寸。
        """
        imgui.set_next_window_size(imgui.ImVec2(880.0, 560.0), imgui.Cond_.first_use_ever)
        return super().begin_panel()

    def draw(self) -> None:
        pages = SettingsPanel.pages()
        if not pages:
            imgui.text_disabled("(no settings pages registered)")
            return
        ids = [p.id for p in pages]
        if SettingsPanel._active_id not in ids:
            SettingsPanel._active_id = ids[0]

        # ── 左列表 [自由度: L1 受控枚举 — 页面集由注册表决定] ──
        imgui.begin_child("##settings_nav", (170.0, 0.0), True)
        for page in pages:
            selected = (page.id == SettingsPanel._active_id)
            label = t(page.title_key)
            if imgui.selectable(f"{label}##settings_page_{page.id}", selected)[0]:
                SettingsPanel._active_id = page.id
        imgui.end_child()

        imgui.same_line()

        # ── 右内容 ──
        imgui.begin_child("##settings_content", (0.0, 0.0), False)
        active = next(p for p in pages if p.id == SettingsPanel._active_id)
        imgui.push_id(f"settings_page_{active.id}")
        active.draw_fn()
        imgui.pop_id()
        imgui.end_child()


# ════════════════════════════════════════════════════════════════
# 内置页: Common（外观 — 字号 / 语言）
# ════════════════════════════════════════════════════════════════

# 字号档（[自由度: L1 受控枚举] — 只登记已实现档位; 应用侧仍做 0.7..1.6 钳制兜底）
_FONT_SIZE_CHOICES = [("Small (0.85)", 0.85),
                      ("Default (1.00)", 1.0),
                      ("Large (1.15)", 1.15),
                      ("Extra Large (1.30)", 1.30)]

# 语言选项 — **由语言目录动态推导**（新增 `Locale/<lang>.json` 即自动出现;
# 显示名用该语言自称, 取自 `_meta.name` — 协议 `Doc/Dev/i18n_protocol.md` §5）
def _lang_choices() -> list:
    from Application.Editor.I18n import available_languages, language_name
    return [(language_name(code), code) for code in available_languages()]


def _draw_common_page() -> None:
    """Common 页 — Appearance 区（字号 / 语言, 即时生效）。"""
    imgui.text_disabled(t("settings.common.appearance"))
    imgui.separator()

    # ── Font size [自由度: L1 受控枚举] — 写入 EditorSettings, 渲染线程帧首应用 ──
    cur = float(EditorSettings.get("ui.font_scale"))
    labels = [lbl for lbl, _v in _FONT_SIZE_CHOICES]
    values = [v for _lbl, v in _FONT_SIZE_CHOICES]
    idx = min(range(len(values)), key=lambda i: abs(values[i] - cur))
    if abs(values[idx] - cur) > 1e-6:
        # 值来自 agent op（连续值, 非档位）→ 追加当前项, 不误导为"最近档位"
        # （ui_protocol §11 假自由度禁令: 控件显示必须与真实值一致）
        labels = labels + [f"Custom ({cur:.2f})"]
        values = values + [cur]
        idx = len(values) - 1
    changed, new_idx = imgui.combo(f"{t('settings.common.font_size')}##ui_font_scale", idx, labels)
    if changed:
        EditorSettings.set("ui.font_scale", values[new_idx])
    imgui.text_disabled(f"x{cur:.2f}  ({t('settings.common.instant')})")

    # ── Language [自由度: L1 受控枚举 — 选项集随语言目录变化] ──
    lang = str(EditorSettings.get("ui.language"))
    choices = _lang_choices()
    lang_labels = [lbl for lbl, _v in choices]
    lang_values = [v for _lbl, v in choices]
    lidx = lang_values.index(lang) if lang in lang_values else 0
    changed, new_idx = imgui.combo(f"{t('settings.common.language')}##ui_language", lidx, lang_labels)
    if changed:
        EditorSettings.set("ui.language", lang_values[new_idx])


# ════════════════════════════════════════════════════════════════
# 内置页: Export（PIE 启动窗口设置 — 迁自 ScenePanel ⚙ Settings 弹层）
# ════════════════════════════════════════════════════════════════

_PIE_MODES = [("Windowed", "windowed"),
              ("Borderless (fullscreen-sized)", "borderless"),
              ("Exclusive fullscreen", "fullscreen")]


def _draw_export_page() -> None:
    """Export 页 — PIE 初始窗口行为（持久化 PIE.json; 下次 Run 生效）。"""
    ctrl = get_ctrl(NAME_SIMULATION)
    if ctrl is None:  # 无头/未注册环境兜底
        imgui.text_disabled("(simulation controller unavailable)")
        return
    s = ctrl.get_pie_settings()

    imgui.text_disabled(f"{t('settings.export.pie')} — {t('settings.export.note')}")
    imgui.separator()

    # ── 模式 [自由度: L1 受控枚举] ──
    # 工程背景色（测试性配置；存 .myproj，完整成品常用 skybox/内容填底）
    from Application.Editor.ProjectManager import ProjectManager as _PM
    if _PM.is_open():
        imgui.text_disabled("Background (project)")
        imgui.same_line()
        _bg = list(_PM.background_color())
        _c0 = imgui.drag_float("R##bg_r", _bg[0], 0.01, 0.0, 1.0, "%.2f")
        imgui.same_line()
        _c1 = imgui.drag_float("G##bg_g", _bg[1], 0.01, 0.0, 1.0, "%.2f")
        imgui.same_line()
        _c2 = imgui.drag_float("B##bg_b", _bg[2], 0.01, 0.0, 1.0, "%.2f")
        if _c0[0] or _c1[0] or _c2[0]:
            _PM.set_background_color(_c0[1], _c1[1], _c2[1])
        imgui.same_line()
        for _n, _rgb in (("White", (1, 1, 1)), ("Gray", (0.2, 0.2, 0.2)), ("Black", (0, 0, 0))):
            if imgui.small_button(f"{_n}##bg_{_n}"):
                _PM.set_background_color(*_rgb)
    else:
        imgui.text_disabled("Background (project) — open a project to edit")
    imgui.separator()

    labels = [m[0] for m in _PIE_MODES]
    keys = [m[1] for m in _PIE_MODES]
    cur = keys.index(s["mode"]) if s["mode"] in keys else 0
    changed, idx = imgui.combo(f"{t('settings.export.mode')}##pie_mode", cur, labels)
    if changed:
        ctrl.set_pie_settings(mode=keys[idx])
        cur = idx

    imgui.separator()
    imgui.begin_disabled(keys[cur] != "windowed")

    # ── 预设 [自由度: L0 固定动作] ──
    imgui.text_disabled(t("settings.export.preset"))
    for label, pw, ph in (("1280 \u00d7 720", 1280, 720),
                          ("1600 \u00d7 900", 1600, 900),
                          ("1920 \u00d7 1080", 1920, 1080)):
        if imgui.small_button(f"{label}##pie"):
            ctrl.set_pie_settings(width=pw, height=ph)
            s = ctrl.get_pie_settings()
        imgui.same_line()
    imgui.new_line()

    # ── 宽高 [自由度: L2 开放输入 + 委托约束] — clamp 在 SimulationController.set_pie_settings ──
    cw, nw = imgui.input_int(f"{t('settings.export.width')}##pie_w", int(s["width"]))
    ch, nh = imgui.input_int(f"{t('settings.export.height')}##pie_h", int(s["height"]))
    if cw or ch:
        ctrl.set_pie_settings(width=nw, height=nh)

    imgui.end_disabled()


# ── 内置页注册（import 即注册 — 与面板类同批加载; id 稳定不可改名） ──
SettingsPanel.register_page(SettingsPage(
    id="common", title_key="settings.page.common", draw_fn=_draw_common_page, order=0))
SettingsPanel.register_page(SettingsPage(
    id="export", title_key="settings.page.export", draw_fn=_draw_export_page, order=10))
