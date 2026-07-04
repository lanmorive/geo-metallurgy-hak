"""Эмбеддинги bge-m3 (FlagEmbedding) и кэш на диск."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from tqdm import tqdm

from app.config import settings

if TYPE_CHECKING:
    from app.schemas.ontology import ParsedChunk

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
EMBEDDINGS_DIR = REPO_ROOT / "data" / "embeddings"

_model = None


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_model():
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel

        logger.info(
            "Loading embedding model %s on %s",
            settings.embedding_model,
            settings.embed_device,
        )
        _model = BGEM3FlagModel(
            settings.embedding_model,
            use_fp16=False,
            device=settings.embed_device,
        )
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Dense 1024-dim vectors, L2-normalized for cosine similarity."""
    if not texts:
        return []

    model = _get_model()
    batch_size = settings.embed_batch
    all_vectors: list[list[float]] = []

    for start in tqdm(range(0, len(texts), batch_size), desc="Embedding", unit="batch"):
        batch = texts[start : start + batch_size]
        output = model.encode(
            batch,
            batch_size=len(batch),
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense = output["dense_vecs"]
        if hasattr(dense, "tolist"):
            dense_list = dense.tolist()
        else:
            dense_list = [v.tolist() if hasattr(v, "tolist") else list(v) for v in dense]

        for vec in dense_list:
            arr = np.asarray(vec, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            all_vectors.append(arr.tolist())

    return all_vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def _manifest_path(doc_id: str) -> Path:
    return EMBEDDINGS_DIR / f"{doc_id}.manifest.json"


def _npy_path(doc_id: str) -> Path:
    return EMBEDDINGS_DIR / f"{doc_id}.npy"


def _load_manifest(doc_id: str) -> dict | None:
    path = _manifest_path(doc_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_cache_atomic(
    doc_id: str,
    chunk_ids: list[str],
    text_hashes: list[str],
    vectors: np.ndarray,
) -> None:
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "chunk_ids": chunk_ids,
        "text_hashes": text_hashes,
        "model": settings.embedding_model,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    npy_final = _npy_path(doc_id)
    npy_tmp = npy_final.with_name(npy_final.name + ".tmp")
    manifest_final = _manifest_path(doc_id)
    manifest_tmp = manifest_final.with_name(manifest_final.name + ".tmp")
    with open(npy_tmp, "wb") as f:
        np.save(f, vectors.astype(np.float32))
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    npy_tmp.replace(npy_final)
    manifest_tmp.replace(manifest_final)


def load_or_compute_embeddings(
    doc_id: str,
    chunks: list[ParsedChunk],
) -> dict[str, list[float]]:
    """
    Return chunk_id -> embedding, using disk cache when text hash matches.

    Recomputes only new or changed chunks; atomically rewrites .npy + manifest.
    """
    if not chunks:
        return {}

    chunk_ids = [c.chunk_id for c in chunks]
    text_hashes = [_text_hash(c.text) for c in chunks]
    hash_by_id = dict(zip(chunk_ids, text_hashes, strict=True))

    cached_vectors: dict[str, list[float]] = {}
    manifest = _load_manifest(doc_id)
    npy_path = _npy_path(doc_id)

    if (
        manifest is not None
        and manifest.get("model") == settings.embedding_model
        and npy_path.exists()
        and manifest.get("chunk_ids")
        and len(manifest["chunk_ids"]) == len(manifest.get("text_hashes", []))
    ):
        arr = np.load(npy_path)
        for i, cid in enumerate(manifest["chunk_ids"]):
            th = manifest["text_hashes"][i]
            if hash_by_id.get(cid) == th and i < len(arr):
                cached_vectors[cid] = arr[i].tolist()

    to_compute = [c for c in chunks if c.chunk_id not in cached_vectors]
    if to_compute:
        logger.info("Computing %d new/changed embeddings for %s", len(to_compute), doc_id)
        new_vecs = embed_texts([c.text for c in to_compute])
        for chunk, vec in zip(to_compute, new_vecs, strict=True):
            cached_vectors[chunk.chunk_id] = vec

    ordered_ids = [c.chunk_id for c in chunks]
    matrix = np.array(
        [cached_vectors[cid] for cid in ordered_ids],
        dtype=np.float32,
    )
    _save_cache_atomic(doc_id, ordered_ids, [hash_by_id[cid] for cid in ordered_ids], matrix)
    return {cid: cached_vectors[cid] for cid in ordered_ids}
