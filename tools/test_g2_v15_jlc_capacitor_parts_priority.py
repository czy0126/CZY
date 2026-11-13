"""JLCPCB/EasyEDA-native capacitor part shortlist fail-closed gates.

These tests deliberately do NOT mistake catalog presence for native PCB device
binding, supplier stock, electrical validation or fab approval.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
D=json.loads((ROOT/'hardware/dcx_main/g2/g2_v15_JLCPCB_EasyEDA_capacitor_native_part_priority_NOT_FOR_FAB.json').read_text('utf8'))

def test_21_nonbulk_caps_each_map_exact_required_value_to_official_C_id():
    p=D['proposed_local_library_parts']
    assert len(p)==21
    assert len({x['ref'] for x in p})==21
    assert len({x['proposed_LCSC_part_number'] for x in p})==7
    assert all(x['proposed_LCSC_part_number'].startswith('C') for x in p)
    assert all('jlcpcb.com/partdetail/' in x['JLC_part_catalog_url'] for x in p)
    assert all(x['native_project_verified_device_binding'] is False for x in p)
    assert all(x['supplier_stock_at_required_qty_confirmed'] is False for x in p)

def test_reg_bulk_and_input_film_are_not_autoswapped():
    d={x['ref']:x for x in D['proposed_local_library_parts']}
    for ref in ('C7','C8','C9','C10'):
        assert d[ref]['proposed_LCSC_part_number']=='C415535'
        assert d[ref]['required_value']=='2.2uF'
        assert d[ref]['native_source_mpn']=='CL10B104KB8NNNC'
    assert d['C5']['required_value']=='220nF'
    assert d['C5']['required_footprint']=='0805'
    assert d['C5']['decision_status']=='PACKAGE_SWAP_REQUIRED'
    b=D['output_bulk_candidates']
    assert b[0]['LCSC']=='C2158170'
    assert b[0]['required_ESR_mOhm_100kHz']==4
    assert b[0]['qty']==72
    assert b[1]['ESR_mOhm_100kHz']==5
    assert b[2]['ESR_mOhm_100kHz']==10
    assert all(x['direct_native_package_verified'] is False for x in b)
    assert len(D['not_safe_to_map_yet'])==3
    assert {q for x in D['not_safe_to_map_yet'] for q in x['refs']}=={'Cin','Cout','Cr'}
    assert D['already_swapped_in_native_CAD'] is False
    assert D['fabrication_approved'] is False

def test_readable_handoff_names_original_problem_and_prevents_auto_release():
    md=(ROOT/'hardware/dcx_main/manufacturing/V15_JLCPCB_CAPACITOR_PARTS_PRIORITY_AND_NATIVE_SWAP_GATES_NOT_FOR_FAB.md').read_text('utf8')
    for text in ('C415535','C92827','C282519','C2760544','C2158170','C2158667','C4952536','CL10B104KB8NNNC','NOT_FOR_FAB'):
        assert text in md
