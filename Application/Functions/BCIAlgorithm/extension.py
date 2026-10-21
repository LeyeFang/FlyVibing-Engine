"""BCI Algorithm extension shell.

The algorithm implementation and node evaluators live in this directory.  This
entry only exposes read-only discovery ops; training still happens through the
graph nodes (InitFBCSP / TrainFBCSP / TestFBCSP / TestCCA).
"""

from __future__ import annotations

from Application.Core.Extension.ExtensionBase import ExtensionBase


class BCIExtension(ExtensionBase):
    id = "bci"
    name = "BCI Algorithm"
    version = "0.1.0"

    def on_load(self, ctx) -> None:
        self.ctx = ctx
        ctx.ops.register("status", self._op_status,
                         summary="BCI extension status / registered packs")
        ctx.ops.register("models", self._op_models,
                         summary="List registered BCI models (spec / trained)")
        ctx.ops.register("datasets", self._op_datasets,
                         summary="List registered epoch datasets")
        ctx.log("loaded — node pack + evaluators owned by this extension")

    def _op_status(self, args: dict) -> dict:
        catalog = self.ctx.nodes.catalog() if getattr(self.ctx, "nodes", None) else []
        return {
            "extension": self.id,
            "version": self.version,
            "maturity": "partial",
            "nodes": sorted({str(item.get("type")) for item in catalog}),
            "ops": ["ext.bci.status", "ext.bci.models", "ext.bci.datasets"],
        }

    def _op_models(self, args: dict) -> dict:
        from Application.Functions.BCIAlgorithm import list_entries

        return {"models": list_entries()}

    def _op_datasets(self, args: dict) -> dict:
        from Application.Functions.BCIAlgorithm import list_datasets

        return {"datasets": list_datasets()}


def create_extension() -> BCIExtension:
    return BCIExtension()
