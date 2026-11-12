"""Direct native G1 control copper: one actionable low-current batch, no beta."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
G1=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1))
import route_g1_control_direct as P
import apply_g1_control_direct as A


def test_real_saved_reopened_132line_parent_and_current_183_native_drc():
    d=P.source()
    assert len(d["components"])==77
    assert len(d["pads"])==299
    assert len(d["nets"])==65
    assert len(d["lines"])==132
    assert len(d["vias"])==18
    assert P.sha(P.SOURCE)==P.EXPECTED_SHA
    assert P.EXPECTED_SHA=="59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0"
    assert P.OLD.categories(json.loads(P.BASE_DRC.read_text(encoding="utf-8")))["Connection Error"]==183


def test_six_independent_pad_pairs_clear_actual_old_copper_pads_vias_and_magnet():
    d=P.report()
    assert d["preflight_problems"]==[],d["preflight_problems"][:20]
    assert d["real_pad_pairs"]==6
    assert d["native_line_primitives"]==17
    assert d["new_vias"]==0
    assert d["nets"]==["OC","OCD","OCM","RUN","SS"]
    assert d["native_before_drc"]["Connection Error"]==183
    assert d["fabrication_approved"] is False
    assert d["native_eda_applied"] is False
    assert d["native_drc_improved"] is False
    assert set(P.copper())==P.PERMITTED
    assert all(x["layer"]==1 and x["width"]==pytest.approx(.20)
               for x in P.copper().values())
    assert all(s["net"] not in P.FORBIDDEN for s in P.R.segments(P.copper()))


def test_all_six_native_route_ends_are_real_same_net_pads():
    board=P.source()
    plan=P.copper()
    for net,ref,pin,dst,dstpin,mode in P.PAIRS:
        a=P.at(board,ref,pin,net)
        b=P.at(board,dst,dstpin,net)
        assert any(path[0]==a and path[-1]==b for path in plan[net]["paths"])
    assert not P.issues()


def test_emitted_copper_is_native_proven_primitive_not_beta_autoroute():
    s=P.R.emit_js(P.copper(),[])
    assert "eda.dmt_EditorControl.openDocument(" in s
    assert "eda.pcb_PrimitiveLine.create(" in s
    assert "eda.pcb_Document.save()" in s
    assert "autoRouting(" not in s
    assert "pcb_PrimitiveVia.create(" in s  # generic emitter contains it; empty via list
    assert "const vias = []" in s
    assert "return await (async () => {" in s


def test_native_disallowed_power_connection_cannot_enter_batch(monkeypatch):
    old=P.PAIRS
    monkeypatch.setattr(P,"PAIRS",old+(("PGND","R3","2","U1","5","direct"),))
    with pytest.raises(ValueError,match="scope changed"):
        P.copper()


def test_changed_actual_132line_board_rejected_even_when_readback_unchanged(tmp_path,monkeypatch):
    p=tmp_path/"fake_new.eprj2"
    p.write_bytes(b"some other PCB")
    monkeypatch.setattr(P,"SOURCE",p)
    with pytest.raises(ValueError,match="132-line G1 CAD bytes changed"):
        P.source()


def test_native_drc_has_to_decrease_without_new_errors(tmp_path,monkeypatch):
    target=tmp_path/"native-direct-candidate.eprj2"
    target.write_bytes(b"test target")
    report=tmp_path/"real_reopen.json"
    report.write_text(json.dumps({
        "placement_drift":[],
        "lines":{"coverage_problems":[]},
        "vias":{"problems":[]},
        "layout_counts":{"unchanged":True}
    }))
    native=tmp_path/"native_drc.json"
    def drc(n,netlist=1,physical=0,missing=False):
        def g(name,count):
            return {"name":name,"list":[{"name":name,"list":[{} for _ in range(count)]}]}
        return {"ok":True,"value":{"count":2 if missing else 3,
          "raw":([g("Connection Error",n),g("Physical Error",physical)]
            if missing else [g("Connection Error",n),g("Netlist Error",netlist),
                             g("Physical Error",physical)])}}
    monkeypatch.setattr(A,"TARGET",target)
    monkeypatch.setattr(A,"RAW_DRC",native)
    monkeypatch.setattr(P,"REPORT_OUT",report)
    native.write_text(json.dumps(drc(182)))
    result=A.compare_native_drc()
    assert result["real_connection_errors_removed"]==1
    assert result["native_after_drc"]["Connection Error"]==182
    assert result["beta_autorouter_used"] is False
    assert result["fabrication_approved"] is False
    native.write_text(json.dumps(drc(183)))
    with pytest.raises(ValueError,match="did not reduce"):
        A.compare_native_drc()
    native.write_text(json.dumps(drc(182,netlist=2)))
    with pytest.raises(ValueError,match="netlist/physical"):
        A.compare_native_drc()
    native.write_text(json.dumps(drc(182,physical=1)))
    with pytest.raises(ValueError,match="netlist/physical"):
        A.compare_native_drc()
    native.write_text(json.dumps(drc(182,missing=True)))
    with pytest.raises(ValueError,match="disappeared"):
        A.compare_native_drc()


def test_old_beta_autoroute_apply_entry_is_explicitly_disabled(monkeypatch):
    import apply_g1_control_autoroute as obsolete
    monkeypatch.setattr(sys, "argv", ["apply_g1_control_autoroute.py", "--apply"])
    with pytest.raises(SystemExit, match="DEPRECATED: beta autoRouting"):
        obsolete.main()


def test_drc_receipt_hash_survives_git_crlf_to_lf_normalization(tmp_path):
    raw = tmp_path / "native.json"
    raw.write_bytes(b'{"ok": true,\r\n"value": []}\r\n')
    source_hash = A.sha(raw)
    canonical_hash = A.sha_repo_text(raw)
    raw.write_bytes(raw.read_bytes().replace(b"\r\n", b"\n"))
    assert A.sha(raw) == canonical_hash
    assert A.sha_repo_text(raw) == canonical_hash
    assert source_hash != canonical_hash


def test_recovery_checks_saved_receipt_without_repeating_native_copper(tmp_path, monkeypatch):
    target = tmp_path / "already_saved.eprj2"
    target.write_bytes(b"previous native save must not be overwritten")
    original = target.read_bytes()
    receipt = tmp_path / "apply.json"
    receipt.write_text(json.dumps({
        "ok": True, "value": {
            "saved": True, "created": [None] * 17, "failed": [],
            "viasCreated": [], "lines": 149
        }
    }))
    monkeypatch.setattr(A, "TARGET", target)
    monkeypatch.setattr(A, "APPLY_RECEIPT", receipt)
    verified = []
    monkeypatch.setattr(A.E, "verify_existing",
                        lambda module, source, prefix: verified.append((module, source, prefix)) or 0)
    monkeypatch.setattr(A, "verify_native_drc", lambda: 0)
    assert A.resume() == 0
    assert verified == [(P, P.SOURCE, A.PREFIX)]
    assert target.read_bytes() == original
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        A.apply()
    assert target.read_bytes() == original

    failed = json.loads(receipt.read_text())
    failed["value"]["saved"] = False
    receipt.write_text(json.dumps(failed))
    with pytest.raises(ValueError, match="receipt missing or invalid"):
        A.resume()
    assert len(verified) == 1
    assert target.read_bytes() == original


def test_recovery_does_not_accept_an_unmodified_or_missing_native_candidate(tmp_path, monkeypatch):
    target = tmp_path / "never_routed.eprj2"
    monkeypatch.setattr(A, "TARGET", target)
    with pytest.raises(ValueError, match="No modified saved native candidate"):
        A.resume()
    target.write_bytes(P.SOURCE.read_bytes())
    with pytest.raises(ValueError, match="No modified saved native candidate"):
        A.resume()
