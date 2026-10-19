# MI

左右手运动想象示例：**0–6 s 始终显示 class cue；2–6 s 叠加 task cue；6–10 s 休息；10 s 下一试次。**

入口：编辑器 **File → Open Example → MI**。

- `scenes/MI.scene`：class cue 是 3 臂 × 每臂 2 个网格实体的 `cue_n_way` 子组；
  task cue 是 2–6 s 的 `cue_window` 子组；rest 是 6 s 触发的 `hide_group` 子组；
  三个子组由外层 `container` 组 `@trial` 嵌套。
- 关键节点带 `@alias` 与 `description`；外层组别名 `@trial`，子组别名
  `@class_cue` / `@task_cue` / `@rest_cue`。
- 并行口地址 `0x3FF8`，class cue 提示码 3/4/5。

## 阶段语义

```text
0 ───────────── 2 ───────────── 6 ───────────── 10
class cue 可见          ↑ task cue 叠加        rest：全部 cue 隐藏
(class 0–6 持续)        (task 2–6)
```

- `@class_cue`：`cue_n_way` 在 0 s 随机选一个臂并显示；选中实体一直保持到 rest。
- `@task_cue`：`cue_window(clock="trial_phase", start=2, end=6, entity="TaskCue")`，
  每帧求值，2–6 s 写 `Visible=true`，窗口外写 `false`。
- `@rest_cue`：`hide_group` 在 6 s 触发，按实体树批量隐藏 `LeftCue` / `RightCue` /
  `NullCue` / `TaskCue`。
- `@trial`：`container` 子组，`children` 为上面三个；`entry` 是 `phase` 的 `exec_in`，
  `done` 接 `next_trial` 的 `exec_out`。

2–6 s 是重叠区间：class cue 与 task cue 写不同实体，互不覆盖；测试见
`Test/Application/NodeGraph/test_mi_groups.py`（14/14）和
`Test/_runs/mi_group_migration/check_overlap.py`。

PIE 证据：`Test/_runs/mi_group_migration/pie_t1_class.png`（0–6 s class cue）、
`pie_t3_overlap.png`（2–6 s class + task 重叠）、`pie_t7_rest.png`（6–10 s rest 只留十字）。

## 改动

```json
{"ops": [
  {"op": "set_group", "group": "@class_cue", "params": {"arms": [
    {"id": "left",  "entities": ["L_arrow_body", "L_arrow_head"], "code": 3},
    {"id": "right", "entities": ["R_arrow_head", "R_arrow_body"], "code": 4}
  ]}},
  {"op": "set_group", "group": "@task_cue",
   "params": {"start": 2, "end": 6, "entity": "TaskCue"}},
  {"op": "set_group", "group": "@rest_cue",
   "params": {"entities": ["LeftCue", "RightCue", "NullCue", "TaskCue"],
              "visible": false}}
]}
```

`@trial` 的成员关系用 `groups --scene scenes/MI.scene` 查看；外层 `@trial` 的 `entry/done`
跨整个试次，子组仍按各自时间窗口/触发点执行。
