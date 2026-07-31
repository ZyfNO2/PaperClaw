from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from paperclaw.academic.text import MiniLMEncoder  # noqa: E402


class _Batch(dict):
    def to(self, device: str):
        return _Batch({key: value.to(device) for key, value in self.items()})


class _Tokenizer:
    @classmethod
    def from_pretrained(cls, model_name: str, *, revision: str):
        assert model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert len(revision) == 40
        return cls()

    def __call__(self, texts, **kwargs):
        rows = [[1, 2], [3, 0]][: len(texts)]
        masks = [[1, 1], [1, 0]][: len(texts)]
        return _Batch(
            {
                "input_ids": torch.tensor(rows),
                "attention_mask": torch.tensor(masks),
            }
        )


class _Model:
    device = torch.device("cpu")

    @classmethod
    def from_pretrained(cls, model_name: str, *, revision: str):
        return cls()

    def to(self, device: str):
        self.device = torch.device(device)
        return self

    def eval(self):
        return self

    def __call__(self, **batch):
        size = batch["input_ids"].shape[0]
        return SimpleNamespace(
            last_hidden_state=torch.tensor(
                [
                    [[1.0, 0.0], [0.0, 1.0]],
                    [[3.0, 4.0], [99.0, 99.0]],
                ],
                device=self.device,
            )[:size]
        )


def test_minilm_encoder_uses_masked_mean_pooling_and_normalization(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModel=_Model, AutoTokenizer=_Tokenizer),
    )
    encoder = MiniLMEncoder(device="cpu")

    values = encoder.encode_documents(["first", "second"])

    assert values[0] == pytest.approx([2**-0.5, 2**-0.5])
    assert values[1] == pytest.approx([0.6, 0.8])
    assert encoder.encode_query("first")  # single-query path shares the implementation
