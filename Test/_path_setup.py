"""
Test path initialisation — import this BEFORE any Application.* imports.

Usage (from Test/ directly):
    import _path_setup

Usage (from Test/SubDir/.../test_xxx.py):
    import sys, os
    # Walk up to find Test/ directory
    _d = os.path.dirname(os.path.abspath(__file__))
    while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
        _d = os.path.dirname(_d)
    if _d:
        sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

Principle:
  Finds the project root (where Application/ lives) by walking up from
  this file's location.  Works regardless of how deep the test file is
  nested inside Test/.
"""

import sys
import os


def _find_project_root() -> str:
    """Walk up from this file until we find the project root.

    The project root is identified by the presence of 'Application/EntryPoint.py'
    (NOT just any 'Application/' directory — Test/ also has one).
    Returns the absolute path to the project root.
    """
    start = os.path.dirname(os.path.abspath(__file__))
    root = start
    while root:
        # Use a specific marker file that only exists in the real project root
        if os.path.isfile(os.path.join(root, 'Application', 'EntryPoint.py')):
            return root
        parent = os.path.dirname(root)
        if parent == root:       # reached filesystem root
            break
        root = parent
    # Fallback: assume this file is in Test/, project root is parent
    return os.path.dirname(start)


_project_root = _find_project_root()

if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Switch working directory to project root (for ResourceManager relative paths)
os.chdir(_project_root)


# ── Extension state sandbox (2026-11-13) ───────────────────────────────────
# `ExtensionPanel.visible` persists to extensions.json on **every** write (that
# is the point of the property setter — one choke point for menu / View menu /
# `ui.panel` op / user X / detach).  Consequence: a test that merely shows a
# panel would silently rewrite the developer's real settings at
# `<APPDATA>/FlyVibingEngine/editor_state/extensions.json`.
#
# Point every test process at a throwaway state/data pair unless the test
# (or the caller) already chose one.  A test that needs its own sandbox still
# wins because it assigns after importing this module.
if not (os.environ.get("FVE_EXTENSIONS_STATE")
        or os.environ.get("MGE_EXTENSIONS_STATE")):
    import tempfile as _tempfile

    _ext_sandbox = _tempfile.mkdtemp(prefix="fve_test_ext_state_")
    os.environ["FVE_EXTENSIONS_STATE"] = os.path.join(_ext_sandbox, "extensions.json")
    os.environ.setdefault("FVE_EXTENSIONS_DATA", os.path.join(_ext_sandbox, "data"))
