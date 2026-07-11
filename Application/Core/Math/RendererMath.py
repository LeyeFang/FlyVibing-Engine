"""
RendererMath — BACKWARD-COMPATIBILITY SHIM
==========================================

This file is kept for backward compatibility. All math functions have been
moved to Core.Math submodules and now accept plain numeric parameters
(no ECS/Scene dependency).

  from Application.Core.Math.Transform import calculate_entity_model
  from Application.Core.Math.Camera import (
      calculate_view_matrix, calculate_projection_matrix, get_world_forward
  )
  from Application.Core.Math import *  # re-exports everything

For ECS convenience, use self.engine.scene.GetEntityModelMatrix(entity_id).

Please update your imports to use the new locations.

See Application/Core/Math/__init__.py for the full matrix convention documentation.
"""

# Re-export from new locations for backward compatibility
from Application.Core.Math.Transform import calculate_entity_model
from Application.Core.Math.Camera import (
    calculate_view_matrix,
    calculate_projection_matrix,
    get_world_forward,
)