# 用户通知草稿 —— Serial/Parallel 设备扩展迁移（2026-11-10）

> 状态: **草稿**。等主线完成 P0/P1 兼容移除后，再按最终版本号/日期定稿发布。
> 依据: `Doc/MAINLINE_COUPLING_AUDIT_2026-11-10.md` + `Doc/MAINLINE_DECOUPLING_PLAN_2026-11-10.md`
> 发送对象: 使用 `SerialSend` / `ParallelSend` / `@设备名` 的实验作者与部署维护者。

---

## 1. 一句话

设备节点、属性名、`@设备名` 语法和 `devices.json` 位置都没有变；旧工程不需要改场景。
本次变化是**归属迁移**（实现从引擎主线收回 Serial/Parallel 扩展），不是节点协议变更。

## 2. 没有变的（兼容承诺）

| 项 | 状态 |
|---|---|
| 节点类型 `SerialSend` / `ParallelSend` | 不变 |
| 引脚名 `exec_in / exec_out / Value / Address` | 不变 |
| 属性键 `port / baud_rate / format / prefix / suffix / address / mode / value` | 不变 |
| `@别名` 语法与"未绑定显式报错" | 不变 |
| 台账文件 `devices.json`（`FVE_DEVICES_FILE` / `MGE_DEVICES_FILE` 覆盖） | 不变 |
| 9 个 `ext.device.*` op 的名称与参数 | 不变（`status` 多一个 `registry_backend` 诊断字段） |
| 并口单字节语义（1–255，0 保留自动复位） | 不变 |
| 面板 / Device Manager 操作 | 不变 |

## 3. 需要你确认的（升级后自查 3 分钟）

1. **别名仍指向正确的口**（换机器/换 USB 口后必须做）：
   ```powershell
   engine-editor-cli call ext.device.status
   ```
   - `devices` 里 `@SSSEP-Stimulator -> COMx` 正确即可；
   - 显示 `(unbound)` 或口号变了：运行 `engine-editor-cli call ext.device.autobind`，
     或在面板 **Device Manager** 重新绑定。
2. **串口协议版本**：
   - 刺激器协议 v2 要求每行带重复率（如 `40,14`）→ `SerialSend.prefix = "40,"`；
   - 旧工程若没填 prefix，实发仍是 `14.0` 形式；升级后请检查 20 Hz / 40 Hz 场景的 prefix。
3. **并口 Trigger**：仍发送单字节 1–255；不要手动发 0（0 表示复位）。
4. **升级方式**：引擎与扩展现版本一起升级；`Paradigm/rst/*` 成品包是自包含快照，
   不受仓库迁移影响。**不要**把旧版扩展目录与新引擎混用。

## 4. 受影响的示例工程（我们已知的）

| 来源 | 场景数 | SerialSend | ParallelSend |
|---|---:|---:|---:|
| MI-SSSEP 扩展 `Examples/`（7 个） | 7 | 7 | 14 |
| 引擎 `Examples/`（MI / RestingState / SerialPulse / ParallelPulse） | 4 | 1 | 6 |
| `Gtec/Examples`（GtecRestingState） | 1 | 0 | 1 |
| `Test/TestProject/MI-SSSEP`（3 个） | 3 | 2 | 7 |
| **合计** | **15** | **10** | **28** |

这些场景在迁移后应**直接可加载**；若出现 `device_alias_unresolved`，按 §3-1 重新绑定即可。

## 5. 回滚/求助

- 出现设备找不到：先 `ext.device.status` → `ext.device.autobind` → 仍失败再手工 `bind_alias`。
- 串口无输出：确认 `format`（`string` 还是 `bytes`）、`baud_rate`、prefix 是否与设备协议一致。
- 需要保留旧行为：使用对应的 `Paradigm/rst/*` 成品包（含当时的引擎副本），不要与新版混搭。

---

> 发布前请补充：版本号、发布日期、`ext.device.status` 截图（本机）、MI-SSSEP 7 个示例的
> 干跑结果（`engine-editor-cli validate`）。
