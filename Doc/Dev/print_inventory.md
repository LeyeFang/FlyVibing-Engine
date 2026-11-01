# 引擎裸 print 清单（生成文件，勿手改）

> 由 `Utils/Dev/print_audit.py` 生成；`test_print_inventory` 校验新鲜度。
> 范围: `Application/**/*.py` 中行首为 `print(` 的语句（排除 `__pycache__` / `Config`）。

## 1. 汇总

| 区域 | print 条数 |
|---|---:|
| Functions | 219 |
| Editor | 173 |
| Core | 104 |
| Runtime | 46 |
| Resource | 4 |
| other | 2 |
| **合计** | **548** |

热路径（`Core/NodeGraph/evaluators` + 运行时循环层）: **49** 条。

保留项（不是调试遗留）: `Application/Core/NodeGraph/evaluators/debug.py`
（`Print` / `PrintString` 节点的输出语义本身）。

## 2. 热路径（每帧可能执行，优先迁移）

| 文件 | 条数 |
|---|---:|
| `Application/Core/NodeGraph/evaluators/entity/component.py` | 24 |
| `Application/Core/NodeGraph/evaluators/io.py` | 4 |
| `Application/Runtime/GameRuntime.py` | 4 |
| `Application/Core/NodeGraph/evaluators/entity/lifecycle.py` | 3 |
| `Application/Runtime/RuntimeNodeLayer.py` | 3 |
| `Application/Core/NodeGraph/evaluators/entity/camera.py` | 2 |
| `Application/Core/NodeGraph/evaluators/entity/destroy.py` | 2 |
| `Application/Core/NodeGraph/evaluators/entity/mesh.py` | 2 |
| `Application/Core/NodeGraph/evaluators/action.py` | 1 |
| `Application/Core/NodeGraph/evaluators/inputs.py` | 1 |
| `Application/Core/NodeGraph/evaluators/media.py` | 1 |
| `Application/Core/NodeGraph/evaluators/time.py` | 1 |
| `Application/Runtime/RuntimeDebugLayer.py` | 1 |


## 3. 全部文件（按条数降序；`Functions/**` 扩展自有，不计入明细）

`Application/Functions/**` 共 **219** 条，由各扩展自行治理，不列入本表。

| 文件 | 条数 |
|---|---:|
| `Application/Editor/ProjectManager.py` | 47 |
| `Application/Runtime/PlayerBootstrap.py` | 34 |
| `Application/Core/NodeGraph/evaluators/entity/component.py` | 24 |
| `Application/Editor/UI/panels/node_editor/panel.py` | 19 |
| `Application/Editor/Services/LiveCommandServer.py` | 12 |
| `Application/Editor/UI/controllers/SimulationController.py` | 11 |
| `Application/Editor/UI/controllers/SceneBrowserController.py` | 10 |
| `Application/Core/Window/glfwWindow.py` | 8 |
| `Application/Core/Project/RuntimeProjectLoader.py` | 7 |
| `Application/Core/Renderer/ZenGL/ZenGLOverlays.py` | 7 |
| `Application/Editor/Extensions/ExtensionManager.py` | 7 |
| `Application/Editor/UI/panels/ScenePanel.py` | 7 |
| `Application/Core/Renderer/ZenGL/ZenGLResourceManager.py` | 6 |
| `Application/Editor/EditorImguiLayer.py` | 6 |
| `Application/Editor/Services/ImportService.py` | 6 |
| `Application/Editor/UI/panels/ResourcePanel.py` | 6 |
| `Application/Editor/UI/panels/node_editor/validate.py` | 6 |
| `Application/Core/Scene/PrefabManager.py` | 5 |
| `Application/Editor/EditorHost.py` | 5 |
| `Application/Core/Media/MediaSystem.py` | 4 |
| `Application/Core/NodeGraph/canvas.py` | 4 |
| `Application/Core/NodeGraph/evaluators/io.py` | 4 |
| `Application/Runtime/GameRuntime.py` | 4 |
| `Application/Core/Engine.py` | 3 |
| `Application/Core/NodeGraph/evaluator_engine.py` | 3 |
| `Application/Core/NodeGraph/evaluators/entity/lifecycle.py` | 3 |
| `Application/Core/Renderer/ZenGL/ZenGLCore.py` | 3 |
| `Application/Editor/EditorLayer.py` | 3 |
| `Application/Editor/UI/UIManager.py` | 3 |
| `Application/Editor/UI/panels/node_editor/group_context.py` | 3 |
| `Application/Resource/ResourceManager.py` | 3 |
| `Application/Runtime/RuntimeNodeLayer.py` | 3 |
| `Application/Core/AppIdentity.py` | 2 |
| `Application/Core/DeviceRegistry.py` | 2 |
| `Application/Core/NodeGraph/evaluators/debug.py` | 2 |
| `Application/Core/NodeGraph/evaluators/entity/camera.py` | 2 |
| `Application/Core/NodeGraph/evaluators/entity/destroy.py` | 2 |
| `Application/Core/NodeGraph/evaluators/entity/mesh.py` | 2 |
| `Application/Core/Renderer/ZenGL/ZenGLRenderer.py` | 2 |
| `Application/Editor/EditorGizmoLayer.py` | 2 |
| `Application/Editor/EditorModule.py` | 2 |
| `Application/Editor/EditorSettings.py` | 2 |
| `Application/Editor/Extensions/ExtensionMenu.py` | 2 |
| `Application/Editor/Extensions/ExtensionUI.py` | 2 |
| `Application/Editor/UI/controllers/ResourceBrowserController.py` | 2 |
| `Application/Editor/UI/panels/node_editor/io.py` | 2 |
| `Application/Editor/UI/panels/node_editor/selection.py` | 2 |
| `Application/Runtime/StubWindow.py` | 2 |
| `Application/Core/Extension/ExtensionContext.py` | 1 |
| `Application/Core/NodeGraph/evaluators/action.py` | 1 |
| `Application/Core/NodeGraph/evaluators/inputs.py` | 1 |
| `Application/Core/NodeGraph/evaluators/media.py` | 1 |
| `Application/Core/NodeGraph/evaluators/time.py` | 1 |
| `Application/Core/NodeGraph/node_packs.py` | 1 |
| `Application/Core/Scene/GizmoQuery.py` | 1 |
| `Application/Core/Scene/SceneManager.py` | 1 |
| `Application/Core/Scene/SceneSync.py` | 1 |
| `Application/Editor/EditorDebugLayer.py` | 1 |
| `Application/Editor/Gizmos/TransformGizmo.py` | 1 |
| `Application/Editor/I18n.py` | 1 |
| `Application/Editor/StartupOptions.py` | 1 |
| `Application/Editor/UI/controllers/SelectionController.py` | 1 |
| `Application/Editor/UI/panels/node_editor/find_window.py` | 1 |
| `Application/EntryPoint.py` | 1 |
| `Application/PlayerEntry.py` | 1 |
| `Application/Resource/_resource_utils.py` | 1 |
| `Application/Runtime/RuntimeDebugLayer.py` | 1 |
| `Application/Runtime/RuntimeWindow.py` | 1 |
| `Application/Runtime/StubRenderer.py` | 1 |

## 4. 迁移约定（2026-11-01 立项）

- **节点求值器（热路径）**: 不再 `print`；需要诊断时用 `ctx.emit_log`（结构化、
  干跑进收集器；真实运行默认不输出）。错误由 `GraphEvaluator._report_node_error`
  统一限流打印。
- **引擎子系统**: 走 `LogBus`（stdout/stderr tee + 环形缓冲），agent 用
  `console.tail` 读取；不新增行首裸 `print`。
- **本条目的目标**: 热路径裸 print 归零；其余按区域逐步收敛，
  新增 print 必须在本清单产生 diff（评审可见）。
- **后续（未开始）**: Settings ▸ Debug —— 选择 Debug layer 隔离哪些事件类型
  （已有先例: 键盘/鼠标事件已隔离，窗口 resize 未隔离）。
