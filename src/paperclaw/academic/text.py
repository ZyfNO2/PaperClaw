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
    """Lazy pinned MiniLM adapter with plain-list public values."""

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    revision: str = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
    device: str | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.model_name}:{self.revision}".encode()).hexdigest()

    def _load(self):
        if not hasattr(self, "_model"):
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer
            except ImportError as exc:
                raise RuntimeError("install paperclaw[academic] for MiniLM") from exc
            device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                revision=self.revision,
            )
            self._model = (
                AutoModel.from_pretrained(
                    self.model_name,
                    revision=self.revision,
                )
                .to(device)
                .eval()
            )
        return self._model

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        import torch

        model = self._load()
        batch = self._tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normalized.detach().float().cpu().tolist()

    def encode_query(self, text: str) -> list[float]:
        return self.encode_documents([text])[0]
