"""
SelectionController — 编辑器实体选中状态的唯一入口（Single Source of Truth）。

职责:
  - 统一管理"哪个实体被选中"，同时同步三套下游系统:
    · SceneBrowserController.selected_entity_id  — 数据层（ScenePanel/Inspector 读取）
    · OutlinerID                                  — 渲染层（3D 视口轮廓高亮）
    · TransformGizmo                              — 渲染层（gizmo 跟随实体位置）
  - 任何入口（Viewport 点选 / ScenePanel 列表点击 / 未来快捷键）都通过本 Controller

架构约束:
  ✅ 可引用: SceneBrowserController, OutlinerID, TransformGizmo
  ❌ 不可引用: imgui, imgui_bundle, Panel, EditorLayer
"""

from __future__ import annotations

from typing import Optional, Callable

from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
from Application.Editor.Gizmos.OutlinerID import OutlinerID
from Application.Editor.Gizmos.TransformGizmo import TransformGizmo
from Application.Core.Scene.SceneManager import SceneManager


class SelectionController:
    """选中状态控制器 — 纯数据层，不 import imgui

    所有选中操作必须经过此类，禁止直接调用 SceneBrowserController.select() 或
    OutlinerID.set_selected_entities()，以保证数据层和渲染层始终一致。
    """

    # ── 回调: 选中变化时通知（EditorLayer 注册 invalidate_camera_gizmos）──
    _on_selection_changed: list[callable] = []

    @classmethod
    def register_selection_callback(cls, cb: callable) -> None:
        """注册选中变化回调。"""
        if cb not in cls._on_selection_changed:
            cls._on_selection_changed.append(cb)

    @classmethod
    def _notify_selection_changed(cls) -> None:
        for cb in cls._on_selection_changed:
            try:
                cb()
            except Exception:
                pass

    # ── 选中操作 ────────────────────────────────────────────

    @classmethod
    def select(cls, entity_id: int) -> None:
        SceneBrowserController.select(entity_id)
        OutlinerID.set_selected_entities({entity_id})
        TransformGizmo._visible = False
        cls._notify_selection_changed()

    @classmethod
    def select_with_gizmo(cls, entity_id: int) -> None:
        SceneBrowserController.select(entity_id)
        OutlinerID.set_selected_entities({entity_id})
        TransformGizmo._visible = True
        TransformGizmo._target_entity_id = entity_id
        try:
            from Application.Core.Math.Transform import calculate_entity_model
            t = EditorHost.scene.GetEntityTransform(entity_id)
            model = calculate_entity_model(
                position=(t.position_x, t.position_y, t.position_z),
                rotation=(t.rotation_x, t.rotation_y, t.rotation_z),
                scale=(t.scale_x, t.scale_y, t.scale_z),
            )
            TransformGizmo.set_target_position(
                (float(model[3, 0]), float(model[3, 1]), float(model[3, 2])))
        except Exception:
            pass

    @classmethod
    def clear(cls) -> None:
        """清除所有选中 — 同时更新数据层 & 渲染层。"""
        SceneBrowserController.clear_selection()
        OutlinerID.clear()
        TransformGizmo._visible = False
        TransformGizmo._target_entity_id = None
        cls._notify_selection_changed()

    # ── 查询 ────────────────────────────────────────────────

    @classmethod
    def get_selected(cls) -> Optional[int]:
        """返回当前选中的实体 ID，无选中时返回 None。"""
        return SceneBrowserController.get_selected()

    @classmethod
    def is_selected(cls, entity_id: int) -> bool:
        """检查指定实体是否被选中。"""
        return SceneBrowserController.get_selected() == entity_id


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SELECTION
from Application.Editor.EditorHost import EditorHost
register(NAME_SELECTION, SelectionController)
