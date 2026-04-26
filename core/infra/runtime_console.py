"""Runtime log capture for the in-app JoyBoy console.

The Linux cloud path needs more than wrapping ``sys.stdout``: subprocesses such
as pip and HuggingFace download helpers write directly to file descriptors.
When possible we tee stdout/stderr at fd level, then expose a small polling API.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
import os
import sys
import threading
from typing import Deque, Dict, Iterable, List


_MAX_LINES = 1200
_entries: Deque[Dict[str, object]] = deque(maxlen=_MAX_LINES)
_lock = threading.RLock()
_seq = 0
_installed = False
_fd_threads: List[threading.Thread] = []
_fallback_streams = {}


class _LineAccumulator:
    def __init__(self, stream_name: str) -> None:
        self.stream_name = stream_name
        self._pending = ""

    def feed(self, text: str) -> None:
        if not text:
            return
        normalized = text.replace("\r", "\n")
        parts = normalized.split("\n")
        if self._pending:
            parts[0] = self._pending + parts[0]
            self._pending = ""

        for line in parts[:-1]:
            _append_entry(self.stream_name, line)

        self._pending = parts[-1]
        if len(self._pending) > 1200:
            _append_entry(self.stream_name, self._pending)
            self._pending = ""

    def flush(self) -> None:
        if self._pending:
            _append_entry(self.stream_name, self._pending)
            self._pending = ""


class _StreamTee:
    """Fallback tee for environments where fd-level capture is unavailable."""

    def __init__(self, wrapped, stream_name: str) -> None:
        self._wrapped = wrapped
        self._accumulator = _LineAccumulator(stream_name)

    def write(self, text):
        written = self._wrapped.write(text)
        self._accumulator.feed(str(text))
        return written

    def flush(self):
        self._wrapped.flush()
        self._accumulator.flush()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _append_entry(stream_name: str, line: str) -> None:
    global _seq
    text = str(line or "").rstrip("\n")
    if not text:
        return

    with _lock:
        _seq += 1
        _entries.append({
            "seq": _seq,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "stream": stream_name,
            "text": text,
        })


def _reader_loop(read_fd: int, mirror_fd: int, stream_name: str) -> None:
    accumulator = _LineAccumulator(stream_name)
    while True:
        try:
            chunk = os.read(read_fd, 8192)
        except OSError:
            break
        if not chunk:
            break
        try:
            os.write(mirror_fd, chunk)
        except OSError:
            pass
        accumulator.feed(chunk.decode(getattr(sys.stdout, "encoding", None) or "utf-8", errors="replace"))
    accumulator.flush()


def _install_fd_capture(fd: int, stream_name: str) -> bool:
    try:
        mirror_fd = os.dup(fd)
        read_fd, write_fd = os.pipe()
        os.dup2(write_fd, fd)
        os.close(write_fd)
    except OSError:
        return False

    thread = threading.Thread(
        target=_reader_loop,
        args=(read_fd, mirror_fd, stream_name),
        name=f"joyboy-runtime-console-{stream_name}",
        daemon=True,
    )
    thread.start()
    _fd_threads.append(thread)
    return True


def _install_stream_fallback() -> None:
    if "stdout" not in _fallback_streams:
        _fallback_streams["stdout"] = sys.stdout
        sys.stdout = _StreamTee(sys.stdout, "stdout")
    if "stderr" not in _fallback_streams:
        _fallback_streams["stderr"] = sys.stderr
        sys.stderr = _StreamTee(sys.stderr, "stderr")


def install_runtime_console(max_lines: int = 1200) -> None:
    """Install one global stdout/stderr capture for the current process."""
    global _installed, _MAX_LINES, _entries
    if _installed:
        return

    with _lock:
        if _installed:
            return
        _MAX_LINES = max(200, int(max_lines or 1200))
        _entries = deque(_entries, maxlen=_MAX_LINES)
        _installed = True

    stdout_ok = _install_fd_capture(1, "stdout")
    stderr_ok = _install_fd_capture(2, "stderr")
    if not (stdout_ok and stderr_ok):
        _install_stream_fallback()

    _append_entry("system", "Console runtime JoyBoy active (F10 dans l'interface).")


def get_runtime_console_entries(after: int = 0, limit: int = 300) -> Dict[str, object]:
    """Return buffered console lines newer than ``after``.

    ``after=0`` returns the most recent ``limit`` entries so opening the panel
    immediately shows useful context.
    """
    try:
        after_seq = int(after or 0)
    except (TypeError, ValueError):
        after_seq = 0
    try:
        max_items = min(800, max(1, int(limit or 300)))
    except (TypeError, ValueError):
        max_items = 300

    with _lock:
        items: Iterable[Dict[str, object]]
        if after_seq > 0:
            items = [entry for entry in _entries if int(entry.get("seq", 0)) > after_seq]
        else:
            items = list(_entries)[-max_items:]
        entries = list(items)[-max_items:]
        next_seq = int(_entries[-1]["seq"]) if _entries else after_seq

    return {
        "success": True,
        "entries": entries,
        "nextSeq": next_seq,
        "installed": _installed,
    }
