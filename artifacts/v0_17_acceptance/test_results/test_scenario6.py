"""Test Scenario 6: Memory privacy and concurrency."""
import sys
sys.path.insert(0, r"G:\PaperClaw\src")

from pathlib import Path
from paperclaw.memory.store import FileMemoryStore, MemoryPrivacyError, MemoryPolicy
import threading
import time

# Create test memory store
test_dir = Path(r"G:\PaperClaw\.tmp\memory-privacy-test")
test_dir.mkdir(parents=True, exist_ok=True)
store = FileMemoryStore(test_dir, policy=MemoryPolicy())

print("=== Scenario 6: Memory Privacy and Concurrency ===")
print()

# Step 1: Attempt to store API-key-shaped value
print("Step 1: Attempt to store API-key-shaped value")
try:
    store.add("user", "My API key is sk-123456789012345678901234567890", category="other")
    print("  ERROR: Should have raised MemoryPrivacyError")
except MemoryPrivacyError as e:
    print(f"  Correctly rejected: {type(e).__name__}")
print()

# Step 2: Attempt to store private key header
print("Step 2: Attempt to store private key header")
try:
    store.add("user", "-----BEGIN RSA PRIVATE KEY-----", category="other")
    print("  ERROR: Should have raised MemoryPrivacyError")
except MemoryPrivacyError as e:
    print(f"  Correctly rejected: {type(e).__name__}")
print()

# Step 3: Attempt to store reserved delimiter
print("Step 3: Attempt to store reserved delimiter")
try:
    store.add("user", "First paragraph\n§\nSecond paragraph", category="other")
    print("  ERROR: Should have raised ValueError")
except ValueError as e:
    print(f"  Correctly rejected: {type(e).__name__}")
print()

# Step 4: Concurrent writes from two processes
print("Step 4: Concurrent writes from two processes")
results = []
errors = []

def write_thread(thread_id):
    try:
        for i in range(5):
            entry = store.add(
                "user",
                f"Thread {thread_id} entry {i}",
                category="other",
                confidence=0.5,
            )
            results.append((thread_id, i, entry.content))
            time.sleep(0.01)
    except Exception as e:
        errors.append((thread_id, str(e)))

threads = [
    threading.Thread(target=write_thread, args=(1,)),
    threading.Thread(target=write_thread, args=(2,)),
]
for t in threads:
    t.start()
for t in threads:
    t.join()

print(f"  Successful writes: {len(results)}")
print(f"  Errors: {len(errors)}")
if errors:
    for thread_id, error in errors:
        print(f"    Thread {thread_id}: {error}")
print()

# Step 5: Verify no stale lock
print("Step 5: Verify no stale lock")
lock_file = test_dir / ".paperclaw-memory.lock"
if lock_file.exists():
    print("  WARNING: Lock file still exists!")
else:
    print("  No stale lock file (correct)")
print()

# Verification
print("=== Verification ===")
final_entries = store.list_entries("user")
print(f"Total user entries: {len(final_entries)}")
thread_entries = [e for e in final_entries if "Thread" in e.content]
print(f"Concurrent thread entries: {len(thread_entries)}")
assert len(thread_entries) >= 10, f"Expected at least 10 concurrent entries, got {len(thread_entries)}"
print("All assertions passed!")
