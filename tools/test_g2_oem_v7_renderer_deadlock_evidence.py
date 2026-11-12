"""Proof that isolated V7 post-restart native API was blocked BEFORE copper write.

These receipts attest to a failed real EDA transaction and cannot qualify PCB.
"""
from pathlib import Path
import json
import sys

G2 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g2"
sys.path.insert(0, str(G2))
import route_t530_oem_v7_recovery_attempt as V7


def receipt(name):
    return json.loads((G2 / ("g2_t530_oem_v7_ocm_r17_c11_" + name + ".json")).read_text(encoding="utf-8"))


def test_v7_restarted_native_render_timeout_is_blocked_before_mutation():
    plan = receipt("route_plan")
    opened, ping, probe, closed = (receipt(x) for x in
                                    ("apply_open", "apply_ping", "apply_native_probe", "apply_close"))
    assert V7.V6.TARGET.name.startswith("dcx_main_board_g2_T530_OEM_DENSITY_B_V6_")
    assert plan["source_eprj2_sha256"] == V7.V6.sha(V7.V6.SOURCE)
    assert plan["native_drc_before"] == {"Connection Error": 172, "Netlist Error": 1}
    assert plan["preflight_problems"] == []
    assert opened["ok"] is True and opened["value"]["headless"] is True
    assert ping["ok"] is True and ping["value"] == 1
    assert probe["ok"] is False
    assert probe["source_shape_verified"] is False
    assert probe["error"]["code"] == "REQUEST_TIMEOUT"
    assert probe["observed_counts"] == [0, 0, 0, 0, 0]
    assert closed["ok"] is True
    assert not (G2 / (V7.PREFIX + "_apply_batch_1.json")).exists()
    assert not (G2 / (V7.PREFIX + "_drc_delta.json")).exists()
