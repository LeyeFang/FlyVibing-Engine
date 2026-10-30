# ParallelPulse

## 范式

最小可运行示例：**每 1 s 发送一个并行口码值，码值 1 → 10 循环**。
用来验证「引擎 → 并口 (LPT)」链路，也是你自己实验的起点。

## 时间线（1 个周期 = 10 s）

| 时间 | 事件 | 发送值 |
|---|---|---|
| 0 s | OnGameStart：生成注视十字、计数器归零、计时器上膛 | — |
| 1 s | 第 1 次脉冲 | `1` |
| 2 s | 第 2 次脉冲 | `2` |
| … | 每 1 s 一次 | … |
| 10 s | 第 10 次脉冲 | `10` |
| 11 s | 回绕，继续 `1` | `1` |

数值从 `SetTimer(-1)` 的命名 Timer `pulse_tick` 驱动，
`Compare(gt)` + `Branch` 负责 `10 → 1` 回绕。

## 节点图

| 组 | 节点 | 说明 |
|---|---|---|
| 启动 | `@start` → `@spawn` → `@reset_index` → `@tick_timer` → `@arm` | 生成模板实体、`pulse_index=0`、Timer 上膛 |
| 帧 | `@frame` → `@seq` → `@tt` | 每帧检查 Timer 是否到 0 |
| 计数 | `@read` → `@add`(+`@one`) → `@cmp`(vs `@max`) → `@branch` | `next = index + 1`，`next > 10` 则回绕 |
| 分支 | `@wrap_set` / `@inc_set` | 写回 `pulse_index` |
| 发送 | `@send`（**唯一设备节点**） | `SerialSend`/`ParallelSend`，设备参数集中在这里 |
| 重上膛 | `@rearm` | `SetTimer(-1)`，周期由此决定 |

所有节点 `description` 以 `[pulse:pulse:<slot>]` 开头 —— 这是「覆写」用的身份标记，
不要改前缀；后面的说明文字可以随便写。

## 运行

- 打开：编辑器 **File → Open Example → ParallelPulse**（显示 `@Official`）。
- 校验：`engine-editor-cli validate`（静态 + 干跑都应为 0 error）。
- 试跑：`engine-editor-cli call sim.play` → 观察发送 → `sim.stop`。
- 导出成品：`engine-editor-cli call project.export target_parent=<out> include_player=true`。

## 改成你自己的设备

三种方式，从轻到重：

1. **直接改面板**：在 Node Editor 里选中 `@send`，改 Port / Baud / Format（串口）
   或 Address（并口）。改完保存场景即可。
2. **用面板端口重绑逻辑名**：先 `engine-editor-cli call ext.device.bind_alias name=mydevice port=COM5 baud=9600`，
   节点里保持 `@mydevice` 不变（换机器也不需要改场景）。
3. **重新写入整条流水线（覆写）**：

```powershell
# 在你自己的场景里生成同一条流水线（1 s，1..10）
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py parallel port=@mydevice period=1 max=10

# 改设备/周期后再跑一次：只更新你显式给出的参数，不会复制出第二份节点
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py parallel port=COM5 baud=115200 period=0.5 max=5

# 把模板值整体压回去（覆盖你在面板上的改动）
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py parallel overwrite=1

# 只看计划、不写入
engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py parallel port=COM5 dry_run=1
```

> 参数用 `key=value`（与 `engine-editor-cli call` 一致）；`--port COM5` 写法在部分 shell 下
> 会被 CLI 当成自己的选项报错。

`apply_pulse_pipeline.py` 认的是节点 `description` 里的 `[pulse:pulse:<slot>]` 前缀：
改属性不会丢身份，所以**面板改完再跑一次 = 覆写同一批节点**。
想换一套独立的流水线：加 `tag=mytask`（标记变成 `[pulse:mytask:...]`）。

## 修改入口

| 想改什么 | 改哪里 |
|---|---|
| 周期 | `@arm` / `@rearm` 的 `value = -period`；或用 applier 的 `period=` |
| 上限 / 循环长度 | `@max` 的 `value`；或用 `max=` |
| 起始值 | `@wrap_set` 的输入常量 `@one`（默认 1） |
| 设备 | `@send` 的 props；或用 applier 的 `port=` / `baud=` / `format=` / `address=` |
| 生成哪个模板实体 | `@spawn` 的 `template`；applier 用 `template=<实体名>`（`template=none` = 不生成） |
| 发送格式 | `@send.format`：`string` → `str(value) + 换行`（如 `1.0\n`）；`bytes` → float32 LE 4 字节 |

## 已知边界

- 串口 `format=string` 时负载是 `str(value)` 加换行（如 `1.0\n`）——下位机按数字解析即可；
  `format=bytes` 则是 4 字节 float32 LE。
- 并行口 `value` 会被夹到 1..255；0 保留给复位（每次写入后 5 ms 自动复位）。
- 没有 live 删除 op：要删流水线就在 Node Editor 里选中后按 Del。
- 逻辑名 `@mydevice` 未绑定时，L1 静态校验会给 1 条 `device_alias_unresolved` 警告（不是错误）；
  绑定后即消失：`engine-editor-cli call ext.device.bind_alias name=mydevice port=COM5 baud=9600`。
- 一个周期内只有 10 个码；需要更长的循环请改 `@max` 或用 applier 的 `max=`。
