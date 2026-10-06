---
name: node-graph
description: "构建/修改 .scene 里的实验节点图（离线通道 — 不需要引擎运行）: 按节读规则、实验 spec→节点图（build_graph）、注入 .scene（apply）。Use when the user asks to generate or edit experiment node graphs from a spec, wire trials/cues/triggers, or apply a graph JSON into a scene file. 校验/实时编辑请用 engine-editor skill（引擎内服务）。通道: python -m Utils.User.NodeEditor.cli（终端首选）或 node-graph-editor MCP（get_rules/get_scene_entities/build_graph/apply_graph）。"
---

# Node Graph 离线构建（MyGameEngine）

从**实验描述 spec** 生成节点图并写入 `.scene`；或按节查阅节点参考。与引擎运行状态无关。
（引擎运行时的实时编辑/校验/截图 → 用 `engine-editor` skill。）

## 0. 通道选择

| 通道 | 常驻成本 | 何时用 |
|---|---|---|
| `python -m Utils.User.NodeEditor.cli`（终端） | **0** | 默认首选（任意终端型 agent） |
| MCP `node-graph-editor`（4 工具） | ~1.5k 字符 schema | 无终端的环境 |

相对路径均基于**引擎仓库根**（部署副本里 = 项目根）。

## 1. 规则查询（渐进披露 — 别拉全文）

```powershell
python -m Utils.User.NodeEditor.cli rules                # 目录（各节标题+规模）— 先看这个
python -m Utils.User.NodeEditor.cli rules "Connection Rules"
python -m Utils.User.NodeEditor.cli rules "Gtec"         # 子标题可单独取
python -m Utils.User.NodeEditor.cli rules "build_graph Spec"
python -m Utils.User.NodeEditor.cli rules --all --out rules_full.md   # 只在真需要全文时（落盘+摘要）
```

MCP 等价: `get_rules()`（目录）/ `get_rules(section="Gtec")` / `get_rules(section="all")`。

## 2. spec → 图 → scene（一条龙）

```powershell
python -m Utils.User.NodeEditor.cli build --spec spec.json --out graph.json   # 只回摘要
python -m Utils.User.NodeEditor.cli apply --scene scenes/My.scene --graph graph.json
```

spec 字段/示例见 `rules "build_graph Spec"`。要点:

- `phases[]`: `cue_pick`（随机分支+显隐+并行口触发）/ `action|show` / `trial_end`；
- `pulse`（可选）: 50ms 发送循环（count/interval/parallel_addr/serial_port/encode）；
- `entities[]` 先 spawn 后统一隐藏；seed 链固定挂 OnGameStart。

**校验（必做）**: 启动引擎后用引擎内服务 —
`engine-editor-cli validate --source graph --graph @graph.json`（或 MCP `engine_validate_graph`），
零告警再交付；无头环境用 `PlayerEntry --dry-run`。

## 3. 场景实体查询

```powershell
python -m Utils.User.NodeEditor.cli entities scenes/My.scene
```

MCP: `get_scene_entities(scene_path)`。

## 4. Token 纪律

- 规则文档**永远先看目录**、按节取；不要把 `--all` 全文或整图 JSON 打印进上下文。
- `build --out` / `rules --out` 落盘 + 摘要回读；需要检查内容时只读关心的片段。
- 多步（build→apply→validate）在同一条命令链里完成，避免多次往返。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| `unknown section` | 先跑无参 `rules` 看准确标题（支持子标题模糊匹配） |
| spec 构建报 KeyError | 对照 `rules "build_graph Spec"` 的字段表检查拼写 |
| apply 后图没生效 | 确认写入的是当前工程加载的 .scene（引擎需重新加载/打开） |
| 校验报错 | 用引擎内 validate 的 summary 定位 node_id → `rules` 查该节点类型规则 |
