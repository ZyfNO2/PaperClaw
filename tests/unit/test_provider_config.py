from __future__ import annotations

import json

import pytest

from paperclaw.provider_config import (
    CredentialRef,
    ModelConfig,
    ProviderCatalog,
    ProviderConfig,
)


def test_credential_ref_resolves_only_from_supplied_environment() -> None:
    ref = CredentialRef("PAPERCLAW_TEST_KEY")
    assert ref.resolve({"PAPERCLAW_TEST_KEY": "secret-value"}) == "secret-value"
    with pytest.raises(RuntimeError, match="missing credential"):
        ref.resolve({})


def test_public_catalog_never_serializes_secret_value() -> None:
    catalog = ProviderCatalog(
        providers=(
            ProviderConfig(
                provider_id="openai-compatible",
                base_url="https://example.invalid/v1/",
                credential=CredentialRef("PAPERCLAW_API_KEY"),
            ),
        ),
        models=(
            ModelConfig(
                provider_id="openai-compatible",
                model_id="example-model",
                capabilities=frozenset({"chat"}),
            ),
        ),
    )
    rendered = catalog.to_public_json()
    payload = json.loads(rendered)
    assert "secret-value" not in rendered
    assert payload["providers"][0]["credential_env_var"] == "PAPERCLAW_API_KEY"
    assert payload["models"][0]["qualified_name"] == "openai-compatible:example-model"


def test_catalog_rejects_unknown_provider_reference() -> None:
    with pytest.raises(ValueError, match="unknown providers"):
        ProviderCatalog(
            providers=(),
            models=(ModelConfig(provider_id="missing", model_id="model"),),
        )


def test_provider_requires_absolute_http_url() -> None:
    with pytest.raises(ValueError, match="absolute HTTP"):
        ProviderConfig(
            provider_id="provider",
            base_url="file:///tmp/provider",
            credential=CredentialRef("PAPERCLAW_API_KEY"),
        )
