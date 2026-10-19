# Third-Party Notices

This distribution includes third-party components. Their licenses are reproduced or
referenced below. If you redistribute this package, keep this file with it.

## Fonts

### Roboto

- File: `Resource/Fonts/Roboto-Regular.ttf`
- Copyright: Copyright 2011 Google Inc. All Rights Reserved.
- License: Apache License, Version 2.0
- License text: <https://www.apache.org/licenses/LICENSE-2.0>
- Upstream: <https://fonts.google.com/specimen/Roboto>

### Font Awesome Free

- File: `Resource/Fonts/fontawesome-webfont.ttf`
- Copyright: Fonticons, Inc. and contributors.
- License: SIL Open Font License 1.1 (font); CC BY 4.0 (icons)
- License texts: <https://fontawesome.com/license/free>
- Upstream: <https://fontawesome.com/>

## Python and runtime components

### CPython

- Location: `Resource/runtime/` (when bundled)
- License: Python Software Foundation License 2.0
- License text: `Resource/runtime/LICENSE.txt` (shipped with the runtime image);
  <https://docs.python.org/3/license.html>

### certifi

- License: Mozilla Public License 2.0 (the bundled CA certificate set has its own
  redistribution terms)
- License text: <https://www.mozilla.org/en-US/MPL/2.0/>
- Upstream: <https://github.com/certifi/python-certifi>

## Python packages shipped in the runtime image

The runtime image also contains the packages from `Resource/wheels/requirements.export.txt`
and their transitive dependencies. Each package retains its own license metadata in its
distribution directory (`.dist-info`). Principal components include:

- `imgui-bundle` / Dear ImGui / ImPlot — MIT
- GLFW — zlib/libpng
- NumPy — BSD-3-Clause
- SciPy — BSD-3-Clause
- Pillow — HPND
- esper — MIT

When updating the runtime image, regenerate this notice if the package set changes.
