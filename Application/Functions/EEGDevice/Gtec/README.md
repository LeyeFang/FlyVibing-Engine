# Gtec — g.tec g.HIamp 品牌目录（独立进程文件应用）

## 角色

本目录是 g.tec 设备接入的**独立单元**：后端实现 + 服务进程入口 +（未来）随附运行环境。
引擎经协议与该进程通信；节点图一侧（`IO ▸ Gtec`）无需改动即可耦合。

## 组成

| 文件 | 职责 |
|---|---|
| `Gtec.py` | 真实后端 `GtecHiampBackend`（pygds 懒导入；需 GDS 服务 + 空闲设备） |
| `GtecStub.py` | 空跑后端 `GtecStubBackend`（干跑 / MCP 验证；不触硬件、不落盘） |
| `service.py` | 服务进程入口（`push` 模式；自有环境运行，外部启动） |

## 环境（本品牌与其他不同：**自有环境**）

- 服务进程运行于 g.tec 环境（示例：`C:\WorkSpace\FLY\GtecAPI\.venv`，Python 3.9 + pygds）；
  引擎环境（3.14t）不安装 pygds —— 跨进程通信正是为此设计。
- 启动示例（自有环境内、仓库根目录为 cwd）：
  `python -m Application.Functions.EEGDevice.Gtec.service --port 47810`
- 引擎侧连接：`MGE_GTEC_SERVICE=host:port`（默认 `127.0.0.1:47810`）；连接失败时报错含启动提示与服务日志尾部。

## 数据模式

**push**：start 后采集线程逐块推送（`{"type":"block","data":…}`）→ 引擎接收线程写会话环形缓冲；
保存仍在引擎侧（`StopGtecRecord` 的落盘逻辑不变）。客户端断开 → 服务进程自动退出（不驻留）。

## 备忘（规划）

- 随品牌目录携带环境：开发期 = venv；导出 = 成品环境同目录携带，且**仅在项目引用时随导出**；
- 多设备协同 / hyper-scanning 的设备池管理见 `Doc/Dev/device_io_protocol.md` §7。
