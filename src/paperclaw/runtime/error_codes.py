"""Stable error code constants for the InstrumentedFlowRunner.

Per Addendum §4.4 (PB6), node failure events MUST include a stable error
code string. These constants are part of the v0.04 event schema; renaming
one is a schema/replay-compatibility change.

Error codes are phase-qualified where possible so a resume or replay can
distinguish "prep failed" from "exec failed" without parsing the exception
message. The classifier ``classify_exception`` maps a (phase, exc) pair to
one of these codes.

Design constraint (Addendum §4.4): "Exceptions MUST NOT be swallowed by
Runner." The classifier only labels the exception for the ``node.failed``
event; the runner re-raises the original exception after emitting the event.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stable error code strings
# ---------------------------------------------------------------------------

#: Node ``exec`` (or ``_exec`` retry loop) raised an exception. This is the
#: generic fallback for errors that are not phase-specific (e.g. nested Flow
#: failures, where the runner does not split prep/exec/post).
NODE_EXEC_FAILED = "NODE_EXEC_FAILED"

#: Node ``prep`` raised an exception. The node never reached ``exec``.
NODE_PREP_FAILED = "NODE_PREP_FAILED"

#: Node ``post`` raised an exception. The node's ``exec`` succeeded but the
#: post-hook (which selects the transition action and mutates shared state)
#: failed. This is the most dangerous phase to fail in because shared state
#: may be partially mutated.
NODE_POST_FAILED = "NODE_POST_FAILED"

#: Node has no ``node_id`` attribute and is not in the NodeRegistry. P0-A
#: should prevent this, but the runner checks defensively so an anonymous
#: ``Node()`` cannot silently produce an untraceable event.
NODE_IDENTITY_MISSING = "NODE_IDENTITY_MISSING"

#: ``resume_point`` was provided but ``services.node_registry`` is None or
#: does not contain ``resume_point.next_node_id``. The runner cannot resolve
#: the resume entry point and refuses to start. Full registry-hash checking
#: is P0-C; P0-B only checks existence.
RESUME_REGISTRY_MISMATCH = "RESUME_REGISTRY_MISMATCH"

#: Cooperative cancellation was triggered between nodes. The runner emitted
#: ``flow.stopped`` with ``stop_reason="cancelled"`` and exited cleanly.
#: This code is used in ``node.failed`` events only when cancellation
#: interrupts a node mid-execution (not the current P0-B behavior — the
#: token is checked between nodes, not inside exec).
CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"

#: Addendum P0-C §5.3: a Checkpoint exists but the runtime cannot safely
#: auto-resume because either (a) a node's ``node.started`` event has no
#: matching ``node.completed`` (the node crashed mid-execution), or (b) a
#: mutating side-effect operation is in a non-terminal state
#: (``operation.started`` without ``committed`` / ``failed`` /
#: ``unknown_outcome``). Resume MUST stop and a human or higher-level
#: recovery process must reconcile the partial state before re-entering
#: the Flow. NEVER auto-replay a mutating operation (Addendum §5.3).
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

#: Addendum P0-C §5.4: the Checkpoint's ``checkpoint_registry_hash`` does
#: not match the current NodeRegistry hash, or ``next_node_id`` is not
#: present in the current registry. The Flow definition has changed since
#: the Checkpoint was written; resume MUST stop and surface both hashes
#: (or the missing node id). Silently mapping to the "closest" node name is
#: explicitly forbidden. Full cross-version migration is a later version.
INCOMPATIBLE_FLOW_DEFINITION = "INCOMPATIBLE_FLOW_DEFINITION"


#: All stable error codes exported by this module. Artifact generators and
#: contract tests iterate over this tuple to verify completeness.
ALL_ERROR_CODES: tuple[str, ...] = (
    NODE_PREP_FAILED,
    NODE_EXEC_FAILED,
    NODE_POST_FAILED,
    NODE_IDENTITY_MISSING,
    RESUME_REGISTRY_MISMATCH,
    CANCELLATION_REQUESTED,
    RECOVERY_REQUIRED,
    INCOMPATIBLE_FLOW_DEFINITION,
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_exception(node_id: str | None, phase: str, exc: BaseException) -> str:
    """Map a ``(phase, exc)`` pair to a stable error code string.

    ``phase`` is one of:

    - ``"prep"``   → ``NODE_PREP_FAILED``
    - ``"exec"``   → ``NODE_EXEC_FAILED``
    - ``"post"``   → ``NODE_POST_FAILED``
    - ``"identity"`` → ``NODE_IDENTITY_MISSING``
    - ``"resume"`` → ``RESUME_REGISTRY_MISMATCH``
    - ``"cancellation"`` → ``CANCELLATION_REQUESTED``

    The classifier does NOT inspect the exception type beyond the phase.
    The phase alone determines the code. This keeps the mapping stable
    across Python versions and exception hierarchies — a ``ValueError`` in
    ``prep`` and a ``RuntimeError`` in ``prep`` both map to
    ``NODE_PREP_FAILED``.

    The exception itself is NOT swallowed; the caller re-raises after using
    the returned code in a ``node.failed`` event payload.

    ``node_id`` is accepted for future per-node error-code customization
    but is not used in v0.04. It exists so the signature can stay stable
    when P0-C adds node-specific recovery hints.
    """
    if phase == "prep":
        return NODE_PREP_FAILED
    if phase == "exec":
        return NODE_EXEC_FAILED
    if phase == "post":
        return NODE_POST_FAILED
    if phase == "identity":
        return NODE_IDENTITY_MISSING
    if phase == "resume":
        return RESUME_REGISTRY_MISMATCH
    if phase == "cancellation":
        return CANCELLATION_REQUESTED
    # Unknown phase: fall back to the generic exec-failed code so the event
    # is still emitted with a stable, known code rather than None. This
    # branch should not be reached in normal operation; it exists as a
    # defensive default for future phases not yet defined.
    return NODE_EXEC_FAILED


# ---------------------------------------------------------------------------
# Error code table (for artifact generation)
# ---------------------------------------------------------------------------


ERROR_CODE_TABLE: list[dict[str, str]] = [
    {
        "code": NODE_PREP_FAILED,
        "phase": "prep",
        "description": "Node prep hook raised an exception before exec.",
    },
    {
        "code": NODE_EXEC_FAILED,
        "phase": "exec",
        "description": "Node exec or _exec retry loop raised an exception.",
    },
    {
        "code": NODE_POST_FAILED,
        "phase": "post",
        "description": "Node post hook raised an exception after exec succeeded.",
    },
    {
        "code": NODE_IDENTITY_MISSING,
        "phase": "identity",
        "description": "Node has no node_id attribute and is not in the registry.",
    },
    {
        "code": RESUME_REGISTRY_MISMATCH,
        "phase": "resume",
        "description": "resume_point references a node_id not in the registry.",
    },
    {
        "code": CANCELLATION_REQUESTED,
        "phase": "cancellation",
        "description": "Cooperative cancellation token was triggered.",
    },
]
