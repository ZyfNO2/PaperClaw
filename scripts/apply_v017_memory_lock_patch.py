from __future__ import annotations

from pathlib import Path

path = Path("src/paperclaw/memory/store.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from dataclasses import dataclass\n",
    "from contextlib import contextmanager\nfrom dataclasses import dataclass\nfrom functools import wraps\n",
    1,
)
text = text.replace(
    "import json\nfrom pathlib import Path\nimport re\nimport threading\n",
    "import json\nimport os\nfrom pathlib import Path\nimport re\nimport threading\nimport time\n",
    1,
)
text = text.replace(
    '''class MemoryStoreError(RuntimeError):
    """Base error for persistent-memory operations."""


class MemoryCapacityError''',
    '''class MemoryStoreError(RuntimeError):
    """Base error for persistent-memory operations."""


class MemoryLockTimeout(MemoryStoreError):
    """Raised when another process holds the memory writer lock too long."""


def _serialized_write(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            with self._process_lock():
                return method(self, *args, **kwargs)

    return wrapped


class MemoryCapacityError''',
    1,
)
text = text.replace(
    '''        self.policy = policy or MemoryPolicy()
        self._lock = threading.RLock()

    def path_for''',
    '''        self.policy = policy or MemoryPolicy()
        self._lock = threading.RLock()

    @contextmanager
    def _process_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".paperclaw-memory.lock"
        deadline = time.monotonic() + 5.0
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime > 60.0
                except OSError:
                    stale = False
                if stale:
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise MemoryLockTimeout(
                        "timed out waiting for the cross-process memory writer lock"
                    )
                time.sleep(0.05)
        try:
            os.write(descriptor, f"pid={os.getpid()} created={time.time()}\\n".encode())
            yield
        finally:
            os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def path_for''',
    1,
)
for signature in ("    def add(\n", "    def replace(\n", "    def remove("):
    replacement = "    @_serialized_write\n" + signature
    if replacement not in text:
        text = text.replace(signature, replacement, 1)
text = text.replace(
    '''        if len(normalized) > self.policy.max_entry_chars:
            raise ValueError(''',
    '''        if any(line.strip() == "§" for line in normalized.splitlines()) or _METADATA_PREFIX in normalized:
            raise ValueError("memory content contains a reserved storage delimiter")
        if len(normalized) > self.policy.max_entry_chars:
            raise ValueError(''',
    1,
)
text = text.replace(
    '''    "MemoryEntry",
    "MemoryMatchError",''',
    '''    "MemoryEntry",
    "MemoryLockTimeout",
    "MemoryMatchError",''',
    1,
)
path.write_text(text, encoding="utf-8")
