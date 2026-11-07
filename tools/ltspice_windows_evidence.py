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


def verify_committed_log_measurements(
    log_path: Path,
    recorded_measures: dict[str, float],
    historical_log_sha256: str,
    parser,
) -> dict:
    """Separate exact original bytes from semantically matching log measures.

    Original Windows .log bytes have not necessarily survived Git transport.
    We refuse to recalculate/replace the original report SHA with one from
    current text. Exact bytes are certified only if current LF/CRLF bytes
    reproduce that historical SHA. Otherwise the original raw log is needed.
    """
    if log_path.suffix.lower() != ".log":
        raise ValueError("only LTspice .log evidence is accepted")
    actual_measures = parser(log_path.read_text(
        encoding="utf-8", errors="replace"))
    if set(actual_measures) != set(recorded_measures):
        raise ValueError("committed log measurement keys differ from report")
    for key, historical in recorded_measures.items():
        if actual_measures[key] != historical:
            raise ValueError(f"changed measurement in committed log: {key}")
    actual_hash = actual_file_sha256(log_path)
    reconstructed = original_windows_deck_sha256(log_path)
    exact = historical_log_sha256 in (actual_hash, reconstructed)
    return {
        "status": ("ORIGINAL_LOG_BYTES_VERIFIED" if exact else
                   "MEASUREMENTS_MATCH_ORIGINAL_LOG_BYTES_UNAVAILABLE"),
        "measurements_exactly_match": True,
        "historical_log_sha256": historical_log_sha256,
        "committed_log_sha256": actual_hash,
        "reconstructed_windows_log_sha256": reconstructed,
        "original_log_bytes_verified": exact,
        "hardware_qualified": False,
        "fabrication_approved": False,
    }
