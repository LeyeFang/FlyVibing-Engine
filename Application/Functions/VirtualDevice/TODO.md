# Virtual Device Extension — TODO（状态档案）

> 状态: **partial**（波形监视面板 v0.1.0 已交付; 见 README）
> 开发规范: `Doc/ExtDev/extension_dev_protocol.md` · 架构: `Doc/Dev/extension_protocol.md`
> manifest: `extension.json`（id=`virtual`; 含 entry — 可装载; ops 前缀 `ext.virtual.*`）

## 0. 现状（已实现资产映射）

| 资产 | 位置 | 说明 |
|---|---|---|
| **监视面板（本扩展）** | `Application/Functions/VirtualDevice/{extension, virtual_display, virtual_scope}.py` | 实时波形 / 显示滤波 / watch·record / 落盘（2026-10-16 交付） |
| 虚拟设备后端 + 服务 | `Application/Functions/VirtualDevice/`（SigGen.py / service.py）— 本目录 | 进程内后端 + VIRTUAL 服务（引擎自动拉起; pump 模式） |
| 设备门面 | `Application/Functions/VirtualDevice/`（Device.py / ServiceClient.py）— 本目录 | 会话注册表 / 环形缓冲 / 落盘 / 服务协议 |
| 节点族 | 核心 `SigGen` 节点（Init/Start/Stop/Kill/Get + 设备池） | 面板与其共用同一条数据通路（facade） |
| 设计参考 | `Test/_gtec_archive_20261016/`（本地留档, 非分发内容） | 社区设备监视面板设计语言（干净重写为目标） |

## 1. TODO

### a) 面板增强（可选）
- [ ] 视图页框架（当前仅波形页; 真机厂商按需加"设备专属视图页", 参考归档 Impedance 页设计）
- [ ] 长窗口/大通道绘制预算观测（当前 64ch 以内 × 抽到 ≤480 列; 如需再降抽取列数）
- [ ] 频谱小窗（FFT 概览 — 仅在做版本标注后开启）

### b) agent 通道
- [ ] snapshot 增加 `filters` 回显（当前 filters 在 status 里）
- [ ] 多会话支持评估（当前单会话 `panel`; 多设备实验走节点侧设备池）

### c) 节点迁移（已完成求值器出核心）
- [x] `node_pack.py` 声明 SigGen/DevicePool（type/pins/props 不变）
- [x] `evaluator_siggen.py` / `evaluator_pool.py` 迁入本目录，核心不再 import
- [x] 扩展壳 + `ext.virtual.*` 九件套 + 面板
- [ ] widget 声明化（去掉 Editor 对设备类型的硬编码）
- [x] 交接书：`HANDOFF.md`

## 2. 迁移/复用注意

- **本目录是复制模板**: 克隆 → 改 id/名称/门面配置即可做自家设备面板（见 README 厂商指南）。
- 面板绝不 import 编辑器层; 只经 `ctx` 能力 + `Application.Functions` 门面（审查器 C6 白名单）。
- 显示滤波为因果 IIR（实时语义）; 离线分析走独立工具链。
- UI 文本保持 ASCII / FontAwesome（C7 字形图集约束）。

## 3. 验收

- [x] sim 后端: 面板显示合成信号（确定性; `Test/Application/Extensions/test_virtual_panel.py` 数值断言）
- [x] watch/record: 监视不累积录制 / 监视中升级 / watch-only stop 无落盘（同一测试）
- [x] 显示滤波 DSP 数值: highpass 30Hz 压制 10Hz 正弦 / lowpass 15Hz 保留（同一测试）
- [x] 设置持久化（ctx.data_dir/settings.json 沙箱往返）; 窗口关闭事件停流; 无头绘制烟测（含全裁剪帧）
- [x] 审查器零 FAIL（C1-C11 / M1-M6 / F2）
