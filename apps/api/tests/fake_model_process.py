"""Child entry points that stand in for the real model server (app/models_server/process.py).

They speak the same protocol over the pipe. Module-level functions, because
`spawn` starts a fresh interpreter that must be able to import them.
"""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection


def echo(connection: Connection, *_: object) -> None:
    """Loads instantly; every vector is [len(text), 0, ...]; rerank scores are passage lengths."""
    connection.send({"ready": True, "load_seconds": 0.0})
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        if request["op"] == "embed":
            connection.send({"ok": True, "vectors": [[float(len(t))] + [0.0] * 3 for t in request["texts"]]})
        elif request["op"] == "rerank":
            connection.send({"ok": True, "scores": [float(len(p)) for p in request["passages"]]})
        elif request["op"] == "stop":
            return


def hang_on_request(connection: Connection, *_: object) -> None:
    connection.send({"ready": True, "load_seconds": 0.0})
    connection.recv()
    time.sleep(60)


def crash_on_request(connection: Connection, *_: object) -> None:
    connection.send({"ready": True, "load_seconds": 0.0})
    connection.recv()
    os._exit(1)


def fail_to_load(connection: Connection, *_: object) -> None:
    connection.send({"ready": False, "error": "OSError: no such model"})
