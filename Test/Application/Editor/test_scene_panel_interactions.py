"""
Test: Scene Panel Interactions — Controller Registry + Mock Injection
═══════════════════════════════════════════════════════════════════════════════

纯 Python 测试（无 imgui，无 OpenGL 窗口）。
验证 ControllerRegistry 的注册/查询/重置 + Mock Controller 的状态转换。

运行: python Test/Application/Editor/test_scene_panel_interactions.py
"""

from __future__ import annotations
import sys, os

# ── 路径引导 ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

from Application.Editor.Services.ControllerRegistry import (
    register, get_ctrl, reset,
    NAME_SIMULATION, NAME_SCENE_BROWSER,
    NAME_RESOURCE_BROWSER, NAME_VIEWPORT,
)

from Test.Helpers.MockControllers import (
    MockSimulationController,
    MockSceneBrowserController,
    MockResourceBrowserController,
    MockViewportController,
)

# ── 真 Controller（验证 auto-register 行为） ──
from Application.Editor.UI.controllers.SimulationController import SimulationController
from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
from Application.Editor.UI.controllers.ResourceBrowserController import ResourceBrowserController
from Application.Editor.UI.controllers.ViewportController import ViewportController


# ═══════════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════════

_passed = 0
_failed = 0


def check(condition: bool, description: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅ {description}")
    else:
        _failed += 1
        print(f"  ❌ FAIL: {description}")


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ═══════════════════════════════════════════════════════════════
# Test 1: ControllerRegistry 基础功能
# ═══════════════════════════════════════════════════════════════

def test_registry_basics():
    section("Test 1: ControllerRegistry 基础功能")

    # 1a. 空的注册表返回 None
    reset()
    check(get_ctrl(NAME_SIMULATION) is None,
          "空注册表 get_ctrl 返回 None")

    # 1b. register → get_ctrl 往返
    register(NAME_SIMULATION, MockSimulationController)
    check(get_ctrl(NAME_SIMULATION) is MockSimulationController,
          "register → get_ctrl 返回同一对象")

    # 1c. register 覆盖
    register(NAME_SIMULATION, SimulationController)
    check(get_ctrl(NAME_SIMULATION) is SimulationController,
          "同名 register 覆盖前值")

    # 1d. reset 清空
    reset()
    check(get_ctrl(NAME_SIMULATION) is None,
          "reset() 后 get_ctrl 返回 None")


# ═══════════════════════════════════════════════════════════════
# Test 2: 真 Controller 的 auto-register
# ═══════════════════════════════════════════════════════════════

def test_real_controllers_auto_register():
    section("Test 2: 真 Controller auto-register")

    # 模拟 import 时模块级 register() 的行为
    # （实际生产中 import 控制器模块就会触发 register）
    reset()
    register(NAME_SIMULATION, SimulationController)
    register(NAME_SCENE_BROWSER, SceneBrowserController)
    register(NAME_RESOURCE_BROWSER, ResourceBrowserController)
    register(NAME_VIEWPORT, ViewportController)

    check(get_ctrl(NAME_SIMULATION) is SimulationController,
          "SimulationController 注册 → get_ctrl 返回正确")
    check(get_ctrl(NAME_SCENE_BROWSER) is SceneBrowserController,
          "SceneBrowserController 注册 → get_ctrl 返回正确")
    check(get_ctrl(NAME_RESOURCE_BROWSER) is ResourceBrowserController,
          "ResourceBrowserController 注册 → get_ctrl 返回正确")
    check(get_ctrl(NAME_VIEWPORT) is ViewportController,
          "ViewportController 注册 → get_ctrl 返回正确")


# ═══════════════════════════════════════════════════════════════
# Test 3: Mock SimulationController 状态机
# ═══════════════════════════════════════════════════════════════

def test_mock_simulation_state_machine():
    section("Test 3: MockSimulationController 状态机")

    MockSimulationController.reset()

    # 3a. 初始状态
    check(MockSimulationController.is_stopped(), "初始状态 STOPPED")
    check(not MockSimulationController.is_running(), "初始非 RUNNING")

    # 3b. play → RUNNING
    MockSimulationController.play()
    check(MockSimulationController.play_called == 1, "play() 调用计数=1")
    check(MockSimulationController.is_running(), "play() → RUNNING")
    check(not MockSimulationController.is_stopped(), "play() → 非 STOPPED")

    # 3c. pause → PAUSED
    MockSimulationController.pause()
    check(MockSimulationController.is_paused(), "pause() → PAUSED")

    # 3d. resume → RUNNING
    MockSimulationController.resume()
    check(MockSimulationController.is_running(), "resume() → RUNNING")

    # 3e. stop → STOPPED
    MockSimulationController.stop()
    check(MockSimulationController.is_stopped(), "stop() → STOPPED")

    # 3f. 连续 stop 不报错
    MockSimulationController.stop()
    check(MockSimulationController.stop_called == 2, "连续 stop() 调用计数正确")


# ═══════════════════════════════════════════════════════════════
# Test 4: Mock SceneBrowserController
# ═══════════════════════════════════════════════════════════════

def test_mock_scene_browser():
    section("Test 4: MockSceneBrowserController")

    MockSceneBrowserController.reset()

    # 4a. 默认返回预设实体
    entities = MockSceneBrowserController.get_renderable_entities()
    check(entities == [1, 2, 3], f"默认实体列表 [1,2,3] → {entities}")

    # 4b. 预设自定义实体
    MockSceneBrowserController.set_entities([100, 200])
    entities = MockSceneBrowserController.get_renderable_entities()
    check(entities == [100, 200], "set_entities 自定义列表生效")

    # 4c. select 记录调用参数
    MockSceneBrowserController.select(42)
    check(42 in MockSceneBrowserController.select_called_with,
          "select(42) 记录到 select_called_with")
    check(MockSceneBrowserController.get_selected() == 42,
          "select(42) → get_selected() 返回 42")

    # 4d. get_summary 返回预设数据
    MockSceneBrowserController.set_summary(1, (1.0, 2.0, 3.0), mesh_id=5)
    s = MockSceneBrowserController.get_summary(1)
    check(s is not None, "预设 summary 存在")
    check(s.entity_id == 1, "summary.entity_id 正确")
    check(s.position == (1.0, 2.0, 3.0), "summary.position 正确")
    check(s.mesh_id == 5, "summary.mesh_id 正确")

    # 4e. 未预设的 entity 返回 None
    s = MockSceneBrowserController.get_summary(999)
    check(s is None, "未预设 entity 返回 None")


# ═══════════════════════════════════════════════════════════════
# Test 5: Mock 注入 & 替换
# ═══════════════════════════════════════════════════════════════

def test_mock_injection():
    section("Test 5: Mock 注入 → Registry → 替换为真 Controller")

    reset()

    # 5a. 注入 Mock
    register(NAME_SIMULATION, MockSimulationController)
    ctrl = get_ctrl(NAME_SIMULATION)
    check(ctrl is MockSimulationController, "注入 Mock 后 get_ctrl 返回 Mock")

    # 5b. Mock 方法可正常调用
    MockSimulationController.reset()
    ctrl.play()
    check(MockSimulationController.play_called == 1, "Mock.play() 被调用")

    # 5c. 替换回真 Controller
    register(NAME_SIMULATION, SimulationController)
    ctrl = get_ctrl(NAME_SIMULATION)
    check(ctrl is SimulationController, "替换后 get_ctrl 返回真 Controller")

    # 5d. reset 后清空
    reset()
    check(get_ctrl(NAME_SIMULATION) is None, "reset 后注册表清空")


# ═══════════════════════════════════════════════════════════════
# Test 6: ScenePanel 从 Registry 获取 Controller
# ═══════════════════════════════════════════════════════════════

def test_scene_panel_controller_wiring():
    section("Test 6: ScenePanel 从 Registry 获取 Controller")

    reset()

    # 注册 Mock 到全部 4 个槽位
    register(NAME_SIMULATION, MockSimulationController)
    register(NAME_SCENE_BROWSER, MockSceneBrowserController)
    register(NAME_RESOURCE_BROWSER, MockResourceBrowserController)
    register(NAME_VIEWPORT, MockViewportController)

    # 需要 ResourceManager/SceneManager 初始化才能创建 ScenePanel
    # （因为 Panel 本身不依赖它们，但 draw() 中调用的 Controller 需要）
    # ScenePanel.__init__ 只做 get_ctrl 获取引用，不调用 Controller 方法
    # 所以此处可以直接创建
    from Application.Editor.UI.panels.ScenePanel import ScenePanel
    panel = ScenePanel()

    # 验证 panel 内部引用指向 Mock
    check(panel._sim_ctrl is MockSimulationController,
          "panel._sim_ctrl → MockSimulationController")
    check(panel._browser_ctrl is MockSceneBrowserController,
          "panel._browser_ctrl → MockSceneBrowserController")
    check(panel._resource_ctrl is MockResourceBrowserController,
          "panel._resource_ctrl → MockResourceBrowserController")
    check(panel._viewport_ctrl is MockViewportController,
          "panel._viewport_ctrl → MockViewportController")

    # 验证 panel 自身状态
    check(panel.name == "Scene", "panel.name == 'Scene'")
    check(panel._active_tab == 0, "初始 tab = 0 (Entities)")

    # 清理
    reset()


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  Scene Panel Interactions — Controller Registry Tests")
    print("=" * 60)

    test_registry_basics()
    test_real_controllers_auto_register()
    test_mock_simulation_state_machine()
    test_mock_scene_browser()
    test_mock_injection()
    test_scene_panel_controller_wiring()

    # ── 清理 ──
    reset()

    # ── 结果 ──
    total = _passed + _failed
    print(f"\n{'=' * 60}")
    print(f"  Results: {_passed}/{total} passed"
          + (f", {_failed} FAILED" if _failed else ""))
    print(f"{'=' * 60}")

    return _failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
