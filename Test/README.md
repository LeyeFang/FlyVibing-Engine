# Test 目录

本目录现在采用**局部纳入 git** 的策略（2026-10-21）：

## 会跟踪

- `Test/Application/**/test_*.py`
- `Test/Application/Editor/scenarios/*.py`、`_ui_boot.py`、`测试需知.md`
- `Test/Application/Editor/_ui_boot.py`
- `Test/Helpers/`、`Test/Resources/`、`Test/Device/`
- `Test/_path_setup.py`、`_test_harness.py`、`_test_scene.py`
- `Test/TestProject/**` 的工程源文件、场景、材质和小型 fixture

## 不跟踪（运行时产物）

- `Test/_runs/`（日志、截图、临时文件）
- `Test/_archive/`、`Test/_gtec_archive_20261016/`
- `Test/TestProject/**/dist/`、`output/`、`runtime/`、`seed/`
- `Test/TestProject/**/*.txt`（seed / 本地记录）
- `Test/**/__pycache__/`、`*.pyc`
- `Test/Application/Editor/imgui.ini`、`graph.json`
- `Test/Application/Functions/_siggen_e2e_out/`

规则源：仓库根 `.gitignore` 的 `Test/` 段。新增测试产物前先确认它不应入库；
不要把 `Test/` 整体 `git add -f`。

## 运行

```powershell
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --list
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier core
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --only test_scene_manager
```

测试节点地图 / UI 展开图：

```powershell
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py check
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py affected Application/Core/Scene/SceneManager.py
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py ui tree
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py ui check
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_map.py ui render
```

修改测试后同步 `Doc/Dev/test_nodes.json`（`test_map.py init --force` 或手工补充 `covers`/`requires`），再运行 `test_map.py render`。
修改 UI 控件/显隐条件后同步 `Doc/Dev/ui_map.json`，再运行 `ui render`；`test_ui_map` 会校验 source/test/scenario 引用。

GUI 场景不再需要单独找入口：

```powershell
.\.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier gui
```

## 约定

- 一个 `test_*.py` 一个子进程；测试之间不依赖执行顺序。
- 输出最后一行必须是 `RESULT: OK (n)` / `RESULT: n/m passed...` / `RESULT: FAIL ...`。
- 写盘只用 `MGE_TEST_TMP` 或临时目录，不写仓库根。
- 需要 GL、硬件、运行中编辑器的测试请标 `TIER: gui/live/manual`，不要混入 core 默认批次。
