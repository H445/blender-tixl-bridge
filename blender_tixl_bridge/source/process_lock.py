"""Kernel-owned sync locks release automatically when a worker exits."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


@contextmanager
def process_lock(path: Path, timeout: float = 7200):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep this inode in place: unlinking a locked file lets a second caller
    # acquire a different inode while the first still owns its lock.
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for TiXL sync: {path.parent}") from error
                time.sleep(.1)
        try:
            yield
        finally:
            release()
