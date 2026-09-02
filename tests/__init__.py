# -*- coding: utf-8 -*-
"""
Test bootstrap.

Importing this package puts the Kodi stubs on sys.path before anything under
resources/lib is imported, which is what makes the add-on importable off a
Kodi box at all. Every test module lives in this package, so both runners hit
this first:

    python3 -m pytest tests
    python3 -m unittest discover -s tests -t .
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(REPO_ROOT, "tests")
STUBS_ROOT = os.path.join(TESTS_ROOT, "kodistubs")
LIB_ROOT = os.path.join(REPO_ROOT, "resources", "lib")

# Stubs first: `import xbmc` must find these, never a real Kodi install that
# happens to be on the path.
for _path in (STUBS_ROOT, LIB_ROOT, REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)
