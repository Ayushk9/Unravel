"""Start the API server: `python -m app`, run from apps/api.

Reads HOST and PORT from settings. The default host, 0.0.0.0, makes the
server reachable from other devices on the same network (an Android phone
on the same Wi-Fi) at http://<this Mac's IP address>:8000. Set HOST=127.0.0.1
to accept connections from this machine only.
"""

from __future__ import annotations

import uvicorn

from app.core.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    # Passed as an import string so that child processes started for parsing,
    # which re-import the main module, do not start a second server.
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
