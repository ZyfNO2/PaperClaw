# v0.38 Known Limitations

- Metadata extraction is local and candidate-only; no Crossref/arXiv verification.
- PDF validity uses strict `pypdf` structure parsing; semantic correctness of
  embedded document content is outside this ingestion gate.
- A failed database transaction can leave an unreferenced content-addressed blob;
  it is retained deliberately to avoid deleting data needed by a concurrent import.
- Imports are synchronous, single-file and bounded to 100 MiB.
- No page/object parsing, OCR, visual index or retrieval mutation.
- Desktop browser mirror cannot open a native file picker; use the pywebview Desktop
  window or CLI.
