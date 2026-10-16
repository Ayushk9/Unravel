"""The model server's own process: load two models once, then answer requests forever.

Runs in a child started by client.ModelServer with `spawn`. torch and
transformers are imported only here, so the API process never loads them.

Protocol, one dict per message over a duplex pipe:

    child -> parent, once:   {"ready": True, "load_seconds": 7.2}
                         or  {"ready": False, "error": "..."}
    parent -> child:         {"op": "embed", "texts": [...]}
                             {"op": "rerank", "query": "...", "passages": [...]}
    child -> parent:         {"ok": True, "vectors": [[...1024 floats...], ...]}
                             {"ok": True, "scores": [0.93, 0.12, ...]}
                         or  {"ok": False, "error": "..."}

When the parent goes away the pipe closes, recv() raises EOFError and the
child exits, so it cannot outlive the API.
"""

from __future__ import annotations

import time
from multiprocessing.connection import Connection
from typing import Any

EMBED_BATCH = 16
# Chunks are at most 1,500 characters (engines/document/chunking.py), well under this.
MAX_TOKENS = 1024


def serve(connection: Connection, embed_model: str, rerank_model: str, device: str) -> None:
    started = time.perf_counter()
    try:
        import torch
        from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

        torch.set_grad_enabled(False)
        embed_tokenizer = AutoTokenizer.from_pretrained(embed_model)
        embedder = AutoModel.from_pretrained(embed_model).to(device).eval()
        rerank_tokenizer = AutoTokenizer.from_pretrained(rerank_model)
        reranker = AutoModelForSequenceClassification.from_pretrained(rerank_model).to(device).eval()
    except Exception as exc:  # noqa: BLE001 - reported to the parent, which fails the job readably
        connection.send({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return
    connection.send({"ready": True, "load_seconds": round(time.perf_counter() - started, 2)})

    def embed(texts: list[str]) -> list[list[float]]:
        """BGE-M3's dense vector: the [CLS] token's final hidden state, scaled to length 1.

        Length 1 means cosine similarity is just a dot product, which is what
        pgvector's <=> operator computes (as distance = 1 - similarity).
        """
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = embed_tokenizer(
                texts[start : start + EMBED_BATCH], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt"
            ).to(device)
            cls = embedder(**batch).last_hidden_state[:, 0]
            vectors.extend(torch.nn.functional.normalize(cls, dim=-1).float().cpu().tolist())
        return vectors

    def rerank(query: str, passages: list[str]) -> list[float]:
        """How well each passage answers the query, 0..1 (sigmoid of the cross-encoder's logit).

        A cross-encoder reads the question and the passage together, so it
        judges relevance far better than comparing two separately made
        vectors. It is too slow to run over every chunk, which is why it
        only re-orders the ~30 candidates that retrieval already found.
        """
        if not passages:
            return []
        batch = rerank_tokenizer(
            [[query, passage] for passage in passages], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt"
        ).to(device)
        logits = reranker(**batch).logits.view(-1).float()
        return torch.sigmoid(logits).cpu().tolist()

    while True:
        try:
            request: dict[str, Any] = connection.recv()
        except EOFError:
            return  # the parent is gone
        try:
            if request["op"] == "embed":
                connection.send({"ok": True, "vectors": embed(list(request["texts"]))})
            elif request["op"] == "rerank":
                connection.send({"ok": True, "scores": rerank(request["query"], list(request["passages"]))})
            elif request["op"] == "stop":
                return
            else:
                connection.send({"ok": False, "error": f"unknown op {request['op']!r}"})
        except Exception as exc:  # noqa: BLE001 - one bad request must not take the server down
            connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
