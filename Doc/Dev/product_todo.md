# 产品待办 — 扩展剥离 / 节点编辑器 UX / 1.0 与 macOS

> 状态：活文档（2026-10-21 建立）。记录“现在不做但别忘”的事项；完成一项就改状态并留验收证据。
> 测试体系待办另见 `Doc/Dev/test_map_todo.md`。

## 1. 流程与 CI（暂缓）

| 事项 | 状态 | 说明 |
|---|---|---|
| GitHub Actions PR 门禁 | **暂缓** | 团队规模小、测试面仍在变；先把本地 `test_runner --tier core` 用顺 |
| 本地 pre-push 快检 | 可选 | `test_map.py check` + `ui check` + `core` 即可；不要阻塞小团队节奏 |
| 重新评估 CI 的信号 | 待触发 | ≥2 名常态维护者 / 外部 PR 增多 / 需要夜间 GUI 回归 / 发布节奏固定 |
| 社区扩展仓库治理 | **不接管** | 我们只保证引擎侧扩展 API、审查器和文档；社区自己的 Git 仓库由他们负责 |

> CI 方案已在上轮讨论：PR 跑 `guards + core`，GUI nightly/self-hosted；不要在团队小、测试未稳时引入高协调成本。

## 2. BCI Algorithm / Virtual Device 出核心

| 事项 | 状态 | 验收 |
|---|---|---|
| BCI 求值器迁入扩展 | **已完成** | `evaluator.py` / `evaluator_epoch.py`；核心不再 import |
| Virtual 求值器迁入扩展 | **已完成** | `evaluator_siggen.py` / `evaluator_pool.py`；核心不再 import |
| BCI 扩展壳 + ops | **已完成** | `extension.py`；`ext.bci.status/models/datasets` |
| 交接书 | **已完成** | `Application/Functions/BCIAlgorithm/HANDOFF.md`；`VirtualDevice/HANDOFF.md` |
| 通用规则注册 API | 待做 | 把 `graph_constraints` 的 BCI/Epoch/DevicePool 规则迁到扩展注册 |
| 通用 dry-run cleanup hook | 待做 | 核心不再直接 import BCI/Virtual 清理函数 |
| Runtime cleanup hook | 待做 | `GameRuntime` / `PlayerBootstrap` 不再知道具体设备扩展 |
| 物理独立仓库/包 | 待做 | 引擎只保留 manifest 发现路径；`export` 清单明确 |
| 扩展自测迁移 | 部分 | BCI 35/35、Virtual 119/49/29；`test_bci_empty_data` 仍在归档 |

## 3. 节点编辑器 UX

> 推进顺序：**节点编辑器系统收口 → BCI Algorithm → Virtual Device**。

### 3a. 节点组拖动 / 重排 / 嵌套

| 事项 | 状态 | 验收 |
|---|---|---|
| 组框可拖动 | **已完成** | 拖动 group frame → 整棵成员子树平移；`node_groups_smoke` 覆盖真实 NodeId 拖动 |
| 组感知 Rearrange | **已完成** | `group_layout.py`；组是外层布局单元，父组包住子组，节点连到组时相邻排开 |
| 组内重排 | **已完成** | 组内递归布局；`Rearrange Group` + `Fit Group`；父组自动回流 |
| 嵌套组编辑 | **已完成（首版）** | Groups 窗口显示 parent/children 树；选中子组可单独重排 |
| 组创建/删除/改父子关系 GUI | **已完成** | 多选右键 Merge；右键组框 / Groups 窗口 Ungroup·Destroy；Destroy 全删成员节点；改父子关系仍由 tools |
| 组框缩放手柄 | **已完成** | 右下角 `+` 手柄实时缩放；节点 position 按比例移动；`min_box` 限制不能缩到成员包围盒 + margin 以下；`node_group_actions` 覆盖放大与下限 |
| 组成员增删 GUI | **已完成** | 节点拖入组框 → 加入 `members` 并只扩不缩；拖出 → 移出并收紧剩余成员；`_apply_node_drop` + `node_group_actions` 覆盖 |
| 组框命名 | **已完成** | Groups 窗口 `Group name`、右键 `Rename Group`、双击标题内联编辑 → `rename_group` 同步 `node_groups[gid].alias`；重名拒绝 |
| 组描述 | **已完成** | Groups 窗口 `Description` 输入框、双击描述行内联编辑；标题行 `Description/Hide` 按钮与普通节点一致，默认展开；空描述有浅色占位 |
| 示例工程组重整 | **已完成（1.0.0）** | `refresh_examples.py` 为 MI/RestingState 写入组描述、box、GroupStart/End；RestingState 新增 `@resting_block` 嵌套 `@open_phase/@closed_phase/@cycle`；`test_examples_catalog` 断言组视觉元数据 |
| 组 exec in/out | **已完成（2026-10-23 修订）** | 每组自动维护真实 `GroupStart`/`GroupEnd` 普通节点（仅 exec_out / exec_in）；编辑器渲染为组框左右端口槽内的 `Group entry/exit` pill，pin 内容带 `●` 并用 pivot 对齐外缘；随组创建、布局、删除；不隐藏成员 Pin、不写 slots，入口可自由拖到任意成员；`e2e_node_group_live` 用真实鼠标验证 |
| 组框配色 | **已完成** | 中性浅灰底 + 浅灰描边；当前组用金色描边强调；不再用天蓝色 |
| 多选节点 | **已完成** | Shift+click 累加；框选用屏幕矩形命中，只选真实节点，不选组框 |
| 右键合并/拆分/删除 | **已完成** | 单选节点 → Delete Node；多选 → Delete Nodes / Merge；组框 → Rename / Edit Description / Ungroup / Destroy；空白无选择 → 浅色 No selected node |
| Groups 窗口动作 | **已完成** | Ungroup / Destroy Group；Destroy 删除组框、子组和全部成员节点 |
| 组操作 CLI | **已完成** | live `graph.group.*`；离线 `group-merge/ungroup/delete` + `apply-ops` |

### 3b. 节点查询窗口与 ImGui ID

- [x] 列表项使用稳定 ID（nid/gid/idx）—— 不再用显示文本作为唯一 ID
- [x] 多选/框选/右键组菜单（`node_group_actions` 场景）
- [x] 未命名节点显示 `#<nid>`；同显示文本仍可区分
- [x] `ui_protocol.md` §2 增加“稳定 ID 纪律”
- [ ] AST 静态守卫：`selectable/menu_item` 在循环内缺少 `##<stable-id>` 时报警
- [x] “乱码”定位：真实工程 157 节点 / 129 无名 / 0 非 ASCII alias·description·props；
      画布缩放过小导致文字退化为不可读像素，不是字体图集或编码问题（Fit All / 滚轮放大即可）
- [x] Import 整体替换后自动 fit（对准新图）
- [ ] 工程/场景首次载入后的自动 fit（保留上次视图，但过小缩放会被启动清理）


| 事项 | 状态 | 验收 |
|---|---|---|
| Find Node 窗口 | **已完成** | 工具栏 Add 同级；搜索 alias/type/label/description；`node_editor_find` 13/13 |
| Go To | **已完成** | `center_node_on_screen`（API 缺失回退 `navigate_to_selection`） |
| Delete | **已完成** | 删除选中结果并清理连线 |
| 快捷键 / 过滤类型 | 待做 | 例如 Ctrl+F、仅看当前组、仅看未命名 |
| 模糊匹配 / 拼音 | 待做 | 当前为大小写不敏感 token 子串匹配 |

### 3c. 适配视图（Fit）

- **结论：保留**。实现是 `imgui_node_editor.navigate_to_content()`，把全部节点/组框缩放进视口；用于全景检查和截图。
- 已加 tooltip（`node_editor.fit_tip`）；`node_editor_smoke` 覆盖调用路径。
- 若未来增加“适配当前组”，使用 `Fit Group`（已实现，选中组成员后 `navigate_to_selection`）。

### 3d. 面板布局 / 点击命中 / 卡片信息

| 事项 | 状态 | 验收 |
|---|---|---|
| DockSpace 占满菜单栏下空间 | **已完成** | 宿主 `DEFAULT_DOCK_RIGHT_FRACTION = 1.0`；右侧拆出 `DEFAULT_PANEL_DOCK_FRACTION = 0.30` 列，Scene / Resources / Node Editor 默认以标签页停靠，左侧显示 3D 视口 |
| 框选/组框命中坐标 | **已完成** | `canvas_to_screen` 只在 `ne.begin/end` 内可靠；绘制帧缓存节点/组框屏幕矩形。★ 节点编辑器内 `get_mouse_pos()` 返回画布坐标，已统一缓存为 `_mouse_screen` 后再与屏幕矩形比较；组框内部是“洞”，只有标题/边框参与命中，组内空白可正常框选 |
| 组标题位置 | **已完成** | 按官方顺序标题先画、`Group(size)` 后画；标题贴在组框上沿，不再用 `set_cursor_pos` 按窗口坐标漂到画布空白处。`node_group_actions` 断言标题矩形落在组框上沿 |
| 组图 Fit 时机 | **已完成** | `graph.fit` 延后到 `_draw_nodes()` 之后，等组框 `SetGroupSize` 写入本帧原生尺寸再 `NavigateToContent()`；新导入组不再缩成极小视图；`test_e2e_node_group_live` 覆盖 |
| 点击目标节点 / 框选误选 | **已完成** | 框选起点必须位于 `_canvas_rect` 内；工具栏/3D 视口点击不再产生陈旧起点；`node_group_actions` 覆盖“视口点击 → 画布空白点击不误选” |
| 面板缩放不拖动节点 | **已完成** | 组框位移仅在左键按住且指针在组框内时解释为拖拽；窗口 resize 不再平移成员 |
| 面板横向 resize 不缩放节点 | **已完成** | 节点编辑器 `CanvasSizeMode.center_only`；实测 docked/floating 宽度 468→761，zoom=0.9336 与节点屏幕宽度 121.1 均保持不变；GetTime 的 combo item width 显式钳制 110–220px（不再取面板可用宽度），GetTime 卡片宽度保持 79.2px |
| 实机 UI 输入注入 | **已完成** | live ops `ui.mouse` / `ui.mouse_button` / `ui.click` / `ui.drag` / `ui.wheel` / `ui.key`；在 backend `new_frame` 后注入并同步 GLFW 光标/焦点；`ui.panel` 返回 Node Editor view 诊断（`canvas_rect` / 节点/组框矩形 / `context_open` / `context_kind`）。节点编辑器诊断不再在渲染帧外调用原生 `get_selected_nodes()`（无 editor context 会崩溃），改用纯 Python 选择快照；`test_node_graph_gestures_live` 覆盖拉框、右键拖拽、右键菜单 |
| 卡片说明文字 | **已完成** | 移除卡片底部浅色 `props_text`；默认写入 `NodeInstance.description`，在 Description 展开区编辑 |
| 提供者签名 | **已完成（2026-10-29）** | 节点卡标题下灰色 `@Official` / `@Author`（`NodeTypeDef.signature`；核心/官方 pack 默认 `@Official`，运行期 pack 默认 `@Community`）；Example 菜单显示 `名称 @Provider`，社区示例从 `%APPDATA%/FlyVibingEngine/examples` 读取，不写主线 `Examples/` |
| 面板代码拆分 | **已完成** | `panel.py` 约 1000 行（原约 1860）；选择/组菜单/组窗口/IO/Find/Validate 拆为独立 mixin 模块 |

## 4. FlyVibing 1.0.1 Release

| 事项 | 状态 | 说明 |
|---|---|---|
| 版本号 / 品牌收口 | **已完成（1.0.1）** | `pyproject.toml` 与 `installer.iss` 版本统一 1.0.1；`AppIdentity`/窗口标题保持 FlyVibingEngine |
| Release 内容冻结 | **已完成** | core **69/69**、GUI **7/7**；节点组、示例、安装器改动已入本版 |
| 安装器 / 导出成品 | **已完成** | `Utils/Dev/Installer/dist/releases/v1.0.1/windows-x64/`；安装器 `FlyVibingEngine-Setup-1.0.1-Windows-x64.exe`（约 206 MB），内置 runtime、wheelhouse、工具链与 `Examples/` |
| Release notes / 兼容矩阵 | **已完成** | 根目录 `CHANGELOG.md`（中英）；Windows 10/11 x64、Python 3.14t、`engine-editor-mcp` 0.5.x / `flyvibing-node-editor` 0.1.x |
| 发布后回归 | **部分完成** | 已完成 staging 内置 runtime 导入、两个示例 `--dry-run`、安装版编辑器启动/打开 MI；干净机安装待执行 |

## 4.1 FlyVibing 1.0.2 Release（2026-10-31）

| 事项 | 状态 | 说明 |
|---|---|---|
| 版本号收口 | **已完成（1.0.2）** | `pyproject.toml` / `installer.iss` / 根目录 `CHANGELOG.md` 统一 1.0.2 |
| 工具链对齐 | **已完成** | `engine-editor-mcp` 0.6.0、`flyvibing-node-editor` 0.1.1、`flyvibing-extension-kit` 0.1.1；安装包内置同一组 wheel |
| Release 内容冻结 | **已完成** | core **77/77**（含 SaveData / GameRuntime input / 节点图手势）；本版含设备免停止保存、通用 File IO `SaveData`、Runtime 输入系统、右键菜单手势语义 |
| 安装器成品 | **已完成** | `Utils/Dev/Installer/dist/releases/v1.0.2/windows-x64/`：`FlyVibingEngine-Setup-1.0.2-Windows-x64.exe`（约 213 MB），`CHECKSUMS.sha256` 与 `release-manifest.json` 已生成 |
| 发布后回归 | **部分完成** | staging 内置 runtime 已能导入工具链与节点注册表（83 类型）；live 手势回归、干净机安装待执行 |

## 5. macOS 适配与发布（1.0 之后）

| 风险 | 说明 | 先验证什么 |
|---|---|---|
| OpenGL / GLFW | macOS 对 OpenGL 已弃用；当前渲染后端是 GL | 先跑最小 GLFW 窗口 + 现有 shader；评估 Metal 后端成本 |
| free-threaded Python | 3.14t 在 macOS 的轮子可用性 | `uv python install 3.14t` + numpy/scipy/pillow/imgui_bundle 安装矩阵 |
| 字体 | `Locale/*.json` 声明 msyh/PingFang；Linux/mac 回退 | 中文 UI 无 `?`；字体候选按 `_meta.fonts` 增量 |
| 路径/大小写 | Windows 反斜杠、junction、盘符 | 全仓路径审计；`Utils/ExtDev` 符号链接替代 |
| 设备 SDK | 厂家 SDK/串并口驱动的平台差异 | 虚拟设备先通；真实品牌按 macOS SDK 单独评估 |
| 打包 | 安装器 / runtime 镜像 / wheelhouse | 先在 macOS 源码运行；再决定 .app / dmg |
| CI | 无 macOS runner 时至少本地脚本 | 先做 `startup.sh` + `test_runner --tier core` 的 macOS 冒烟 |

> 原则：**先让源码在 macOS 跑起来，再谈发布**；不要在没有真实 macOS 回归前承诺 Release 可用。

## 6. 规范与压力测试改进方向（竞态事故复盘）

这次 `dictionary changed size during iteration` 不是单点 bug，暴露了三个缺口：

1. **共享状态的读写契约不完整**：`SceneManager.entities` 等注册表有多个线程读者/写者，
   但没有“谁可以写 / 谁必须快照 / 锁只保护什么”的矩阵。
2. **压力测试缺“并发场景”维度**：现有 core 主要测功能正确性，没有把
   `project.open / scene.switch` 与 `TextSystem.tick / UI 扫描` 交错执行。
3. **UI ID 与显示身份混用**：节点 alias / label 是人类标签，不是唯一键；ImGui 控件必须用 nid/gid。

建议按以下顺序收口：

| 优先级 | 改进 | 验收 |
|---|---|---|
| P0 | 为 SceneManager/ThreadRegistry/Executor 等共享表补“写者/读者/锁/快照”矩阵 | 文档 + 静态扫描 |
| P0 | 禁止遍历实时注册表：统一 `entity_ids_snapshot()` 一类 API | 代码评审 + grep 守卫 |
| P1 | 增加确定性竞态测试：Barrier 控制 writer 在 reader 迭代中插入/清空 | `test_registry_race.py` |
| P1 | `--stress N` 场景：N 轮 project.open → scene.switch → tick → 查询 | runner 失败即留线程时间线 |
| P1 | UI 稳定 ID AST 守卫（循环内 selectable/menu_item 必须有 nid/gid/idx） | 新 core 守卫 |
| P2 | 把并发场景纳入夜间/自托管 runner（不要在普通 PR 门禁里跑重压力） | nightly 报告 |

> 原则：**锁只保护内存结构，不跨 IO/GL/阻塞调用**；读者要么拿锁复制快照，要么完全不加锁地读不可变数据。
> 不要用“多跑几次没复现”代替确定性交错测试。

## 7. 稳定性修复记录

| 日期 | 问题 | 处理 |
|---|---|---|
| 2026-10-21 | 手动加载 MI-SSSEP 工程时 `TextSystem.tick` 抛 `dictionary changed size during iteration` | `SceneManager` 增加实体注册表 RLock + `entity_ids_snapshot()`；SceneSync / EntityManager / PrefabManager / EditorHost / EditorLayer / SimulationController 的写入与迭代统一走锁；`test_scene_manager` 增加并发快照回归（52 checks） |
| 2026-10-21 | `startup.bat` 在 PowerShell 下出现 `'al'`/`'hon'` 等碎片命令错误 | 文件由 LF-only 转为 CRLF；`startup.bat` 启动输出已验证干净 |
| 2026-10-27 | 物理显示器拔除、向日葵远程直连时，编辑器/PIE/导出成品窗口看似全白 | **环境呈现问题，非引擎回归**；独立 GLFW 探针前缓冲为绿色、系统截图为白色；归档 `remote_display_white_screen.md`，不改渲染/场景/导出逻辑 |
| 2026-10-29 | 安装包 staging 复制本地扩展 fixture；游戏导出与安装包误共用 `export:false` 语义 | 安装包改用 `Application/Functions/official_extensions.json` mainline allowlist；游戏导出改为场景节点按需 + `export:false` opt-out；`test_release_layout.py` / `test_export_extension_scope.py` 锁定两条策略，避免错杀官方扩展或漏掉本地 fixture |
| 2026-10-29 | 扩展无法创建/检索自己的节点并刷新 GUI（设备扩展反馈） | `ctx.graph` 增加 `owned_nodes` / `find_type` / `add_node` / `update_node` / `set_props` / `replace_props` / `remove_node` / `add_link` / `remove_link` / `request_redraw`；默认限制本扩展 owner；`NodeCanvas.revision` 驱动面板缓存失效；`test_extension_graph.py` 覆盖 |
| 2026-10-30 | 扩展自带 Example 在 `File ▸ Open Example` 不可见，作者只能复制到用户目录并自行判重/清理 | 新增 `ExtensionExamplesRegistry`：扩展 enable 时自动登记 `<extension_dir>/Examples`，disable/unload 自动移除；manifest `provider` / `.myproj.provider` 决定签名；声明 `capabilities:["examples"]` 注入 `ctx.examples.register/unregister` 支持额外只读根目录；宿主不复制、不覆盖用户示例；旧式 `.injected.json` 副本在源根注册时去重；`test_extension_examples.py` 覆盖 |
| 2026-10-31 | 图内无法在录制中途保存数据，无法用 GetData 与落盘标签互证（设备/信号处理扩展反馈） | `RecordingSession.save` 支持 `elapsed_s/pump/tag`（保存前 pump、微秒+序号唯一路径）；门面 `save_record`、节点 `SaveDeviceData`（Path/MetaPath/Samples/Duration/Written/Ok）、agent op `device.save` 共用实现；兼容旧式 `save(scope)` vendor（先 `get_data` pump）；`test_device_save.py` 覆盖 |

## 8. 运行时场景 / 游戏内 GUI / 输入（默认方案已预设，待复核）

> 详细设计稿：`runtime_scene_ui_input_plan.md`（2026-10-27）。
> 用户已确认先做 Utils/B0（2026-10-29）；其余默认方案仍可复核，不阻塞 B0 开工。
> 拆成 **A 运行时场景生命周期** 与 **B 运行时交互层（GUI + 输入）** 两个工作流；GUI 与输入必须共用事件消费顺序。

| 事项 | 状态 | MVP 验收 |
|---|---|---|
| A1 `RuntimeSceneService` + 安全帧边界切换/清理 | 待开工（默认方案） | 无头测试：请求→替换→旧实体/GPU 清理；旧图停止、新图 `OnGameStart` |
| A2 `SwitchScene` 节点 + 相机/game_type/背景色/模板重建 | 待开工（默认方案） | 2D/3D/overlay 场景切换首帧相机正确；场景缺失可回滚 |
| A3 PIE/导出成品场景切换 e2e | 待开工（默认方案） | PIE 不污染编辑器；成品可见新场景且无旧实体残留 |
| B0 Utils 虚拟输入高层封装（鼠标/键盘/组合键、editor/PIE/game 目标） | 下一迭代（已规划） | agent 脚本可拖拽场景镜头、缩放/右键节点图；无手工点击 |
| B1 `UIWidget` + 屏幕空间 `UISystem`（button/label/panel/popup） | 待讨论（见 §10） | 无 ImGui 依赖；hover/pressed/click；PIE 截图 |
| B2 运行时输入队列 + `OnKeyPressed`/`OnMouseClicked` + UI 优先消费 | **输入队列/事件节点已落地**；UI 优先消费待 B1 | `RuntimeInputLayer` + `RuntimeInputFrame`；点击=原地释放（拖拽不触发）；`test_runtime_input` 覆盖键盘/鼠标/ESC；PIE/导出共用 |
| B3 Popup/modal + ESC 策略 + 焦点/禁用态 | 待开工（默认方案） | 弹窗拦截下层；ESC 先关弹窗；按钮禁用不可点 |
| B4 UI 实体进场景保存/加载 + 编辑器预览 | 待开工（默认方案） | UI 实体保存/加载往返；编辑器中可摆放；导出一致 |
| B5 两个官方 Example 的 ESC 退出 + 清理 | 待开工（默认方案） | MI/RestingState ESC 停止，无设备/媒体/GPU 残留；成品同语义 |
| B6 运行时 UI/输入测试、文档、示例 | **输入部分已落地**；UI/e2e 待 B1/B3 | `test_runtime_input` 已接入 core；`test_runtime_ui`/e2e 待补 |

### 默认决策（待复核）

1. 场景切换：设备/BCI 会话保留；场景变量、计时器、旧图状态重置；持久变量后置。
2. UI 架构：实体化 `UIWidget` + 屏幕空间 `UISystem`，不采用 imgui-bundle。
3. MVP 控件：`button/label/panel/popup`；文本输入、滚动视图、复杂布局后置。
4. ESC：保留“ESC 关闭窗口”安全网 + 工程开关；有 modal 时先关弹窗。
5. UI 坐标：先以 1920×1080 参考分辨率 + 像素偏移，后续再加自适应锚点。

## 9. Debug / 日志治理（2026-11-01 立项）

现状清单：`Doc/Dev/print_inventory.md`（由 `Utils/Dev/print_audit.py` 生成，
`test_print_inventory` 守新鲜度；当前 543 条裸 print，其中热路径 **49** 条）。

| 事项 | 状态 | 说明 |
|---|---|---|
| `EntityGet` 每帧 print | **已完成** | 成功路径静默（输出仍写 `Entity` 引脚）；仅干跑记一条结构化 `not_found` 日志 |
| 裸 print 盘点 | **已完成** | `Utils/Dev/print_audit.py` → `Doc/Dev/print_inventory.md`；新增/删除 print 必须带清单 diff |
| 热路径 print 收敛 | 待办 | `Core/NodeGraph/evaluators/**` + `Runtime` 循环层 → `ctx.emit_log`（干跑收集器）或节点级限流日志 |
| Settings ▸ Debug | **已完成**（2026-11-01） | `Core/Diagnostics/DebugEvents.py` 事件分类表（17 类）+ `RuntimeDebugLayer` 按勾选汇报/consume；面板页 Settings ▸ Debug ▸ Terminal（开关 + 全选/全不选 + 分组勾选）；`debug.events` op/CLI 读写同一状态 |
| 日志级别 | 待办 | `LogBus` 目前按文本启发式分级；后续 print 迁移时改为显式 `level` |

## 10. 运行期 UI 设计讨论（2026-11-04 立项，待决策）

> 与 §8 B1（`UIWidget` + 屏幕空间 `UISystem`）同一条线。本节只记录**待拍板的问题**与
> 无外部依赖实现的复杂度评估；讨论收敛前不动 B1 代码。

### 10.1 已收敛的判断

1. UI **做成组件**（带 UI 组件的实体 = 一个 UI 元素）方向正确；
   **不要**把 UI 组件强绑 `MeshRenderer` —— 后者是"世界空间网格 + 材质 + 受光"，
   UI 要的是屏幕空间矩形 + 锚点/枢轴 + 裁剪 + 排序 + 焦点，两套语义焊一起会互相污染。
2. 渲染走**独立 pass**（复用现有 overlay/sprite 批量机制），不进实体 pass。
3. 命中用**矩形数学**，不用 GPU pick：pick 只认网格轮廓（字母之间的空白也算命中），
   而 overlay 穿透要求"没画东西的地方必须穿过去"。
4. 键鼠事件**先给 UI**，UI 消费即 consume（B2 的 `RuntimeInputLayer` 已有队列/事件语义）。
5. 编辑器侧已有等价语义可参照：`io.want_capture_keyboard`（热键让路，见 `ui_protocol.md` §15）。

### 10.2 最小原语（覆盖 ~80% 游戏 UI）

| 层 | 原语 | 说明 |
|---|---|---|
| 绘制 | Rect / Sprite(九宫格) / Text / Bar / Clip(scissor) | 5 个原语足够拼积木 |
| 容器 | Linear(行/列 + 间距 + 对齐) / Scroll(裁剪 + 偏移) | 网格 = 线性 × 线性 |
| 交互 | Hover/Press/Click、Toggle、Drag(slider)、Popup、Focus(顺序) | 矩形命中 + 焦点栈 |
| 组合 | 按钮 = Rect + Text + 状态色；血条 = Rect + Bar；背包格 = 网格 + Icon + Text；对话框 = Panel + Text + 按钮组；设置页 = Tab + 控件 | 都不需要新机制 |

### 10.3 无外部依赖的复杂度（估算）

| 模块 | 量级 | 难点 |
|---|---|---|
| 批渲染 + scissor | ~200-300 行 | 排序 / 半像素对齐 |
| 文本（图集 + 度量 + 断行） | ~400-600 行 | **最大隐性成本**；CJK 字体大 → 需动态图集 |
| 布局（锚点 / 线性 / 网格 / 自适应分辨率） | ~300-500 行 | 边界 bug 多 |
| 命中 + 焦点 + 键盘导航 | ~200-300 行 | 与节点图抢键 |
| 滚动 / 裁剪 | ~150-250 行 | scissor 栈 |
| 文本输入（光标 / 选区 / ASCII） | ~400-600 行 | 需补 `char` 回调（`InputPipeline` 目前没有） |
| IME（中文） | ~200-400 行 + 调试 | `set_ime_position` + 预编辑串渲染 |
| 动画 / 主题 | ~150-300 行 | 纯插值 |

合计：展示层 **M0 ≈ 1.5-2k 行（2-3 天）**；交互 **M1 ≈ +1k 行（2 天）**；
文本输入 **M2 ≈ +0.5-0.8k 行（2-3 天）**；IME 另 1-2 天。成本主要在**文本与输入**。

### 10.4 待决策

| # | 问题 | 建议默认 |
|---|---|---|
| D1 | 组件粒度：单 `UIWidget` 带 type，还是 `UIRect + UISprite/UIText/UIButton` 组合？ | 组合（与 ECS / `MeshRenderer` 同风格） |
| D2 | 坐标：参考分辨率 1920×1080 + 缩放策略，还是像素直给？ | 参考分辨率 + `scale_mode` + 安全区 |
| D3 | 列表 / 滚动是否 M0 就要？ | 不要；实验范式先用固定条目数 |
| D4 | 运行期是否需要文本输入？ | **暂不需要**（输入都在编辑器参数/节点里）→ IME 后置 |
| D5 | UI 与 3D 内容层级：永远最上，还是可插入实体之间？ | UI 独立 pass 永远最上；世界空间 UI 另立项 |
| D6 | 编辑器里怎么摆 UI？ | 先 `UIRect` 数值字段 + 视口矩形叠加显示；gizmo 拖拽后置 |

### 10.5 里程碑

- **M0 展示层**：`UIRect` / `UISprite` / `UIText` + `UIPass` + 参考分辨率缩放 —— overlay / 2D / 3D 场景都能放文字和色块
- **M1 交互层**：`UIButton` / `UISlider` + 焦点栈 + 事件优先消费 + 与 overlay 穿透联动（UI 区域必须捕获）
- **M2 容器**：线性布局 + 网格 + 滚动/裁剪
- **M3 输入框（ASCII）** + `char` 回调；**M4** IME / 多行

### 10.6 风险

- 字体图集与 CJK（动态图集 / 按需纹理；现有 `Core/Text/TextSystem.py` 是"一行一纹理"，够 M0 不够列表）
- 半像素对齐与 DPI（编辑器侧已有窗口 DPI 换算经验可复用）
- 透明排序与覆盖层穿透的交互：`glfwWindow._is_click_through_target` 目前只看 pick 缓冲，UI 命中需并入
- 焦点与节点图抢键：UI 模态必须能吞掉 ESC（与 §8 默认决策 4 的 ESC 策略对齐）

### 10.7 暂停 / 模态 / 全屏覆盖（2026-11-04 待讨论）

**结论先行**：暂停菜单可以是 UI 组件；**暂停本身不能是组件**（它是全局运行状态）。

| 关注点 | 归属 | 理由 |
|---|---|---|
| 时间（`time_scale` / 暂停原因集） | 运行时服务 `RuntimeClock` | 多来源暂停（ESC / 设备掉线 / 节点要求等待 / 断点）需要仲裁，不能每个实体各持一份 |
| 输入模态 + ESC 策略 | `InputRouter` 焦点/模态栈 | 必须在节点图之前消费；ESC 走策略表而非组件行为 |
| 暂停菜单的呈现 | UI 组件（`UIPanel(modal=True, scrim=…)`） | 纯视觉 + 交互声明，可摆可测 |
| 全屏覆盖 | `UIPass` 的模态层 + overlay 强制捕获开关 | 窗口级 `WS_EX_TRANSPARENT` 是窗口状态，组件碰不到 |

**暂停作用域必须可配**（本领域硬约束）：BCI 实验中"暂停"通常意味着
**图/计时器/媒体停，设备采集与 epoch 不能停**（否则数据报废）。建议
`pause_scope = {graph, timers, media, device_io, render}` 逐项开关，写进工程设置。

**iframe 式技术债清单（把暂停做成组件/散落的 if 会踩的坑）**

1. 时间源分散 → 暂停后各系统 dt 不一致，实验时间戳漂移
2. 输入优先级 → 组件无法在节点图之前吞键
3. 窗口层行为（穿透/置顶/透明）组件不可达 → overlay 下全屏暂停菜单点不到
4. 生命周期耦合 → 组件随实体销毁；场景切换后暂停态丢失或残留
5. 多画布/多场景 → 每场景一份暂停态 → 双暂停、状态不一致
6. 存档/导出 → 暂停态被序列化进 `.scene`（下次打开仍是暂停）
7. 编辑器 vs 成品 → 同一组件被迫写 host 分支（PIE 的 ESC 是关窗口）
8. 扩展生态 → 第三方扩展也能暂停/全屏覆盖，需要审计与权限边界

**建议里程碑**：P0 `RuntimeClock`（`time_scale` + `pause_reasons` + scope 表，无 UI）→
P1 `InputRouter` 模态栈 + ESC 策略（并入 §8 B3）→ P2 依赖 §10 M1 的 `UIPanel(modal, scrim)` →
P3 主题 token（颜色/间距/字号不写死在组件里）→ P4 `SetPaused` / `OnPauseChanged` 节点 + 工程设置 + 审计日志。

### 10.8 组件清单、风格交付与长期测试 Example（2026-11-04 待讨论）

**术语对照（讨论用）**

| 日常说法 | 标准名 | 建议组件 | 备注 |
|---|---|---|---|
| 浮窗 / widget | Panel / Window / Dialog | `UIPanel` | `closable` 开关决定有没有关闭按钮；无关闭 = 常驻面板 |
| 按钮 | Button | `UIButton` | 变体：`primary / secondary / danger / ghost`；图标版 `IconButton` |
| 不可编辑文字 | Label | `UILabel` | 多行 = 同一控件 + `wrap` 开关 |
| 离散档位滑条（全屏/窗口化、分辨率、语言） | Segmented control / Radio group / Dropdown / Stepper | **`UISelect`**（一个数据模型，三种皮肤） | 2-4 项且要一眼看全 → `segmented`；多项 → `dropdown`；数值步进 → `stepper` |
| 连续滑条 | Slider | `UISlider` | `step=0` 即连续；有 step 就是离散但形态仍是滑条 |
| 开关 | Toggle / Checkbox | `UIToggle` | 布尔值，和 `UISelect` 二元选项是两回事 |

> **已定（2026-11-04）**：三种皮肤共享 `{options: [...], index: int}`，只换渲染形态 —— "全屏/窗口化"
> 和"分辨率列表"不用两套控件。

**风格怎么交给开发者：三层 + 优先级（不建议 CSS）**

| 层 | 谁改 | 内容 |
|---|---|---|
| 1. 主题 token | 用户 / 主题包 | 颜色、字体、字号、间距、圆角、动画时长（`ui_theme.json`，工程根） |
| 2. 控件类型默认 | 主题包 | `button.bg` / `button.bg.hover` / `label.font_size` … |
| 3. 实例覆盖 | 场景/实体 | 只在必要时：`variant="danger"`，或显式 `color="@color.warn"` |

优先级：实例 > 控件类型默认 > token > 内置兜底。

**不采用 CSS 的理由**：CSS 是"层叠 + 选择器 + 布局 + 单位 + 伪类"的整套引擎，
只做子集会变成"看起来像 CSS 但不是"；而我们需要的东西 20 个键就够。
参照物选 **Godot Theme**（按控件类型 + 状态给属性、可继承）而不是 CSS。

**主题文件草案**

```json
{
  "tokens": {
    "color.surface": "#1E1E1EE6",
    "color.surface.hover": "#2A2A2AEE",
    "color.text": "#EDEDED",
    "color.accent": "#4C9AFF",
    "radius.panel": 10,
    "space.md": 12,
    "font.body": "Resource/Fonts/NotoSansSC-Regular.otf",
    "font.size.body": 26
  },
  "button": { "bg": "@color.surface", "bg.hover": "@color.surface.hover",
              "fg": "@color.text", "radius": "@radius.panel" },
  "label":  { "fg": "@color.text", "font": "@font.body", "size": "@font.size.body" }
}
```

规则：组件属性里**优先写 token 名 / variant 名**；`hover/pressed/disabled` 由控件自动派生，
不让用户写伪类；变体表达**语义**（primary/danger）而不是颜色。

**长期测试 Example**：`Examples/UIShowcase/`

- 一场景一页，覆盖全部 M0/M1 控件（Panel/Label/Button/Select/Slider/Toggle/Progress/Scroll）；
  另加一屏"拥挤布局"专门压裁剪与对齐；深浅两套主题可切换。
- 四重身份：① `File ▸ Open Example` 的人工演示；② core 守卫（场景可加载、控件齐全、
  token 全部可解析、无常量色）；③ live e2e（PIE 截图 + 稳定点像素探针 + `overlay_probe` 的
  捕获/穿透断言）；④ 用户模板（复制即用）。
- 稳定性要求：新增控件时必须同步该 Example（相当于 UI 的"验收清单"）。
- 守卫建议：`test_ui_showcase.py`（core）+ `e2e_ui_showcase`（live，探针点少而稳，不做整图 diff）。

**待决策**

| # | 问题 | 建议默认 |
|---|---|---|
| D7 | 主题文件位置：工程根单文件 vs `Assets/themes/*.json` 多主题 | **已定（2026-11-04）**：单文件 `ui_theme.json`，多主题目录后置 |
| D8 | 文字来源：字面量 vs 工程字符串表 key | 先字面量 + `SetText` 节点；字符串表后置 |
| D9 | Panel 嵌套：父子是否就是 `UIRect` 父子链 | 是（与实体父子同一套语义） |
| D10 | 编辑器内主题热重载 | M2 再做（文件监听即可） |

### 10.9 M0 已落地：运行时 UI pass + ESC 退出确认（2026-11-04）

**已完成**

| 内容 | 位置 | 说明 |
|---|---|---|
| 绘制指令 | `Application/Core/UI/layout.py`（`UIQuad`） | 纯数据：屏幕像素矩形 + 颜色 + 可选 RGBA 纹理 |
| 布局数学 | 同上（`content_box` / `resolve_rect` / `rect_hit`） | 参考分辨率 1920×1080 + `fit_height`（超宽屏居中留边）+ 9 宫格锚点/枢轴 |
| 主题 token | `Application/Core/UI/theme.py` | 颜色/字号/间距的默认值（`@color.text` 引用式），后续接 `ui_theme.json` |
| 渲染 pass | `Core/Renderer/OpenGL/OpenGLUI.py` + `Renderer.set_ui_quads` | 关深度/开 alpha/关切面；按 `key` 缓存文本纹理；**永远画在场景与 overlay 之上** |
| 运行时 UI 层 | `Application/Runtime/RuntimeUILayer.py` | 模态状态机 + 矩形命中 + 内置退出确认对话框；**模态时消费键鼠**（节点图收不到） |
| ESC 策略 | 同上 + `EditorLayer`（关窗按钮）+ `RuntimeWindow`（overlay 强制捕获） | ESC / 点 X → 弹确认；Yes → `RuntimeNodeLayer.request_stop()`（与 `ExitGame` 同链）；No/ESC → 留下 |
| 文案 | `pie.exit.title/yes/no/hint`（en+zh） | 编辑器侧 `t()` 注入；成品默认英文 |
| 测试 | `Test/Application/Core/test_runtime_ui.py`（23 checks） | 布局数学 / 命中 / 打开关闭 / Yes 停止 / 遮罩空白不触发 / 模态吞键 |

**实机验证（2026-11-04）**

- 3D 窗口化 PIE：ESC → 对话框（`Test/_runs/_overlay_probe/pie_exit_dialog.png`）；
  `No` → `sim.state=Running`；再次 ESC → `Yes` → `sim.state=Stopped`。
- Overlay PIE：ESC → 对话框；`overlay_probe --modal` 显示整窗捕获
  （`WS_EX_TRANSPARENT` 关闭，`WindowFromPoint` = `Game (PIE)`）；点 `Yes` → `Stopped`。

**未做（后续）**

- `UISelect`（segmented/dropdown/stepper 三皮肤）、`UISlider`、`UIToggle`、`UIProgress`、`UIScrollView`
- 场景驱动的 UI 实体 → **已在 §10.10 完成**（`UICanvas + UIPanel/UILabel/UIButton` + `Examples/UIShowcase`）
- 圆角/九宫格/图标、主题文件加载、文本图集、焦点键盘导航、IME

### 10.10 M1 已落地：场景驱动 UI 组件 + `Examples/UIShowcase`（2026-11-04）

> 协议正文（字段表/布局/命中/动作/线程/穿透/验收）：`Doc/Dev/runtime_ui_protocol.md`。
> 本节只记"做了什么 / 验证到什么程度 / 还差什么"。

**组件（`Application/Core/Scene/UIComponents.py`）**

| 组件 | 作用 | 关键字段 |
|---|---|---|
| `UICanvas` | 屏幕空间根 | `scale_mode`（fit_height/fit_width/**contain**/stretch）、参考分辨率、`sort_order` |
| `UIRect` | 布局 | `anchor`/`pivot`（9 宫格）、`pos`、`width/height`（0 = 撑满父级）、`visible`、`order` |
| `UIPanel` | 面板/浮窗/对话框 | 底色/描边（token）、`scrim_color`（整屏遮罩）、`modal`、`role` |
| `UILabel` | 不可编辑文字 | `text`/`size`/`color`/`align`/`bold` |
| `UIButton` | 唯一产生点击的元素 | `text`/`variant`（primary/secondary/danger/ghost）/`action`/`enabled` |

- 全部是 `DataclassContract`：随 `.scene` 读写，无额外工厂；`ComponentRegistry.ensure_defaults` 注册，
  Inspector 通用检视 + 受控枚举（anchor/pivot/scale_mode/align/variant）自动可用。
- `PIE` 模板白名单、`PrefabManager` 组件映射、`i18n` 组件显示名（`comp.ui_*`）已同步。

**编译器与运行时**

| 内容 | 位置 |
|---|---|
| 元素 → quad + 命中矩形（纯数据，可离线单测） | `Application/Core/UI/tree.py`（`build_ui` / `captures`） |
| 场景 → 元素快照（只在逻辑线程） | `Application/Core/UI/scene.py`（`collect_elements` / `find_by_role`） |
| 场景 UI + 内置兜底 + ESC + 动作派发 | `Application/Runtime/RuntimeUILayer.py` |
| 编辑期预览（不 PIE 也能看到 UI） | `Application/Editor/EditorLayer.py`（`_collect_ui_elements` / `_render_ui_preview`） |
| overlay 穿透联动（按钮上 = 捕获） | `RuntimeWindow._cursor_over_ui` + `RuntimeUILayer.captures_at` |
| 新增缩放模式 `contain`（窄视口不裁切） | `Core/UI/layout.content_box` |

**内置对话框改为同一编译器**：`RuntimeUILayer._builtin_elements()` 生成 `UIElement`（负 eid），
与场景 UI 共用 `build_ui` —— 只有一份布局/绘制/命中实现；`build_quads()` 行为与 M0 完全兼容（12 quad / `_rects` yes/no）。

**`Examples/UIShowcase`（四重身份）**

- 22 个 UI 实体：画布 + 顶部栏（2 标签）+ 控制面板（3 标签 + 5 按钮：4 变体 + disabled）+
  详情浮窗（2 标签 + Close）+ 退出确认（`role=exit_confirm`、modal、遮罩、默认隐藏、Stay/Exit）。
- 生成器 `Examples/tools/build_ui_showcase.py`（可重复执行，场景/工程一起产出）。
- 守门：`Test/Application/Core/test_ui_showcase.py`（44 checks）+ `test_ui_tree.py`（42 checks）。

**实机验证（2026-11-04，全新实例 · 3D + Overlay）**

- 编辑器预览：打开工程即看到 TopBar / Controls / 5 个按钮变体 / DetailPanel
  （`Test/_runs/_overlay_probe/editor_ui_preview2.png`、`pie_showcase_hud5.png`）。
- 3D PIE（1280×720）：HUD 布局正确 → ESC 打开**场景对话框**（整屏遮罩 + 模态，
  `pie_showcase_dialog.png`）→ `Stay` 留下（`sim.state=Running`）→ `Secondary` 切换详情浮窗
  （`pie_showcase_toggle_off.png`）→ ESC → `Exit` → `sim.state=Stopped`。
- Overlay PIE（1920×1080 无边框全屏）：`overlay_probe --content 340,560 --blank 60,1020`
  **10/10**（按钮上捕获 / 空白穿透，证明 NDC→framebuffer 换算的 UI 命中共存于 GPU pick 之前）；
  ESC 后 `overlay_probe --modal` **8/8**（整窗捕获，`pie_overlay_scene_dialog.png`）。

**联调中发现并修掉的 4 个坑（都已回归覆盖）**

1. PIE 的 Runtime `SceneManager` 只登记 MeshRenderer 实体 → UI 实体不在枚举表里 → 补
   `_sync_scene_to_runtime` 的 UI 登记（**含父链**，否则子元素全部掉到画布根）。
2. `_anchor_offset` 把 `left/right` 当成"左上/右上" → `anchor=right` 的元素跑到屏幕顶部；
   已改为"左边中/右边中"（`test_ui_tree` 两个用例锁定）。
3. `RuntimeUILayer._text_image` 丢了 `resolve_font` import → 渲染线程 NameError；
   同时给 `OnRender` 加整体兜底（UI 出错只丢这一帧的 UI，不打死渲染循环）。
4. 新增 `contain` 缩放模式：编辑器/非 16:9 窗口下 `fit_height` 会把右侧内容裁掉。

**未做（M1 之后）**

- `UISelect` / `UISlider` / `UIToggle` / `UIProgress` / `UIScrollView`（裁剪栈）→ 前三项已在 §10.11 完成
- 主题文件 `ui_theme.json` 加载 + 多主题 + 热重载（token 仍在代码）
- 文本图集/自动折行/圆角/九宫格/图标；焦点链与键盘导航
- 场景 UI 文本走字符串表（现在字面量）；世界空间 UI

### 10.11 M2 已落地：设置控件 + UI 节点（2026-11-05）

> 协议：`Doc/Dev/runtime_ui_protocol.md`（§2 组件、§4 命中、§5.1 事件→节点）。

**控件（同一套编译器，`Core/UI/controls.py`）**

| 组件 | 交互 | 关键实现 |
|---|---|---|
| `UIToggle` | 点击任意处翻转 | 轨道（开=主色）+ 方块旋钮；hover 变色 |
| `UISlider` | 按下即跳 / 拖拽跟手 / 松开提交 | 轨道 → 数值映射 + `step` 吸附 + 数值回显 |
| `UISelect(segmented)` | 点某一段直接选中 | 逐段命中矩形（index） |
| `UISelect(stepper)` | `−` / `+` 步进（端点钳制） | 两个命中矩形（index=±1） |
| `UISelect(dropdown)` | 点开→选一项 / 点空白关闭 | 弹层画在所有元素之后（命中排最后）；靠近底边**向上翻**；不透明底 |

- 控件值存 `RuntimeUILayer._values`（运行期，不写回场景）；`read_value()` 供节点读。
- 命中种类扩为 `button/toggle/slider/select/step/dropdown`（`UIHitRect.kind`）。

**节点（`Core/NodeGraph/node_types/ui.py` + `evaluators/ui.py` + `widgets/ui.py`）**

| 节点 | 语义 | 备注 |
|---|---|---|
| `SetUIVisible` | 运行期显隐任意 UI 实体（子树跟随） | `Entity` 连线优先，否则 `props.target` 名字 |
| `OnUIClick` | 每次 UI 交互触发一次（释放时） | **必须归 Event 分类**（`trigger` 只遍历 Event）；按 action/name 过滤 |
| `GetUIValue` | 读开关(0/1)/滑条/选择下标 | 纯数据节点 |

- 菜单新分组 `UI`（Set UI Visible / On UI Click / Get UI Value）+ i18n `node.*` / `menu.node_group.ui`。
- `RuntimeNodeLayer` 每帧取走 `RuntimeUILayer.drain_events()` → `trigger("OnUIClick")`；
  事件记录是**对象**（`.kind`），与 `RuntimeInputFrame` 一致。

**示例与守卫**

- `Examples/UIShowcase`：新增 `SettingsPanel`（Sound/Volume/Quality/Resolution/Theme = 三控件 + 三皮肤）
  与 `NodeHint` 标签 + 两条分支的图（`OnGameStart` 隐藏、`OnUIClick(show:DetailPanel)` 显示）。
- `Test/Application/Core/test_ui_controls.py`（55 checks）：控件数学 / 图层交互 / 值读取 / 节点求值 /
  「点击 → `OnUIClick` → `SetUIVisible` → `SetUIText`」全链（真示例场景）。
- `test_ui_showcase.py` 55 checks（新增控件齐全 + 图断言）、`test_ui_tree.py` 44 checks。

**实机验证（2026-11-05，1280×720 PIE）**

- HUD/设置面板布局正确；开关翻转、分段选中、步进 +1、下拉展开并选中（`ui2_*.png`、`ui4_*.png`）。
- 启动时 `NodeHint` 被图隐藏；点 `Primary` 后出现（`ui7_node_show.png`）—— 证明事件→节点→显隐全链。
- ESC 打开场景对话框（`ui7_dialog.png`），点 `Exit` → `sim.state=Stopped`。

**联调中发现并修掉的问题（都已回归覆盖）**

1. `slider_range` 用 `x or default` → `max_value=0` 被当成缺省吞掉（0.0 合法值）。
2. `OnUIClick` 若归 "UI" 分类，`GraphEvaluator.trigger` 根本不遍历 → 必须 Event 分类。
3. UI 事件最初用 dict，而求值器按 `getattr(event,"kind")` 读 → 永远 `_blocked`；改对象记录。
4. 按钮点击最初不 `_emit`（只跑动作）→ `OnUIClick` 收不到按钮。
5. 名字解析只看 UI 快照 → `OnGameStart` 早于第一帧快照时找不到目标；回退查场景实体表。
6. 下拉弹层越界 + 半透明透字 → 向上翻 + 不透明底；弹层宽度改为控件区域（不含左侧标签）。

**未做（后续）**

- ~~`SetUIText`（标签动态文本）~~ → **2026-11-05 已落地**：`RuntimeUILayer.set_text/get_text` +
  `build_ui(texts=...)` + `SetUIText` 节点（`Text` 引脚优先、空串清除覆盖回落 `UILabel.text`）；
  示例图改为 `OnUIClick → SetUIVisible → SetUIText(DetailTitle, "Trial 1 / 12")`。
- **明确暂缓（用户决策 2026-11-05）**：`UIScrollView`（裁剪栈 + 滚动）与 `ui_theme.json` 主题加载 ——
  先把实验链路（动态文本 / 参数化）补完，再回头做 UI 表现层；`UIProgress` 同步排队。
- 焦点链与键盘导航、hover 动画、拖拽排序
- 文本图集、圆角

### 10.12 内容 schema 基座（提案，2026-11-05）

问题：一个可调项要同时写进四个地方（GLSL 解析 / 材质默认 / Inspector 分支 / MCP key / 文档），
每加一层内容（默认材质颜色、漫反射、SSVEP 相位频率、`time`）就膨胀一次，agent 无法自检能力边界。

提案：`Doc/Dev/content_schema_plan.md` —— `FieldSpec` 单一结构 + GLSL `//!` 注解 + 稀疏材质覆盖 +
`schema.get` op + 覆盖率守卫测试；S1/S2 即可解决“颜色/漫反射/SSVEP 参数怎么调”且不碰 op 契约。
顺带发现：`SSVEP.time` 无任何运行期写入者（方块实际是静态的），需按 `owner=runtime` 每帧注入。
