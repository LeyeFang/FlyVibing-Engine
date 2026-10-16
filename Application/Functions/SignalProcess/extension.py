"""SignalProcess Extension — 骨架入口（M0, 可装载）。

当前贡献: `ext.sigproc.info`（ops 通道样例 — 验证扩展 op 增量扫描链路）。
节点族实现见 TODO.md（skeleton 阶段）。
"""

from Application.Core.Extension.ExtensionBase import ExtensionBase


class SignalProcessExtension(ExtensionBase):
    id = "sigproc"
    name = "Signal Process"
    version = "0.1.0"

    def on_load(self, ctx) -> None:
        self.ctx = ctx
        ctx.ops.register("info", self._op_info, summary="SignalProcess 扩展状态（骨架）")
        ctx.log("loaded (skeleton) — node family pending, see TODO.md")

    def _op_info(self, args: dict) -> dict:
        return {
            "extension": self.id,
            "maturity": "skeleton",
            "planned_nodes": [
                "SignalProcessorInit",   # a) 初始化: 配置模板 + 输入形状维度语义
                "BandpassFilter",        # b) 滤波器: 类型/阶数/上下截止 (即时 in→out)
                "Reference",             # c) 参考: 通道 / 均值 / 拉普拉斯 (动态模板依赖)
                "FFT / SDFT / CWT / Hilbert",  # d) 变换族
                "BadChannelDetect",      # e) 坏道
                "ICA",                   # f) 独立成分分析
            ],
            "note": "迁移与落地清单见 Application/Functions/SignalProcess/TODO.md",
        }


def create_extension() -> SignalProcessExtension:
    return SignalProcessExtension()
