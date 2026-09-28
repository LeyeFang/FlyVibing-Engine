"""
Evaluators: Entity 节点 — 实体生命周期 + 类型安全引用 (EntityRef)。

v1 节点 (裸 int EntityID):
  EntityDestroy       → destroy.py
  EntityAddMesh       → mesh.py
  EntityAddCamera     → camera_entity.py
  EntitySetRenderVisible → render_visible.py

v2 节点 (EntityRef):
  EntitySpawn         → lifecycle.py
  CameraSetMain       → camera.py
  ComponentAdd / SetComponent / GetComponent / ComponentRemove → component.py

辅助:
  resolve_entity_id   → helpers.py
"""

from __future__ import annotations

# ── v1: 裸 int EntityID 节点 ──────────────────────────────────
from . import destroy         # noqa: F401 — EntityDestroy
from . import mesh            # noqa: F401 — EntityAddMesh
from . import camera_entity   # noqa: F401 — EntityAddCamera
from . import render_visible  # noqa: F401 — EntitySetRenderVisible

# ── v2: EntityRef 节点 ───────────────────────────────────────
from . import lifecycle  # noqa: F401 — EntitySpawn
from . import camera     # noqa: F401 — CameraSetMain
from . import component  # noqa: F401 — ComponentAdd, SetComponent, GetComponent, ComponentRemove
