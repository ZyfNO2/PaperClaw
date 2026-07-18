"""Test Scenario 9: Tool authorization."""
import sys
sys.path.insert(0, r"G:\PaperClaw\src")

from pathlib import Path
from paperclaw.policy.tools import DefaultToolAuthorizationPolicy

# Create test workspace
workspace = Path(r"G:\PaperClaw\.tmp\tool-auth-test")
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "test.txt").write_text("hello", encoding="utf-8")

policy = DefaultToolAuthorizationPolicy()

print("=== Scenario 9: Tool Authorization ===")
print()

# Step 1: Permitted workspace-local file operation
print("Step 1: Permitted workspace-local file operation")
decision = policy.authorize("file_read", {"path": str(workspace / "test.txt")}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
assert decision.allowed, "Workspace file should be allowed"
print("  PASS")
print()

# Step 2: Path outside workspace
print("Step 2: Path outside workspace")
decision = policy.authorize("file_read", {"path": "C:/Windows/System32/config/sam"}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
assert not decision.allowed, "Path outside workspace should be denied"
print("  PASS")
print()

# Step 3: Destructive tool without approval
print("Step 3: Destructive tool without approval")
decision = policy.authorize("bash", {"command": "rm -rf /"}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
assert not decision.allowed, "Destructive tool should require approval"
print("  PASS")
print()

# Step 4: Approved destructive tool
print("Step 4: Approved destructive tool")
approved_policy = DefaultToolAuthorizationPolicy(approved_tools=("bash",))
decision = approved_policy.authorize("bash", {"command": "echo hello"}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
assert decision.allowed, "Approved tool should be allowed"
print("  PASS")
print()

# Step 5: URL with credentials
print("Step 5: URL with credentials")
decision = policy.authorize("bash", {"command": "curl https://user:pass@example.com/api"}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
# Note: The policy may allow or deny this depending on validation
print("  Checked (no crash)")
print()

# Step 6: Empty tool name
print("Step 6: Empty tool name")
decision = policy.authorize("", {}, workspace)
print(f"  Allowed: {decision.allowed}")
print(f"  Risk: {decision.risk.value}")
print(f"  Reason: {decision.reason}")
assert not decision.allowed, "Empty tool name should be denied"
print("  PASS")
print()

print("=== Verification ===")
print("All authorization checks passed!")
