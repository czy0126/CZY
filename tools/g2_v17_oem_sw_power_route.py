"""Source-locked SW segment for QH.1 to Cr.1 on top copper, new candidate.

Cr.1 0.8mm land forces a short 0.8mm final neck; full resonant loop is NOT
closed. Do not infer current rating, EMI clearance, or manufacturing release.
"""
from pathlib import Path
import pcbnew as pcb
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]; G=ROOT/"hardware/dcx_main/g2"
PARENT=G/"dcx_main_board_g2_V17_OEM_T530_72_VIN_INPUT_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
OUTPUT=G/"dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
META=G/"g2_v17_OEM_T530_72_VIN_SW_native_receipt_NOT_FOR_FAB.json"
PARENT_SHA="4a0390fcb492df27b178d398f4697b528fa81c9a9f7fe1bb2d0ce45f7aef8e5a"
SEGMENTS=[
 ((46.089682,9.750718),(39.300331,9.750718),1.8),
 ((39.300331,9.750718),(39.300331,6.998882),.8),
]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pos(x,y):return pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y))
def run():
 if sha(PARENT)!=PARENT_SHA:raise ValueError("Parent VIN native board hash drift")
 if OUTPUT.exists() or META.exists():raise ValueError("Do not overwrite an existing saved candidate")
 b=pcb.LoadBoard(str(PARENT))
 refs={f.GetReference():f for f in b.GetFootprints()}
 def pad(ref,pin):
  obj=next(q for q in refs[ref].Pads() if q.GetNumber()==pin)
  if obj.GetNetname()!="SW":raise ValueError("Power SW pin network drift")
  return obj
 src=pad("QH","1");dst=pad("Cr","1")
 for q,target in ((src,SEGMENTS[0][0]),(dst,SEGMENTS[-1][1])):
  if max(abs(pcb.ToMM(q.GetPosition().x)-target[0]),
         abs(pcb.ToMM(q.GetPosition().y)-target[1]))>.01:
   raise ValueError("Power SW endpoint position drift")
 before=len(list(b.GetTracks()))
 for a,c,width in SEGMENTS:
  t=pcb.PCB_TRACK(b);t.SetNet(src.GetNet());t.SetLayer(pcb.F_Cu)
  t.SetWidth(pcb.FromMM(width));t.SetStart(pos(*a));t.SetEnd(pos(*c))
  b.Add(t)
 pcb.ZONE_FILLER(b).Fill(b.Zones())
 pcb.SaveBoard(str(OUTPUT),b)
 rb=pcb.LoadBoard(str(OUTPUT))
 if len(list(rb.GetTracks()))!=before+2:raise ValueError("SW copper not saved")
 rec={"status":"NATIVE_VIN_AND_PARTIAL_SW_POWER_COPPER_DRC_PENDING_NOT_FOR_FAB",
      "parent":PARENT.name,"parent_sha256":sha(PARENT),
      "candidate":OUTPUT.name,"candidate_sha256":sha(OUTPUT),
      "net":"SW","endpoints":["QH.1","Cr.1"],
      "physical_top_copper_segments":[{"start":list(a),"end":list(c),"width_mm":w} for a,c,w in SEGMENTS],
      "source_track_and_via_count":before,"new_track_and_via_count":len(list(rb.GetTracks())),
      "QH_QL_SW_full_copper_verified":False,"Cr_terminal_current_rated":False,
      "hot_loop_losses_and_emc_verified":False,
      "factory_approved":False}
 META.write_text(json.dumps(rec,indent=2)+"\n",encoding="utf8")
 print(json.dumps(rec))
if __name__=="__main__":
 try:run()
 except (ValueError,OSError,RuntimeError,StopIteration) as exc:
  print("SW route failed:",exc,file=sys.stderr);sys.exit(1)
