"""编辑器热键动作 + 注册表条目（唯一实现 — 面板/CLI 与真实按键同源）。

分工：
  - `Application/Core/Input/Hotkeys.py` —— 通用注册表（解析/匹配/派发），不依赖编辑器
  - 本模块 —— 编辑器实际动作（gizmo 模式、预览相机…）+ 注册那批既有绑定

约定：**先有实现才注册**。菜单里没接线的占位（Ctrl+N/S/Z…）不进注册表，
否则面板会再次变成"写着但按了没用"的假提示。
"""

from __future__ import annotations

from Application.Core.Input.Hotkeys import Hotkey, register

_registered: bool = False


# ════════════════════════════════════════════════════════════════
# 动作（真实实现 — 从 EditorInputLayer 的事件分支搬过来）
# ════════════════════════════════════════════════════════════════

def _apply_gizmo_mode(mode_name: str) -> None:
    """切换 gizmo 模式；有选中实体时顺带显示 gizmo（等价于旧按键行为）。"""
    from Application.Editor.Gizmos.TransformGizmo import GizmoMode, TransformGizmo

    mode = getattr(GizmoMode, mode_name)
    TransformGizmo.set_mode(mode)
    from Application.Editor.UI.controllers.SelectionController import SelectionController

    selected = SelectionController.get_selected()
    if selected is None:
        return
    from Application.Editor.EditorHost import EditorHost

    TransformGizmo.show(EditorHost.get_editor_renderer(), selected)


def gizmo_grab() -> None:
    _apply_gizmo_mode("GRAB")


def gizmo_rotate() -> None:
    _apply_gizmo_mode("ROTATE")


def gizmo_scale() -> None:
    _apply_gizmo_mode("SCALE")


def toggle_preview_camera() -> None:
    """Space — 编辑器视口在场景相机 / 自由相机之间切换。"""
    from Application.Editor.EditorGizmoLayer import EditorGizmoLayer

    EditorGizmoLayer._toggle_preview_camera()


# ════════════════════════════════════════════════════════════════
# 注册
# ════════════════════════════════════════════════════════════════

def register_editor_hotkeys() -> None:
    """登记编辑器热键（幂等 — 多次调用只生效一次）。"""
    global _registered
    if _registered:
        return
    _registered = True

    # ── 视口变换 gizmo（全局派发）──
    register(Hotkey(
        id="viewport.gizmo_grab", keys="G", scope="viewport", action="gizmo.grab",
        description_key="hotkey.viewport.gizmo_grab",
        dispatch="global", impl=gizmo_grab))
    register(Hotkey(
        id="viewport.gizmo_rotate", keys="R", scope="viewport", action="gizmo.rotate",
        description_key="hotkey.viewport.gizmo_rotate",
        dispatch="global", impl=gizmo_rotate))
    register(Hotkey(
        id="viewport.gizmo_scale", keys="S", scope="viewport", action="gizmo.scale",
        description_key="hotkey.viewport.gizmo_scale",
        dispatch="global", impl=gizmo_scale))
    register(Hotkey(
        id="viewport.toggle_preview", keys="Space", scope="viewport",
        action="viewport.toggle_preview",
        description_key="hotkey.viewport.toggle_preview",
        dispatch="global", impl=toggle_preview_camera))

    # ── 视口鼠标操作（仅提示：由编辑器鼠标事件实现，不是键位和弦）──
    register(Hotkey(
        id="viewport.select", keys="LMB click", scope="viewport", action="selection.pick",
        description_key="hotkey.viewport.select", kind="mouse"))
    register(Hotkey(
        id="viewport.orbit", keys="MMB drag", scope="viewport", action="camera.orbit",
        description_key="hotkey.viewport.orbit", kind="mouse"))
    register(Hotkey(
        id="viewport.pan", keys="Shift+MMB drag", scope="viewport", action="camera.pan",
        description_key="hotkey.viewport.pan", kind="mouse"))
    register(Hotkey(
        id="viewport.zoom", keys="Wheel", scope="viewport", action="camera.zoom",
        description_key="hotkey.viewport.zoom", kind="mouse"))

    # ── 节点编辑器（拥有者语境派发：只在画布焦点内生效）──
    register(Hotkey(
        id="node_editor.delete", keys="Delete", scope="node_editor",
        action="node.delete", description_key="hotkey.node_editor.delete",
        dispatch="owner"))

    # ── 运行时（PIE / 成品：glfwWindow + RuntimeInputLayer 实现）──
    register(Hotkey(
        id="pie.exit", keys="Esc", scope="pie", action="runtime.exit",
        description_key="hotkey.pie.exit", dispatch="owner"))


def registered() -> bool:
    return _registered
