# MI-SSSEP 运动想象实验设计

## 概述

基于 SSVEP 视觉线索的运动想象 (Motor Imagery) 实验。被试注视屏幕中央的十字 (Cross)，根据左侧或右侧出现的视觉线索执行对应的运动想象任务。

## 实验参数

| 参数 | 值 |
|------|-----|
| 初始延迟 | 5 秒 |
| 总 trial 数 | 60 |
| 单个 trial 时长 | 10 秒 |
| 全程注视点 | Cross (十字) — 始终可见 |
| 左线索 | LeftCue (触发码 11) |
| 右线索 | RightCue (触发码 12) |
| 任务线索 | TaskCue |
| 并口地址 | 0x3FF8 (LPT1) |
| 种子保存路径 | `Test/TestProject/MI-SSSEP/seed/` |

## 实验流程

### 单个 Trial 时序 (10s)

```
┌─────────────────────────────────────────────────────┐
│ Phase 0 (0-2s)   │ Phase 2 (2-6s)  │ Phase 6 (6-10s) │
│                   │                  │                  │
│ LeftCue 或        │ Cue 保持可见     │ 所有 Cue 隐藏    │
│ RightCue 随机出现  │ + TaskCue 出现   │                  │
│ 发送触发码 11/12  │                  │                  │
│                   │                  │                  │
│ Cross ────────────────────────────────────────────── │
│ (整个 trial 全程可见)                                 │
└─────────────────────────────────────────────────────┘
  0s               2s                6s              10s
```

### 完整实验流程

```
延迟 5s → Trial 1 → Trial 2 → ... → Trial 60 → 自动结束
```

## 随机化

每个 trial 开始时：
1. 从离散分布 {1, 2} 中随机抽取
2. 抽到 1 → LeftCue (触发码 11)
3. 抽到 2 → RightCue (触发码 12)
4. 通过并口 0x3FF8 发送对应触发码

使用硬件随机源 (`RandomSetSeed(source=hardware)`)，种子自动保存为日期戳文件。

## 实体定义

| 实体 | 说明 | MeshRenderer | 初始可见 |
|------|------|-------------|---------|
| Cross | 注视十字（父实体） | 无 | — |
| row (子) | 十字水平条 | 有 | 是 |
| col (子) | 十字垂直条 | 有 | 是 |
| LeftCue | 左线索（父实体） | 无 | 否 |
| arrow_body (子) | 左箭头身体 | 有 | — |
| arrow_head_copy (子) | 左箭头头部 | 有 | — |
| RightCue | 右线索（父实体） | 无 | 否 |
| arrow_head (子) | 右箭头头部 | 有 | — |
| arrow_body_copy (子) | 右箭头身体 | 有 | — |
| TaskCue | 任务线索 | 有 | 否 |

## 节点图结构

- **OnGameStart**: 初始化随机种子 → 保存种子 → 生成实体 → 初始化变量 → 初始隐藏所有 cue
- **OnFrameUpdate**: 每帧读取 `next_time` → TimeTrigger 驱动阶段状态机
- **阶段机**: 根据 `second` 变量 (0/2/6/10) 判断当前阶段，执行对应操作
- **OnGameStop**: (预留)

## 运行方式

1. 在编辑器中打开项目 `Test/TestProject/MI-SSSEP/MI-SSSEP.myproj`
2. 确保激活场景为 `MI`
3. 在 Node Editor 面板检查/编辑节点图
4. 点击 ▶ Run 启动 PIE
5. 实验自动运行 60 个 trial 后退出

## 验证

```bash
# 静态检查
python Utils/Validators/node_graph_validator.py Test/TestProject/MI-SSSEP/scenes/MI.scene

# 静态 + 600 帧干跑
python Utils/Validators/node_graph_validator.py Test/TestProject/MI-SSSEP/scenes/MI.scene --frames 4000
```
