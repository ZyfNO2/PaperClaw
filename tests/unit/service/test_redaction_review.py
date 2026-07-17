from __future__ import annotations

from paperclaw.durability import SQLiteDurableServiceStore
from paperclaw.service.contracts import sanitize_public


def test_token_secrets_are_removed_without_dropping_token_counts(tmp_path):
    payload = {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "token_value": "token-secret",
        "input_tokens": 11,
        "output_tokens": 7,
    }
    assert sanitize_public(payload) == {
        "input_tokens": 11,
        "output_tokens": 7,
    }

    store = SQLiteDurableServiceStore(tmp_path / "redaction.sqlite3")
    store.create_run("svc-redaction", "digest")
    event = store.append_event("svc-redaction", "model.completed", payload)
    assert event.payload == {"input_tokens": 11, "output_tokens": 7}
