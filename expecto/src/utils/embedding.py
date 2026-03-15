from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def _normalize_text(text: str) -> str:
    """Normalize text for stable hashing and better embedding consistency."""
    return " ".join(text.strip().split())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class EmbeddingRecord:
    model: str
    text_hash: str
    vector: List[float]


class Embedding:
    """
    Service for retrieving text embeddings with a simple cache.

    - Uses OpenAI embeddings API by default.
    - Caches in memory; optional JSON file persistence if cache_path is provided.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-large",
        cache_path: Optional[Path] = None,
    ) -> None:
        self.model = model
        self._cache: Dict[str, EmbeddingRecord] = {}
        self._lock = threading.Lock()
        self._cache_path = cache_path
        if cache_path is not None:
            self._load_cache()

    def _cache_key(self, text: str) -> str:
        normalized = _normalize_text(text)
        return f"{self.model}:{_sha256(normalized)}"

    def _load_cache(self) -> None:
        try:
            if self._cache_path and self._cache_path.exists():
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                for key, rec in data.items():
                    self._cache[key] = EmbeddingRecord(
                        model=rec["model"],
                        text_hash=rec["text_hash"],
                        vector=rec["vector"],
                    )
        except Exception:
            # Best-effort cache; ignore load failures
            pass

    def _save_cache(self) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {
                key: {
                    "model": rec.model,
                    "text_hash": rec.text_hash,
                    "vector": rec.vector,
                }
                for key, rec in self._cache.items()
            }
            self._cache_path.write_text(json.dumps(serializable), encoding="utf-8")
        except Exception:
            # Best-effort cache; ignore save failures
            pass

    def _get_openai_embedding(self, text: str) -> List[float]:
        """Call OpenAI embeddings API using the modern SDK."""
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.embeddings.create(
            model=self.model, input=_normalize_text(text)
        )
        return list(response.data[0].embedding)

    def get_embedding(self, text: str) -> List[float]:
        """
        Get embedding for text, using cache when available.
        """
        key = self._cache_key(text)
        with self._lock:
            if key in self._cache:
                return self._cache[key].vector

        vector = self._get_openai_embedding(text)
        record = EmbeddingRecord(model=self.model, text_hash=key, vector=vector)
        with self._lock:
            self._cache[key] = record
            self._save_cache()
        return vector

    @staticmethod
    def cosine_similarity_from_vec(v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(v1) != len(v2):
            raise ValueError("Embedding vectors must have the same length")
        dot = 0.0
        norm1 = 0.0
        norm2 = 0.0
        for a, b in zip(v1, v2):
            dot += a * b
            norm1 += a * a
            norm2 += b * b
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / ((norm1**0.5) * (norm2**0.5))

    def cosine_similarity(self, t1: str, t2: str) -> float:
        """Compute cosine similarity between embeddings of two texts."""
        e1 = self.get_embedding(t1)
        e2 = self.get_embedding(t2)
        return self.cosine_similarity_from_vec(e1, e2)
