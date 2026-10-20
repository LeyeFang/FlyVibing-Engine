"""ExtensionContext — 扩展上下文门面（纯数据容器 + 日志）。

能力注入模型（见 Doc/ExtDev/extension_dev_protocol.md §5）:
  - 由 ExtensionManager 构造并注入可用能力;
  - 实装: ops / ui.register_window / graph / nodes（M1） / log / 目录信息;
  - 设计未实装: threads / jobs / settings（M2/M1, 按 capabilities 发放）;
  - 未注入的能力属性为 None（扩展应做能力检测, 不得假设存在）。

★ 本文件属 Core（GUI 无关）; ops 注册器由 Editor 侧注入, Core 不依赖 Editor。
"""

from __future__ import annotations


class ExtensionContext:
    """扩展上下文 — 传透给 ExtensionBase.on_load。"""

    def __init__(
        self,
        *,
        extension_id: str,
        name: str,
        version: str,
        manifest: dict,
        extension_dir: str,
        data_dir: str,
        engine_root: str,
    ) -> None:
        self.id: str = extension_id
        self.name: str = name
        self.version: str = version
        self.manifest: dict = dict(manifest or {})
        self.capabilities: list = list(manifest.get("capabilities", []) if manifest else [])
        self.extension_dir: str = extension_dir     # 扩展文件目录（只读资产）
        self.data_dir: str = data_dir               # 扩展可写数据目录（隔离; 由 Manager 创建）
        self.engine_root: str = engine_root

        # ── 能力门面（由 ExtensionManager 注入; 未实装的能力保持 None） ──
        self.ops = None      # M0: _ExtensionOpRegistrar — ctx.ops.register(name, fn, summary="")
        self.ui = None       # M1: register_window / register_command / post
        self.threads = None  # M2: spawn / stop_all
        self.jobs = None     # M2: submit → Future
        self.settings = None # M1: schema 化设置（持久化 + 自动 UI）
        self.nodes = None    # M1: NodePack 注册（manifest capabilities 含 nodes 时注入）
        self.graph = None    # M1: 受限图访问（capabilities 含 "graph" 才注入 —
                             #     见 Application/Editor/Extensions/ExtensionGraph.py）

    # ════════════════════════════════════════════════════════════
    # 基础能力（M0）
    # ════════════════════════════════════════════════════════════

    def log(self, msg: str) -> None:
        """日志 — 统一前缀 [ext:<id>]（未来接入 Console 过滤通道, dev protocol §5.5）。"""
        print(f"[ext:{self.id}] {msg}")
