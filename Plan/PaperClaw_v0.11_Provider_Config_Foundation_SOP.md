# PaperClaw v0.11 Provider Configuration Foundation SOP

> Status: implemented; CI pending
> Base: `main@1160f5ce26b78c3ff2723bd32a71a6e8d600febe`
> Scope: configuration contracts and secret-storage boundary only.

## Goal

Freeze a desktop-safe Provider/Credential/Model configuration contract before Runtime or UI wiring.

## Security boundary

- Catalogs persist only a credential reference (`env_var`), never API-key values.
- Secret resolution occurs at the adapter construction boundary.
- Public serialization is allow-listed and excludes resolved credentials.
- Provider URLs must be absolute HTTP(S) URLs.
- No keyring, plaintext config writer, migration, provider probing, or network call is introduced in this slice.

## Delivery sequence

1. Add immutable credential-reference, provider, model, and catalog contracts.
2. Validate identifiers, URL schemes, limits, duplicate entries, and provider/model references.
3. Add deterministic public JSON serialization with sorted capabilities.
4. Add unit tests proving secret values cannot enter serialized catalog output.
5. Run targeted tests, repository non-live tests, and Ruff through GitHub Actions.

## Acceptance gates

- Missing credentials fail closed.
- Catalog serialization contains only environment-variable names.
- Unknown provider references and invalid URLs are rejected.
- Existing `OpenAICompatibleModel.from_env()` remains unchanged.
- No Runtime, CLI, TUI, Desktop, or persistence behavior changes.
