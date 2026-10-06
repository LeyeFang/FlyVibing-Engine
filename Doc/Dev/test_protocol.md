# 测试协议（Test Protocol）— 隔离 / 档位 / 输出契约 / 场景回放

> 适用：`Test/**`（测试资产）、`Utils/Dev/test_runner.py`（统一运行器）、
> `Test/Application/Editor/ui_scenario.py`（UI 场景回放）。
> 目标：**测试独立、互不干扰；agent 一次命令看懂结果，只在必要时读日志**（省 token）。
> 修改/新增测试前必读本文；UI 交互细节另见 `Test/Application/Editor/测试需知.md`。

---

## 1. 运行方式（agent 默认入口）

```powershell
# core 档（无 GUI，默认）— 一次跑完，紧凑摘要
python Utils/Dev/test_runner.py

# 只看清单（含档位）
python Utils/Dev/test_runner.py --list

# 过滤 / 其它档位
python Utils/Dev/test_runner.py --only editor
python Utils/Dev/test_runner.py --tier gui
python Utils/Dev/test_runner.py --tier all --json     # 末行 JSON 摘要（机器读）

# UI 场景回放（真实面板 + 快照 PNG）
python Test/Application/Editor/ui_scenario.py scenarios/panels_smoke.py
python Test/Application/Editor/ui_scenario.py --preview          # 交互预览（ESC 退出）
```

运行器输出示例（agent 只读这几行 + 失败行）：

```
[  1/12] PASS  test_graph_io (1.2s)
[  3/12] FAIL  test_x (0.4s)  first_error: [FAIL] xxx  log: Test/_runs/run_xxx/logs/test_x.log
SUMMARY: 11/12 passed in 84s | failed: test_x | tier=core | skipped=5 | runs: Test/_runs/run_xxx
```

## 2. 档位（tier）

| 档位 | 含义 | 运行环境 | 进默认批次 |
|---|---|---|---|
| `core` | 无 GUI / 无硬件 / 无网络; 秒级~分钟级 | venv | ✅ |
| `gui` | 需要 GL 窗口（面板/ gizmo / 网格视觉） | venv + 显卡 | ❌ |
| `heavy` | 重 IO（导出包等，分钟级） | venv | ❌ |
| `live` | 需要**运行中的编辑器**（e2e；可能启停引擎进程） | 编辑器 + venv | ❌ |
| `manual` | 交互式工具（人工使用，不进批次） | 人 | ❌ |

- 文件头声明：`# TIER: core`（60 行内任意位置）；未声明按文件名启发式（`e2e_*`→live, `*gizmo*/*grid*/*outliner*`→gui, `*live_ui*`/`*node_runtime*`→manual, `*export_game_bundle*`→heavy, 其余 core）。
- 运行器只默认扫描 `Test/Application/**`；其他目录（Device/RHI 等）按需 `--only` + `--tier all`。

## 3. 输出契约（每个测试必须遵守）

1. **最后一行**输出：`RESULT: OK (n)` 或 `RESULT: FAIL (k): <名字列表>` 或 `RESULT: <m>/<n> passed, <k> failed`（运行器据此判定; 缺失或格式未识别时按退出码判定并打 `[no RESULT line]`/`unrecognized RESULT format` 标记）。
2. 过程行允许详细，但**失败行**以 `[FAIL] ...` 开头（运行器提取首条做 `first_error`）。
3. 退出码：0 通过 / 非 0 失败。不要用 `pause`/`input()`（会挂死批次）。
4. 长输出（逐帧日志、大 diff）**写日志文件**或 `MGE_TEST_TMP` 沙箱，不要刷 stdout。

## 4. 隔离规则（运行时）

| 规则 | 说明 |
|---|---|
| 一进程一测试 | 运行器永远子进程执行; 测试不得依赖执行顺序、不得假设前一个测试的残留状态 |
| 沙箱目录 | 用 `os.environ.get("MGE_TEST_TMP")` 作为写盘根（运行器已按测试创建）; 禁止写仓库路径（示例: 不要往 `Test/Application/Editor/` 落 `imgui.ini` 之类产物） |
| 全局单例清理 | 涉及下列全局态时，测试开头/结尾显式复位（能 `finally` 就 `finally`）:<br>· `ControllerRegistry.reset()`（Mock 注入后必须）<br>· 设备池 / epoch 数据集 / 模型注册表: `reset_pools()` / `reset_all()` / 注册表 reset<br>· 画布/场景: 用局部 `NodeCanvas()`; 需要 `EditorHost.scene` 时用 `_ui_boot`（最小引导） |
| imgui 持久化 | 任何 imgui 测试必须 `io.set_ini_filename("")`（`_ui_boot` 已内置）——禁止生成/依赖 `imgui.ini` |
| 端口/句柄 | 服务测试用 ephemeral 端口（`port=0` + 读回）; 启动的进程/窗口必须关闭（`finally`） |
| 设备/网络 | 真实硬件只在 `test_gtec_device.py` 这类显式测试中; 其余一律 stub/dry-run |
| 干跑命名空间 | 引擎内校验/干跑统一 `dryrun#` 前缀（既有机制，勿绕开） |

## 5. UI 场景回放（ui_scenario）

- 结构：`Test/Application/Editor/scenarios/*.py`，协议 `NAME` + `def run(ctx)`；
  ctx 提供 `frames(n)` / `snapshot(name)` / `expect(cond,msg)` / `key/mouse_move/click` / `ctrl(name)` / `panel(name)`。
- **快照 = glReadPixels 后缓冲（swap 前）→ PNG，含完整 ImGui 界面**（已验证；隐藏窗口同样可拍）。
- 快照落在 `Test/_runs/ui_<ts>/<scenario>/`；失败退出码 1；agent 可直接看图（或人工审核）。
- 原则：**行为断言走 Controller/action（快、稳）；只有"看起来对不对"才用快照**。
  像素级 diff 暂不做（先人/agent 目检）; 需要时再加。
- `--preview` 为交互预览（替代旧 `test_live_ui.py` 的日常用法）; `test_live_ui.py` 使用同一引导 `_ui_boot.py`。

## 6. e2e（live 档）纪律

- 脚本必须：用唯一名字前缀（实体/计时器/数据集）→ 不假设空场景; `finally` 清理; 只在自己启动了编辑器时才 `editor.quit`（提供 `--keep` 开关）。
- 端口走 `MGE_EDITOR_MCP_PORT` 默认值; 失败时保留截图/日志路径供排查。
- 运行入口：`python Utils/Dev/test_runner.py --tier live`（或手工单跑脚本）。
- 验收模板（新 op 实机验证）：`view.set_grid` on/off 截图对比（`Test/_runs/e2e_grid/`）—— 行为断言走 core 回环 + scenario，视觉证据走 e2e 截图。
- 线程探针：`python Utils/Dev/thread_probe.py --assert-alive <name,...>`（协议 `threading_protocol.md` §4）。

## 7. 测试地图（按域）

| 域 | 位置 | 档位 | 备注 |
|---|---|---|---|
| 图数据/校验/IO | `Test/Application/NodeGraph/` | core | `test_graph_validation` / `test_graph_io`；`Test/Application/Editor/test_node_runtime.py` 为交互演示（manual） |
| 设备/算法/Functions | `Test/Application/Functions/` | core | gtec / siggen / pool / epoch / bci（stub 后端） |
| 动态媒体 | `Test/Application/Media/` | core | `test_media_system`（解码/时钟/引擎帧去重/错误遏制）+ `test_media_node`（ShowMedia 注册/静态检查/干跑惰性/节点驱动 + PIE 模板白名单）; 协议 `media_protocol.md` |
| 渲染器 | `Test/Application/Renderer/` | core | `test_render_commands`（16 命令 dispatch 契约 + CommandQueue 并发）+ `test_vertex_layout`（布局不变式 + shader 一致性快照）+ `test_gl_pixels`（隐藏窗真 GL 像素: 映射/深度/纹理/动态重传/混合排序; 夹具 `_gl_probe.py`）+ `test_gl_lighting`（光照数值锁定）+ `test_gl_render_targets`（RT 生命周期）；`test_material_isolation`（Core/ — 内置材质模板保护）; 协议 `rendering_protocol.md` + `shader_protocol.md` |
| 编辑器服务（回环） | `Test/Application/Editor/test_live_command_server.py` | core | 含边界扫描; 无 GUI |
| agent 通道包 | `Test/Application/Editor/{test_editor_mcp_package,test_node_editor_mcp}.py` | core | wheel/CLI/注册表 |
| UI 场景回放 | `Test/Application/Editor/scenarios/` | gui | 快照 + 行为断言（panels_smoke / menu_smoke / node_editor_smoke） |
| ~~UI 面板/gizmo（遗留交互 demo）~~ | ~~`test_*_{opengl,zengl}.py`~~ | — | **2026-10-05 已清理**（18 个交互 demo 删除; 覆盖转入 scenarios + e2e） |
| 实机 E2E | `Test/Application/Editor/e2e_*.py` | live | 需编辑器运行中（例: `e2e_renderer_check` — 渲染快照 + 裸帧像素采样） |
| 线程压力/边界 | `Test/Application/stress/` + `Core/test_thread_boundary.py` | core | `--stress N` 放大; 协议 `threading_protocol.md` |
| 导出包 | `test_export_game_bundle.py` | heavy | 分钟级重 IO |

## 8. 新增测试清单

1. 归入对应目录 + `test_` 前缀; 文件头声明 `# TIER: ...`。
2. 遵守 §3 输出契约（末行 RESULT + 失败 `[FAIL]`）。
3. 写盘只用 `MGE_TEST_TMP`; 全局态按 §4 复位。
4. 跑一次：`python Utils/Dev/test_runner.py --only <你的文件名>` 确认摘要正常。
5. 若是 UI：优先写"行为断言"测试（core）；只有视觉结果需要固定时再加 scenario + 快照。
