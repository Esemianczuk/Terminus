"""Small flock-compatible process locks, including Windows byte-range locks.

The lock belongs to the open file handle and is released by the OS on a crash.
No PID file can accidentally unlock a different process.
"""
import errno
import os
import time

if os.name != 'nt':
    from fcntl import flock, LOCK_EX, LOCK_NB, LOCK_UN
else:
    import msvcrt
    LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

    def flock(file, operation):
        fd = file if isinstance(file, int) else file.fileno()
        os.lseek(fd, 0, os.SEEK_SET)
        if operation & LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError(errno.EAGAIN, 'Terminus lock is held') from error
                time.sleep(.1)
