# PaperClaw v0.30 Desktop Product Integration

> Status: implementation complete / acceptance complete  
> Stack base: `feat/v0.29-artifact-revisions @ cc3f656ee2b9d82910913fdd172e557dd5d5307f`  
> Branch: `feat/v0.30-desktop-product-integration`  
> Draft PR: `#59`  
> Validated implementation SHA: `b15f0d11dc81c7deba7b9f224e366727029f0068`

## Goal

Expose the v0.27-v0.29 product foundations through the existing thin pywebview/loopback Desktop boundary without moving runtime logic or credentials into JavaScript.

## Delivered

### Desktop Product Service

`DesktopProductService` exposes bounded operations for:

- capability catalog;
- project manifest, validation and index status;
- explicit project index refresh;
- artifact list and detail;
- artifact export;
- combined product overview.

The service never accepts Provider configuration or returns credentials.

### Desktop bridge

The existing `DesktopAPI` is extended through an idempotent bootstrap extension. Native pywebview and token-protected browser mode share the same allowlist:

```text
get_product_overview
get_capabilities
get_project_status
refresh_project_index
list_artifacts
get_artifact
export_artifact
```

Unexpected Python exceptions are converted to a generic public error and private exception details do not cross the bridge.

### Project management surface

Desktop distinguishes:

- project absent;
- manifest invalid;
- project valid without knowledge;
- index current;
- index stale/missing/invalid.

Index refresh is explicit. No watcher starts in the Desktop runtime.

### Artifact management surface

Desktop supports:

- bounded artifact listing;
- revision history detail;
- latest-revision export;
- optional explicit relative export name;
- default export under `.paperclaw/exports`.

The UI does not receive blob paths or direct SQLite access.

### Capability truth

The v0.30 catalog now records:

- `project.knowledge_runtime` as v0.28 foundation;
- `retrieval.hybrid_rrf` as v0.28 foundation;
- `artifact.revisions` as v0.29 foundation;
- `desktop.product_management` as v0.30 experimental;
- project/capability catalog availability on Desktop.

### Thin UI projection

The existing Desktop shell now includes a Product panel with:

- overview metrics;
- capability catalog;
- project state and refresh action;
- artifact list, revision detail and export action.

The panel uses DOM `textContent`, not `innerHTML`; CSP remains external-script only. Product JavaScript caches the loopback token before the legacy application removes it from the URL fragment.

## Safety boundaries

- workspace must be a real existing directory and cannot be a symbolic link;
- project and Artifact stores remain inside that workspace;
- Artifact storage/database symlinks are rejected;
- external database/blob paths are never accepted;
- export is restricted to `.paperclaw/exports`;
- parent traversal and malformed relative paths are rejected;
- existing export targets are not overwritten by default;
- artifact list limit is capped;
- artifact detail revision history is capped;
- public JSON responses are capped at 1 MiB;
- artifact summaries omit arbitrary metadata;
- no Provider keys or authorization values are exposed.

## Preserved non-goals

- no Desktop framework rewrite;
- no connector OAuth or secret management;
- no Skill installation/enable mutation;
- no Artifact editing or arbitrary HTML execution;
- no background project watcher;
- no sharing/publication service;
- no automatic merge.

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

- Ubuntu focused Desktop/Product acceptance: SUCCESS;
- Windows focused Desktop/Product acceptance: SUCCESS;
- legacy Desktop/product CLI compatibility: SUCCESS on both platforms;
- Chromium Playwright desktop interactions: SUCCESS;
- full Windows non-live repository regression: SUCCESS;
- focused and repository Ruff correctness checks: SUCCESS.

Machine-readable regression:

```text
940 passed / 0 failed
10 marker-driven setup skips
artifact: v030-full-regression-29661793529
digest: sha256:a9d773a622a10f62eee78fc2d5b9e0cf873019d99305babafa58547a53c62a79
```

Focused evidence:

```text
Linux digest:  sha256:0f5dca17fd8616d61548c62af02d1ac7965886129ba486766dbb83e5bf684344
Windows digest: sha256:44aeea9bf1f4e3d9a842c09a7a4a565ef5eacdcc51d10ad95267ab9a0e3817cf
```

## Negative evidence preserved

Initial acceptance found and fixed:

1. Desktop export path validation was accidentally wrapped as `artifact_export_failed` because `DesktopPublicError` inherits from `ValueError`; validation now occurs outside the generic exception wrapper and retains `validation_error`.
2. The historical Capability Catalog test still expected `artifact.revisions` to be planned after v0.29 had implemented it; capability truth and tests now reflect the delivered stacked version.
3. Desktop product list/detail contracts were hardened with response-size and revision-history limits before final acceptance.

No tests were weakened or skipped to hide these findings.

## Final classification

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

PR #59 remains Draft and unmerged.
