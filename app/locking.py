"""One nonblocking Linux lock for commands that access persistent state."""

import os
from functools import wraps

from app.i18n import t
from app.paths import runtime_path

try:
    import fcntl
except ImportError:
    fcntl = None


class LockBusy(RuntimeError):
    """Another Bridge command holds the common database lock."""


def acquire_lock():
    if fcntl is None:
        raise RuntimeError(t('platform.linux_required'))
    path = runtime_path('data/gmail_bridge.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+', encoding='utf-8')
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    except BaseException:
        stream.close()
        raise
    try:
        stream.seek(0)
        stream.truncate()
        stream.write(f'pid={os.getpid()}\n')
        stream.flush()
    except BaseException:
        stream.close()
        raise
    return stream


def locked_command(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        # Keep Windows offline status/init support; runtime commands require Linux.
        if fcntl is None:
            return function(*args, **kwargs)
        stream = acquire_lock()
        if stream is None:
            raise LockBusy(t('lock.busy'))
        try:
            return function(*args, **kwargs)
        finally:
            stream.close()
    return invoke
