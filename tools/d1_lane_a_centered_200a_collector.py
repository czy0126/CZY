"""Second actual KiCad layout trial: move both output polarity terminals from
the far edge to a centered, paired F/B outlet to compare incremental 4x50A
collector path losses. Source locked to the already native-reopened E1 board.
The pads/footprints/planes are real; 200A capability is NOT demonstrated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pcbnew as k

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon"
SOURCE=OUT/"e1_4cell_200A_pair_collector_copper_coldplate_interface_NOT_FOR_FAB.kicad_pcb"
SOURCE_REPORT=OUT/"e1_4cell_200A_pair_collector_reuse_source_locked_NOT_FOR_FAB.json"
CANDIDATE=OUT/"e1_4cell_200A_center_output_pair_collector_NOT_FOR_FAB.kicad_pcb"
REPORT=OUT/"e1_4cell_200A_center_output_source_bound_NOT_FOR_FAB.json"
ORIGINAL_X_MM=95.
CENTER_X_MM=50.
Y_MM=36.
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def posmm(f):
    p=f.GetPosition()
    return (round(k.ToMM(p.x),3),round(k.ToMM(p.y),3))
def build():
    receipt=json.loads(SOURCE_REPORT.read_text("utf8"))
    if sha(SOURCE)!=receipt["output_native_pcb_sha256"]:
        raise ValueError("source E1 edge-output coupon hash drift")
    b=k.LoadBoard(str(SOURCE))
    sr_before={f.GetReference():[(q.GetNumber(),q.GetNetname()) for q in f.Pads()]
               for f in b.GetFootprints() if f.GetReference().startswith("SR")}
    if set(sr_before)!={f"SR{i}{c}" for i in range(1,5) for c in "AB"}:
        raise ValueError("missing inherited V17 SR8")
    f={x.GetReference():x for x in b.GetFootprints()}
    if posmm(f["OUT_POS"])!=(ORIGINAL_X_MM,Y_MM) or posmm(f["OUT_NEG"])!=(ORIGINAL_X_MM,Y_MM):
        raise ValueError("unexpected old output pad locations")
    for ref in ("OUT_POS","OUT_NEG"):
        f[ref].SetPosition(k.VECTOR2I(k.FromMM(CENTER_X_MM),k.FromMM(Y_MM)))
    try:k.ZONE_FILLER(b).Fill(b.Zones())
    except Exception as err:raise RuntimeError("native fill of real source coupon failed") from err
    k.SaveBoard(str(CANDIDATE),b)
    again=k.LoadBoard(str(CANDIDATE))
    cf={x.GetReference():x for x in again.GetFootprints()}
    for name in ("OUT_POS","OUT_NEG"):
        if posmm(cf[name])!=(CENTER_X_MM,Y_MM):
            raise ValueError("center pad move not saved by KiCad")
    if set((z.GetLayer(),z.GetNetname()) for z in again.Zones())!={(k.F_Cu,"PGND"),(k.B_Cu,"VOUT")}:
        raise ValueError("paired output zones lost")
    for sr,pins in sr_before.items():
        if pins!=[(q.GetNumber(),q.GetNetname()) for q in cf[sr].Pads()]:
            raise ValueError("SR real-pad mapping drift "+sr)
    return {
      "schema":"d1_e1_centered_output_trial/1",
      "status":"REAL_KICAD_CENTERED_PAIR_OUTPUT_TEST_COUPON_NOT_FOR_FAB",
      "source_edge_coupon_sha256":sha(SOURCE),
      "source_edge_coupon_receipt_sha256":sha(SOURCE_REPORT),
      "centered_CAD_relative":str(CANDIDATE.relative_to(ROOT)).replace("\\","/"),
      "centered_CAD_sha256":sha(CANDIDATE),
      "exact_same_8_SR_physical_pin_nets":True,
      "output_net_layers_unchanged":True,
      "edge_contact_x_before_mm":ORIGINAL_X_MM,
      "center_contact_x_after_mm":CENTER_X_MM,
      "positive_negative_moved_together":True,
      "centered_design_can_meet_200A_continuous_current":False,
      "hardware_standards_and_copper_straps_unverified":True,
      "fab_approval":False
    }
def main(argv=None):
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
    opts=a.parse_args(argv)
    if opts.write:
        result=build()
        REPORT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n","utf8")
    else:
        result=json.loads(REPORT.read_text("utf8"))
        if sha(CANDIDATE)!=result["centered_CAD_sha256"] or sha(SOURCE)!=result["source_edge_coupon_sha256"]:
            raise ValueError("source or center CAD changed")
        b=k.LoadBoard(str(CANDIDATE))
        f={q.GetReference():q for q in b.GetFootprints()}
        if posmm(f["OUT_POS"])!=(CENTER_X_MM,Y_MM) or posmm(f["OUT_NEG"])!=(CENTER_X_MM,Y_MM):
            raise ValueError("center pads not where expected")
    print(json.dumps({"stage":result["status"],"cad":result["centered_CAD_relative"],
                      "sha256":result["centered_CAD_sha256"]}))
if __name__=="__main__":
    main()
