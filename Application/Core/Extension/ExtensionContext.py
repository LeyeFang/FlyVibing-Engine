"""ExtensionContext — 扩展上下文门面（纯数据容器 + 日志）。

能力注入模型（见 Doc/ExtDev/extension_dev_protocol.md §5）:
  - 由 ExtensionManager 构造并注入可用能力;
  - 实装: ops / ui.register_window / graph / nodes（M1）/ examples（M1）/ log / 目录信息;
  - 设计未实装: threads / jobs / settings（M2/M1, 按 capabilities 发放）;
  - 未注入的能力属性为 None（扩展应做能力检测, 不得假设存在）。

★ 本文件属 Core（GUI 无关）; ops 注册器由 Editor 侧注入, Core 不依赖 Editor。
"""

from __future__ import annotations


def _resolve_output_dir(engine_root: str) -> str:
    """扩展的默认数据落点（绝对路径）。

    优先用当前 Engine 已设置的输出根（PIE/成品由宿主注入），否则
    `<引擎>/output`。**绝不返回 CWD** —— 成品里 CWD 就是成品目录，
    往那里写会污染安装目录（装到只读位置还会直接失败）。
    """
    try:
        from Application.Core.FileSystem.DataPaths import data_roots
        roots = data_roots()
        if roots.get("output"):
            return roots["output"]
    except Exception:      # noqa: BLE001 — 无引擎上下文单测：退回引擎根
        pass
    return engine_root.rstrip("\\/") + "/output"


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
        # 默认数据落点（写文件请用它，不要用 os.getcwd()）——
        #   编辑器里 = <引擎>/output；PIE/成品 = <工程|成品>/output。
        #   见 Application/Core/FileSystem/DataPaths.py（相对路径默认落在 output/）。
        self.output_dir: str = _resolve_output_dir(engine_root)

        # ── 能力门面（由 ExtensionManager 注入; 未实装的能力保持 None） ──
        self.ops = None      # M0: _ExtensionOpRegistrar — ctx.ops.register(name, fn, summary="")
        self.ui = None       # M1: register_window / register_command / post
        self.threads = None  # M2: spawn / stop_all
        self.jobs = None     # M2: submit → Future
        self.settings = None # M1: schema 化设置（持久化 + 自动 UI）
        self.nodes = None    # M1: NodePack 注册（manifest capabilities 含 nodes 时注入）
        self.graph = None    # M1: 受限图访问（capabilities 含 "graph" 才注入 —
                             #     见 Application/Editor/Extensions/ExtensionGraph.py）
        self.examples = None # M1: 扩展示例根目录（capabilities 含 "examples" 才注入 —
                             #     register(root) / unregister(root)；扩展自带
                             #     <extension_dir>/Examples 由宿主自动登记，见
                             #     Application/Editor/Extensions/ExtensionExamples.py）

    # ════════════════════════════════════════════════════════════
    # 基础能力（M0）
    # ════════════════════════════════════════════════════════════

    def log(self, msg: str) -> None:
        """日志 — 统一前缀 [ext:<id>]（未来接入 Console 过滤通道, dev protocol §5.5）。"""
        print(f"[ext:{self.id}] {msg}")
