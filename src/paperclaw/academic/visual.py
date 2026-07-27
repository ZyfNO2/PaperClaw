"""Replaceable late-interaction visual encoder seam."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol, Sequence


class VisualEncoder(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def encode_images(self, paths: Sequence[Path]) -> list[list[list[float]]]: ...
    def encode_query(self, query: str) -> list[list[float]]: ...


@dataclass
class ColQwen2Encoder:
    """Lazy colpali-engine adapter; third-party tensors never cross this seam."""

    model_name: str = "vidore/colqwen2-base"
    revision: str = "9fe8a713422a7cb4ef79ca77a09b381ee2243101"
    device: str = "cuda"
    dtype: str = "bfloat16"

    @property
    def fingerprint(self) -> str:
        raw = f"{self.model_name}:{self.revision}:{self.dtype}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _load(self):
        if hasattr(self, "_model"):
            return self._model, self._processor
        try:
            import torch
            from colpali_engine.models import ColQwen2, ColQwen2Processor
        except ImportError as exc:
            raise RuntimeError(
                "install paperclaw[academic-visual] for ColQwen"
            ) from exc
        dtype = torch.bfloat16 if self.dtype == "bfloat16" else torch.float32
        try:
            model = (
                ColQwen2.from_pretrained(
                    self.model_name, revision=self.revision, torch_dtype=dtype
                )
                .to(self.device)
                .eval()
            )
        except torch.OutOfMemoryError:
            model = (
                ColQwen2.from_pretrained(
                    self.model_name, revision=self.revision, torch_dtype=torch.float32
                )
                .to("cpu")
                .eval()
            )
            self.device = "cpu"
        self._model = model
        self._processor = ColQwen2Processor.from_pretrained(
            self.model_name, revision=self.revision
        )
        return model, self._processor

    def encode_images(self, paths: Sequence[Path]) -> list[list[list[float]]]:
        from PIL import Image
        import torch

        model, processor = self._load()
        encoded = []
        for path in paths:
            with Image.open(path) as source:
                image = source.convert("RGB")
            batch = processor.process_images([image]).to(model.device)
            try:
                with torch.inference_mode():
                    embedding = model(**batch)
            except torch.OutOfMemoryError:
                torch.cuda.empty_cache()
                model = model.to("cpu", dtype=torch.float32)
                self.device = "cpu"
                batch = processor.process_images([image]).to("cpu")
                with torch.inference_mode():
                    embedding = model(**batch)
            encoded.append(embedding[0].detach().float().cpu().tolist())
        return encoded

    def encode_query(self, query: str) -> list[list[float]]:
        import torch

        model, processor = self._load()
        batch = processor.process_queries([query]).to(model.device)
        with torch.inference_mode():
            embeddings = model(**batch)[0]
        return embeddings.detach().float().cpu().tolist()


def late_interaction_score(
    query: list[list[float]], document: list[list[float]]
) -> float:
    if not query or not document:
        return 0.0
    total = 0.0
    for q in query:
        total += max(sum(a * b for a, b in zip(q, d)) for d in document)
    return total / len(query)
