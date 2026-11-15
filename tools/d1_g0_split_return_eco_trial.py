"""Physical return-domain PCB ECO proof-of-concept (NOT FOR FAB).

This is NOT merely renaming SRET pads: it renets 129 actual secondary copper
lands, the secondary PGND tracks/vias, 6 secondary ground zones and splits
the full-board In1 primary PGND plane into separate primary/secondary planes.
Adds a candidate primary T4 return via the between-slot corridor, then runs
native KiCad DRC to expose remaining physical disconnections/shorts.

Never replace original G0 motherboard with an unverified trial.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_r8_safe_enable_eco as original
import d1_g0_cross_domain_audit as witness
import d1_g0_integrated_native_board as initial

OUT=initial.OUT
STEM="d1_g0_SPLIT_PRIMARY_SECONDARY_RETURN_TRIAL_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/(STEM+"_audit.json")
SRET=witness.SRET
REGION_PRI=(1.,1.,154.,44.)
REGION_SRET=(1.,45.,154.,112.)

def at(p):return pcb.VECTOR2I(pcb.FromMM(p[0]),pcb.FromMM(p[1]))
def mm(v):return pcb.ToMM(v)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def make_rect(zone,rect):
    poly=zone.Outline()
    poly.RemoveAllContours()
    poly.NewOutline()
    x0,y0,x1,y1=rect
    for point in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
        poly.Append(pcb.FromMM(point[0]),pcb.FromMM(point[1]))

def track(b,n,layer,start,end,width=.5):
    obj=pcb.PCB_TRACK(b)
    obj.SetStart(at(start));obj.SetEnd(at(end))
    obj.SetNet(n);obj.SetLayer(layer);obj.SetWidth(pcb.FromMM(width));b.Add(obj)

def via(b,n,p):
    obj=pcb.PCB_VIA(b)
    obj.SetPosition(at(p));obj.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    obj.SetNet(n);obj.SetWidth(pcb.FromMM(1.0));obj.SetDrill(pcb.FromMM(.40));b.Add(obj)

def transform():
    r=original.check()
    board=pcb.LoadBoard(str(original.BOARD))
    refs_before,_=witness.pinpassport(board)
    if len(refs_before)!=155:raise ValueError("Expected 155-source")
    net={x.GetNetname():x for x in board.GetNetInfo().NetsByNetcode().values()}
    if SRET in net:raise ValueError("SRET already exists; new source review needed")
    n=pcb.NETINFO_ITEM(board,SRET)
    board.Add(n)
    net[SRET]=n
    converted_pads=[]
    for fp in board.GetFootprints():
        ref=fp.GetReference()
        pset=witness.SECONDARY_RET_REFS.get(ref,frozenset())
        for pad in fp.Pads():
            if pad.GetNumber() in pset:
                if pad.GetNetname()!="PGND":
                    raise ValueError("source secondary pad drift "+ref+"."+pad.GetNumber())
                pad.SetNet(n)
                converted_pads.append((ref,pad.GetNumber()))
    if len(converted_pads)!=129:
        raise ValueError("Actual 129 pads not converted: "+str(len(converted_pads)))
    converted_tracks=[]
    ambiguous=[]
    for obj in board.GetTracks():
        if obj.GetNetname()!="PGND":continue
        y1=mm(obj.GetStart().y);y2=mm(obj.GetEnd().y)
        if min(y1,y2)>=44.:
            obj.SetNet(n);converted_tracks.append([round(y1,3),round(y2,3)])
        elif max(y1,y2)>44.:
            ambiguous.append((round(y1,3),round(y2,3)))
    if ambiguous:
        raise ValueError("Existing PGND trace crosses primary/secondary domain boundary "+str(ambiguous[:10]))
    changed_zones=[]
    old_in1=None
    for i,z in enumerate(board.Zones()):
        if z.GetNetname()!="PGND":continue
        layer=z.GetLayer()
        bb=z.GetBoundingBox()
        top=mm(bb.GetY())
        if layer==pcb.In1_Cu:
            if old_in1 is not None:raise ValueError("Duplicate plane instead of one")
            old_in1=z
            make_rect(z,REGION_PRI)
            changed_zones.append({"layer":"In1.Cu","new_net":"PGND","area":"primary","region":REGION_PRI})
        elif top>=44.:
            z.SetNet(n)
            changed_zones.append({"layer":pcb.LayerName(layer),"new_net":SRET,"area":"secondary",
             "region":[round(mm(bb.GetX()),2),round(mm(bb.GetY()),2)]})
    if old_in1 is None:raise ValueError("Missing source PGND In1 all-board plane")
    z=pcb.ZONE(board)
    z.SetNet(n);z.SetLayer(pcb.In1_Cu)
    z.SetLocalClearance(pcb.FromMM(.25))
    z.SetThermalReliefGap(pcb.FromMM(.3))
    z.SetThermalReliefSpokeWidth(pcb.FromMM(.3))
    make_rect(z,REGION_SRET)
    board.Add(z)
    changed_zones.append({"layer":"In1.Cu","new_net":SRET,"area":"secondary",
      "region":REGION_SRET})
    # Primary transformer T4 PRI_B is PGND and must NOT become secondary.
    t4=next(x for x in board.GetFootprints() if x.GetReference()=="T4")
    pad=next(x for x in t4.Pads() if x.GetNumber()=="PRI_B")
    if pad.GetNetname()!="PGND":raise ValueError("T4 original primary return drift")
    # Adjacent open x~125 mm corridor between Edge.Cuts slots at
    # x=122.46 and x=130.10, connecting primary return pad to In1.Cu.
    p=(mm(pad.GetPosition().x),mm(pad.GetPosition().y))
    for a,b in zip((p,(125.0,46.75)),((125.0,46.75),(125.0,43.6))):
        track(board,net["PGND"],pcb.F_Cu,a,b,.65)
    via(board,net["PGND"],(125.,43.6))
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(BOARD),board)
    return {"source_sha256":sha(original.BOARD),"new_board_sha256":sha(BOARD),
        "converted_physical_pads":len(converted_pads),
        "converted_pgnd_secondary_tracks_or_vias":len(converted_tracks),
        "changed_or_added_zones":changed_zones,
        "primary_return_T4_path":"T4 PRI_B to (125,46.75), (125,43.6) via to In1 PGND",
        "made_isolated_bias_complete":False,
        "real_vendor_magnetics_isolation_approved":False}

def native_drc():
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    proc=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
       "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
    if proc.returncode or not DRC.is_file():raise ValueError("KiCad native DRC tool failed "+proc.stderr)
    return json.loads(DRC.read_text("utf-8"))

def readback(evidence,d):
    b=pcb.LoadBoard(str(BOARD))
    refs,_=witness.pinpassport(b)
    domains=witness.audited_domains(refs)
    # Original witness primary permits PGND; secondary expects SRET.
    if domains["shared_primary_secondary_return_nets"] or domains["secondary_net_set"]!=[SRET]:
        raise ValueError("Electrical ground split incomplete at package pads")
    if domains["primary_net_set"]!=["PGND"]:
        raise ValueError("Primary ground drift")
    count=sum(len([p for p in f.Pads() if p.GetNetname()==SRET]) for f in b.GetFootprints())
    if count!=129:raise ValueError("secondary net count wrong")
    areas=witness.zone_evidence(b)
    common=[z for z in areas if z["net"]=="PGND" and
      z["copper_layer"]=="In1.Cu" and z["bbox_mm"][1]<=10 and z["bbox_mm"][1]+z["bbox_mm"][3]>=70]
    if common:raise ValueError("legacy full-area copper return plane still in design")
    return {**evidence,
      "status":"ISOLATED_OUTPUT_RETURN_PCB_ECO_PROTOTYPE_NOT_FOR_FAB",
      "physical_pads_SRET":count,
      "pad_level_primary_secondary_return_net_common":False,
      "PCB_copper_zones_primary_secondary_split":True,
      "native_drc_report_sha256":sha(DRC),
      "native_DRC_violations":len(d.get("violations",[])),
      "native_DRC_unconnected":len(d.get("unconnected_items",[])),
      "native_DRC_violation_types":sorted({x["type"] for x in d.get("violations",[])}),
      "real_isolation_clearance_qualification":False,
      "bias_supply_uvlo_and_48v_disconnect_implemented":False,
      "factory_approved":False,"G0_approved":False,"energization_allowed":False}

def build():
    evidence=transform()
    report=readback(evidence,native_drc())
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def check():
    if not all(x.is_file() for x in (BOARD,DRC,REPORT)):raise ValueError("missing split domain trial")
    current=json.loads(REPORT.read_text("utf-8"))
    # Preserve original transformation inventory while binding current file hash.
    assert current["new_board_sha256"]==sha(BOARD)
    assert current["native_drc_report_sha256"]==sha(DRC)
    r=readback({k:current[k] for k in (
      "source_sha256","new_board_sha256","converted_physical_pads",
      "converted_pgnd_secondary_tracks_or_vias","changed_or_added_zones",
      "primary_return_T4_path","made_isolated_bias_complete",
      "real_vendor_magnetics_isolation_approved")},json.loads(DRC.read_text("utf-8")))
    if current!=r:raise ValueError("split native DRC receipt drift")
    return r

def main():
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    c=a.parse_args()
    result=build() if c.write else check()
    print(json.dumps({k:result[k] for k in ("status","converted_physical_pads",
        "converted_pgnd_secondary_tracks_or_vias","native_DRC_violations",
        "native_DRC_unconnected")}))
if __name__=="__main__":main()
