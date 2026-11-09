"""Audit the independently saved/reopened driver-placement CAD increment."""
import hashlib
import json
import math
import argparse
import copy
from pathlib import Path
import make_g1_report as g

HERE=Path(__file__).resolve().parent
MOVES={'U2':(54,62),'C5':(51,60),'D_BT':(47,62),'C103':(57,65),
       'C104':(57,67),'R18':(49,55),'R19':(58,55)}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pin_distance(pads,ref_a,pin_a,ref_b,pin_b):
    a=next(p for p in pads if p['ref']==ref_a and str(p['PadNumber'])==pin_a)
    b=next(p for p in pads if p['ref']==ref_b and str(p['PadNumber'])==pin_b)
    return math.hypot(a['X']-b['X'],a['Y']-b['Y'])/g.MIL


def relative_shape(shape, ox, oy):
    """POLYGON sources are absolute board mils; translate to the component origin."""
    if not shape or shape[0]!='POLYGON':
        return shape
    nums=[v for v in shape[1] if isinstance(v,(int,float))]
    rel=[round((v-ox) if i%2==0 else (v-oy),3) for i,v in enumerate(nums)]
    return ('POLYGON',tuple(rel))


def pad_keys(pads, origins):
    """(identity, dx, dy) per pad, with the two representation differences removed.

    * ``g1_pads.json`` hardcoded ``Layer: 1`` on every component pad, so a
      reopened through-hole pad reading layer 12 is not a footprint change.
      A free pad's layer was read for real and stays in the key.
    * polygon sources are absolute, so their coordinates are compared relative
      to the component origin (a moved component is checked separately).

    Offsets are compared with a tolerance by :func:`pads_match`, because the
    editor re-rounds the component origin to 1e-4 mil on a move and that shows
    up as ~0.05 mil of relative drift on the pads.
    """
    rows=[]
    for p in pads:
        ref=p.get('ref')
        ox,oy=origins.get(ref,(0.0,0.0))
        key=(ref or '',str(p.get('PadNumber') or ''),p.get('Net') or '',
             str(relative_shape(p.get('Pad'),ox,oy)),
             f"{float(p.get('Rotation') or 0):.1f}",
             str(p.get('Layer')) if ref is None else '*')
        rows.append((key,float(p.get('X') or 0)-ox,float(p.get('Y') or 0)-oy))
    return rows


def pads_match(old_pads, old_origins, new_pads, new_origins, tol_mil=0.25):
    """True when every pad keeps its pin, net, shape, layer and offset.

    The default 0.25 mil (6.4 µm) covers the editor's own re-derivation on
    reopen: the observed maximum drift across this board is 0.112 mil
    (D_BT pin 2).  A real footprint edit moves a pad by whole mils.
    """
    old=pad_keys(old_pads,old_origins)
    new=pad_keys(new_pads,new_origins)
    if sorted(k for k,_,_ in old)!=sorted(k for k,_,_ in new):
        return False
    groups={}
    for key,x,y in new:
        groups.setdefault(key,[]).append((x,y))
    for key,x,y in old:
        candidates=groups[key]
        hit=next((i for i,(u,v) in enumerate(candidates)
                  if math.hypot(u-x,v-y)<=tol_mil),None)
        if hit is None:
            return False
        candidates.pop(hit)
    return True


def main(preview=False):
    old=json.loads((HERE/'g1_pads.json').read_text(encoding='utf-8'))
    response=json.loads((HERE/'driver_readback.json').read_text(encoding='utf-8'))
    if preview:
        new=copy.deepcopy(old)
        new['nets']=sorted({p['Net'] for p in old['pads'] if p.get('Net')})
        new['polylines']=old['counts']['polylines']
        for c in new['components']:
            if c['ref'] not in MOVES: continue
            x,y=MOVES[c['ref']]
            dx,dy=x*g.MIL-c['X'],-y*g.MIL-c['Y']
            for pad in new['pads']:
                if pad['ref']==c['ref']:pad['X']+=dx;pad['Y']+=dy
            c['X'],c['Y']=x*g.MIL,-y*g.MIL
    else:
        assert response['ok'],'Reopen readback failed; use --preview only for predicted geometry, never verification'
        new=response['value']
    refs=json.loads((g.ROOT/'hardware/dcx_main/gen/netlist_export_raw.json').read_text(encoding='utf-8'))['value']['refs']
    audit=g.audit_pad_nets(new['pads'],refs,{c['ref'] for c in new['components']})
    assert audit['snapshot_equivalent'],audit
    assert len(new['components'])==77 and len(new['pads'])==299
    assert len(new['nets'])==65 and new['polylines']==38
    for c in new['components']:
        before=next(o for o in old['components'] if o['ref']==c['ref'])
        target=MOVES.get(c['ref'],(before['X']/g.MIL,-before['Y']/g.MIL))
        assert abs(c['X']/g.MIL-target[0])<.001 and abs(-c['Y']/g.MIL-target[1])<.001,c
        assert c['Rotation']==before['Rotation'],c
    old_origins={c['ref']:(c['X'],c['Y']) for c in old['components']}
    new_origins={c['ref']:(c['X'],c['Y']) for c in new['components']}
    assert pads_match(old['pads'],old_origins,new['pads'],new_origins),\
        'Changed footprint geometry, pin or network'
    clashes=[]
    for i,a in enumerate(new['pads']):
        for b in new['pads'][i+1:]:
            if a['ref']!=b['ref'] and g.overlaps(g.pad_bbox_mm(a),g.pad_bbox_mm(b),.01):
                clashes.append([a['ref'],a['PadNumber'],b['ref'],b['PadNumber']])
    zones=[]
    for ref in MOVES:
        boxes=[g.pad_bbox_mm(p) for p in new['pads'] if p['ref']==ref]
        box=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
        for z in old['tbd_zones']:
            if g.overlaps(box,(z['x_mm'],z['y_mm'],z['x_mm']+z['w_mm'],z['y_mm']+z['d_mm'])):
                zones.append([ref,z['ref']])
    assert not clashes and not zones,(clashes,zones)
    distances={}
    for name,args in {'GH_DRV':('U2','4','R4','1'), 'GL_DRV':('U2','10','R5','1'),
                      'bootstrap_HB':('U2','3','C5','1'), 'bootstrap_SW':('U2','5','C5','2')}.items():
        distances[name]={'before_mm':pin_distance(old['pads'],*args),'after_mm':pin_distance(new['pads'],*args)}
        assert distances[name]['after_mm']<distances[name]['before_mm'],name
    files=['dcx_main_board_g1.eprj2','dcx_main_board_g1_driver_eco.eprj2','g1_pads.json',
           'driver_readback.json','driver_readback_timeout_2026-11-10T0208.json','driver_eco.js']
    result={'date':'2026-11-10','status':'G1_PLACEMENT_INCREMENT_NOT_FOR_FAB','hardware_qualified':False,
            'routed':False,'native_drc_passed':False,'erc_passed':False,
            'reopened_readback':not preview,'geometry_evidence':'PREDICTED_FROM_BASELINE_AND_MOVE_COMMANDS' if preview else 'NATIVE_REOPEN_READBACK',
            'moved_components':MOVES,'pin_audit':audit,
            'cross_component_pad_bbox_overlaps':clashes,'magnetic_zone_pad_bbox_overlaps':zones,
            'endpoint_distances':distances,'sha256':{n:sha(HERE/n) for n in files},
            'limitations':['Distances are straight endpoint distances, not routed lengths or loop inductance.',
                           'Pad bounding boxes do not replace courtyard, assembly or native DRC checks.',
                           'Pad identity ignores the snapshot hardcoded component-pad Layer and compares offsets at 0.25 mil; free-pad layers are compared.',
                           '24 concept magnetic pads remain provisional; no physical magnet terminals locked.',
                           'C103/C104 assignment checked only by VCC12/PGND nets; exact values/MPNs need native BOM ECO.']}
    output='driver_eco_preview_report.json' if preview else 'driver_eco_report.json'
    (HERE/output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(distances,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--preview',action='store_true',help='Predicted geometry only; cannot verify saved CAD')
    main(ap.parse_args().preview)
