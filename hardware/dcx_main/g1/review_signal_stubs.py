"""Finish the existing signal candidate's review without rewriting its CAD.

Capture reopened primitives and native DRC in one session, with CAD hashes
before/after. Old failed receipts are retained; this is not a routing tool.
"""
import argparse
import json
import sys
from pathlib import Path
import apply_increment as A
import run_driver_drc as D
import route_lr_signal_stubs as S
import apply_lr_signal_stubs as checks

HERE=Path(__file__).resolve().parent
BOARD=(HERE/S.CANDIDATE).resolve()
PREFIX='lr_signal_review'
sys.path.insert(0,str(HERE.parents[2]/'tools'))
from text_identity import sha256_file  # noqa: E402  (repo path, not installed)

#: Hash of the canonical stored bytes, not the local checkout: the JSON
#: receipts are written CRLF by Python on Windows while Git stores LF, so a raw
#: ``read_bytes()`` digest would never match the committed file (docs/agent/TRAPS.md).
HASH_CONVENTION = 'sha256 of LF-canonical text bytes (tools/text_identity.py)'


def digest(path):
    return sha256_file(path)


def run():
    rb=HERE/f'{PREFIX}_readback.json'
    drc=HERE/f'{PREFIX}_drc_raw.json'
    output=HERE/f'{PREFIX}_report.json'
    if any(p.exists() for p in (rb,drc,output)):
        raise SystemExit('Review receipts already exist; do not overwrite evidence')
    before=digest(BOARD)
    session=A.open_and_ping(BOARD,PREFIX,'open')
    if not session:raise SystemExit('Editor not available')
    try:
        snapshot=A.invoke(session,(HERE/'read_driver_route.js').read_text(encoding='utf-8'))
        rb.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        if not snapshot.get('ok'):raise RuntimeError('Native readback failed')
        raw=A.invoke(session,(HERE/'driver_drc.js').read_text(encoding='utf-8'))
        drc.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
        if not raw.get('ok'):raise RuntimeError('Native DRC call failed')
    finally:
        A.dump(PREFIX,'close',D.call(D.build_close_args(session)))
    after=digest(BOARD)
    verified=S.verify(rb)
    old=checks.categories(HERE/'lr_repack_drc_raw.json')
    new=checks.categories(drc)
    geometry_ok=(verified['layout_counts']['unchanged'] and not verified['lines']['coverage_problems']
                 and not verified['vias']['problems'] and not verified['placement_drift'])
    drc_improved=(new.get('Connection Error',0)<old.get('Connection Error',0)
                  and new.get('Physical Error',0)==0
                  and all(v<=old.get(k,0) for k,v in new.items()))
    ok=geometry_ok and drc_improved and before==after
    report={'status':'NATIVE_SIGNAL_INCREMENT_ACCEPTED_NOT_FOR_FAB' if ok else 'REVIEW_FAILED',
            'candidate':BOARD.relative_to(S.ROOT).as_posix(),'cad_sha256_before':before,'cad_sha256_after':after,
            'cad_unchanged':before==after,'readback_sha256':digest(rb),'drc_sha256':digest(drc),
            'parent_cad_sha256':digest(S.SOURCE),'parent_drc_sha256':digest(HERE/'lr_repack_drc_raw.json'),
            'hash_convention':HASH_CONVENTION,
            'geometry':verified,'drc_before':old,'drc_after':new,
            'connection_errors_reduced':old.get('Connection Error',0)-new.get('Connection Error',0),
            'native_drc_passed':sum(new.values())==0,'fabrication_approved':False,'hardware_qualified':False,
            'note':'Increment accepted only; existing wider same-net copper covers C103-C104. No CAD rewritten. Old failed receipts retained.'}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not ok:raise SystemExit('Native increment review failed')


def resign() -> int:
    """Re-derive only the byte-identity fields of an existing report.

    The editor capture is never re-run: the receipts on disk are the evidence.
    This exists because the first report hashed CRLF working-tree bytes; the
    committed receipts are stored LF, so the digest must be canonicalised
    (docs/agent/TRAPS.md). Every other field is left byte-for-byte as captured.
    """
    output=HERE/f'{PREFIX}_report.json'
    report=json.loads(output.read_text(encoding='utf-8'))
    report['readback_sha256']=digest(HERE/f'{PREFIX}_readback.json')
    report['drc_sha256']=digest(HERE/f'{PREFIX}_drc_raw.json')
    report['parent_drc_sha256']=digest(HERE/'lr_repack_drc_raw.json')
    report['hash_convention']=HASH_CONVENTION
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',
                      encoding='utf-8',newline='\n')
    print(json.dumps({'resigned':output.name,'readback_sha256':report['readback_sha256'],
                      'drc_sha256':report['drc_sha256']},ensure_ascii=False))
    return 0


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture',action='store_true')
    mode.add_argument('--resign',action='store_true',
                      help='recompute only the canonical byte-identity fields of the existing report')
    args=ap.parse_args()
    if args.resign:
        raise SystemExit(resign())
    run()
