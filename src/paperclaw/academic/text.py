"""Replaceable text embedding seam for Academic RAG."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol, Sequence


class DenseEncoder(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def encode_query(self, text: str) -> list[float]: ...


@dataclass
class MiniLMEncoder:
    """Lazy sentence-transformers adapter with plain-list public values."""

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    revision: str = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
    device: str | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.model_name}:{self.revision}".encode()).hexdigest()

    def _load(self):
        if not hasattr(self, "_model"):
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("install paperclaw[academic] for MiniLM") from exc
            self._model = SentenceTransformer(
                self.model_name, revision=self.revision, device=self.device
            )
        return self._model

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        values = self._load().encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return values.tolist()

    def encode_query(self, text: str) -> list[float]:
        return self.encode_documents([text])[0]
