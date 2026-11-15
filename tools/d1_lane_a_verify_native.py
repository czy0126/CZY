"""Independent KiCad pcbnew readback for Lane-A net/pad and copper artifacts."""
from __future__ import annotations
import collections,hashlib,json,sys
from pathlib import Path
import pcbnew as k
ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
ORIGINAL=G/"dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
NEW=G/"d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb"
def count(board):
 f=list(board.GetFootprints())
 return len(f),sum(len(list(q.Pads())) for q in f),board.GetCopperLayerCount(),len(list(board.Zones())),len(list(board.GetTracks()))
def maps(board):
 return {f.GetReference():sorted((q.GetNumber(),q.GetNetname()) for q in f.Pads()) for f in board.GetFootprints()}
def net_traces(board):
 return collections.Counter(t.GetNetname() for t in board.GetTracks())
def go():
 a=k.LoadBoard(str(ORIGINAL)); b=k.LoadBoard(str(NEW))
 if count(a)!=(149,425,12,11,529):raise ValueError("Original V17 counts changed")
 if count(b)!=(149,425,12,11,580):raise ValueError("Final V17 board counts changed")
 if maps(a)!=maps(b):raise ValueError("Actual ref/pin/net parity changed")
 tra,trb=net_traces(a),net_traces(b)
 want={"VIN_P":4,"SW":20,"GH":8,"GH_DRV":5,"HB":9,"OC":4,"RT":1}
 # RT one old object was removed then split into two, hence net +1.
 delta={n:trb[n]-tra[n] for n in set(tra)|set(trb) if trb[n]!=tra[n]}
 if delta!=want:raise ValueError(f"Unexpected native copper delta {delta}")
 refs={f.GetReference():f for f in b.GetFootprints()}
 for i in range(1,73):
  f=refs[f"CHB{i:02}"]
  if f.GetValue()!="T530X477M006ATE004":raise ValueError("OEM T530 changed")
 pad=next(q for q in refs["U1"].Pads() if q.GetNumber()=="3")
 if pad.GetNetname()!="OC":raise ValueError("U1 OC net mismatch")
 pc=pad.GetPosition()
 vias=[t for t in b.GetTracks() if isinstance(t,k.PCB_VIA) and t.GetNetname()=="OC"]
 if len(vias)!=2 or not any(t.GetPosition().x==pc.x and t.GetPosition().y==pc.y for t in vias):
  raise ValueError("OC via-in-pad physical readback mismatch")
 print(json.dumps({"status":"TRUE_KICAD_PAD_NET_PARITY_AND_ROUTING_DELTA_PASS",
                   "source":count(a),"candidate":count(b),"added_objects_by_net":delta,
                   "oem_t530_units":72,"oc_via_in_pad_unsigned":True,
                   "fabrication_approved":False}))
if __name__=="__main__":
 try:go()
 except (ValueError,OSError) as e:print("Native check failed: "+str(e),file=sys.stderr);sys.exit(1)
