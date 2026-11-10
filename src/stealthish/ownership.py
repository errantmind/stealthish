"""One OS-backed lock. No polling, PID guessing, queue, or lock-file deletion."""
import os
from pathlib import Path
import stat
import sys

from .errors import StartupError


def private_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise StartupError("INVALID_CONFIG")
    if sys.platform != "win32":
        if path.stat().st_uid != os.getuid():
            raise StartupError("INVALID_CONFIG")
        path.chmod(0o700)


class ProfileLock:
    def __init__(self, root: Path):
        self.root = root
        self.fd = None

    def acquire(self):
        if self.fd is not None:
            raise StartupError("PROFILE_BUSY")
        private_directory(self.root)
        private_directory(self.root / "state")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.root / "state/owner.lock", flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StartupError("INVALID_CONFIG")
            if sys.platform == "win32":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise StartupError("PROFILE_BUSY") from None
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    @classmethod
    def adopt(cls, root: Path, fd: int):
        """Use the same open lock description in a maintenance child process."""
        if sys.platform != "linux":
            raise StartupError("UNSUPPORTED_PLATFORM")
        import fcntl
        lock = cls(root)
        held = os.fstat(fd)
        expected = (root / "state/owner.lock").lstat()
        if not stat.S_ISREG(held.st_mode) or (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
            raise StartupError("PROFILE_BUSY")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.fd = os.dup(fd)
        return lock

    def close(self):
        if self.fd is not None:
            # Closing the descriptor releases the OS lock, including after a crash.
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.close()
