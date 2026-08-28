"""Side-effect import: puts the repo root on sys.path so `contracts`
resolves, and loads engines/document/.env if present.

engines/document ships its own venv and this repo has no packaging metadata
for `contracts` (no pyproject.toml, not pip-installed) — it is a plain
package meant to be imported with the repo root on PYTHONPATH. Rather than
require every caller (scripts, pytest, a future job worker) to set that up
by hand, any module here that needs `contracts` does `import _bootstrap`
first. Idempotent and cheap enough to run on every import.

The .env load is `override=False`: a real value already exported in the
shell (e.g. a CI secret) always wins over whatever's on disk. See
.env.example for what to put there — same GEMINI_API_KEY name apps/api
uses. .env itself is gitignored at the repo root (`.env` / `.env.*`), so
this never risks committing a real key.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_ENGINE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ENGINE_DIR.parents[1]

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_ENGINE_DIR / ".env", override=False)
