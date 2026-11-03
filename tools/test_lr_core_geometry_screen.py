"""No catalog ELP set can be silently passed using area OR height alone."""
import json
import pytest
import lr_core_geometry_screen as m
def test_catalog_cores_are_from_manufacturer_and_fail_closed():
    z=m.build()
    assert len(z["cores"])==5
    assert not any(r["three_turn_joint_pass"] or r["four_turn_joint_pass"] for r in z["cores"])
    assert all(not r["complete_mechanical_stack_verified"] and not r["gap_and_L_I_100c_verified"]
               for r in z["cores"])
    assert not z["fab_release"]
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==z
def test_el32_low_profile_core_fails_flux_even_at_four_turns():
    x=next(r for r in m.build()["cores"] if r["id"]=="ELP32_I32")
    assert x["core_plus_plate_height_max_mm"]==9.8
    assert x["height_under_converter_limit_by_core_alone"]
    assert x["amin_mm2"]==128
    assert x["flux_model_3turn_t"]>.248 and x["flux_model_4turn_t"]>.248
def test_el38_43_geometries_fail_height_even_when_flux_passes():
    r={x["id"]:x for x in m.build()["cores"]}
    assert r["ELP38_I38"]["core_plus_plate_height_min_mm"]==11.75
    assert r["ELP38_I38"]["three_turn_area_pass"]
    assert not r["ELP38_I38"]["height_under_converter_limit_by_core_alone"]
    assert r["ELP43_I43"]["core_plus_plate_height_min_mm"]==13.3
    assert r["ELP43_I43"]["amin_mm2"]==217
    assert r["ELP43_I43"]["three_turn_area_pass"]
    assert not r["ELP43_I43"]["height_under_converter_limit_by_core_alone"]
def test_all_three_turn_flux_values_use_amin_not_ae():
    rows=m.build()["cores"]
    for x in rows:
        assert x["flux_model_3turn_t"]==pytest.approx(round(.34809*128/x["amin_mm2"],6),abs=1e-9)
