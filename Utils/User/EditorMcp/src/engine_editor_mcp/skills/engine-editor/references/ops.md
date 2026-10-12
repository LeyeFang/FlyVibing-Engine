# Engine op 完整参考

> 由 `python -m engine_editor_mcp.docgen` 从 `ops.py` 生成 — 勿手改。
> CLI: `engine-editor-cli call <op> k=v ...`; MCP(lite): `engine_call(op, args)`。
> 旧工具名可用（如 `editor_run_pie` → `sim.play`）。数组/对象值在终端里请加引号。

## 运行控制

### `sim.play`

启动 PIE（等同 Run 按钮）

- 示例: `engine-editor-cli call sim.play`

### `sim.stop`

停止 PIE（等同 Stop 按钮）

- 示例: `engine-editor-cli call sim.stop`

### `sim.state`

查询模拟状态（state / runtime_alive）

- 示例: `engine-editor-cli call sim.state`

## 视图 / 摄像机

### `view.set_mode`

设置 Scene Type（3d / 2d / overlay；含 game_type + 视口）

- `mode` (enum, 必填) — "3d" / "2d" / "overlay"

- 示例: `engine-editor-cli call view.set_mode mode="2d"`

### `view.set_grid`

显示/隐藏编辑器视口网格（View 菜单 Show Grid 同路径）

- `visible` (bool, 必填) — true=显示 false=隐藏

- 示例: `engine-editor-cli call view.set_grid visible=true`

### `camera.get`

读取场景摄像机（Transform + Camera）

- `role` (enum, 可选) — "3d"(默认) / "2d" / "overlay"

- 示例: `engine-editor-cli call camera.get role="2d"`

### `camera.set`

修改场景摄像机（仅传字段）

- `role` (enum, 必填) — "3d" / "2d" / "overlay"
- `position` (json, 可选) — [x,y,z]
- `rotation` (json, 可选) — [x,y,z] 角度
- `projection` (enum, 可选) — "persp" / "ortho"
- `ortho_size` (float, 可选)
- `fov` (float, 可选)

- 示例: `engine-editor-cli call camera.set role="2d" position={"k":1}`

## 渲染器诊断

### `renderer.snapshot`

渲染器状态快照（后端 / GL 信息 / 资源计数 / 视口 / 帧统计; 无头时 available=false）

- 示例: `engine-editor-cli call renderer.snapshot`

## 实体

### `entity.list`

列出实体（roots_only=true 仅根）

- `roots_only` (bool, 可选) — 默认 false

- 示例: `engine-editor-cli call entity.list roots_only=true`

### `entity.get`

读取实体快照（组件/层级/可见性/transform）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）

- 示例: `engine-editor-cli call entity.get id=5 name=VALUE`

### `entity.add`

新建实体（Transform only；有选中时成为其子级；自动选中新实体）

返回: {entity_id, name, components, ...} — 后续 op 用 id=entity_id。

- `name` (str, 可选) — 实体名
- `parent` (str, 可选) — 父实体 id/名称；"none"=强制根实体

- 示例: `engine-editor-cli call entity.add name=VALUE parent=VALUE`

### `entity.rename`

重命名实体（不强制唯一）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `new_name` (str, 必填)

- 示例: `engine-editor-cli call entity.rename id=5 name=VALUE`

### `entity.delete`

删除实体（连同子实体）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）

- 示例: `engine-editor-cli call entity.delete id=5 name=VALUE`

### `entity.transform`

设置 transform（编辑器坐标；rotation 角度；relative=相对调整）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `position` (json, 可选) — [x,y,z]
- `rotation` (json, 可选) — [x,y,z] 角度
- `scale` (json, 可选) — 标量或 [x,y,z]
- `local` (bool, 可选) — 本地坐标
- `relative` (bool, 可选) — 位移加/旋转加/缩放乘（gizmo 语义）

- 示例: `engine-editor-cli call entity.transform id=5 name=VALUE`

### `entity.visible`

设置可见性（editor=视口 / render=渲染）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `editor` (bool, 可选)
- `render` (bool, 可选)

- 示例: `engine-editor-cli call entity.visible id=5 name=VALUE`

### `entity.reparent`

设置父实体（parent="none" 解除）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `parent` (str, 必填) — id/名称/"none"

- 示例: `engine-editor-cli call entity.reparent id=5 name=VALUE`

## 选中

### `selection.get`

当前选中实体

- 示例: `engine-editor-cli call selection.get`

### `selection.set`

选中实体（gizmo=true 同时显示 gizmo）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `gizmo` (bool, 可选) — 默认 true

- 示例: `engine-editor-cli call selection.set id=5 name=VALUE`

### `selection.clear`

清除选中

- 示例: `engine-editor-cli call selection.clear`

## 组件

### `component.types`

已注册组件类型表

- 示例: `engine-editor-cli call component.types`

### `component.list`

实体的组件名列表

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）

- 示例: `engine-editor-cli call component.list id=5 name=VALUE`

### `component.add`

添加组件（MeshRenderer 自动绑默认 Cube）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `type` (str, 必填) — Camera / MeshRenderer / Transform

- 示例: `engine-editor-cli call component.add id=5 name=VALUE`

### `component.remove`

移除组件（Transform 不可移除）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `type` (str, 必填)

- 示例: `engine-editor-cli call component.remove id=5 name=VALUE`

### `component.get`

读取组件字段快照（MeshRenderer 附 mesh/material 摘要）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `type` (str, 必填)

- 示例: `engine-editor-cli call component.get id=5 name=VALUE`

### `component.set`

部分字段更新（Transform/MeshRenderer/Camera 专用 setter）

- `id` (int, 可选) — 实体 id（id / name 二选一）
- `name` (str, 可选) — 实体名（id / name 二选一；重名取首个）
- `type` (str, 必填)
- `fields` (json, 必填) — 字段 dict，如 {"color":[1,0,0]}
- `local` (bool, 可选)
- `relative` (bool, 可选)

- 示例: `engine-editor-cli call component.set id=5 name=VALUE`

## 场景

### `scene.list`

场景列表 + 活跃场景

- 示例: `engine-editor-cli call scene.list`

### `scene.switch`

切换场景（保存当前/加载/视口同步全流程）

- `name` (str, 必填)

- 示例: `engine-editor-cli call scene.switch name=VALUE`

### `scene.create`

新建场景并切换为活跃（含视口/节点图同步）

- `name` (str, 必填)

- 示例: `engine-editor-cli call scene.create name=VALUE`

### `scene.save`

保存当前场景（省略 path 用最近路径）

- `path` (str, 可选)

- 示例: `engine-editor-cli call scene.save path=VALUE`

### `scene.load`

加载 .scene 文件并设为活跃

- `path` (str, 必填)

- 示例: `engine-editor-cli call scene.load path=VALUE`

## 资源

### `resource.list`

资源列表

- `kind` (enum, 必填) — mesh / shader / texture / material / prefab

- 示例: `engine-editor-cli call resource.list kind="mesh"`

### `resource.find`

按名查找（返回全部匹配）

- `kind` (enum, 必填)
- `name` (str, 必填)

- 示例: `engine-editor-cli call resource.find kind="mesh" name=VALUE`

### `resource.material.get`

材质详情（shader/颜色/纹理槽/uniform）

- `id` (int, 可选) — id / name 二选一
- `name` (str, 可选)

- 示例: `engine-editor-cli call resource.material.get id=5 name=VALUE`

## 节点图

### `graph.list`

节点图快照（nodes: id/type/props/pins; links）

- 示例: `engine-editor-cli call graph.list`

### `graph.add`

添加节点（等同 Add 菜单）

- `type` (str, 必填) — 节点类型名，如 EntitySpawn
- `props` (json, 可选) — 节点属性 dict
- `position` (json, 可选) — [x,y] 画布位置

- 示例: `engine-editor-cli call graph.add type=VALUE props={"k":1}`

### `graph.link`

连接两个引脚（from/to 各 {node,pin}）

- `from` (json, 必填) — {"node":1,"pin":"exec"}
- `to` (json, 必填) — {"node":2,"pin":"exec_in"}

- 示例: `engine-editor-cli call graph.link from={"k":1} to={"k":1}`

### `graph.set_props`

更新节点属性

- `node` (int, 必填) — 节点 id
- `props` (json, 必填)

- 示例: `engine-editor-cli call graph.set_props node=5 props={"k":1}`

### `graph.validate.start`

启动干跑校验（静态+模拟；source=canvas/graph）

- `source` (enum, 可选) — canvas(默认) / graph
- `graph` (json, 可选) — source=graph 时必填
- `frames` (int, 可选) — 默认 360
- `seed` (int, 可选) — 默认 0
- `verbose` (bool, 可选) — 默认 true

- 示例: `engine-editor-cli call graph.validate.start source="mesh" graph={"k":1}`

### `graph.validate.state`

校验任务状态（task_id 省略=最新）

- `task_id` (int, 可选)

- 示例: `engine-editor-cli call graph.validate.state task_id=0`

### `graph.validate.report`

取回校验报告（可 save_path 落盘）

- `task_id` (int, 可选)
- `save_path` (str, 可选) — .json/.txt

- 示例: `engine-editor-cli call graph.validate.report task_id=0 save_path=VALUE`

### `graph.validate.cancel`

取消校验任务（帧间生效）

- `task_id` (int, 可选)

- 示例: `engine-editor-cli call graph.validate.cancel task_id=0`

### `graph.export`

导出画布 JSON（path 落盘；inline=false 只回摘要 — 省 token）

- `path` (str, 可选) — 落盘路径（自动补 .json）
- `include_rules` (bool, 可选) — 默认 true；不需规则文档时传 false
- `inline` (bool, 可选) — 默认 true 返回完整图；false 只回 counts+saved_path

- 示例: `engine-editor-cli call graph.export path=VALUE include_rules=true`

### `graph.import`

导入图替换画布（validate_first 默认开；有静态 error 拒绝）

- `graph` (json, 可选) — graph dict（或 path）
- `path` (str, 可选) — .json 文件
- `validate_first` (bool, 可选) — 默认 true

- 示例: `engine-editor-cli call graph.import graph={"k":1} path=VALUE`

## 工程

### `project.open`

打开 .myproj 工程（资源+场景全加载）

- `path` (str, 必填) — .myproj 路径

- 示例: `engine-editor-cli call project.open path=VALUE`

### `project.save`

保存工程（File ▸ Save Project；带 path = Save As）

- `path` (str, 可选) — 省略=保存到当前路径（需已保存过）；提供=Save As

- 示例: `engine-editor-cli call project.save path=VALUE`

### `project.export`

导出工程包（File ▸ Export；include_player=true 附游戏层成品）

- `target_parent` (str, 必填) — 父目录 → 输出 <target_parent>/<Name>/
- `include_player` (bool, 可选) — 默认 true（含 runtime 自包含）；false=纯工程包

- 示例: `engine-editor-cli call project.export target_parent=VALUE include_player=true`

## 扩展体系

### `extension.list`

扩展列表+状态+扩展 op（ext.<id>.* 在此发现）

扩展 op 为运行期增量注册（不在本静态表中）— 用 extension.list 获取当前清单。

- 示例: `engine-editor-cli call extension.list`

### `extension.enable`

启用扩展（等同 Extensions 菜单勾选; 加载 on_load/on_enable）

- `id` (str, 必填) — 扩展 id（如 sigproc）

- 示例: `engine-editor-cli call extension.enable id=VALUE`

### `extension.disable`

停用扩展（on_disable/on_unload + 注销其全部 ops）

- `id` (str, 必填) — 扩展 id

- 示例: `engine-editor-cli call extension.disable id=VALUE`

## 设置

### `settings.get`

读取编辑器设置（省略 key = 全量; UI: Settings 面板 Common 页）

- `key` (str, 可选) — 如 ui.font_scale / ui.language

- 示例: `engine-editor-cli call settings.get key=VALUE`

### `settings.set`

写入编辑器设置（校验+钳制 → 持久化 → 下一渲染帧生效）

- `key` (str, 必填) — 如 ui.font_scale / ui.language
- `value` (json, 必填) — 新值（数值 / 字符串）

- 示例: `engine-editor-cli call settings.set key=VALUE value={"k":1}`

## 线程诊断

### `threads.snapshot`

线程注册表快照（注册/未注册漂移/停滞检测; 见 Doc/Dev/threading_protocol.md）

- 示例: `engine-editor-cli call threads.snapshot`

## 编辑器

### `editor.quit`

请求关闭编辑器（下一帧正常退出）

- 示例: `engine-editor-cli call editor.quit`
