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
        """打开一个带标题的 imgui 窗口，返回该窗口是否可见/展开"""
        expanded, self.visible = imgui.begin(
            self.name, self.visible, self.flags
        )
        return expanded

    def end_panel(
        self
    ) -> None:
        """结束 imgui 窗口"""
        imgui.end()
