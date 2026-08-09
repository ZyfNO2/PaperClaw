# PaperClaw v0.39 Test Report

## Current hardening verification (supersedes the historical Memory-only summary)

| Check | Result |
|---|---|
| v0.39 durable contract tests | 9 passed |
| Focused Memory / Context / Trace regression | passed; included in the targeted runs |
| Real process acceptance | 2 passed with local mock Provider and restart flow |
| Full non-live regression, writable USERPROFILE | 1078 passed, 23 skipped, 12 deselected; 2 pre-existing Bash failures |
| Ruff high-signal CI check | `All checks passed!` |
| Full repository Ruff check | not clean: 873 pre-existing findings across unrelated files; no v0.39-wide rewrite |
| Type check | NOT CONFIGURED / NOT VERIFIED; no mypy/pyright gate exists in active repository CI |
| Package build | passed with `python -m build --no-isolation` |
| Exact-head GitHub CI | `AWAITING REAL TEST` — branch not pushed |
| Real LLM / Docker / manual native OS | `NOT VERIFIED` |

The two full-suite failures are existing Windows Bash tests:
`test_bash_tool_respects_stop_token_mid_execution` and
`test_bash_timeout_kills_child_process_tree`. Their failures occur in the
PowerShell quoting/timeout path and no Bash code was changed for v0.39.

Commands for the current verification used an isolated dependency directory
and a writable `USERPROFILE`; the implementation itself does not commit that
directory or any generated database.

## 结果摘要

| 检查 | 结果 |
|---|---|
| Memory 专项测试 | 37 passed |
| Context contracts / migration / demo 定向回归 | 49 passed |
| 全量非 live 回归 | 1071 passed, 23 skipped, 12 deselected, 2 warnings |
| Ruff 语法/致命错误检查 | passed |
| Package build | passed |
| Real LLM / external provider / CI | 未运行 |

## 实际运行命令

### 基线检查

以下结果来自 v0.39 改动前的 canonical 命令。测试发现的是 Windows 临时目录权限问题，而不是断言失败：

```text
python -m pytest -q -m "not real_llm and not distributed"
494 passed, 10 skipped, 12 deselected, 571 errors in 43.41s
PermissionError: [WinError 5] for C:\Users\ZYF\AppData\Local\Temp\pytest-of-ZYF
```

```text
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
All checks passed!
```

### v0.39 专项与回归

```text
python -m pytest --basetemp .tmp-v039-memory tests/unit/memory -q
37 passed in 0.95s
```

```text
python -m pytest --basetemp .tmp-final-check \
  tests/integration/test_v0_08_demo_script.py \
  tests/unit/memory/test_memory_traceability.py \
  tests/unit/test_context_contracts.py -q
49 passed in 1.22s
```

```text
python -m pytest --basetemp .tmp-reg-full2 -q -m "not real_llm and not distributed"
1071 passed, 23 skipped, 12 deselected, 2 warnings in 73.13s
```

```text
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
All checks passed!
```

```text
python -m build
Successfully built paperclaw-0.38.0.tar.gz and paperclaw-0.38.0-py3-none-any.whl
```

## Acceptance gates

| Gate | 结果 | 证据 |
|---|---|---|
| M39-01 schema migration | PASS | `test_memory_migration.py`、full regression |
| M39-02 add/list | PASS | `test_memory_service.py` |
| M39-03 immutable replace | PASS | `test_memory_service.py` |
| M39-04 tombstone remove | PASS | `test_memory_service.py` |
| M39-05 USER isolation | PASS | `test_memory_boundaries_and_compat.py` |
| M39-06 PROJECT isolation | PASS | `test_memory_boundaries_and_compat.py` |
| M39-07 frozen pinned snapshot | PASS | `test_frozen_session_memory.py` |
| M39-08 mid-session write isolation | PASS | `test_frozen_session_memory.py` |
| M39-09 next-session refresh | PASS | `test_frozen_session_memory.py` |
| M39-10 deterministic rendered hash | PASS | `test_frozen_session_memory.py`、`test_memory_service.py` |
| M39-11 L5 pinned injection | PASS | `test_memory_context_source.py` |
| M39-12 L5 recall injection | PASS | `test_memory_context_source.py` |
| M39-13 provenance traceability | PASS | `test_memory_traceability.py` |
| M39-14 external_untrusted guard | PASS | `test_memory_boundaries_and_compat.py` |
| M39-15/16/17 separation boundaries | PASS | `test_memory_contracts.py`、boundary tests |
| M39-18 ToolRegistry integration | PASS | `test_structured_memory_runtime.py` |
| M39-19 audit events | PASS | `test_memory_traceability.py` |
| M39-20 ContextSnapshot memory traceability | PASS | `test_memory_traceability.py` |
| M39-21 empty/disabled compatibility | PASS | `test_memory_boundaries_and_compat.py`、full regression |
| M39-22 full non-live regression | PASS | 1071 passed |

## SOP hook

执行：`python .claude/hooks/sop_completion_check.py`

结果：`0/0` checkbox done，`0` pending；hook exit code `0`，并报告 `artifacts/v0_39/` package complete。
