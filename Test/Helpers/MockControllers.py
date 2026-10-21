"""
MockControllers — 测试用 Controller 替代品。

每个 Mock Controller 提供与真实 Controller 完全相同的方法签名，
但行为是纯数据操作：记录调用、返回预设值、不触碰引擎。

使用方式:

    from Test.Helpers.MockControllers import (
        MockSimulationController,
        MockSceneBrowserController,
        MockResourceBrowserController,
        MockViewportController,
    )
    from Application.Editor.Services.ControllerRegistry import register

    # 注入 Mock
    register(NAME_SIMULATION, MockSimulationController)
    register(NAME_SCENE_BROWSER, MockSceneBrowserController)
    # ...

    # 创建 Panel（内部从 Registry 取得 Mock）
    panel = ScenePanel()

    # 模拟用户点击 Run
    # panel 内部的 self._sim_ctrl.play() 会调用 MockSimulationController.play()
    # 检查: MockSimulationController.play_called == True

    # 测试结束，恢复
    ControllerRegistry.reset()

设计原则:
  - 每个 Mock 是独立类，类变量作为「状态存储」
  - 提供 `reset()` 类方法，测试间清零
  - 方法签名与真 Controller 完全一致（@classmethod 风格）
  - 业务方法记录调用次数/参数，查询方法返回预设数据
"""

from __future__ import annotations

from typing import Optional


# ═══════════════════════════════════════════════════════════════
# MockSimulationController
# ═══════════════════════════════════════════════════════════════

class MockSimulationController:
    """SimulationController 的测试替身。

    状态变更不触发 EngineLifecycleEvent、不启动 GameRuntime。
    所有方法调用记录到类变量，供 assert 验证。
    """

    # ── 模拟状态 ──
    _state: str = "STOPPED"  # "STOPPED" | "RUNNING" | "PAUSED"

    # ── 调用记录 ──
    play_called: int = 0
    pause_called: int = 0
    stop_called: int = 0
    resume_called: int = 0

    @classmethod
    def reset(cls) -> None:
        """重置状态和调用记录（每个测试前调用）。"""
        cls._state = "STOPPED"
        cls.play_called = 0
        cls.pause_called = 0
        cls.stop_called = 0
        cls.resume_called = 0

    @classmethod
    def play(cls) -> None:
        cls.play_called += 1
        cls._state = "RUNNING"

    @classmethod
    def pause(cls) -> None:
        cls.pause_called += 1
        if cls._state == "RUNNING":
            cls._state = "PAUSED"

    @classmethod
    def resume(cls) -> None:
        cls.resume_called += 1
        if cls._state == "PAUSED":
            cls._state = "RUNNING"

    @classmethod
    def stop(cls) -> None:
        cls.stop_called += 1
        cls._state = "STOPPED"

    @classmethod
    def is_running(cls) -> bool:
        return cls._state == "RUNNING"

    @classmethod
    def is_paused(cls) -> bool:
        return cls._state == "PAUSED"

    @classmethod
    def is_stopped(cls) -> bool:
        return cls._state == "STOPPED"

    @classmethod
    def get_state(cls) -> str:
        return cls._state

    @classmethod
    def get_state_label(cls) -> str:
        return {"STOPPED": "Not running", "RUNNING": "Running", "PAUSED": "Paused"}[cls._state]


# ═══════════════════════════════════════════════════════════════
# MockSceneBrowserController
# ═══════════════════════════════════════════════════════════════

class MockSceneBrowserController:
    """SceneBrowserController 的测试替身。

    返回预设的实体列表和摘要数据，不访问 SceneManager。
    """

    # ── 预设数据 ──
    _entities: list[int] = [1, 2, 3]
    _selected: Optional[int] = None
    _summaries: dict[int, dict] = {}

    # ── 调用记录 ──
    select_called_with: list[int] = []

    @classmethod
    def reset(cls) -> None:
        cls._entities = [1, 2, 3]
        cls._selected = None
        cls._summaries = {}
        cls.select_called_with.clear()

    @classmethod
    def set_entities(cls, entity_ids: list[int]) -> None:
        """预设实体列表（测试数据注入）。"""
        cls._entities = list(entity_ids)

    @classmethod
    def set_summary(cls, entity_id: int, position: tuple, mesh_id=None, material_id=None) -> None:
        """预设实体摘要（测试数据注入）。"""
        cls._summaries[entity_id] = {
            "entity_id": entity_id,
            "position": position,
            "mesh_id": mesh_id,
            "material_id": material_id,
        }

    @classmethod
    def get_renderable_entities(cls) -> list[int]:
        return list(cls._entities)

    @classmethod
    def select(cls, entity_id: int) -> None:
        cls.select_called_with.append(entity_id)
        cls._selected = entity_id

    @classmethod
    def get_selected(cls) -> Optional[int]:
        return cls._selected

    @classmethod
    def clear_selection(cls) -> None:
        cls._selected = None

    @classmethod
    def get_summary(cls, entity_id: int, use_local: bool = False):
        """返回预设摘要或 None。"""
        preset = cls._summaries.get(entity_id)
        if preset:
            # 返回一个简单的命名元组式对象
            return _Summary(
                entity_id=preset["entity_id"],
                position=preset["position"],
                mesh_id=preset.get("mesh_id"),
                material_id=preset.get("material_id"),
            )
        return None


class _Summary:
    """EntitySummary 的轻量替身。"""
    __slots__ = ("entity_id", "position", "mesh_id", "material_id")

    def __init__(self, entity_id, position, mesh_id=None, material_id=None):
        self.entity_id = entity_id
        self.position = position
        self.mesh_id = mesh_id
        self.material_id = material_id


# ═══════════════════════════════════════════════════════════════
# MockResourceBrowserController
# ═══════════════════════════════════════════════════════════════

class MockResourceBrowserController:
    """ResourceBrowserController 的测试替身。返回空/预设资源列表。"""

    _meshes: dict = {}
    _shaders: dict = {}
    _textures: dict = {}
    _materials: dict = {}

    @classmethod
    def reset(cls) -> None:
        cls._meshes = {}
        cls._shaders = {}
        cls._textures = {}
        cls._materials = {}

    @classmethod
    def set_meshes(cls, data: dict) -> None:
        cls._meshes = dict(data)

    @classmethod
    def set_shaders(cls, data: dict) -> None:
        cls._shaders = dict(data)

    @classmethod
    def set_textures(cls, data: dict) -> None:
        cls._textures = dict(data)

    @classmethod
    def set_materials(cls, data: dict) -> None:
        cls._materials = dict(data)

    @classmethod
    def get_meshes(cls) -> dict:
        return dict(cls._meshes)

    @classmethod
    def get_shaders(cls) -> dict:
        return dict(cls._shaders)

    @classmethod
    def get_textures(cls) -> dict:
        return dict(cls._textures)

    @classmethod
    def get_materials(cls) -> dict:
        return dict(cls._materials)

    @classmethod
    def get_resource_name(cls, resource: dict) -> str:
        return resource.get("name", "unnamed")


# ═══════════════════════════════════════════════════════════════
# MockViewportController
# ═══════════════════════════════════════════════════════════════

class MockViewportController:
    """ViewportController 的测试替身。不操作 EditorCamera。"""

    _mode_2d: bool = False

    # ── 调用记录 ──
    switch_to_2d_called: int = 0
    switch_to_3d_called: int = 0

    @classmethod
    def reset(cls) -> None:
        cls._mode_2d = False
        cls.switch_to_2d_called = 0
        cls.switch_to_3d_called = 0

    @classmethod
    def is_2d(cls) -> bool:
        return cls._mode_2d

    @classmethod
    def is_3d(cls) -> bool:
        return not cls._mode_2d

    @classmethod
    def switch_to_2d(cls) -> None:
        cls.switch_to_2d_called += 1
        cls._mode_2d = True

    @classmethod
    def switch_to_3d(cls) -> None:
        cls.switch_to_3d_called += 1
        cls._mode_2d = False
