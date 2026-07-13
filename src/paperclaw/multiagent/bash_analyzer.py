"""Static analysis of PowerShell bash commands for scope/lease/CAS enforcement.

This module closes the P0-1 bypass where ``ScopedBashTool`` ran arbitrary
PowerShell commands without checking whether they wrote to files outside the
task's ``writable_paths``, without acquiring FileLease, and without CAS.

The approach is **static best-effort**: we classify commands as read-only,
write, or dangerous, and extract write target paths from common PowerShell
file-operation cmdlets. We cannot catch dynamically constructed commands
(``Invoke-Expression``, ``-EncodedCommand``, ``& $var``); those constructs are
classified as ``dangerous`` and denied outright.

Limitations (documented for users):
- Commands like ``python script.py`` that indirectly write files cannot be
  statically analyzed. They are classified as ``unknown`` and handled per the
  caller's policy (typically: allowed if ``writable_paths == ["."]``, denied
  otherwise).
- Regex-based path extraction may miss unusual argument syntax. When a write
  cmdlet is detected but no target path can be extracted, the analysis returns
  an empty ``write_targets`` list and the caller must decide whether to deny.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class BashCommandAnalysis:
    """Result of analyzing a bash command string."""

    classification: Literal["read_only", "write", "dangerous", "unknown"]
    write_targets: list[str] = field(default_factory=list)
    reason: str = ""


# --- Dangerous constructs — always denied -----------------------------------
#
# Dynamic execution constructs make static analysis impossible. We deny them
# outright so the analyzer can trust that the remaining command text is what
# the shell will actually execute.
_DYNAMIC_EXECUTION = re.compile(
    r"(?i)"
    r"\binvoke-expression\b|\biex\b|"
    r"-encodedcommand\s|"
    r"\[scriptblock\]|"
    r"\binvoke-command\b|"
    r"^\s*&\s*\$|"
    r"\|\s*iex\b|"
    r"\|\s*invoke-expression\b"
)

# --- Write cmdlets — require lease + CAS ------------------------------------
#
# Each entry maps a cmdlet regex to a path-extraction regex. The path regex
# must capture the write target as a named group ``path``.
_WRITE_CMDLETS: list[tuple[re.Pattern[str], re.Pattern[str]]] = [
    # Set-Content -Path "X" / Set-Content "X"
    (
        re.compile(r"(?i)\bset-content\b"),
        re.compile(r"""(?i)(?:-path\s+["']?|set-content\s+["']?)([^\s"']+)["']?"""),
    ),
    # Out-File -FilePath "X" / Out-File "X"
    (
        re.compile(r"(?i)\bout-file\b"),
        re.compile(r"""(?i)(?:-filepath\s+["']?|out-file\s+["']?)([^\s"']+)["']?"""),
    ),
    # Add-Content -Path "X"
    (
        re.compile(r"(?i)\badd-content\b"),
        re.compile(r"""(?i)(?:-path\s+["']?|add-content\s+["']?)([^\s"']+)["']?"""),
    ),
    # Clear-Content -Path "X"
    (
        re.compile(r"(?i)\bclear-content\b"),
        re.compile(r"""(?i)(?:-path\s+["']?|clear-content\s+["']?)([^\s"']+)["']?"""),
    ),
    # New-Item -Path "X" -ItemType File
    (
        re.compile(r"(?i)\bnew-item\b.*\b(?:file|directory)\b", re.DOTALL),
        re.compile(r"""(?i)(?:-path\s+["']?|new-item\s+["']?)([^\s"']+)["']?"""),
    ),
    # Remove-Item -Path "X" (destructive = write)
    (
        re.compile(r"(?i)\bremove-item\b|\bdel\b|\berase\b|\bri\b|\brm\b"),
        re.compile(r"""(?i)(?:-path\s+["']?|(?:remove-item|del|erase|ri|rm)\s+["']?)([^\s"']+)["']?"""),
    ),
    # Copy-Item -Destination "Y" (write target is destination)
    (
        re.compile(r"(?i)\bcopy-item\b|\bcp\b|\bcopy\b"),
        re.compile(r"""(?i)-destination\s+["']?([^\s"']+)["']?"""),
    ),
    # Move-Item -Destination "Y"
    (
        re.compile(r"(?i)\bmove-item\b|\bmv\b|\bmove\b"),
        re.compile(r"""(?i)-destination\s+["']?([^\s"']+)["']?"""),
    ),
    # Rename-Item -NewName "Y" (write target is new name in same dir)
    (
        re.compile(r"(?i)\brename-item\b|\bren\b"),
        re.compile(r"""(?i)-newname\s+["']?([^\s"']+)["']?"""),
    ),
    # Set-Item -Path "X"
    (
        re.compile(r"(?i)\bset-item\b"),
        re.compile(r"""(?i)(?:-path\s+["']?|set-item\s+["']?)([^\s"']+)["']?"""),
    ),
]

# Redirection: "content" > X or "content" >> X
_REDIRECTION = re.compile(r""">\s*["']?([^\s"';|&]+)["']?""")

# --- Read-only commands — no lease needed -----------------------------------
#
# ``echo`` and ``Write-Host`` are safe here because any redirection (``> file``)
# is captured by ``_REDIRECTION`` before this check runs, so a bare ``echo``
# only writes to stdout. ``sleep`` / ``Start-Sleep`` are pure waits. ``python``
# without arguments is a REPL banner, not a script invocation — but we do NOT
# classify ``python script.py`` as read-only because the script may write files.
_READ_ONLY = re.compile(
    r"(?i)"
    r"\bget-content\b|\bget-childitem\b|\bget-item\b|\btest-path\b|"
    r"\bselect-string\b|\bmeasure-object\b|\bget-acl\b|"
    r"\bls\b|\bcat\b|\btype\b|\bdir\b|\bhead\b|\btail\b|\bmore\b|"
    r"\bpython\s+-m\s+pytest\b|\bpython\s+-m\s+py_compile\b|"
    r"\bpytest\b|\bpy\.exe\s+-m\s+pytest\b|"
    r"\bsleep\b|\bstart-sleep\b|"
    r"\becho\b|\bwrite-host\b|\bwrite-output\b|\bwrite-debug\b|\bwrite-verbose\b|"
    r"\bpwd\b|\bget-location\b|\bwhoami\b|\bhostname\b|\bdate\b|\bget-date\b"
)


def analyze_bash_command(command: str) -> BashCommandAnalysis:
    """Classify a PowerShell command and extract write targets.

    Returns a :class:`BashCommandAnalysis` with:
    - ``classification``: ``read_only``, ``write``, ``dangerous``, or ``unknown``
    - ``write_targets``: list of raw path strings the command will write to
    - ``reason``: human-readable explanation

    The caller is responsible for resolving ``write_targets`` against the
    workspace and checking scope/lease/CAS.
    """

    if not command or not command.strip():
        return BashCommandAnalysis("unknown", reason="empty command")

    # Dynamic execution → always deny.
    if _DYNAMIC_EXECUTION.search(command):
        return BashCommandAnalysis(
            "dangerous",
            reason="dynamic execution construct detected (Invoke-Expression/-EncodedCommand/& $var); static analysis cannot verify safety",
        )

    # Check for write cmdlets first — a command can be both read and write
    # (e.g. Get-Content X | Out-File Y), and we must treat it as write.
    write_targets: list[str] = []
    for cmdlet_re, path_re in _WRITE_CMDLETS:
        if cmdlet_re.search(command):
            for match in path_re.finditer(command):
                target = match.group(1).strip().strip("\"'")
                if target and target not in write_targets:
                    write_targets.append(target)

    # Redirection: > X or >> X
    for match in _REDIRECTION.finditer(command):
        target = match.group(1).strip().strip("\"'")
        if target and target not in write_targets:
            write_targets.append(target)

    if write_targets:
        return BashCommandAnalysis(
            "write",
            write_targets=write_targets,
            reason=f"write cmdlet detected; targets={write_targets}",
        )

    # A write cmdlet was present but we couldn't extract a path — treat as
    # write with unknown targets so the caller can deny safely.
    for cmdlet_re, _ in _WRITE_CMDLETS:
        if cmdlet_re.search(command):
            return BashCommandAnalysis(
                "write",
                write_targets=[],
                reason="write cmdlet detected but no target path could be extracted; caller should deny",
            )

    # Redirection present without an extractable path.
    if re.search(r"(?i)\b>\s*$|>>\s*$", command) or ">" in command and not _REDIRECTION.search(command):
        return BashCommandAnalysis(
            "write",
            write_targets=[],
            reason="redirection detected but target path could not be extracted",
        )

    # Read-only commands.
    if _READ_ONLY.search(command):
        return BashCommandAnalysis("read_only", reason="read-only cmdlet or test execution detected")

    # Everything else is unknown — the caller decides based on writable_paths.
    return BashCommandAnalysis(
        "unknown",
        reason="command does not match any known pattern; caller must decide policy",
    )
