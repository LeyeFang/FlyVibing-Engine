# Examples

每个范式一个独立工程，入口均为编辑器 **File → Open Example**：

| 工程 | 范式 | 场景 |
|---|---|---|
| `MI/MI.myproj` | 左右手运动想象 | `scenes/MI.scene` |
| `RestingState/RestingState.myproj` | 静息态（睁眼/闭眼） | `scenes/RestingState.scene` |
| `SerialPulse/SerialPulse.myproj` | **每 1 s 串口发码，1..10 循环**（最小可运行链路） | `scenes/SerialPulse.scene` |
| `ParallelPulse/ParallelPulse.myproj` | **每 1 s 并口发码，1..10 循环**（最小可运行链路） | `scenes/ParallelPulse.scene` |
| `UIShowcase/UIShowcase.myproj` | **运行期 UI 组件全清单**（Canvas/Panel/Label/Button 变体 + 退出确认对话柜） | `scenes/UIShowcase.scene` |

## 工具：把流水线写进任意场景（可覆写）

`tools/apply_pulse_pipeline.py` 用 live op（`graph.add` / `graph.set_props` / `graph.link`）
把上面两个示例同款的 1 Hz 流水线写进**当前打开的场景**，可反复运行：

```powershell
# 第一次：创建整套节点 + 连线（core 链 + 一个 SerialSend/ParallelSend）
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial port=@mydevice

# 改了设备/周期再跑一次：只更新你显式给出的参数，不会复制出第二份节点
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial port=COM5 period=0.5 max=5

# 把模板值整体压回去（覆盖面板上的改动）
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial overwrite=1
```

节点身份靠 `description` 里的 `[pulse:<tag>:<slot>]` 前缀：

- 面板里改属性、挪位置都不会丢身份 → **再跑一次就是覆写同一批节点**；
- 想在同一场景里再放一套独立流水线：加 `tag=mytask`；
- 当前没有 live 删除 op，删节点请在 Node Editor 里选中后按 Del。

## 可读性约定

- 关键节点带 `@alias`（`@start`、`@phase`、`@tt_cue`、`@trial`、`@next_trial` 等），`flow` / `find` 可按别名定位。
- 关键节点带 `description`：可在节点卡 **Description** 中查看和编辑。
- 组框带描述，标题行有 **Description / Hide description** 开关；默认展开。
- 组框左右端口槽提供 `Group entry` / `Group exit` pill，圆点可直接拖线到组内任意成员。
- 组框可整体拖动、右下角 `+` 缩放、成员拖入拖出；组内空白框选只选成员，不选组框。
- MI 的提示分支由 `cue_n_way` 展开，3 臂 × 每臂 2 个网格实体；改臂只改参数，不改图。
- MI 的时间相位由外层 `container` 组 `@trial` 嵌套三个子组：`@class_cue`（0–6 s，
  `cue_n_way`）、`@task_cue`（2–6 s，`cue_window`）、`@rest_cue`（6 s，`hide_group`）；
  2–6 s 是 class/task 重叠区间，写不同实体，互不覆盖。
- RestingState 用外层 `@resting_block` 容器嵌套 `@open_phase`（0 s）、`@closed_phase`
  （20 s）、`@cycle`（40 s）三个子组，演示嵌套组与阶段描述。
