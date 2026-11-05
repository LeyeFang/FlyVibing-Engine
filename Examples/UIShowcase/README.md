# UIShowcase — 运行期 UI 组件示例

**File → Open Example → UIShowcase**，然后 ▶ Play。

这个工程是运行期 UI 的**验收清单**：新增控件必须同步它（守卫：`Test/Application/Core/test_ui_showcase.py`）。
协议：`Doc/Dev/runtime_ui_protocol.md`（`engine-editor-cli doc show dev/runtime_ui_protocol`）。

## 里面有什么

| 区域 | 实体 | 演示什么 |
|---|---|---|
| 画布 | `UIHUD`（`UICanvas`，`contain`，1920×1080 参考） | 参考分辨率 + 缩放策略 |
| 顶部栏 | `TopBar` / `TopBarTitle` / `TopBarHint` | 面板 `width=0` 撑满；左对齐 / 右对齐文字 |
| 控制面板 | `ControlsPanel` + 3 个标签 + 5 个按钮 | 4 个按钮变体（primary/secondary/danger/ghost）+ disabled |
| 设置面板 | `SettingsPanel` + 5 行控件 | `UIToggle` / `UISlider`（step 吸附 + 数值回显） / `UISelect` 三皮肤（segmented / stepper / dropdown） |
| 详情浮窗 | `DetailPanel` + 3 个标签 + `Close` | `action=toggle:...` / `show:...` / `close`；`NodeHint` 由**节点图**控制显隐 |
| 退出确认 | `ExitDialog`（`role=exit_confirm`、`modal`、遮罩、默认隐藏） | ESC 策略 + 模态输入捕获 |
| 节点图 | `OnGameStart→SetUIVisible`、`OnUIClick→SetUIVisible→SetUIText` | 启动隐藏 `NodeHint`；点 `Primary` 再显示它，并把 `DetailTitle` 改成 `Trial 1 / 12` |

## 交互

| 操作 | 结果 |
|---|---|
| `Primary` | 显示 `DetailPanel`（`show:DetailPanel`） |
| `Secondary` | 切换 `DetailPanel`（`toggle:DetailPanel`） |
| `Close`（详情浮窗内） | 关闭自己所在面板（`close`） |
| 开关 `Sound` | 翻转（开=蓝色轨道） |
| 滑条 `Volume` | 按下即跳、拖拽跟手（step=5，右侧显示数值） |
| `Quality` / `Resolution` / `Theme` | 分段选择 / `−+` 步进 / 下拉列表 |
| `Esc` | 打开退出确认（场景面板优先，没有则用内置对话框） |
| 退出确认 `Stay` | 关闭对话框，继续运行（`close`） |
| 退出确认 `Exit` | 停止运行（`exit`，与 `ExitGame` 节点同一条链） |

## 改这个工程

- 编辑器里直接加组件：选中实体 → **Add Component** → `UI Canvas / UI Rect / UI Panel /
  UI Label / UI Button`，Inspector 里改 `anchor/pivot/width/height/visible/order`；
  颜色/字号**只写 token**（`@color.surface`）。
- 批量重建（推荐，可重复执行）：

  ```powershell
  .venv-py314t\Scripts\python.exe Examples\tools\build_ui_showcase.py
  ```

  脚本是这一场景的**唯一信源**；手改 `.scene` 后重跑会覆盖。

## 已知限制

- 场景里的文字是字面量，不随编辑器语言切换（内置退出确认才走 `pie.exit.*`）。
- 编辑器视口预览按窗口尺寸布局（右侧被停靠面板遮住的部分只是被挡），且 UI 不参与编辑器 pick。
- 尚未实现：`UIProgress`/`UIScrollView`/`SetUIText`、圆角、主题文件、文本图集、焦点键盘导航。
