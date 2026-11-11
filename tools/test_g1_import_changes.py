"""Lock the Import-Changes diff normalizer and, if captured, its receipt.

The editor's beta comparator is documented with ``netlist1Name``/``netlist2Name``
but its own example reads ``net1``/``net2``. The normalizer must accept both and
never invent a difference. The receipt check only runs when the capture exists.

The second half locks the derived difference: only the five magnetics' 24
logical terminals may be unmatched, no PCB pin may be missing a schematic
partner, and a receipt or a comparator column that stops agreeing is refused.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
RECEIPT = G1 / "lr_signal_import_changes.json"

sys.path.insert(0, str(G1))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import read_import_changes as R  # noqa: E402
import g1_import_changes_diff as D  # noqa: E402


def test_both_documented_field_spellings_normalize_identically():
    signed = [{"type": "Component", "object": "T1",
               "netlist1Name": ["PRI_A"], "netlist2Name": []}]
    example = [{"type": "Component", "object": "T1",
                "net1": ["PRI_A"], "net2": []}]
    assert R.normalize(signed) == R.normalize(example)
    assert R.normalize(signed) == [
        {"type": "Component", "object": "T1", "schematic": ["PRI_A"], "pcb": []}]


def test_rows_are_sorted_and_missing_lists_become_empty():
    entries = [
        {"type": "Net", "object": "VOUT", "netlist1Name": ["A"], "netlist2Name": ["A"]},
        {"type": "Component", "object": "R6", "netlist1Name": ["VCC12"]},
    ]
    rows = R.normalize(entries)
    assert [r["object"] for r in rows] == ["R6", "VOUT"]
    assert rows[0]["pcb"] == []
    assert R.normalize(None) == []
    assert R.normalize([]) == []


def test_a_non_list_payload_fails_closed():
    # An exception or an undefined result stringifies to "undefined"; it must
    # never be mistaken for a difference list.
    with pytest.raises(ValueError, match="not a list"):
        R.normalize("undefined")
    with pytest.raises(ValueError, match="not an object"):
        R.normalize(["undefined"])


def test_captured_receipt_is_bound_to_the_candidate_and_a_copy():
    if not RECEIPT.exists():
        pytest.skip("Import-Changes receipt not captured on this checkout")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["editor_ok"] is True, receipt.get("readback_error")
    assert receipt["candidate_sha256"] == receipt["probe_copy_sha256"]
    assert receipt["probe_copy_sha256"] == receipt["probe_copy_sha256_after"]
    assert receipt["probe_copy_sha256"] == R.sha256(R.BOARD)
    assert receipt["count"] == len(receipt["normalized"])


def _inputs() -> dict:
    for path in (D.IMPORT, D.EXPORT, D.MODEL, D.NETLIST, D.READBACK, D.BOARD):
        if not path.is_file():
            pytest.skip(f"{path.name} not captured on this checkout")
    return dict(
        import_receipt=json.loads(D.IMPORT.read_text(encoding="utf-8")),
        export_receipt=json.loads(D.EXPORT.read_text(encoding="utf-8")),
        model_receipt=json.loads(D.MODEL.read_text(encoding="utf-8")),
        readback=json.loads(D.READBACK.read_text(encoding="utf-8"))["value"],
        netlist_text=D.NETLIST.read_text(encoding="utf-8"),
        board_sha=D.sha256(D.BOARD),
    )


def test_committed_diff_report_reproduces():
    inputs = _inputs()
    result = D.build(**inputs)
    assert result == json.loads(D.REPORT.read_text(encoding="utf-8"))


def test_only_the_five_magnetics_terminals_are_unmatched():
    result = D.build(**_inputs())
    assert result["difference"]["unmatched_schematic_pins_total"] == 24
    assert result["difference"]["unmatched_schematic_pins_by_ref"] == {
        "CT": 4, "T1": 5, "T2": 5, "T3": 5, "T4": 5}
    assert result["difference"]["unmatched_pcb_pins_total"] == 0
    assert result["difference"]["nets_only_in_schematic"] == ["PRI_12", "PRI_23", "PRI_34"]
    assert result["difference"]["nets_only_in_pcb"] == []
    assert result["difference"]["schematic_components_absent_from_pcb"] == [
        "CT", "T1", "T2", "T3", "T4"]
    assert result["pcb_netlist"]["unassigned_pins"] == [
        "D_CT1.2", "D_CT2.2", "D_CT3.2", "D_CT4.2", "U2.2"]
    assert result["unassigned_pins_agree"] is True
    assert result["fabrication_approved"] is False


def test_comparator_pcb_column_is_empty_but_the_pcb_netlist_is_not():
    result = D.build(**_inputs())
    comparator = result["editor_comparator"]
    assert comparator["net_rows"] == comparator["net_rows_with_empty_pcb_side"] == 65
    assert comparator["pcb_side_usable"] is False
    assert result["pcb_netlist"]["named_nets"] == 62
    assert result["pcb_netlist"]["assigned_pins"] == 254


def test_a_receipt_bound_to_another_board_is_refused():
    for key in ("import_receipt", "model_receipt"):
        inputs = _inputs()
        inputs[key] = dict(inputs[key], candidate_sha256="0" * 64)
        with pytest.raises(ValueError, match="candidate_sha256"):
            D.build(**inputs)


def test_a_non_empty_comparator_pcb_column_is_refused():
    # If a future editor build starts publishing a PCB column, the derivation
    # above is no longer the whole difference and must be revisited.
    inputs = _inputs()
    rows = [dict(row) for row in inputs["import_receipt"]["normalized"]]
    rows[0] = dict(rows[0], pcb=["R4.1"])
    inputs["import_receipt"] = dict(inputs["import_receipt"], normalized=rows)
    with pytest.raises(ValueError, match="non-empty PCB column"):
        D.build(**inputs)
