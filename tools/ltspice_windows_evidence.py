"""Exact LTspice Windows source-byte identity across Git LF checkouts.

The 2026-11-07 Rev-B LTspice 26.0.2 .cir files were simulated with
CRLF bytes on Windows. Git committed normalized LF text. The historical
report SHA-256 records the *original simulated CRLF bytes*, which must
never be overwritten or claimed to have been re-simulated.

For .cir only, restore CRLF deterministically before computing the
recorded SHA. This is valid ONLY if the complete file text matches the
committed generated source; current deck equality remains a separate
required test. Logs remain byte-hashed verbatim. Any other input difference
still changes SHA, and model/hardware certification remains false.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def original_windows_deck_sha256(path: Path) -> str:
    """Reconstruct the actual Windows .cir byte sequence, not a new run."""
    if path.suffix.lower() != ".cir":
        raise ValueError("Windows-deck SHA reconstruction applies only to .cir")
    raw = path.read_bytes()
    if b"\x00" in raw or b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("not a plain LF/CRLF SPICE deck")
    original_windows = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return hashlib.sha256(original_windows).hexdigest()


def actual_file_sha256(path: Path) -> str:
    """Strict byte hash, used for immutable .log evidence and other files."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
