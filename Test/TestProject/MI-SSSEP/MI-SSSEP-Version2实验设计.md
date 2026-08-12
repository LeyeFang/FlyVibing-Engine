# MI-SSSEP-Version2 精简实验设计

## 概述

MI-SSSEP 的精简修改版。基于 MI-SSSEP 场景，仅修改节点图。沿用在 MI-SSSEP 原 Scene 的模板 entity。

## 与原始 MI-SSSEP 的差异

| 方面 | MI-SSSEP (原版) | MI-SSSEP-Version2 (精简版) |
|------|----------------|---------------------------|
| SSSEP 条件数 | 14 (11-24) | 8 (11,12,13,15,17,19,21,23) |
| SSSEP 选择方式 | Random(11, 24) 直接取值 | Random(1, 8) 索引映射 |
| Trigger 编码 | `(MI << 6) \| SSSEP` | `(MI << 5) \| SSSEP` |
| MI 基值 (Left) | 64 | 32 |
| MI 基值 (Right) | 128 | 64 |
| MI 基值 (None) | 192 | 96 |
| SSSEP 计算时机 | Phase 0 内实时计算 | OnGameStart + 每 trial 结束时预计算 |

## 实验条件

### SSSEP 条件 (8 类)

| 索引 | SSSEP 值 | 串口信号 |
|------|---------|---------|
| 1 | 11 | 11 |
| 2 | 12 | 12 |
| 3 | 13 | 13 |
| 4 | 15 | 15 |
| 5 | 17 | 17 |
| 6 | 19 | 19 |
| 7 | 21 | 21 |
| 8 | 23 | 23 |

选取规则: 从 13 开始隔一个抽一个。即：11, 12, 13 (连续3个), 然后 15, 17, 19, 21, 23 (步长2)。

### MI 条件 (3 类, 不变)

| 条件 | 含义 | 编码 (bit 6-5) |
|------|------|---------------|
| 1 | Left — 左手运动想象, 显示 LeftCue | `01` (32) |
| 2 | Right — 右手运动想象, 显示 RightCue | `10` (64) |
| 3 | None — 不进行运动想象, 显示 NullCue | `11` (96) |

### Trigger 编码 (8 bit)

```
Trigger = (MI_code << 5) | SSSEP_code
```

前 5 位 (bit 0-4): SSSEP 条件编码
第 6-7 位 (bit 5-6): MI 条件编码
第 8 位 (bit 7): 未使用 (恒为 0)

| MI | SSSEP | Trigger (bin) | Trigger (dec) |
|----|-------|--------------|---------------|
| Left (1) | 11 | 00 01 01011 | 43 |
| Left (1) | 13 | 00 01 01101 | 45 |
| Right (2) | 11 | 00 10 01011 | 75 |
| Right (2) | 15 | 00 10 01111 | 79 |
| None (3) | 11 | 00 11 01011 | 107 |
| None (3) | 23 | 00 11 10111 | 119 |

共 3 × 8 = **24 种** trigger 编码。

## Trial 流程

```
┌──────────────────────────────────────────────────────┐
│ Phase 0 (0-2s)  │ Phase 2 (2-6s)     │ Phase 6 (6-10s) │
│                  │                    │                  │
│ 选 MI 条件 (1-3) │ Cue 保持可见       │ 所有 Cue 隐藏    │
│ SSSEP 已预计算   │ TaskCue 出现       │                  │
│ 显示对应 cue     │ ★ 开始 80 脉冲    │                  │
│ 编码 trigger     │   每 50ms 发送:   │                  │
│                  │   - ParallelSend(trigger编码)       │
│                  │   - SerialSend(SSSEP频率)           │
│                  │   共 4s = 80 次    │                  │
│                  │                    │                  │
│ Cross ──────────────────────────────────────────────── │
└──────────────────────────────────────────────────────┘
  0s               2s                  6s              10s
```

### SSSEP 预计算机制

- **首次计算**: OnGameStart 链末尾 (第 1 个 trial 使用)
- **后续计算**: 每个 trial 的 Phase 10 末尾 (为下一个 trial 准备)

预计算流程:
1. Random(1, 8) → sss_idx
2. 如果 sss_idx ≤ 3: sss_code = sss_idx + 10
3. 否则: sss_code = sss_idx × 2 + 7

### 脉冲时序 (Phase 2, 2-6s, 不变)

- 频率: 20 Hz (每 50ms 一次)
- 持续: 4 秒
- 次数: 80 次
- 每次发送:
  - **Parallel port (0x3FF8)**: trigger 编码 (MI<<5 | SSSEP)
  - **Serial port (COM3, 9600)**: SSSEP 频率码

## 实验参数 (不变)

| 参数 | 值 |
|------|-----|
| 初始延迟 | 5 秒 |
| 总 trial 数 | 60 |
| 单个 trial 时长 | 10 秒 |
| MI 条件数 | 3 (Left/Right/None) |
| SSSEP 条件数 | 8 (11,12,13,15,17,19,21,23) |
| Trigger 编码数 | 24 |
| SSSEP 脉冲频率 | 20 Hz |
| 每 trial 脉冲数 | 80 |
| 全程注视点 | Cross |

## 实体定义

沿用 MI-SSSEP 原 Scene 的所有 entity 模板:
- Cross (含子实体 row, col)
- LeftCue (含子实体 L_arrow_body, L_arrow_head)
- RightCue (含子实体 R_arrow_body, R_arrow_head)
- TaskCue
- NullCue (含子实体 part1, part2)
- DefaultCamera3D, DefaultCamera2D, DefaultCameraOverlay

## 节点图变更摘要

1. **Random SSSEP (node 246)**: `min=1, max=8` (原 `11, 24`)
2. **MI 基值常量**: `32/64/96` (原 `64/128/192`), 对应 `MI<<5`
3. **Phase 0 简化**: TimeTrigger(t=0) 直接进入 MI 分支, 不再设置 sss_code
4. **SSSEP 预计算链** (新增 ~22 节点):
   - OnGameStart 末尾: 计算首个 trial 的 sss_code
   - Phase 10 末尾 (False 分支): 计算下一 trial 的 sss_code
5. **节点 247 (旧 VarSet sss_code) 已移除**, 由新的 VarSet sss_code 节点替代
