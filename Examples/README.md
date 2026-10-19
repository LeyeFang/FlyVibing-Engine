# Examples

每个范式一个独立工程，入口均为编辑器 **File → Open Example**：

| 工程 | 范式 | 场景 |
|---|---|---|
| `MI/MI.myproj` | 左右手运动想象 | `scenes/MI.scene` |
| `RestingState/RestingState.myproj` | 静息态（睁眼/闭眼） | `scenes/RestingState.scene` |

两个工程共享同一套可读性约定：

- 关键节点带 `@alias`（`@start`、`@phase`、`@tt_cue`、`@trial`、`@next_trial` 等），`flow` / `find` 可按别名定位。
- 关键节点带 `description`：可在节点卡 **Description** 中查看和编辑。
- MI 的提示分支由 `cue_n_way` 展开，3 臂 × 每臂 2 个网格实体；改臂只改参数，不改图。
- MI 的时间相位由外层 `container` 组 `@trial` 嵌套三个子组：`@class_cue`（0–6 s，
  `cue_n_way`）、`@task_cue`（2–6 s，`cue_window`）、`@rest_cue`（6 s，`hide_group`）；
  2–6 s 是 class/task 重叠区间，写不同实体，互不覆盖。
