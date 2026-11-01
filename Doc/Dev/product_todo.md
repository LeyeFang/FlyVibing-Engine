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
| B1 `UIWidget` + 屏幕空间 `UISystem`（button/label/panel/popup） | 待开工（默认方案） | 无 ImGui 依赖；hover/pressed/click；PIE 截图 |
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
| Settings ▸ Debug | 待办 | Debug layer **事件类型隔离**（已有先例：键盘/鼠标事件已隔离，窗口 resize 未隔离）；后续接输出通道分级 |
| 日志级别 | 待办 | `LogBus` 目前按文本启发式分级；后续 print 迁移时改为显式 `level` |

