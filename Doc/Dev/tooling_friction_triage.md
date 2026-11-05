# 工具链摩擦治理（社区反馈 2026-11-01）

来源：`Phase-Encoded-SSSEP-MI-FlyVibing-Extension/doc/tooling_friction.md`
（扩展作者在线闭环集成时记录的 20+ 条摩擦）。分诊结论：**真设计缺陷优先修，
文档缺口进第二批**，用户用法问题回文档而不是改行为。

## 10.1 已修（设计/打包缺陷）

| 编号 | 缺陷 | 处置 | 落点 |
|---|---|---|---|
| A1 | 每次 CLI 调用都往 stderr 喷 `pydantic_settings` 警告 | 导入期按消息过滤该警告（不动引擎） | `engine_editor_mcp/__init__.py` |
| A2 | 错误只走 stderr，用户 `2>$null` 后"命令成功、输出为空" | 失败回执写 **stdout JSON**（`ok/error/detail/suggest`），stderr 只留人读文本；退出码 0/1/2 | `cli.py::_fail` / `cmd_call` |
| B6 | `help graph.link` 的示例 `{"k":1}` 照抄即报错 | `OpSpec.example` + json 参数优先用参数文档里的字面量 | `ops.py` |
| B3 | `scene.switch` 被当成"保存+加载"，手改 JSON 后改动被内存态覆盖 | 明确"**不写盘**"，新增 `reload=true` 从磁盘重读 | `LiveCommandServer._op_scene_switch` |
| C1 | `entity.list` 不返回位姿，16 个实体 = 17 次调用 | `with_transform=true` | `LiveCommandServer._op_entity_list` |
| C2 | `probe` 不在 `ops` 目录 → 只能靠猜发现 | `ops` 尾部新增「非 op 通道」（全部 CLI 子命令）+ 主题 `help probe` / `help exitcodes`；守卫锁定 | `ops.py::CLI_COMMANDS` / `TOPIC_HELP` / `cli.py` |
| C3 | `probe editor` 恒返回全透明（1600x900） | **未能复现**（新构建逐点取到真实像素）；不沉默化：引擎帧末判 `blank`，`probe` 自动重抓（默认 3 次）+ stderr 说明，`capture` 同样透出 | `FrameCaptureSlot` / `Engine._maybe_capture` / `cli.cmd_probe` |
| C5 | 未知节点类型只在加载时 WARNING，链路静默断掉 | `NodeCanvas.unknown_node_types` + `SimulationController.play()` 硬预检（`sim.play` 返回 `preflight_failed`；`force=true` 强跑） | `Core/NodeGraph/canvas.py` + `SimulationController` |
| F1 | `dist/*.whl` 与 site-packages 装的是旧构建，静默遮蔽源码 | 清理过期副本，`.pth` 指向源码；重建 0.6.1 发布包 | `scripts/release_tools.py` + venv |

## 10.2 已补文档（第二批）

| 编号 | 缺口 | 落点 |
|---|---|---|
| B1 | `entity.transform` 数组顺序被误读成 `(x,z,y)` | op 帮助 + `extdev/node_development` §8.5（op=编辑器坐标，`.scene`=GL） |
| B2 | `entity.add` 有选中即变子级只写在 `ops` 列表 | `node_development` §8.4 + op detail（`parent="none"`） |
| B4 | 渲染状态被别的每帧链覆盖 | `node_development` §8.3 |
| B5 | `.scene` 结构无文档（dict/`position_*`+`local_pos_*`/pin id ↔ 引脚名） | **新主题** `dev/scene_format` + 引擎 stub `Doc/Dev/scene_format.md` |
| C4 | `capture` 与 `probe` 是否同一 framebuffer 无说明 | `dev/editor_live_protocol` §5 + **实测核对**（同坐标 PNG 像素 == probe RGBA） |
| F2 | `engine-editor-cli.exe` 不在 PATH | README「CLI on PATH」+ 发布包 `engine-cli.cmd` / `engine-cli.sh` |
| F3 | 开发态/发布态扩展扫描根不同 | `extdev/extension_dev_protocol` §3.1（junction vs 安装包 allowlist、`unknown_type` 硬拦） |

## 10.3 仍待办

| 编号 | 事项 | 说明 |
|---|---|---|
| C6 | 干跑看不到设备侧错误 | `console.tail` 已可用；后续在 validate 报告里附 warning/error 摘要 |
| C7 | `ext.<id>.status` 只反映面板 | 扩展侧语义问题（面板 vs 节点图会话），由扩展拆分 `panel:` / `sessions:` |
| E4/E5 | props 切片批量套 / 节点输出不跨帧 | 已写入 `dev/scene_format` §6 与 `node_development` §8 |

## 11. 第三方 ISSUE 2026-11-03（两份）

来源: `Phase-Encoded-SSSEP-MI-FlyVibing-Extension/doc/ISSUE_20261103_*.md`。

### 11.1 材质引用 id 跨会话漂移 → 静默变白（**核心侧设计缺陷，已修**）

根因：`material_id` 是**会话级自增**计数器，却被写进 `.scene` 当持久化身份。
任何让 id 空间变化的路径（旧 `.myproj` 缺 `material_id`、会话里先开过别的工程、
内置材质被重复注册、手改场景）都会让实体拿到“存在但不对”的材质 —— 渲染成默认白，
没有任何提示。

处置（三件套）：

| 层 | 修复 |
|---|---|
| 数据 | `MeshRenderer.material_path`（`builtin://名称` 或文件路径）随场景保存；加载时 `Scene._resolve_material_ref` 解析回**本会话** live id（精确路径 → 文件名唯一回退） |
| 幂等 | `ResourceManager.Init()` 加 `_initialized` 守卫：内置材质只注册一次，杜绝 Default/DefaultLit 二次注册位移 id 空间 |
| 可观测 | 解析失败 → `scene.reference_warnings`；`project.open` 新增 `reference_audit`（`missing_materials` / `missing_meshes` / `unresolved_refs`）并打印点名清单 |

验证：`Test/Application/Core/test_scene_material_refs.py`（13 项，含“故意换一套 id 再加载”的自愈断言）
+ 实机：`Examples/MI` → 示例工程 连开，`reference_audit` 干净、引用正确。

未采纳的建议 C（场景改存资源路径/UUID）：`material_path` 已经是“路径 + 兼容回退”的最小形态，
不再需要改 schema；如果后续要做工程 UUID 命名空间，再另行立项。

### 11.2 扩展被禁用 → PIE 起不来（**一半是核心侧，一半是扩展侧**）

核心侧（已修）：

| 问题 | 修复 |
|---|---|
| `extension.enable` 后画布仍缓存 unknown → 只 enable 不重载场景还是起不来 | `NodeCanvas.refresh_unknown_types()` + `rehydrate_unknown()`；`ExtensionManager.enable` 成功后自动调用，回执带 `rehydrated_nodes` |
| 预检读的是画布缓存，可能误报 | `SimulationController.preflight_problems()` 先 `refresh_unknown_types()` 再判定 |
| hint 只有自然语言 | problems 增 `owners` + `fix`（可复制命令）+ `auto_fix`；`sim.play auto_fix=true` 一键 enable→补全→启动 |
| `force=true` 只警告一次 | `sim.state.forced_unknown_types` 持久可见 + 运行期每 ~300 帧提醒一次 |
| 打开工程时不知道依赖哪些扩展 | `project.open` 旧 `missing_extensions`（从节点 `ext.<id>.` 前缀派生，不改 `.myproj` schema） |
| 停用画布在用的扩展时无提示 | `extension.disable` 回执带 `unresolved_nodes` + 控制台警告（含面板 X 触发的停用） |

扩展侧（**需扩展作者决策**，宿主默认值不是这个）：
`ctx.ui.register_window(close_policy=...)` 默认 `"hide"`；内置设备扩展把 Monitor 面板
设成了 `"disable"` —— 于是“关掉面板”＝“停用整个扩展”，并持久化到下次启动。
设备类扩展应改用 `"hide"`（面板只是视图，节点依赖扩展持续运行）。
纪律已写进 `extdev/extension_dev_protocol` §3.2。

验证：`Test/Application/Core/test_canvas_unknown_types.py`（10 项）+ 实机：
禁用扩展 → 重载场景 → `sim.play` 被拦（带 owners/fix）→ `sim.play auto_fix=true` → Running。
