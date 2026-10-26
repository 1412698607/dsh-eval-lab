"""One cooperative scheduler per batch; kernel locks release on process exit."""
from contextlib import contextmanager
import os

from .formats import require

LOCK_NAME = ".batch-execution.lock"


@contextmanager
def batch_lock(directory, *, create=False):
    path = directory / LOCK_NAME
    require(create or path.is_file(), "Batch has no execution lock; legacy batches cannot be resumed")
    with path.open("a+b" if create else "r+b") as stream:
        if create and stream.seek(0, 2) == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Batch is active or locked by another scheduler") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
