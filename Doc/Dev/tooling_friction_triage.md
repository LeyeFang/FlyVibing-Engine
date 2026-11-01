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
| C5 | 未知节点类型只在加载时 WARNING，链路静默断掉 | `NodeCanvas.unknown_node_types` + `SimulationController.play()` 硬预检（`sim.play` 返回 `preflight_failed`；`force=true` 强跑） | `Core/NodeGraph/canvas.py` + `SimulationController` |
| F1 | `dist/*.whl` 与 site-packages 装的是旧构建，静默遮蔽源码 | 清理过期副本，`.pth` 指向源码；重建 0.6.1 发布包 | `scripts/release_tools.py` + venv |

## 10.2 已补文档（第二批）

| 编号 | 缺口 | 落点 |
|---|---|---|
| B1 | `entity.transform` 数组顺序被误读成 `(x,z,y)` | op 帮助 + `extdev/node_development` §8.5（op=编辑器坐标，`.scene`=GL） |
| B2 | `entity.add` 有选中即变子级只写在 `ops` 列表 | `node_development` §8.4 + op detail（`parent="none"`） |
| B4 | 渲染状态被别的每帧链覆盖 | `node_development` §8.3 |
| B5 | `.scene` 结构无文档（dict/`position_*`+`local_pos_*`/pin id ↔ 引脚名） | **新主题** `dev/scene_format` + 引擎 stub `Doc/Dev/scene_format.md` |
| C2 | `probe` 不在 ops 目录 → 靠猜发现 | `dev/editor_live_protocol` §5（CLI 子命令清单 + probe 用法） |
| C4 | `capture` 与 `probe` 是否同一 framebuffer 无说明 | 同上（共用 `fetch_raw_frame`，顶左坐标系） |
| F2 | `engine-editor-cli.exe` 不在 PATH | README「CLI on PATH」+ 发布包 `engine-cli.cmd` / `engine-cli.sh` |
| F3 | 开发态/发布态扩展扫描根不同 | `extdev/extension_dev_protocol` §3.1（junction vs 安装包 allowlist、`unknown_type` 硬拦） |

## 10.3 仍待办

| 编号 | 事项 | 说明 |
|---|---|---|
| C3 | `probe editor` 采样全透明 | 已写排查路径（`renderer.snapshot.viewport` 核对 + 窗口最小化）；若复现需查 editor framebuffer 读回时机 |
| C6 | 干跑看不到设备侧错误 | `console.tail` 已可用；后续在 validate 报告里附 warning/error 摘要 |
| C7 | `ext.<id>.status` 只反映面板 | 扩展侧语义问题（面板 vs 节点图会话），由扩展拆分 `panel:` / `sessions:` |
| E4/E5 | props 切片批量套 / 节点输出不跨帧 | 已写入 `dev/scene_format` §6 与 `node_development` §8 |
