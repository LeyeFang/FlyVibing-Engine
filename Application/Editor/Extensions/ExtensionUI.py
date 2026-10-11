"""Extension UI 桥 — `ctx.ui` 的宿主侧实现（M1）。

协议: Doc/ExtDev/extension_dev_protocol.md §7（UI 规范）; 大纲: Doc/Dev/extension_protocol.md §5.1。

职责:
  - `register_window(name, draw_fn, ...)` — 把扩展的绘制函数注册为编辑器面板
    （创建 ExtensionPanel 并注册进 UIManager; 自动出现在 View 菜单与 DockSpace）;
  - `unregister_window(name)` / `purge(ext_id)` — 注销（卸载保险丝由 ExtensionManager 调用）;
  - **异常遏制**（协议 §7 第 3 条）: draw_fn 异常 → 本帧跳过 + 计数;
    连续 `_QUARANTINE_AFTER` 帧异常 → 自动隐藏（可经扩展 Rescan 恢复）。

线程纪律:
  - register/unregister 在装配期/主线程调用（与 ctx.ops 注册同侧）;
  - draw_fn 在渲染线程的 `UIManager.draw_all` 帧内被调用 — 禁止自建 imgui context、
    禁止跨帧持有 imgui 对象; 后台线程 → UI 数据必须经快照/`ctx.ui.post`（[M1 后续]）。

命名冲突: 窗口名与既有面板（含其它扩展）重名 → `ValueError`（不静默改写）。
"""

from __future__ import annotations

import traceback

from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel

# 连续异常帧数阈值 — 达到即隔离该窗口（协议 §7.3）
_QUARANTINE_AFTER = 120


class ExtensionPanel(BasePanel):
    """扩展贡献窗口 — 包装扩展 draw_fn（异常遏制 + 隔离记录 + 关闭策略）。

    close_policy（窗口生命周期完备性 — dev protocol §7）:
      "hide"    仅隐藏（默认）; "disable" 关闭即请求停用扩展; "custom" 仅回调。
    用户点击 X → visible True→False → `_notify_closed()` → on_ui_event("closed", name)
    + （disable 策略）ExtensionManager.request_disable。
    """

    def __init__(self, name: str, draw_fn, ext_id: str,
                 visible: bool = True, flags: imgui.WindowFlags = imgui.WindowFlags_.none,
                 on_closed=None, close_policy: str = "hide") -> None:
        super().__init__()
        self.name = str(name)
        self.visible = bool(visible)
        self.flags = flags
        self._draw_fn = draw_fn
        self._ext_id = ext_id
        self._error_streak = 0
        self._last_error = ""
        self._on_closed = on_closed          # callable(name) — 宿主钩子（由 ExtensionUI 组装）
        self.close_policy = str(close_policy)

    # ── 供 ExtensionUI / ExtensionManager 读取 ──
    @property
    def ext_id(self) -> str:
        return self._ext_id

    def begin_panel(self) -> bool:
        """覆写: 检测用户关闭（X）→ 派发关闭事件（区分于 programmatic visible 翻转）。"""
        was_visible = self.visible
        expanded = super().begin_panel()
        if was_visible and not self.visible:
            print(f"[Extensions] window closed by user: '{self.name}' (policy={self.close_policy})")
            self._notify_closed()
        return expanded

    def _notify_closed(self) -> None:
        """关闭事件派发（begin_panel 自动调用; 单元测试可直接调用）。"""
        if self._on_closed is None:
            return
        try:
            self._on_closed(self.name)
        except Exception:  # noqa: BLE001 — 事件处理异常不得拖垮帧
            traceback.print_exc()

    def draw(self) -> None:
        """渲染线程帧内调用 — 异常遏制: 本帧跳过 + 连续异常隔离。"""
        try:
            self._draw_fn()
            self._error_streak = 0
        except Exception as e:  # noqa: BLE001 — 扩展绘制异常不得拖垮编辑器
            self._error_streak += 1
            self._last_error = f"{type(e).__name__}: {e}"
            # 首次异常与达到隔离阈值时打印 traceback（避免逐帧刷屏）
            if self._error_streak == 1 or self._error_streak == _QUARANTINE_AFTER:
                traceback.print_exc()
            if self._error_streak >= _QUARANTINE_AFTER:
                self.visible = False
                print(f"[Extensions] window '{self.name}' quarantined after "
                      f"{self._error_streak} consecutive draw errors: {self._last_error}")


class ExtensionUI:
    """注入到 `ExtensionContext.ui` 的窗口注册门面（每个扩展一个实例）。"""

    def __init__(self, ext_id: str, instance=None) -> None:
        self._ext_id = ext_id
        self._instance = instance      # 扩展实例（关闭事件回派 on_ui_event; 可为 None）

    # ── 注册 / 注销 ──────────────────────────────────────────────

    def register_window(self, name: str, draw_fn, visible: bool = True, flags=None,
                        close_policy: str = "hide") -> str:
        """注册扩展窗口。

        Args:
            name:   窗口显示名（全局唯一 — 与内置面板/其它扩展重名则报错）;
            draw_fn: 无参绘制函数（在 imgui.begin/end 之间被调用 — 只画内容）;
            visible: 初始可见性;
            flags:  imgui.WindowFlags（None = 默认）;
            close_policy: 窗口关闭（X）语义 —
                "hide"（默认）仅隐藏 / "disable" 关闭即请求停用扩展（菜单勾选同步消失） /
                "custom" 仅回调 on_ui_event。生命周期完备性见 dev protocol §7。
        Returns:
            注册后的窗口名（与 name 相同 — 供 unregister_window 使用）。
        """
        if close_policy not in ("hide", "disable", "custom"):
            raise ValueError(f"unknown close_policy: {close_policy!r} (expected hide/disable/custom)")
        from Application.Editor.UI.UIManager import UIManager
        full = str(name)
        if not full:
            raise ValueError("window name must not be empty")
        if UIManager.find(full) is not None:
            raise ValueError(f"window name already registered: {full!r}")
        panel = ExtensionPanel(full, draw_fn, self._ext_id,
                               visible=visible,
                               flags=flags if flags is not None else imgui.WindowFlags_.none,
                               on_closed=self._make_on_closed(close_policy),
                               close_policy=close_policy)
        UIManager.register(panel)
        return full

    def _make_on_closed(self, policy: str):
        """组装关闭回调: 回派 on_ui_event + （disable 策略）入队停用请求。"""
        def _callback(name: str) -> None:
            instance = self._instance
            if instance is not None:
                handler = getattr(instance, "on_ui_event", None)
                if callable(handler):
                    try:
                        handler("closed", name)
                    except Exception:  # noqa: BLE001 — 扩展回调异常隔离
                        traceback.print_exc()
            if policy == "disable":
                try:
                    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
                    ExtensionManager.request_disable(self._ext_id)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        return _callback

    def unregister_window(self, name: str) -> bool:
        """注销本扩展注册的窗口。返回是否找到并移除。"""
        from Application.Editor.UI.UIManager import UIManager
        panel = UIManager.find(str(name))
        if isinstance(panel, ExtensionPanel) and panel.ext_id == self._ext_id:
            return UIManager.unregister(panel)
        return False

    # ── 宿主保险丝（ExtensionManager 卸载路径调用） ───────────────

    @classmethod
    def purge(cls, ext_id: str) -> None:
        """移除某扩展的全部已注册窗口（on_disable/on_unload 后由管理器调用）。"""
        from Application.Editor.UI.UIManager import UIManager
        for panel in list(UIManager._panels):
            if isinstance(panel, ExtensionPanel) and panel.ext_id == ext_id:
                UIManager.unregister(panel)

    @classmethod
    def show_all(cls, ext_id: str) -> None:
        """把某扩展的全部窗口置为可见（enable 时宿主重置 — “勾选启用 = 想看面板”）。

        配合 close_policy="hide": 用户 X 隐藏后, 再次勾选启用即重新打开
        （菜单勾选/窗口可见性闭环）; 由 ExtensionManager.enable 调用。
        """
        from Application.Editor.UI.UIManager import UIManager
        for panel in list(UIManager._panels):
            if isinstance(panel, ExtensionPanel) and panel.ext_id == ext_id:
                panel.visible = True
