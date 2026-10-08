"""Create the private Supabase Storage bucket, if it is missing.

Only needed when STORAGE_BACKEND=supabase. The default backend keeps files
in a local folder and needs no setup.

Run once per Supabase project, from apps/api:
    ../../.venv/bin/python scripts/create_bucket.py

Safe to run again: an existing private bucket is left alone, and an existing
PUBLIC bucket of the same name is refused rather than used.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make `app` importable when this file is run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.storage.supabase import SupabaseStorage  # noqa: E402


async def main() -> None:
    settings = get_settings()
    if not settings.supabase_service_role_key:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY is not set. It is only needed when STORAGE_BACKEND=supabase.")
    storage = SupabaseStorage(settings.supabase_url, settings.supabase_service_role_key, settings.storage_bucket)
    created = await storage.ensure_bucket()
    state = "created" if created else "already exists"
    print(f"Private bucket {settings.storage_bucket!r} {state}.")


if __name__ == "__main__":
    asyncio.run(main())
