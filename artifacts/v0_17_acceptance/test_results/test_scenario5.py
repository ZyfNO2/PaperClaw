"""Test Scenario 5: User profile and long memory."""
import sys
sys.path.insert(0, r"G:\PaperClaw\src")

from pathlib import Path
from paperclaw.memory.store import FileMemoryStore, MemoryPolicy

# Create test memory store
test_dir = Path(r"G:\PaperClaw\.tmp\memory-test")
test_dir.mkdir(parents=True, exist_ok=True)
store = FileMemoryStore(test_dir, policy=MemoryPolicy())

print("=== Scenario 5: User Profile and Long Memory ===")
print()

# Step 1: Add high-confidence user preference
print("Step 1: Add high-confidence user preference")
entry1 = store.add(
    "user",
    "User prefers concise responses with code examples",
    category="preference",
    confidence=0.95,
)
print(f"  Added: {entry1.content[:50]}...")
print(f"  Confidence: {entry1.confidence}")
print()

# Step 2: Add low-confidence user preference
print("Step 2: Add low-confidence user preference")
entry2 = store.add(
    "user",
    "User might prefer dark theme",
    category="preference",
    confidence=0.3,
)
print(f"  Added: {entry2.content[:50]}...")
print(f"  Confidence: {entry2.confidence}")
print()

# Step 3: Add project convention to memory
print("Step 3: Add project convention to memory")
entry3 = store.add(
    "memory",
    "Project uses Python 3.12 with strict type hints",
    category="convention",
    confidence=0.9,
)
print(f"  Added: {entry3.content[:50]}...")
print(f"  Category: {entry3.category}")
print()

# Step 4: Get snapshot (simulates new runtime)
print("Step 4: Get snapshot (new runtime)")
snapshot = store.snapshot()
print(f"  User entries: {len(snapshot.user_entries)}")
print(f"  Memory entries: {len(snapshot.memory_entries)}")
print(f"  High-confidence user entries: {sum(1 for e in snapshot.user_entries if e.confidence >= 0.8)}")
print(f"  Low-confidence user entries: {sum(1 for e in snapshot.user_entries if e.confidence < 0.8)}")
print()

# Step 5: Replace high-confidence entry
print("Step 5: Replace high-confidence entry")
replaced = store.replace(
    "user",
    "User prefers concise responses with code examples",
    "User prefers detailed responses with explanations",
)
print(f"  Replaced: {replaced.content[:50]}...")
print()

# Step 6: Remove entry and get new snapshot
print("Step 6: Remove entry and get new snapshot")
removed = store.remove(
    "user",
    "User prefers detailed responses with explanations",
)
print(f"  Removed: {removed.content[:50]}...")
snapshot2 = store.snapshot()
print(f"  User entries after removal: {len(snapshot2.user_entries)}")
print()

# Step 7: Test capacity limit
print("Step 7: Test capacity limit")
try:
    for i in range(100):
        store.add(
            "user",
            f"Test preference {i}: " + "x" * 100,
            category="preference",
            confidence=0.5,
        )
    print("  ERROR: Should have raised MemoryCapacityError")
except Exception as e:
    print(f"  Capacity error raised: {type(e).__name__}")
print()

# Verify key assertions
print("=== Verification ===")
final_snapshot = store.snapshot()
assert len(final_snapshot.user_entries) >= 1, "Should have at least 1 user entry"
assert len(final_snapshot.memory_entries) >= 1, "Should have at least 1 memory entry"
print("All assertions passed!")
