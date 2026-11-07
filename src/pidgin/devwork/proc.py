"""Process helpers: detached spawn, liveness with start-time check, tree kill.

Runs are spawned detached with output going to files (not pipes), so a Pidgin
restart neither kills them nor loses their output. Their stdin is a pipe Pidgin
keeps open to send messages into the session (stream-json); after a restart
that pipe is gone, so the run finishes its current turn and exits. PIDs are reused on Windows,
so liveness also compares the process creation time recorded at spawn.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def _win_creation_time(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        STILL_ACTIVE = 259
        if exit_code.value != STILL_ACTIVE:
            return None
        creation, exit_t, kernel_t, user_t = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_t),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def process_fingerprint(pid: int) -> str | None:
    """A string identifying this exact process (pid + creation time), or None if gone."""
    if IS_WINDOWS:
        created = _win_creation_time(pid)
        return f"{pid}:{created}" if created is not None else None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        return f"{pid}:{stat[21]}"
    except OSError:
        return f"{pid}:?"


def is_alive(pid: int | None, fingerprint: str | None) -> bool:
    if not pid:
        return False
    current = process_fingerprint(pid)
    if current is None:
        return False
    return fingerprint is None or current == fingerprint


def spawn_detached(
    args: list[str],
    *,
    cwd: Path,
    stdin_path: Path | None,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    # No stdin file: a pipe the caller writes to (and closes to end the run).
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.PIPE  # noqa: SIM115
    stdout = open(stdout_path, "ab")  # noqa: SIM115
    stderr = open(stderr_path, "ab")  # noqa: SIM115
    kwargs: dict[str, object] = {}
    if IS_WINDOWS:
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(  # noqa: S603
            args,
            cwd=str(cwd),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            close_fds=True,
            **kwargs,  # type: ignore[arg-type]
        )
    finally:
        if stdin is not subprocess.PIPE:
            stdin.close()  # type: ignore[union-attr]
        stdout.close()
        stderr.close()
    return proc


def kill_tree(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(  # noqa: S603, S607
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass
