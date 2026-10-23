# 节点编辑器踩坑档案

本文记录节点编辑器（ImGui + imgui-node-editor）已经踩过、修复过、
并且用回归测试锁住的坑。新增交互前先扫一遍，避免重复踩。

## 1. 坐标系：画布坐标 ≠ 屏幕坐标

**现象**
- 框选拖拽时高亮矩形在鼠标附近，但松开后选中的是远处节点。
- 右键组框时命中不到组，或命中到相邻组。
- 测试里 `_node_point()` 得到的节点坐标与真实截图像素对不上。

**根因**
- `imgui.get_mouse_pos()` 在 `ne.begin()/end()` 内返回的是**画布坐标**。
- `imgui.get_item_rect_min()` / `ne.get_node_position()` 在节点构建期间也是
  画布坐标。
- `ne.canvas_to_screen()` 只在 `ne.begin()/end()` 内可靠；`end()` 之后调用会
  按当前 ImGui 窗口解析，可能落到 Node Groups 浮窗的坐标系。
- `_node_screen_rects`、`_group_screen_rects`、`_canvas_rect` 是屏幕坐标；
  混用就会“看起来差一点，实际差几百像素”。

**约定**
- 绘制帧内统一缓存：
  - `panel._mouse_screen` = `ne.canvas_to_screen(imgui.get_mouse_pos())`
  - `panel._node_screen_rects[nid]` = 屏幕矩形
  - `panel._group_screen_rects[gid]` = 屏幕矩形
- 所有跨帧命中（框选、组框右键、组拖动、测试点击）只读缓存。
- 需要画布坐标时（成员包含判断、组框尺寸计算）再显式
  `ne.screen_to_canvas()` 或直接用节点 `inst.pos`。

**回归**
- `node_group_actions`：组内空白框选、组框右键、画布外点击不产生陈旧框选。
- 实机 `ui.drag` + `ui.panel` 的 `last_box_apply` 诊断。

## 2. 组标题漂到画布空白处

**现象**
- 新建组后画布空白处出现 `@group_1 [container] (2)` 一行字，组框在别处。

**根因**
- 旧实现先 `Group(size)` 再 `set_cursor_pos(8, 6)` 画标题。
- `set_cursor_pos` 是窗口局部坐标，不是组节点局部坐标；`Group()` 又把光标
  推到了框底，标题自然落到画布别的位置。
- 组标题还会参与节点 bounds 计算，导致组框位置与标题各走各的。

**修复**
- 按 imgui-node-editor 官方顺序：先画标题，再 `Group(size)`；或先
  `Group(size)` 后把光标显式放回组框左上角（必须用同一坐标系）。
- 标题、组框、组节点 bounds 必须由同一份 `box` 几何驱动。

**回归**
- `node_group_actions` 断言标题矩形贴在组框上沿：
  `title.bottom <= frame.top + 2`，且横向落在组框内。

## 3. 组框中心是“洞”

**现象**
- 在组框内部空白拖动无法框选，或者误把整组拖走。
- 右键组框内部被判定成背景。

**根因**
- imgui-node-editor 的 Group 只有标题栏/四条边可交互，中心是透明洞。
- 自定义命中若用整块矩形，会把洞也当成组。

**约定**
- `_group_hit_point(rect, mouse)`：标题栏（顶部 `34px`）或边框附近
  （四边 `10px`）才算组框。
- 组内空白拖拽 = 框选；组标题/边框拖拽 = 移动组。
- 组框拖动守卫还要满足“左键按住 + 指针在可交互区域”，否则面板 resize
  会被误判成拖动，带着成员一起跑。

**回归**
- `node_group_actions`：组内框选成员，`selected_groups` 必须为空。
- `node_groups_smoke`：组框拖动会平移成员子树。

## 4. 面板 resize 会缩放节点卡片

**现象**
- 向右拉伸 Node Editor，GetTime 节点卡片跟着变宽。
- 停靠/浮空切换后节点整体缩放，文字大小变化。

**根因**
- 默认 `CanvasSizeMode.fit_vertical_view` 会按新宽高比重新算 zoom。
- `BeginCombo` 默认 item width 取当前窗口可用宽度；面板越宽，combo 越宽，
  节点卡片也跟着变宽。

**修复**
- `Config.canvas_size_mode = center_only`：resize 只平移视图，不改 zoom。
- `_ne_combo` 显式 `push_item_width(110..220)`，宽度只由预览文字决定。

**回归**
- `node_editor_smoke`：整屏宽度下 GetTime 卡片宽度必须 `< 500px`。

## 5. 框选状态残留

**现象**
- 点击 GetTime 后再点空白，会选中远处其他节点。
- 在工具栏/3D 视口点一下，下一次画布点击拉出巨大选框。

**根因**
- 框选起点只在“空白按下”时更新；节点点击/面板外点击没有清空旧起点。
- 原生选择在 `ne.end()` 后才提交，自定义框选又晚一帧应用，状态容易跨帧。

**约定**
- 框选起点必须在 `_canvas_rect` 内。
- 必须真实拖动超过 `6px` 才应用框选；纯点击绝不应用。
- 点节点、点画布外、release 丢失、焦点丢失都清空框选状态。
- 应用框选时只使用绘制帧缓存的节点屏幕矩形。

**回归**
- `node_group_actions`：点节点 → 点空白 → 选中必须清空。
- `node_editor_smoke` / `node_group_actions` 的框选分支。

## 6. Live UI 注入被 GLFW 覆盖

**现象**
- `ui.mouse` / `ui.click` 返回成功，但画面上的鼠标没动，点击也没生效。

**根因**
- GLFW backend 每帧 `new_frame` 会把真实光标位置写回 ImGui IO。
- 在 `OnUpdate` 里 `add_mouse_pos_event` 会被覆盖。

**修复**
- 在 `EditorImguiLayer.OnRender` 中，backend `new_frame` 之后、
  `imgui.new_frame` 之前调用 `LiveCommandServer.apply_input()`。
- 同时 `glfw.focus_window()` + `glfw.set_cursor_pos()`，让真实光标与注入
  坐标一致。
- `ui.click` / `ui.drag` 按帧分步执行（移动 → 按下 → 抬起）。

## 7. 渲染帧外读 node-editor 原生状态会崩溃

**现象**
- 调用 `ui.panel name="Node Editor"` 时编辑器直接退出，Windows 事件日志
  显示 `_imgui_bundle.pyd` 访问违例（`c0000005`）。

**根因**
- `ui.panel` 的诊断代码在渲染帧外调用 `ne.get_selected_nodes()`。
- Node Editor 标签页未激活时没有当前 editor context，原生 API 直接解引用
  空指针；Python `try/except` 抓不到访问违例。
- 无头测试里即使没有 ImGui 上下文，`imgui.get_mouse_pos()` 也会崩。

**约定**
- 帧外诊断只读纯 Python 快照：
  `_selection_snapshot`、`_node_screen_rects`、`_group_screen_rects`。
- 任何 ImGui getter 前先判 `imgui.get_current_context() is not None`。
- 需要原生状态时，先 `frame.request` 让渲染线程采样，再由诊断读取缓存。

**回归**
- `test_live_command_server.py`：无头 `ui.panel` Node Editor 必须返回
  `selected_groups`，且不得崩溃。

## 8. 测试用浮窗遮挡合成点击

**现象**
- `node_group_actions` 单独跑通过，GUI 全量跑偶发失败：点击节点没选中。

**根因**
- 场景打开 Node Groups 浮窗后，自动布局把首个节点排在左上角，正好被浮窗
  遮住；合成点击落到浮窗上。
- 节点布局位置随视口宽度变化，属于真实的“可能被遮挡”，不是产品 bug。

**约定**
- 用合成点击验证画布逻辑时，先关闭会遮挡画布的浮窗，或显式把节点滚到
  可见区域。
- 需要验证浮窗本身时，单独用真实鼠标坐标，并先断言目标矩形不在浮窗内。

## 9. 组框尺寸不要每帧从成员包围盒重算

**现象**
- 用户拖动组框右下角缩放后，下一帧组框又弹回成员包围盒大小。
- 组内节点被拖动时，组框跟着抖动，无法保持用户手工布局。

**根因**
- 旧实现 `group_bounds(canvas, gid)` 每帧按成员节点 `pos` 推导，没有持久化
  组框矩形；任何手工 resize 都会被下一帧覆盖。

**约定（自 2026-10-22 组框编辑起）**
- 组框几何持久化在 `node_groups[gid]["box"]`（画布坐标 + 宽高）。
- 成员进入/离开、组内重排时才显式 `fit_group()`；普通组框平移不重算。
- 手工 resize 按比例平移成员位置，并受 `min_box` 限制。

## 10. `Group(size)` 只在首次创建时使用 size

**现象**
- 持久化 box 改大了，`ui.panel` 里的 `group_boxes` 也变大了，但画面组框
  一点都不变。
- 双击/拖动 resize 后节点位置变了，组框却还是旧宽高。

**根因**
- imgui-node-editor 的 `NodeBuilder::Group(size)` 内部：
  `if (IsGroup(node)) ImGui::Dummy(node->m_GroupBounds.GetSize()); else ImGui::Dummy(size);`
  也就是组节点一旦存在，后续 `size` 参数会被忽略。

**约定**
- 每次绘制前（`BeginNode` 之前）对已有组调用
  `ne.set_group_size(NodeId, ImVec2(w, h))`，再 `BeginNode` / `Group(size)`。
- `GetNodeSize` 读的是节点 bounds，不一定等于组框；组框尺寸以持久化
  `box` 为准。

**回归**
- `node_group_actions`：手柄缩放后 `_group_frame_rects` 的屏幕宽度必须变大。

## 11. Group 节点不能挂 pin

**现象**
- 在组框上画 exec in/out 时直接抛：
  `IM_ASSERT(false == m_IsGroup) imgui_node_editor.cpp:5694`。
- 即使绕过断言，组节点的 pin 也不会参与连线命中。

**根因**
- `NodeBuilder::BeginPin()` 明确断言当前节点不是 Group。

**约定（2026-10-23 修订）**
- **不要用透明代理节点**：代理必须隐藏成员 pin、把组接口绑定到
  first/last 节点，用户无法把组入口自由连到任意成员。
- 每个组创建/加载时补齐两个**真实内部节点**：
  - `GroupStart`：只有 `exec_out`；
  - `GroupEnd`：只有 `exec_in`。
- 它们是普通组成员，随组布局/平移/删除；不隐藏、不改写任何成员 Pin。
- 编辑器不把它们画成普通卡片，而是渲染为组框左右端口槽内的紧凑
  `Group entry` / `Group exit` pill；PinId 仍是真实节点 pin。注意视觉标签
  表示组边界角色，而不是内部 pin 方向：左上 GroupStart 只有 exec_out，
  右下 GroupEnd 只有 exec_in；直接交换两者会把内部流向变成右下往左上。
- 组不写 `slots`/`params.entry/done`，成员 Pin 保持原样。
- 早期场景缺少这两个节点时由 `ensure_group_io_nodes()` 在编辑器首帧补齐；
  Ungroup/Delete/Destroy 时移除。拖出组框会被夹回，不改变归属。
- 组标题/描述支持双击内联编辑；空描述显示浅色占位，避免“看起来没有描述区”。
- 组描述与普通节点一致：标题行右侧 `Description` / `Hide` 按钮折叠/展开，
  默认展开，首次打开仍能看到描述。按钮点击不能触发整组拖动：命中用上一帧
  按钮屏幕矩形，并在点击后给组拖动冷却。这不是技术限制，之前只是因为
  “描述必须可见”而做成了永久展开。

**端口视觉（2026-10-23 实机修订）**
- 左右各留 100px 端口槽（`MARGIN_LEFT/RIGHT` 与 `PAD_LEFT/RIGHT`）：
  `Group entry` 在左上，`Group exit` 在右下；pill 与成员卡片
  在垂直方向不重叠，入口连线不会从成员卡片上方穿过。
- exec 引脚没有原生圆形图标；在 pin 内容里加 `●`，并把
  `pin_pivot_alignment` 设为右/左中点。否则连线会从 pill **底部中心**
  出发，看起来没有接在端口上。
- 圆点必须位于 pin 内容内（不是 overlay），这样“看到圆点”和“命中
  引脚”是同一个区域；`ui.panel` 的 `hovered_pin_id` 可验证命中。

**回归**
- `test_group_ops`：GroupStart/GroupEnd 引脚方向、生命周期与幂等。
- `node_groups_smoke`：嵌套组内部节点随组平移；成员 `slots` 不被改写。
- `node_group_actions`：组内 start/end 节点类型与真实 pin 存在。
- `e2e_node_group_live`（`TIER: live`）：实机断言标题/描述/端口 pill 可见，
  pill 不压成员卡片，真实鼠标拖标题/拖出拖入成员，并从左右端口拖出
  `GroupStart → 成员 → GroupEnd` 链。快照在
  `Test/_runs/e2e_node_group_live/`。

## 12. 上一帧组矩形被清空导致手柄/拖动永远命中不到

**现象**
- 组框右下角 `+` 手柄点不动；组标题拖动也失效（测试用 force 才通过）。

**根因**
- `_draw_group_hints` 开头 `self._group_screen_rects.clear()`，随后又用
  同一张表查上一帧的组矩形，结果永远是 `None`。

**约定**
- 进入绘制前先保存 `prev_group_screen = self._group_screen_rects`，再新建
  空表；命中/拖动/手柄读 `prev_group_screen`，绘制完成后新表供右键菜单和
  下一帧使用。
- 组标题/边框拖动、右下角 `+` 缩放都用**自定义鼠标增量**实现，不依赖
  imgui-node-editor 原生的 group drag / size 命中（其区域在不同 zoom /
  title 布局下不稳定）；开始拖动/缩放时同步清空框选状态。

## 13. Ungroup / Delete / Destroy 必须是三种语义

**现象**
- 右键菜单的 Destroy 和 Ungroup 都只删组框，成员节点全部留下。
- 空白画布右键没有菜单项，用户看不到“没有选中节点”的反馈。

**约定**
- `Ungroup`：只拆框；成员节点保留，子组提升到父级。
- `Delete Group`（工具/兼容）：删除组框与组内 GroupStart/GroupEnd，
  用户成员节点保留。
- `Destroy Group`：删除组框、子组和**全部成员节点**及其连线。
- 空白右键始终打开上下文菜单：0 个选中节点显示浅色
  `No selected node`；单选显示 `Delete Node`；多选显示 Delete/Merge。
- 组右键提供 `Rename Group` / `Edit Description`；双击组标题或描述行也可
  内联编辑。空描述必须显示浅色占位，否则用户会以为没有描述区。
- 单选节点右键必须提供 `Delete Node`，走与 Delete 键相同的
  `_delete_nodes()`（含设备 Init/Kill 级联、组成员清理、组框收紧）。

**回归**
- `test_group_ops`：destroy 清空成员节点；metadata delete 只移除内部节点。
- `node_group_actions`：Destroy 后成员节点消失；空白右键保持无选择状态。

## 14. Fit 不能早于组框尺寸注册

**现象**
- 新导入带组的图后自动 `graph.fit`，视图缩放到极小：组框还在，但成员卡片/
  端口几乎看不见；手动再点 Fit 也未必恢复。

**根因**
- `_draw_canvas_contents()` 在绘制节点之前执行 `NavigateToContent()`；此时
  imgui-node-editor 里组节点的原生 `Group(size)` 还没有写入本帧尺寸，Fit
  只按组内普通节点/上一帧旧尺寸计算边界。

**约定**
- `_fit_requested` 必须在 `_draw_nodes()`（含组框绘制）之后执行；
  组框尺寸先 `SetGroupSize`，再 `NavigateToContent()`。
- 组框首次出现或成员进出后，给一帧稳定期；E2E 的 `activate_and_fit()`
  先激活 Node Editor 标签，再等待绘制帧后 Fit。
- `_prepare_group_boxes` 的 `ready` 判断要排除 `GroupStart`/`GroupEnd`
  （它们由组框边缘绘制，不会进入普通节点 canvas rect 表）。

**回归**
- `test_e2e_node_group_live`：从空画布导入组后 Fit，组框/成员/端口必须
  达到可读尺寸；随后拖标题、缩放组框、拖入拖出成员和端口拖线全部通过。


