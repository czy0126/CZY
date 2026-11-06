"""Byte identity for Git-tracked text, independent of checkout line endings.

Git stores text as LF.  A Windows checkout with ``core.autocrlf=true`` -- or a
tool such as KiCad that rewrites a file with CRLF -- must not change a SHA256
recorded in a committed JSON, otherwise CI (an LF checkout) and the developer
(CRLF) disagree about the same file.  Record the canonical form instead.

Binary files keep their byte identity: a ``.raw`` is evidence, not source.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Suffixes whose content is text.  Gerber/drill/position exports are textual
# numerical tooling formats too: kicad-cli emits them with CRLF on Windows.
FAB_TEXT_SUFFIXES = frozenset({
    ".gbl", ".gbs", ".gbp", ".gbo", ".gm1", ".gtl", ".gts", ".gtp",
    ".gbrjob", ".drl", ".csv",
})

TEXT_SUFFIXES = FAB_TEXT_SUFFIXES | frozenset({
    ".cir", ".inc", ".json", ".kicad_pcb", ".kicad_pro", ".kicad_sch",
    ".lib", ".md", ".net", ".py", ".sch", ".sub", ".svg", ".tsv", ".txt",
    ".yaml", ".yml",
})


def canonical_bytes(path: Path) -> bytes:
    """LF-normalised bytes for text; the raw bytes for anything else."""
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES and b"\x00" not in data:
        return data.replace(b"\r\n", b"\n")
    return data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()
