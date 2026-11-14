"""One source-locked V17 OEM board primary VIN_P input power path candidate.

This addresses only J_IN.1 to QH.5 using a 1.8 mm F.Cu route above
the half-bridge SW region. Cin.1 remains an open and primary high-frequency
loop compliance remains NOT_FOR_FAB. Never edit baseline PCB.
"""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
PARENT=G/"dcx_main_board_g2_V17_OEM_T530_72_INTEGRATED_NOT_FOR_FAB.kicad_pcb"
OUTPUT=G/"dcx_main_board_g2_V17_OEM_T530_72_VIN_INPUT_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
META=G/"g2_v17_OEM_T530_72_VIN_input_native_receipt_NOT_FOR_FAB.json"
EXPECTED_PARENT="059ef9222714c9e8da262629381fce48a11ec64f9bd7ca60460e40bd3ceccabb"
WAYPOINTS=((65.458755,6.998882),(65.458755,2.25),(49.908454,2.25),(49.908454,4.249078))
WIDTH=1.8
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def v(x,y):return pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y))
def run():
    if sha(PARENT)!=EXPECTED_PARENT:raise RuntimeError("Parent CAD hash drift")
    if OUTPUT.exists() or META.exists():raise RuntimeError("Candidate already exists: refuse overwrite")
    board=pcb.LoadBoard(str(PARENT))
    refmap={f.GetReference():f for f in board.GetFootprints()}
    def pad(ref,pin,net):
        o=next(q for q in refmap[ref].Pads() if q.GetNumber()==pin)
        if o.GetNetname()!=net:raise RuntimeError(f"Bad pad/net {ref}.{pin}")
        return o
    pad_j=pad("J_IN","1","VIN_P")
    pad_q=pad("QH","5","VIN_P")
    for q,xy in ((pad_j,WAYPOINTS[0]),(pad_q,WAYPOINTS[-1])):
        x,y=q.GetPosition().x,q.GetPosition().y
        if abs(pcb.ToMM(x)-xy[0])>.005 or abs(pcb.ToMM(y)-xy[1])>.005:
            raise RuntimeError("Pad site does not match route design input")
    net=pad_j.GetNet()
    original_tracks=len(list(board.GetTracks()))
    for a,b in zip(WAYPOINTS,WAYPOINTS[1:]):
        route=pcb.PCB_TRACK(board)
        route.SetNet(net)
        route.SetLayer(pcb.F_Cu)
        route.SetWidth(pcb.FromMM(WIDTH))
        route.SetStart(v(*a))
        route.SetEnd(v(*b))
        board.Add(route)
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(OUTPUT),board)
    reopened=pcb.LoadBoard(str(OUTPUT))
    if len(list(reopened.GetTracks()))!=original_tracks+3:raise RuntimeError("Track readback incomplete")
    if len(list(reopened.GetFootprints()))!=149:raise RuntimeError("Footprints drift")
    data={"status":"NATIVE_VIN_P_3_TRACK_CANDIDATE_PENDING_DRC_NOT_FOR_FAB",
          "parent":PARENT.name,"parent_sha256":sha(PARENT),
          "candidate":OUTPUT.name,"candidate_sha256":sha(OUTPUT),
          "net":"VIN_P","endpoint_a":"J_IN.1","endpoint_b":"QH.5",
          "width_mm":WIDTH,"waypoints_mm":[list(p) for p in WAYPOINTS],
          "actual_tracks_added":3,"source_track_count":original_tracks,
          "saved_readback_track_count":len(list(reopened.GetTracks())),
          "input_Cin_VIN_P_connection_verified":False,
          "full_primary_hot_loop_emc_verified":False,
          "fabrication_approved":False}
    META.write_text(json.dumps(data,indent=2)+"\n",encoding="utf8")
    print(json.dumps(data))
if __name__=="__main__":
    try:run()
    except (OSError,RuntimeError,ValueError,StopIteration) as ex:
        print("Primary route failure:",str(ex),file=sys.stderr);sys.exit(1)
