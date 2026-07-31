from __future__ import annotations

import pytest

from paperclaw.academic.real_models import (
    RealModelBlocked,
    check_real_model_environment,
    require_real_encoder,
)


class FakeMiniLMEncoder:
    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    revision = "fixed"


class CpuColQwen2Encoder:
    model_name = "vidore/colqwen2-base"
    revision = "fixed"
    device = "cpu"


def test_missing_or_fake_model_never_becomes_real() -> None:
    with pytest.raises(RealModelBlocked, match="not configured"):
        require_real_encoder(None, "minilm")
    with pytest.raises(RealModelBlocked, match="Fake"):
        require_real_encoder(FakeMiniLMEncoder(), "minilm")
    with pytest.raises(RealModelBlocked, match="CPU fallback"):
        require_real_encoder(CpuColQwen2Encoder(), "colqwen2")


def test_environment_check_is_explicitly_blocked_for_unpinned_identity() -> None:
    status = check_real_model_environment(
        "minilm",
        model_name="wrong/model",
        revision="",
    )
    assert status.status == "BLOCKED"
