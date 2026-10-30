from __future__ import annotations
from abc import ABC, abstractmethod

from imgui_bundle import imgui

from Application.Core.Events.Event import Event


class BasePanel(ABC):
    """所有 UI 面板的基类 — 纯绘制，不持业务逻辑"""

    # ============================================================
    # 子类可重写的属性
    # ============================================================
    name: str = "UnnamedPanel"
    visible: bool = True
    flags: imgui.WindowFlags = imgui.WindowFlags_.none
    # 显示标题的 I18n 键（可翻译 — 协议 `Doc/Dev/i18n_protocol.md` §4)。
    # 空 = 直接用 `name`（英文标识符）。imgui 窗口 ID 恒为 `###<name>`，
    # 因此标题文案随语言变化不影响 dock 布局与状态身份。
    title_key: str = ""
    # 首次出现位置（None = 交给 ImGui 默认级联）。
    # 扩展的附属窗口（如设备管理）用它避免叠在主面板上。
    first_use_pos: tuple[float, float] | None = None
    # 首次出现尺寸（None = 自动适应内容）。附属窗口用它固定布局宽度。
    first_use_size: tuple[float, float] | None = None

    def __init__(
        self
    ) -> None:
        """初始化面板（子类应调用 super().__init__()）"""
        self._first_frame = True

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(
        self
    ) -> None:
        """面板被注册时的初始化回调"""
        pass

    def on_detach(
        self
    ) -> None:
        """面板被移除时的清理回调"""
        pass

    # ============================================================
    # 绘制入口
    # ============================================================

    @abstractmethod
    def draw(
        self
    ) -> None:
        """每帧绘制面板内容（子类必须实现）"""
        ...

    def on_event(
        self,
        event: Event
    ) -> None:
        """可选：处理引擎事件"""
        pass

    # ============================================================
    # 工具方法
    # ============================================================

    def begin_panel(
        self
    ) -> bool:
        """打开一个带标题的 imgui 窗口，返回该窗口是否可见/展开。

        标题 = `t(title_key)`（设置了键时）；imgui ID 经 `###<name>` 固定 ——
        显示文案可随语言即时变化，dock/折叠状态身份不变。
        """
        if self.title_key:
            from Application.Editor.I18n import t
            label = f"{t(self.title_key)}###{self.name}"
        else:
            label = self.name
        if self.first_use_pos is not None:
            imgui.set_next_window_pos(
                (float(self.first_use_pos[0]), float(self.first_use_pos[1])),
                imgui.Cond_.first_use_ever)
        if self.first_use_size is not None:
            imgui.set_next_window_size(
                (float(self.first_use_size[0]), float(self.first_use_size[1])),
                imgui.Cond_.first_use_ever)
        expanded, self.visible = imgui.begin(
            label, self.visible, self.flags
        )
        return expanded

    def end_panel(
        self
    ) -> None:
        """结束 imgui 窗口"""
        imgui.end()
