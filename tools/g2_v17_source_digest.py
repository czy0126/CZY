"""V17 frozen CAD evidence SHA256 independent of Git newline checkout.

A limited set of legacy generated JSON files was originally hashed after
Windows text-mode CRLF encoding, but Git commits normalized these to LF.
Reproduce the historical CRLF digest for those *named* files while retaining
the strict bytewise SHA for the native binary, nominal layout and PGND inputs.
No JSON parsing/reformatting: ANY non-newline content change changes digest.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

LEGACY_WIN_TEXT_JSON = frozenset({
    "g2_v17_signal_legal_route_plan_NOT_FOR_FAB.json",
    "g2_v17_bcu_short_control_bridges_NOT_FOR_FAB.json",
    "g2_v17_u2_gd1_gd2_layer_escape_NOT_FOR_FAB.json",
    "g2_v17_local_primary_gate_routes_NOT_FOR_FAB.json",
    "g2_v17_short_sr_drain_kelvin_NOT_FOR_FAB.json",
    "g2_v17_remaining_VD_B_short_sense_NOT_FOR_FAB.json",
    "g2_v17_local_SW_finger_reference_NOT_FOR_FAB.json",
})

def source_sha256(path: str | Path) -> str:
    path=Path(path)
    content=path.read_bytes()
    if path.name in LEGACY_WIN_TEXT_JSON:
        content=content.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
    return hashlib.sha256(content).hexdigest()
