# eCon — 念通科技（econEXG）品牌目录（预留）

## 状态

**预留占位**：API 尚未接入。`service.py` 目前直接报未实现并退出。

## 接入清单（未来）

1. `backend.py`：用 econEXG API 实现 `DeviceBackend`
   （`configure / start / stop / close / pump / info`；`configure` 内懒导入 API）；
2. `service.py`：改为 `run_service("econ", <mode>, ...)`（借鉴 `Gtec/service.py`）；
3. 门面 `EEGDevice._make_backend`：新增路由 `cfg.device == "ECON"`（连接 `MGE_ECON_SERVICE`）；
4. 节点侧：沿用现有五件套（Init/Start/Stop/Kill/Get 通过 `device` 配置路由）；
5. 测试：参照 `Test/Application/Functions/test_eeg_service.py`（进程机制）
   与 `test_gtec_device.py`（品牌链路）。

## 目录契约（与 Gtec / VirtualDevice 一致）

- 品牌 = 独立进程文件应用；通信 = `EEGDevice.ServiceProtocol/ServiceHost`；
- 环境：自有环境（本品牌），随品牌目录携带（开发 = venv；导出 = 成品环境，按引用选择性导出）。
