# graph_validation_protocol.md — 节点图校验协议（引擎内服务）

> 消费者：agent / 开发者。**改校验规则、干跑语义、报告格式、Validate UI、图导入导出时必读本文。**
> 状态：2026-10-02 落地（v4）。离线校验（`Utils/User/NodeEditor/node_graph_validator` 链路）已退场。

---

## 1. 定位（单一事实源）

节点图校验**在引擎内执行**，唯一定义于 `Application/Core/NodeGraph/validation/`：

```
validation/
    checks.py    # L1 静态检查: static_check_graph(scene_data) → list[{level, code, message, node_id}]
    dry_run.py   # L2 干跑: run_dry_run(graph_data, frames, dt, seed, progress_cb, cancel_event)
    service.py   # 任务服务: ValidationService (start/state/report/cancel) + run_validation() 同步链
```

三个入口共用同一服务实例（UI 与 MCP 完全同源）：

| 入口 | 位置 | 说明 |
|---|---|---|
| UI | Node Editor 面板工具栏 **Validate** 按钮 | 选项: 静态 / 360 帧 / 600 帧; 完成后自动弹报告窗口 |
| MCP | `graph.validate.start/state/report/cancel`（LiveCommandServer）+ `editor_graph_validate` 等工具 | 阻塞编排工具内部 start→poll→report |
| 程序 | `run_validation(graph, options)`（同步） | `PlayerBootstrap.dry_run` 与无头测试使用 |

**离线 `validate_graph` 已弃用**（`Utils/User/NodeEditor/mcp_server.py` 仅返回指引）；agent 干跑验证需要引擎运行中。

## 2. 输入源

| source | 取图方式 | 典型用途 |
|---|---|---|
| `"canvas"`（默认） | `NodeCanvas.to_dict()` 快照（深拷贝序列化） | UI 按钮 / 验证编辑器里的当前图 |
| `"graph"` | 直接传入 graph dict（含 `nodes`） | agent 生成图先验、导入前预检 |

scene 文件格式（`{"scene": {"node_graph": ...}}`）由 `extract_graph_data` 兼容（PlayerBootstrap 路径）。

## 3. 检查规则（L1 静态）

结构化条目：`{level: "error"|"warning", code, message, node_id}`。code 一览：

| code | level | 含义 |
|---|---|---|
| `empty_graph` | error | 无 nodes |
| `unknown_type` | error | 节点类型不在 `_TYPES` 注册表 |
| `missing_pin` | error | 实例 pin_ids 缺少模板引脚（标记 `optional` 的版本兼容 pin 除外；`NodeCanvas.from_dict` 加载时自动补齐） |
| `pin_collision` | error | Pin ID 全局冲突 |
| `link_endpoint` / `link_direction` / `duplicate_link` / `malformed_link` | error | 连线端点/方向/重复/结构错误 |
| `isolated_node` | **warning** | 孤立节点（可能是刻意保留 — 离线版为 error, 内化时降级） |
| `required_pin_unconnected` | error | 必连引脚（当前仅 `Branch.Condition`） |
| `gtec_pairing` / `siggen_pairing` | error | 设备 Init/Kill 强制配对（规则源: `graph_constraints.*_pairing_errors`） |
| `pool_pairing` / `pool_reference` | error | 设备池 Create/Kill 配对 + Add/设备引用池校验（`pool_pairing_errors` / `pool_reference_errors`） |
| `device_pin_unconnected` / `device_pin_source` / `device_multi_pool` | error | AddToDevicePool.device pin: 未连 / 来源非 Init*Device / 一设备多池连线（单池成员制） |
| `epoch_reference` | error | Epoch 数据集引用（Count/Clear/Save 的 epochs_name 未命中画布源 / 空名多源歧义） |
| `epoch_pin_unconnected` | error | EpochAppend 的 Data / Label 未连 |
| `bci_reference` | error | BCI 算法引用（Init/Train/Test 模型与数据集绑定 / TestCCA 频率组 <2 / load 缺 model_path） |

**静态有 error 时跳过干跑**（报告 `runtime.skipped=True`）；warning 不拦截（`ok` 只由 error 决定）。

## 4. 干跑语义（L2）

- fake-time: 默认 `dt=1/60`、`frames=360`（6s 模拟），逐帧 `trigger("OnFrameUpdate")`，前后触发 `OnGameStart` / `OnGameStop`；
- **确定性**: 开始时重置全局随机种子（`evaluators.math.seed_global_rng(seed)`, 默认 0）——同图同参 → 同日志；
- **副作用隔离**: `ExecutionContext.dry_run=True`（设备走 stub 后端、实体/IO 副作用转 emit_log）；
- **会话隔离**: 干跑中的设备会话统一 `dryrun#` 前缀（`evaluators/gtec.py`）；设备池共用同一命名空间（`evaluators/device_pool.py`），任务结束自动 `kill_device` + `destroy_pool` 清理；
- **取消**: `cancel_event` 帧间检查 → 报告 `state="cancelled"`；
- ExitGame 被触发时提前收敛（记录 `exit_game_frame`）。

## 5. 任务模型（ValidationService）

- **单活动任务**: 运行中再 start → `{started: False, busy: True, task_id}`（不排队）；
- worker 线程执行（不占用主线程/逻辑线程）；`state()` 返回 `{task_id, state, phase, progress}`；
- 报告内存留存**最近 5 份**（超限淘汰最旧）；
- 线程纪律：任务记录/报告访问全部经 `threading.Lock`（free-threading 无 GIL）。

## 6. 报告格式（UI / MCP / 文件三端同构）

```json
{
  "task_id": 3, "state": "done", "ok": true,
  "options": {"frames": 360, "dt": 0.016667, "seed": 0, "verbose": true},
  "graph": {"nodes": 141, "links": 180, "hash": "sha1:xxxxxxxxxxxx"},
  "static": {"errors": [], "warnings": []},          // 条目数组（结构化）
  "runtime": {"errors": [], "skipped": false, "frames_simulated": 360,
               "total_events": 1234, "events_by_type": {...}, "cancelled": false,
               "killed_sessions": [], "log": [...]},
  "counts": {"errors": 0, "warnings": 0, "log_lines": 1234},
  "timing": {"started_iso": "...", "finished_iso": "...", "duration_ms": 48.2},
  "log": [{"frame": 0, "node_id": 5, "node_type": "Print", "action": "print", "detail": "42.0"}]
}
```

- `ok = (state=="done") and 无静态 error and 无运行时 error`；
- 落盘: `save_path` 以 `.txt` 结尾 → 人类可读文本（含事件日志全文）；其余 → JSON；
- MCP 回传时 `log` 超过 500 条会截断并附 `log_truncated/log_total`（完整日志用 `save_path` 落盘）。

## 7. UI 行为（Node Editor 面板）

- 工具栏 `Validate` 按钮: 运行中显示 `Validating… N%`（读服务 state）；完成后按钮旁显示 `OK (nw)` / `nE/nW` 徽标 + `Report` 按钮；
- 报告窗口（非 modal）: 汇总行 + 错误/警告条目（**点击条目 → 画布选中并居中该节点**）+ 事件日志折叠段 + Copy summary / Export .json；
- **UI 与 MCP 共见**: 任一入口启动的任务，另一端可见（同一服务实例）。

## 8. 图导入导出（GraphIO）

| op | 行为 |
|---|---|
| `graph.export {path?, include_rules?, inline?}` | `canvas.to_dict()`（含 `_rules` 规则文档）→ 返回完整 JSON + 可选落盘 |
| `graph.import {graph\|path, validate_first=true}` | 先静态检查（有 error → `imported: False` + `static_errors` 返回, 拒绝导入）；通过后替换画布内容（原地清空+拷贝, 等同面板 Import） |

UI 面板 Import/Export 按钮与新 op 并存（面板现有实现行为一致：Import 无静态门禁，如需门禁优先用 MCP op 或先 Validate）。

## 9. 测试与基线

```powershell
# 校验服务专项（29 项: 静态规则 / 干跑 / 任务流 / 忙拒绝 / 取消）
.venv-py314t\Scripts\python.exe Test/Application/NodeGraph/test_graph_validation.py
# 回环套件 v4 段（60 项全套: 含 graph.validate.* / report 落盘 / 受控错误）
.venv-py314t\Scripts\python.exe Test/Application/Editor/test_live_command_server.py
# 实机 E2E（需 startup.bat）: 打开 MI-SSSEP 工程 → 切场景 → 干跑校验 → 导出/回灌
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_mcp_validate_mi_sssep.py
```

## 10. 扩展指引

- **新增静态规则**: 在 `checks.py` 加检查段（沿用 `_entry(level, code, message, node_id)`），如有配套约束放 `graph_constraints.py`；
- **新增干跑选项**: `service._default_options` 白名单 + `run_validation` 传递（`frames/dt/seed/verbose` 现有四项）；
- **算法章节预留钩子**: 算法契约验证（`AlgorithmBase` 合规检查）后续作为新 checker 接入 `static_check_graph` 或独立子检查，报告结构复用本文 §6。
