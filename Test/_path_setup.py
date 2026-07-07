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
