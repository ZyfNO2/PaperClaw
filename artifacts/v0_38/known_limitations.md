# v0.38 Known Limitations

- Metadata extraction is local and candidate-only; no Crossref/arXiv verification.
- PDF validity gate checks the header before the parser adapter runs.
- Imports are synchronous, single-file and bounded to 100 MiB.
- No page/object parsing, OCR, visual index or retrieval mutation.
- Desktop browser mirror cannot open a native file picker; use the pywebview Desktop
  window or CLI.
