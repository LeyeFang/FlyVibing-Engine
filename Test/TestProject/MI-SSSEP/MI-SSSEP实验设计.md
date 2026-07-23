# MI-SSSEP 联合实验设计

## 概述

同时进行运动想象 (MI) 和稳态体感诱发电位 (SSSEP) 刺激的实验范式。

## 实验条件

### MI 条件 (3 类, 编码占高 2 bit)

| 条件 | 含义 | 编码 (bit 7-6) |
|------|------|---------------|
| 1 | Left — 左手运动想象, 显示 LeftCue | `01` (64) |
| 2 | Right — 右手运动想象, 显示 RightCue | `10` (128) |
| 3 | None — 不进行运动想象, 无 cue | `11` (192) |

### SSSEP 条件 (14 类, 编码占低 6 bit)

| 序号 | 串口信号 | 说明 |
|------|---------|------|
| 1-14 | 11-24 | 14 种稳态刺激频率, 对应刺激器串口输入 |

### Trigger 编码 (8 bit, 1-255)

```
Trigger = (MI_code << 6) | SSSEP_code
```

| MI | SSSEP | Trigger (bin) | Trigger (dec) |
|----|-------|--------------|---------------|
| Left (1) | 11 | 01 001011 | 75 |
| Left (1) | 13 | 01 001101 | 77 |
| Right (2) | 11 | 10 001011 | 139 |
| None (3) | 11 | 11 001011 | 203 |
| None (3) | 17 | 11 010001 | 209 |

共 3 × 14 = **42 种** trigger 编码。

## Trial 流程

```
┌──────────────────────────────────────────────────────┐
│ Phase 0 (0-2s)  │ Phase 2 (2-6s)     │ Phase 6 (6-10s) │
│                  │                    │                  │
│ 选 MI 条件 (1-3) │ Cue 保持可见       │ 所有 Cue 隐藏    │
│ 选 SSSEP (11-24) │ TaskCue 出现       │                  │
│ 编码 trigger     │ ★ 开始 80 脉冲    │                  │
│ 显示对应 cue     │   每 50ms 发送:   │                  │
│                  │   - ParallelSend(trigger编码)       │
│                  │   - SerialSend(SSSEP频率)           │
│                  │   共 4s = 80 次    │                  │
│                  │                    │                  │
│ Cross ──────────────────────────────────────────────── │
└──────────────────────────────────────────────────────┘
  0s               2s                  6s              10s
```

### 脉冲时序 (Phase 2, 2-6s)

- 频率: 20 Hz (每 50ms 一次)
- 持续: 4 秒
- 次数: 80 次
- 每次发送:
  - **Parallel port (0x3FF8)**: 编码后的 8-bit trigger (MI<<6 \| SSSEP)
  - **Serial port**: SSSEP 频率码 (11-24)

## 实验参数

| 参数 | 值 |
|------|-----|
| 初始延迟 | 5 秒 |
| 总 trial 数 | 60 |
| 单个 trial 时长 | 10 秒 |
| MI 条件数 | 3 (Left/Right/None) |
| SSSEP 条件数 | 14 (11-24) |
| Trigger 编码数 | 42 |
| SSSEP 脉冲频率 | 20 Hz |
| 每 trial 脉冲数 | 80 |
| 全程注视点 | Cross |

## 实体定义

同 MI 场景: Cross, LeftCue, RightCue, TaskCue 及其子实体。

## 与纯 MI 实验的差异

| 方面 | 纯 MI | MI-SSSEP |
|------|-------|----------|
| MI 条件 | 2 (Left/Right) | 3 (Left/Right/None) |
| SSSEP | 无 | 14 频率 |
| 触发输出 | ParallelSend(11/12) | ParallelSend(trigger编码) + SerialSend(频率) |
| Phase 2 | 仅显示 TaskCue | 显示 TaskCue + 80 脉冲 |
| 随机数 | 1 个 (1-2) | 2 个 (1-3, 11-24) |
