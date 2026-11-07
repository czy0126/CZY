"""Exact LTspice Windows source-byte identity across Git LF checkouts.

The 2026-11-07 Rev-B LTspice 26.0.2 .cir inputs and .log outputs used
CRLF bytes on Windows. Git committed normalized LF text for both. The
historical SHA-256 fields record *original Windows CRLF bytes*, which must
never be overwritten or claimed to have been re-simulated.

Restore CRLF deterministically for .cir AND .log before computing the
recorded SHA. This is valid ONLY if the complete deck text matches the
committed generated source, and the complete log bytes have no alterations
except newline encoding. Any non-EOL difference changes SHA, and no new
simulation or hardware certification is inferred.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def original_windows_deck_sha256(path: Path) -> str:
    """Reconstruct original Windows .cir/.log bytes, not a new run."""
    if path.suffix.lower() not in {".cir", ".log"}:
        raise ValueError("Windows text SHA reconstruction applies only to .cir/.log")
    raw = path.read_bytes()
    if b"\x00" in raw or b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("not a plain LF/CRLF LTspice text file")
    original_windows = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return hashlib.sha256(original_windows).hexdigest()


def actual_file_sha256(path: Path) -> str:
    """Strict byte hash, used for immutable .log evidence and other files."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
