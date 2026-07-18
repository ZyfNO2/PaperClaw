# PaperClaw v0.30 Desktop Product Integration

> Status: implementation in progress  
> Stack base: `feat/v0.29-artifact-revisions @ cc3f656ee2b9d82910913fdd172e557dd5d5307f`  
> Branch: `feat/v0.30-desktop-product-integration`

## Goal

Expose the v0.27-v0.29 product foundations through the existing thin pywebview/loopback Desktop boundary without moving runtime logic or credentials into JavaScript.

## Scope

- bounded `DesktopProductService` over existing Capability Catalog, Project Runtime and Artifact Store;
- allow-listed Desktop API methods for:
  - capability catalog;
  - project manifest/validation/index status;
  - explicit project refresh;
  - artifact list and detail;
  - artifact export;
- workspace confinement and symlink rejection at every public path boundary;
- no provider credentials in product API responses;
- product overview panel in the existing desktop shell;
- browser-mode parity through the same token-protected loopback API;
- deterministic, bounded public JSON contracts;
- Linux/Windows unit and desktop regression evidence.

## Architecture

```text
Desktop HTML/JS
  -> allow-listed DesktopAPI method
  -> DesktopProductService
  -> CapabilityCatalog / ProjectKnowledgeRuntime / FileArtifactStore
```

The UI remains a projection. It does not open SQLite directly and does not compose Agent runtimes.

## Non-goals

- no Desktop framework rewrite;
- no connector OAuth or secret management;
- no Skill installation/enable mutation;
- no Artifact editing or arbitrary HTML execution;
- no background project watcher;
- no sharing/publication service;
- no automatic merge.

## Acceptance

- all product endpoints validate workspace and reject external/symlink paths;
- capability output contains no credential values;
- project status distinguishes absent, valid, stale and invalid configurations;
- project refresh is explicit and cannot run outside workspace;
- artifacts are listed/read through bounded metadata only;
- export remains root-confined and non-overwriting by default;
- native pywebview and loopback browser API expose the same method allowlist;
- existing run/cancel/poll/provider UI remains compatible;
- full non-live regression and desktop-focused tests pass.
