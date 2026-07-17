# Known Limitations

- The router is static and consumes configured candidate facts only.
- Provider health, actual billing, cache behavior and live rate limits are not queried.
- Cost values are estimates, not provider-reported billing facts.
- Context overflow is intentionally non-fallback and requires a later v0.08 reduction integration.
- Runtime/Provider wiring remains a separate PR.
