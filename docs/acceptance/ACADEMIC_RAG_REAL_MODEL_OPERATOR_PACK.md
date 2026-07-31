# P0 real-model operator commands

These commands are live-model operators, not fixtures. Run only after the legal
real-paper manifest and controlled PDF directory have been reviewed. Never set
the runtime to a Fake encoder and never report a CPU placeholder as a real Gate.

## MiniLM dense retrieval

From the PaperClaw repository, with the target environment activated:

    $env:PAPERCLAW_ACADEMIC_DENSE = "1"
    $env:PAPERCLAW_ACADEMIC_VISUAL = "0"
    python -m pytest tests/unit/academic/test_real_paper_benchmark.py -q

The actual benchmark runner must record the pinned model
sentence-transformers/all-MiniLM-L6-v2 at revision
c9745ed1d9f207416be6d2e6f8de32d1f16199bf, device, dtype, batch, dimension,
normalization, index fingerprint, runtime, and environment. The existing recorded
RTX 4070 SUPER smoke is engineering/runtime evidence, not a 32-question quality
Gate.

## ColQwen2 visual retrieval

    $env:PAPERCLAW_ACADEMIC_DENSE = "0"
    $env:PAPERCLAW_ACADEMIC_VISUAL = "1"
    python -m paperclaw.academic.cli --workspace <controlled-workspace> index

Use the fixed vidore/colqwen2-base revision
9fe8a713422a7cb4ef79ca77a09b381ee2243101 and record processor fingerprint,
GPU/CUDA/dtype, page rendering and resolution, batch, index fingerprint,
retrieval trace, OOM/retry, and elapsed time. A missing dependency, download
timeout, fingerprint mismatch, or OOM without a recorded retry is BLOCKED; do not
replace it with FakeVisualEncoder or a CPU placeholder.

## Real academic LLM

Load the API secret only in the process environment or a secret store. Run the
existing PaperAgent AcademicRAGWorkflow/real provider path and export a redacted
trace containing provider/model, request/response hashes, usage, latency, retry,
structured-output parse, planner, accepted-only ledger, claim validation,
Artifact revisions, and decision. A generic v0.05 coding trace is not an
academic P0 trace.

## Evidence handoff

Copy only redacted manifests and summaries into the P0 evidence directory. Keep
PDFs, model caches, vector indexes, databases, Authorization headers, API keys,
raw private payloads, and personal reviewer data outside Git. If any required
operator input is missing, set the corresponding report status to BLOCKED.

