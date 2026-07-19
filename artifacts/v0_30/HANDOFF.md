# PaperClaw v0.30 Desktop Product Integration — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Repository: `ZyfNO2/PaperClaw`
- Branch: `feat/v0.30-desktop-product-integration`
- Draft PR: `#59`
- Stack base: `feat/v0.29-artifact-revisions @ cc3f656ee2b9d82910913fdd172e557dd5d5307f`
- Exact validated implementation SHA: `b15f0d11dc81c7deba7b9f224e366727029f0068`
- Validation run: `29661793529`
- Plan: `Plan/PaperClaw_v0.30_Desktop_Product_Integration.md`

## Delivered

### Desktop Product Service

A bounded Python service now projects existing product foundations to Desktop:

```text
get_product_overview
get_capabilities
get_project_status
refresh_project_index
list_artifacts
get_artifact
export_artifact
```

It delegates to the existing Capability Catalog, Project Knowledge Runtime and Artifact Store. JavaScript does not access SQLite, blobs or Provider configuration directly.

### Native and browser bridge parity

The product extension updates the same allowlist used by:

- native pywebview bridge;
- token-protected loopback browser API.

Public arity is fixed and unknown methods remain rejected.

Expected `DesktopPublicError` values cross the bridge unchanged. Unexpected exceptions become:

```json
{
  "ok": false,
  "error_code": "runtime_error",
  "error_message": "Desktop product operation failed."
}
```

Private exception details do not cross the bridge.

### Capability panel

Desktop displays current stacked truth including:

- v0.28 Project Knowledge Runtime;
- v0.28 deterministic Hybrid RRF seam;
- v0.29 Artifact Revisions;
- v0.30 Desktop Product Management.

Maturity remains explicit: shipped, foundation, experimental or planned.

### Project panel

Desktop distinguishes:

- absent manifest;
- invalid manifest;
- valid project without knowledge;
- missing/stale/current/invalid index;
- declared Skills and Connectors.

Project index refresh is an explicit user action. No watcher is started by Desktop.

### Artifact panel

Desktop provides:

- bounded recent artifact list;
- Artifact type/title/source links;
- bounded revision history;
- latest-revision export;
- default export location under `.paperclaw/exports`.

The UI never receives content-addressed blob filesystem paths.

### Thin UI implementation

- Product overview panel added to existing desktop shell;
- no Desktop framework rewrite;
- separate external `product.js` and `product.css` assets;
- no inline script;
- `textContent`/DOM construction only, no `innerHTML`;
- responsive layout;
- existing Provider, Run, Cancel, Poll, Trace and theme UI preserved.

## Public contract bounds

- workspace must be a real existing non-symlink directory;
- Artifact root and database symlinks rejected;
- arbitrary database/blob roots never accepted;
- list maximum: 100 returned rows;
- detail maximum: 100 revisions;
- public response maximum: 1 MiB;
- Artifact list returns bounded summaries without arbitrary metadata;
- export root fixed beneath current Workspace;
- parent traversal and malformed paths rejected;
- existing export file not overwritten unless explicitly requested;
- Provider API key, Authorization and Cookie values never enter Product API responses.

## Validation

Exact implementation SHA:

```text
b15f0d11dc81c7deba7b9f224e366727029f0068
```

GitHub Actions run:

```text
29661793529
```

Results:

- Ubuntu Desktop/Product focused acceptance — SUCCESS
- Windows Desktop/Product focused acceptance — SUCCESS
- legacy Desktop/product CLI compatibility — SUCCESS on both platforms
- Chromium Playwright desktop interactions — SUCCESS
- full Windows non-live repository regression — SUCCESS
- focused Ruff — SUCCESS
- repository correctness Ruff — SUCCESS

Machine-readable full regression:

```text
940 passed / 0 failed
10 marker-driven setup skips
artifact: v030-full-regression-29661793529
digest: sha256:a9d773a622a10f62eee78fc2d5b9e0cf873019d99305babafa58547a53c62a79
```

Focused evidence:

```text
Linux artifact digest:
sha256:0f5dca17fd8616d61548c62af02d1ac7965886129ba486766dbb83e5bf684344

Windows artifact digest:
sha256:44aeea9bf1f4e3d9a842c09a7a4a565ef5eacdcc51d10ad95267ab9a0e3817cf
```

## Preserved negative evidence

1. The first v0.30 focused run exposed that `DesktopPublicError` inherits from `ValueError`; export path validation was accidentally converted into `artifact_export_failed`. Validation now runs outside the generic wrapper and retains `validation_error`.
2. A historical capability test still classified `artifact.revisions` as planned after v0.29 completed it. The current catalog and regression now reflect the actual stacked version.
3. Product list/detail contracts were tightened with public response and revision-history caps before final acceptance.
4. Focused report artifacts were added so future failures retain machine-readable node IDs and outcomes.

No tests, CSP restrictions or path assertions were weakened.

## Known limits

v0.30 does not implement:

- Skill installation or enable/disable mutation;
- Connector OAuth, credential storage or permission management;
- Artifact editing, sharing or publication;
- background Project watcher;
- arbitrary Artifact HTML/script execution;
- Desktop framework replacement;
- complete Product panel localization;
- external cloud Artifact storage.

## Stack state

```text
v0.27 PR #56
  ↓
v0.28 PR #57
  ↓
v0.29 PR #58
  ↓
v0.30 PR #59
```

All remain Draft and unmerged.

## Recommended next line

```text
v0.31 Aggregate Eval / Cost / Latency
  -> multi-run benchmark records
  -> task success and tool-call accuracy
  -> collaboration efficiency
  -> latency P50/P95/P99
  -> token/provider cost
  -> failure taxonomy and export
```

## Final classification

**COMPLETE**

PR #59 remains Draft and unmerged. No branch was deleted.
