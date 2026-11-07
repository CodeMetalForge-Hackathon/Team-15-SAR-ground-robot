"""One owner per replay-state FILE, however its path is spelled.

The state path is resolved once (os.path.realpath: symlinks, symlinked folders,
"..", relative paths) and that canonical path is then used for the lock, for
loading, and for every save. Hard links cannot be told apart by path, so a state
file with more than one link is rejected outright. The lock is an exclusive,
non-blocking flock on "<canonical path>.lock", held for the process lifetime; the
kernel releases it when the process exits. Out of scope: the same file reached
through different mounts (bind mounts, network shares).
"""
from __future__ import annotations

import fcntl
import os
import stat


class OwnerError(Exception):
    """The replay state is owned by another process, or its path is ambiguous."""


def canonical_state_path(path) -> str:
    """Absolute real path of the state file; rejects hard-linked state."""
    real = os.path.realpath(os.fspath(path))
    try:
        st = os.stat(real)
    except FileNotFoundError:
        return real                                 # load_state then fails closed
    if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
        raise OwnerError(f"replay state {real} has {st.st_nlink} hard links; refusing ambiguous ownership")
    return real


def acquire_owner(canonical_path: str) -> int:
    """Lock "<canonical path>.lock" or raise OwnerError. Returns the open lock fd."""
    lock = f"{canonical_path}.lock"
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:                          # e.g. the lock file is itself a symlink
        raise OwnerError(f"cannot open lock file {lock}: {exc.strerror}") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise OwnerError(f"replay state {canonical_path} is owned by another verifier process") from None
    return fd
