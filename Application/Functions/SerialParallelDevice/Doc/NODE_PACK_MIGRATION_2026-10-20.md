# Serial/Parallel 节点包迁移与开发须知（2026-10-20）

> 读者：Serial/Parallel 扩展维护者（下一任接手人）、外部 Extension 开发者。
> 本文记录 2026-10-20 的节点注入改造，以及 Serial 侧需要补的收尾工作。

## 1. 本次已改什么

1. **核心不再声明 SerialSend / ParallelSend**
   - 已从 `Application/Core/NodeGraph/node_types/io.py` 移除这两个节点类型；
   - `Application/Core/NodeGraph/node_types/device_pool.py`、`siggen.py`、`epoch.py`、`bci_algorithm.py` 也已完成职责迁出（节点定义不再由核心注册）。
2. **设备节点包已建立**
   - 本目录新增 `node_pack.py`（纯声明 + Serial/Parallel evaluator）；
   - type 名保持 `SerialSend` / `ParallelSend` 不变（MI-SSSEP 兼容红线）；
   - `NodeGraph` 会自动发现 `Application/Functions/**/node_pack.py`，**不需要扩展 enable**；
   - Add 菜单的 `Device` 分区由 pack 的 `menu` 动态生成。
3. **求值器已收回本扩展**
   - Serial/Parallel 的求值逻辑从 `Core/NodeGraph/evaluators/io.py` 移到本目录 `node_pack.py`；
   - 运行期通过 pack 的 `evaluator` 注册，dry-run 语义保持不变。
4. **Agent 工具已补齐**
   - 新 op `graph.types`：列出核心/扩展节点类型、引脚、owner；
   - `extension.list` 的每个 extension 增加 `nodes`；
   - `graph.add` 返回 `owner` + `pins`，且**不要求连线**（可先建节点池）；
   - `graph.add` 未知类型会给出相近类型提示。

## 2. 验证命令（Serial 侧提交前必须跑）

```powershell
# 1) 节点类型自动发现（无需启动编辑器）
.venv-py314t\Scripts\python.exe -c "from Application.Core.NodeGraph import _TYPES; print('SerialSend' in _TYPES, 'ParallelSend' in _TYPES)"

# 2) 设备语义回归
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_serial_parallel_device.py
.venv-py314t\Scripts\python.exe Test\Application\Functions\test_device_alias.py

# 3) 实机（可选但推荐）：启动编辑器后
engine-editor-cli call graph.types owner=device
# PowerShell 会把内联 JSON 的引号吃掉，批量带 props 时用文件传参：
$argsPath = Join-Path $env:TEMP "node_add_args.json"
@'{"type":"SerialSend","props":{"port":"@SSSEP-Stimulator","baud_rate":9600,"format":"bytes"}}'@ |
    Set-Content $argsPath -Encoding utf8
engine-editor-cli call graph.add --json "@$argsPath"
engine-editor-cli call graph.list          # 节点应在池中，即使没有连线
```

## 3. Serial 侧待补/确认

- [x] `SerialSend` / `ParallelSend` 的卡片控件已由 `node_pack.py` 的 `fields` 通用控件接管；核心 `flow_io.py` 不再保留这两个节点的自定义控件。
- [ ] 若以后 `fields` 不足以表达交互（例如需要“扫描端口”按钮），先在 host 增加 `node_widgets.py` 注册协议，再在本目录实现；**不要**把控件逻辑写回核心。
- [x] 把本文件的 evaluator 依赖（`Application.Functions.SerialParallelDevice`）保持在扩展目录内，不要把新逻辑再写回 `Core/NodeGraph`。
- [x] `node_pack` 注册/发现已有工具包测试；图级回归已补：`Test/Application/NodeGraph/test_node_pack.py` 17/17（自动发现 / 无连线持久化 / unload 反注册）。
- [x] `extension_dev_protocol.md` §8 已记录 `nodes` 能力、pack schema、发现与反注册规则。
- [x] 本扩展 `HANDOFF.md` 的节点清单已补 `node_pack.py` / `identity.py` 行。
- [x] 已重新导出 MI-SSSEP 成品包（`Paradigm/rst/MI-SSSEP`，2026-10-20） —— 部署副本带 `node_pack.py`/`identity.py`；
  旧成品（2026-10-19，无节点包且 `ScalarMath` 仍有 `mul` 缺陷）留档在 `Paradigm/rst_old_20261019/`。
- [ ] 确认 MI-SSSEP 的旧场景（`SerialSend` / `ParallelSend`）在扩展 pack 自动发现后可直接加载；若图里出现 missing extension，先检查 `node_pack.py` 是否被自动发现。

## 4. 开发约束（不要绕过）

- `node_pack.py` **禁止 import Editor / imgui**；它同时会被导出成品运行时加载。
- type 名是持久化契约：`SerialSend` / `ParallelSend` 不改名、不改 pin 名；新增节点建议 `ext.device.<Name>`。
- 节点类型不得覆盖其他 owner 已注册的 type（`NodePackError`）。
- 节点可以没有连线：NodeCanvas 的 node/link 是两张表；`graph.add` 只创建节点，不要求 `graph.link`。
- 未安装/未发现 pack 时，图节点应被视为 missing extension；不要静默丢节点。
- 真实串口/并口 I/O 仍由本扩展的 IO 线程执行；pack evaluator 只做参数读取、编码、入队。

## 5. 关联文档

- `HANDOFF.md` / `TODO.md`（本扩展交接与 backlog）
- `Application/Core/NodeGraph/node_packs.py`（注册表实现）
- `Application/Editor/Services/LiveCommandServer.py`：`graph.types` / `graph.add`
- `engine-editor-cli doc show extdev/extension_dev_protocol#8`（节点包规范）
- `engine-editor-cli doc show dev/editor_live_protocol#4`（graph ops）

## 6. 已知遗留（不阻塞 Serial 迁移）

- `VirtualDevice` / `BCIAlgorithm` / `Epoch` 的**求值器实现**仍在
  `Application/Core/NodeGraph/evaluators/{siggen,device_pool,epoch,bci_algorithm}.py`；
  本次只迁出节点类型/菜单/字段，`node_pack.py` 通过核心 evaluator 继续工作。
  后续应由对应扩展维护者把 evaluator 收回到各自目录，并补 `node_pack` 的 evaluator 字段。
- `Application/Core/NodeGraph/graph_constraints.py` / `graph_rules.py` 仍含设备、epoch、BCI
  的图语义规则与 AI 提示词；外部 agent 的**实时发现**走 `graph.types`，但离线规则仍以核心
  规则表为主。彻底解耦需要给 node pack 增加 `constraints` / `rules` 贡献点。
- 扩展节点的复杂自定义控件（如需按钮/动态行）目前仍需核心 `widgets` 注册；声明式 `fields`
  已覆盖 Serial 的 port/baud/format 与 Parallel 的 address/mode/value。
