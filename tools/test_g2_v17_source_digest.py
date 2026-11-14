"""Guard immutable source lock across LF/CRLF Git worktree checkout."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from g2_v17_source_digest import source_sha256,LEGACY_WIN_TEXT_JSON

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"

def test_windows_generated_evidence_SHA_matches_historical_expected():
    bcu=json.loads((G/"g2_v17_bcu_short_control_bridges_NOT_FOR_FAB.json").read_text("utf8"))
    fine=json.loads((G/"g2_v17_u2_gd1_gd2_layer_escape_NOT_FOR_FAB.json").read_text("utf8"))
    gate=json.loads((G/"g2_v17_local_primary_gate_routes_NOT_FOR_FAB.json").read_text("utf8"))
    assert bcu["source_signal_sha"]==source_sha256(G/"g2_v17_signal_legal_route_plan_NOT_FOR_FAB.json")
    assert fine["source_bcu_sha"]==source_sha256(G/"g2_v17_bcu_short_control_bridges_NOT_FOR_FAB.json")
    assert gate["source_gd_sha"]==source_sha256(G/"g2_v17_u2_gd1_gd2_layer_escape_NOT_FOR_FAB.json")

def test_known_LF_and_CRLF_are_same_source_not_changed_data(tmp_path):
    content=b'{"net": "SW", "pins": 2}\n'
    a=tmp_path/"g2_v17_signal_legal_route_plan_NOT_FOR_FAB.json"
    a.write_bytes(content)
    expected=source_sha256(a)
    a.write_bytes(content.replace(b"\n",b"\r\n"))
    assert source_sha256(a)==expected
    a.write_bytes(b'{"net": "VIN_P", "pins": 2}\r\n')
    assert source_sha256(a)!=expected

def test_binary_and_nonlegacy_json_sha_still_strict(tmp_path):
    f=tmp_path/"board.eprj2"
    f.write_bytes(b"\x00\x01\n\r\n")
    assert source_sha256(f)==hashlib.sha256(f.read_bytes()).hexdigest()
    f=tmp_path/"g2_v17_compact_emc_first_screen_LOCKED_NOT_FOR_FAB.json"
    f.write_bytes(b'{"a":1}\n')
    first=source_sha256(f)
    f.write_bytes(b'{"a":1}\r\n')
    assert source_sha256(f)!=first
