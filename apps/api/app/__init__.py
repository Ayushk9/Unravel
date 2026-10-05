"""Unravel API application package.

Importing this package puts the repository root on sys.path so that the
shared `contracts` package can be imported.

`pip install -e .` at the repo root is meant to do that, and does on most
machines. On this project's macOS development machine the virtualenv's
.pth files carry the "hidden" file flag, and Python 3.12 deliberately skips
hidden .pth files, so the editable install has no effect there. Engine A
solves the same problem the same way in engines/document/_bootstrap.py.
"""

import sys
from pathlib import Path

# apps/api/app/__init__.py -> repo root is three levels up.
_REPO_ROOT = Path(__file__).resolve().parents[3]

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
