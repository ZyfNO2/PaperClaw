# Local Corpus Smoke

Date: 2026-07-27

- Source: untracked `data/paper_corpus/` (107 PDFs; source files unchanged).
- Sample: 5 representative PDFs across Chinese, reconstruction, crack detection,
  segmentation and thesis folders.
- Import success: 5/5.
- Repeated first file: correctly returned `created=false`.
- Filename coverage: Chinese, English, spaces and non-ASCII.
- Pre-install run: all five reported `pdf_metadata_dependency_unavailable`.
- Post-dependency run with `pypdf 6.14.2`: 5/5 imported, 0 parser warnings;
  four titles fell back to filename and one used embedded PDF metadata.
- Managed smoke workspace: ignored `.tmp` directory; not part of release artifacts.
