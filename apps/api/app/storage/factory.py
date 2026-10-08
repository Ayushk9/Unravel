"""Choose the storage backend from settings."""

from __future__ import annotations

from app.core.config import Settings
from app.storage.base import DocumentStorage
from app.storage.local import LocalDiskStorage
from app.storage.supabase import SupabaseStorage


def create_storage(settings: Settings) -> DocumentStorage:
    """Local disk by default; Supabase Storage when STORAGE_BACKEND=supabase.

    Both satisfy the same DocumentStorage interface, so nothing else in the
    application knows or cares which one is in use.
    """
    if settings.storage_backend == "supabase":
        # Settings validation has already ensured the key is present.
        assert settings.supabase_service_role_key is not None
        return SupabaseStorage(settings.supabase_url, settings.supabase_service_role_key, settings.storage_bucket)
    return LocalDiskStorage(settings.local_storage_path)
