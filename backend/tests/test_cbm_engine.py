"""Unit tests for TradeSathi AI Shipping CBM, Cargo Volume & Weight Engine
Milestone 2F — Logistics Engine Verification
"""

import math
import pytest

from backend.app.cbm_engine import (
    CargoLineInput,
    calculate_cargo_aggregate,
    calculate_cargo_line,
    compare_all_containers_for_cargo,
    convert_cbm_to_cuft,
    convert_kg_to_lb,
    estimate_single_package_container_capacity,
    normalize_dimension_to_meters,
    normalize_weight_to_kg,
)


# 1. Cubic meters from meter dimensions
def test_1_cbm_from_meter_dimensions():
    inp = CargoLineInput(
        description="Standard Export Crate",
        length=1.5,
        width=1.0,
        height=0.8,
        dimension_unit="m",
        gross_weight_per_pkg=50.0,
        quantity=1,
    )
    res = calculate_cargo_line(inp)
    assert pytest.approx(res.cbm_per_pkg, rel=1e-6) == 1.2
    assert pytest.approx(res.total_cbm, rel=1e-6) == 1.2


# 2. Centimeter-to-meter conversion
def test_2_centimeter_to_meter_conversion():
    m = normalize_dimension_to_meters(100.0, "cm")
    assert pytest.approx(m, rel=1e-6) == 1.0

    m50 = normalize_dimension_to_meters(50.0, "cm")
    assert pytest.approx(m50, rel=1e-6) == 0.5


# 3. Millimeter-to-meter conversion
def test_3_millimeter_to_meter_conversion():
    m = normalize_dimension_to_meters(1000.0, "mm")
    assert pytest.approx(m, rel=1e-6) == 1.0

    m250 = normalize_dimension_to_meters(250.0, "mm")
    assert pytest.approx(m250, rel=1e-6) == 0.25


# 4. Inches-to-meter conversion
def test_4_inches_to_meter_conversion():
    m = normalize_dimension_to_meters(1.0, "inch")
    assert pytest.approx(m, rel=1e-6) == 0.0254

    m10 = normalize_dimension_to_meters(10.0, "inches")
    assert pytest.approx(m10, rel=1e-6) == 0.254


# 5. Feet-to-meter conversion
def test_5_feet_to_meter_conversion():
    m = normalize_dimension_to_meters(1.0, "foot")
    assert pytest.approx(m, rel=1e-6) == 0.3048

    m5 = normalize_dimension_to_meters(5.0, "feet")
    assert pytest.approx(m5, rel=1e-6) == 1.524


# 6. Cubic feet conversion
def test_6_cubic_feet_conversion():
    cuft = convert_cbm_to_cuft(1.0)
    assert pytest.approx(cuft, rel=1e-6) == 35.3146667

    cuft_half = convert_cbm_to_cuft(0.5)
    assert pytest.approx(cuft_half, rel=1e-6) == 17.65733335


# 7. Kilogram-to-pound conversion
def test_7_kilogram_to_pound_conversion():
    lb = convert_kg_to_lb(1.0)
    assert pytest.approx(lb, rel=1e-6) == 2.2046226218

    lb100 = convert_kg_to_lb(100.0)
    assert pytest.approx(lb100, rel=1e-6) == 220.46226218


# 8. Pound-to-kilogram conversion
def test_8_pound_to_kilogram_conversion():
    kg = normalize_weight_to_kg(2.2046226218, "lb")
    assert pytest.approx(kg, rel=1e-6) == 1.0


# 9. Multiple package totals
def test_9_multiple_package_totals():
    inp = CargoLineInput(
        description="Carton A",
        length=50,
        width=40,
        height=30,
        dimension_unit="cm",
        gross_weight_per_pkg=10.0,
        weight_unit="kg",
        quantity=25,
    )
    res = calculate_cargo_line(inp)
    # 0.5 * 0.4 * 0.3 = 0.06 CBM per pkg
    assert pytest.approx(res.cbm_per_pkg, rel=1e-6) == 0.06
    assert pytest.approx(res.total_cbm, rel=1e-6) == 1.5
    assert pytest.approx(res.total_gross_weight_kg, rel=1e-6) == 250.0


# 10. Mixed cargo lines aggregation
def test_10_mixed_cargo_lines():
    l1 = CargoLineInput("Small Boxes", 20, 20, 20, "cm", 2.0, "kg", 10)
    l2 = CargoLineInput("Large Crates", 1.0, 1.0, 1.0, "m", 100.0, "kg", 2)
    agg = calculate_cargo_aggregate([l1, l2])

    # l1: 0.2*0.2*0.2 = 0.008 * 10 = 0.08 CBM, 20 kg
    # l2: 1.0 * 2 = 2.0 CBM, 200 kg
    assert agg.total_packages == 12
    assert pytest.approx(agg.total_cbm, rel=1e-6) == 2.08
    assert pytest.approx(agg.total_gross_weight_kg, rel=1e-6) == 220.0
    assert pytest.approx(agg.smallest_cbm_pkg, rel=1e-6) == 0.008
    assert pytest.approx(agg.largest_cbm_pkg, rel=1e-6) == 1.0


# 11. Invalid dimensions
def test_11_invalid_dimensions_rejected():
    with pytest.raises(ValueError, match="positive finite"):
        normalize_dimension_to_meters(-5.0, "cm")


# 12. Zero and negative values
def test_12_zero_and_negative_values():
    with pytest.raises(ValueError):
        normalize_dimension_to_meters(0.0, "m")
    with pytest.raises(ValueError):
        normalize_weight_to_kg(-1.0, "kg")


# 13. NaN and infinity values
def test_13_nan_and_infinity():
    with pytest.raises(ValueError):
        normalize_dimension_to_meters(float("nan"), "cm")
    with pytest.raises(ValueError):
        normalize_dimension_to_meters(float("inf"), "cm")
    with pytest.raises(ValueError):
        normalize_weight_to_kg(float("nan"), "kg")


# 14. Invalid quantities
def test_14_invalid_quantities():
    with pytest.raises(ValueError, match="positive integer"):
        calculate_cargo_line(CargoLineInput("Box", 10, 10, 10, "cm", 1.0, "kg", quantity=0))
    with pytest.raises(ValueError, match="positive integer"):
        calculate_cargo_line(CargoLineInput("Box", 10, 10, 10, "cm", 1.0, "kg", quantity=-5))


# 15. Large but allowed quantities
def test_15_large_quantities():
    inp = CargoLineInput("Mass Pack", 10, 10, 10, "cm", 0.5, "kg", quantity=100000)
    res = calculate_cargo_line(inp)
    assert res.quantity == 100000
    assert pytest.approx(res.total_cbm, rel=1e-6) == 100.0  # 0.001 * 100000
    assert pytest.approx(res.total_gross_weight_kg, rel=1e-6) == 50000.0


# 16. Invalid units
def test_16_invalid_units():
    with pytest.raises(ValueError, match="Unsupported dimension unit"):
        normalize_dimension_to_meters(10.0, "lightyears")
    with pytest.raises(ValueError, match="Unsupported weight unit"):
        normalize_weight_to_kg(10.0, "tons_metric")


# 17. Volumetric weight using divisor 5,000 (Courier Express)
def test_17_volumetric_weight_divisor_5000():
    # 50cm x 50cm x 50cm = 125,000 cm3. / 5000 = 25 kg per pkg
    inp = CargoLineInput("Express Box", 50, 50, 50, "cm", 15.0, "kg", quantity=2)
    res = calculate_cargo_line(inp, dimensional_divisor=5000.0)
    assert pytest.approx(res.volumetric_weight_kg, rel=1e-6) == 50.0  # 25 * 2


# 18. Volumetric weight using divisor 6,000 (Standard Air IATA)
def test_18_volumetric_weight_divisor_6000():
    # 60cm x 50cm x 40cm = 120,000 cm3. / 6000 = 20 kg per pkg
    inp = CargoLineInput("Air Freight Cargo", 60, 50, 40, "cm", 10.0, "kg", quantity=1)
    res = calculate_cargo_line(inp, dimensional_divisor=6000.0)
    assert pytest.approx(res.volumetric_weight_kg, rel=1e-6) == 20.0


# 19. Chargeable-weight calculation
def test_19_chargeable_weight_calculation():
    # Light but bulky cargo: actual weight 10kg, volumetric 20kg -> chargeable = 20kg
    l1 = CargoLineInput("Bulky Box", 60, 50, 40, "cm", 10.0, "kg", 1)
    agg1 = calculate_cargo_aggregate([l1], dimensional_divisor=6000.0)
    assert agg1.chargeable_weight_kg == 20.0

    # Dense cargo: actual weight 35kg, volumetric 20kg -> chargeable = 35kg
    l2 = CargoLineInput("Dense Metal Parts", 60, 50, 40, "cm", 35.0, "kg", 1)
    agg2 = calculate_cargo_aggregate([l2], dimensional_divisor=6000.0)
    assert agg2.chargeable_weight_kg == 35.0


# 20. Per-package versus aggregate chargeable weight comparison
def test_20_per_package_versus_aggregate_rounding():
    # Package 1: Heavy (actual 30kg, vol 10kg)
    # Package 2: Bulky (actual 5kg, vol 25kg)
    # Aggregate actual = 35kg, Aggregate vol = 35kg -> Aggregate chargeable = 35kg
    # Per-package chargeable: max(30, 10) + max(5, 25) = 30 + 25 = 55kg!
    l1 = CargoLineInput("Heavy Pkg", 30, 30, 30, "cm", 30.0, "kg", 1)   # vol = 27000/6000 = 4.5kg
    l2 = CargoLineInput("Bulky Pkg", 60, 60, 60, "cm", 5.0, "kg", 1)    # vol = 216000/6000 = 36kg

    agg_total = calculate_cargo_aggregate([l1, l2], dimensional_divisor=6000.0, per_package_chargeable_rounding=False)
    # total gross = 35kg, total vol = 40.5kg -> max = 40.5kg
    assert pytest.approx(agg_total.chargeable_weight_kg, rel=1e-6) == 40.5

    agg_per_pkg = calculate_cargo_aggregate([l1, l2], dimensional_divisor=6000.0, per_package_chargeable_rounding=True)
    # pkg1: max(30, 4.5) = 30. pkg2: max(5, 36) = 36. sum = 66kg
    assert pytest.approx(agg_per_pkg.chargeable_weight_kg, rel=1e-6) == 66.0


# 21. Container volume utilization
def test_21_container_volume_utilization():
    est = estimate_single_package_container_capacity(
        package_length_m=1.0,
        package_width_m=1.0,
        package_height_m=1.0,
        package_weight_kg=100.0,
        container_key="20_standard",
        usable_ratio=0.85,
    )
    # Nominal 20' volume = 5.90 * 2.35 * 2.39 = 33.13735 CBM
    assert pytest.approx(est.nominal_volume_cbm, rel=1e-4) == 33.13735
    assert pytest.approx(est.usable_volume_cbm, rel=1e-4) == 33.13735 * 0.85
    assert est.estimated_units_by_grid > 0
    assert 0.0 < est.volume_utilization_pct <= 100.0


# 22. Geometric fit across package orientations
def test_22_geometric_fit_orientations():
    # Package 2.0m x 0.5m x 0.4m
    # Container 5.90m x 2.35m x 2.39m
    # Checks that permutations are evaluated to maximize units
    est = estimate_single_package_container_capacity(
        package_length_m=2.0,
        package_width_m=0.5,
        package_height_m=0.4,
        package_weight_kg=15.0,
        container_key="20_standard",
    )
    assert est.does_fit_geometrically is True
    assert est.estimated_units_by_grid > 0
    assert est.best_orientation is not None


# 23. Packages that cannot fit in any permitted orientation
def test_23_package_too_large_for_container():
    # 7 meters long does not fit in 20' container (5.90m length, 2.35m width, 2.39m height)
    est = estimate_single_package_container_capacity(
        package_length_m=7.0,
        package_width_m=3.0,
        package_height_m=3.0,
        package_weight_kg=500.0,
        container_key="20_standard",
    )
    assert est.does_fit_geometrically is False
    assert est.estimated_units_by_grid == 0


# 24. Unknown payload capacity reporting
def test_24_unknown_payload_capacity():
    est = estimate_single_package_container_capacity(
        package_length_m=0.5,
        package_width_m=0.5,
        package_height_m=0.5,
        package_weight_kg=10.0,
        container_key="20_standard",
        custom_payload_capacity_kg=None,
    )
    # Default spec has max_payload_kg; override to 0 or None for testing unknown
    est_unknown = estimate_single_package_container_capacity(
        package_length_m=0.5,
        package_width_m=0.5,
        package_height_m=0.5,
        package_weight_kg=10.0,
        container_key="20_standard",
        custom_payload_capacity_kg=0.0,
    )
    assert est_unknown.payload_feasibility == "Unknown"


# 25. Payload capacity exceeded reporting
def test_25_payload_capacity_exceeded():
    # Extremely heavy lead blocks: 5000 kg each
    est = estimate_single_package_container_capacity(
        package_length_m=0.5,
        package_width_m=0.5,
        package_height_m=0.5,
        package_weight_kg=5000.0,
        container_key="20_standard",
        custom_payload_capacity_kg=20000.0,
    )
    # Geometric count will easily be > 4, so total weight > 20000 kg
    assert est.payload_feasibility == "Exceeds Payload"


# 26. Invalid container dimensions
def test_26_invalid_container_dimensions():
    with pytest.raises(ValueError, match="positive finite"):
        estimate_single_package_container_capacity(
            0.5, 0.5, 0.5, 10.0,
            custom_dimensions={"length_m": -5.0, "width_m": 2.0, "height_m": 2.0}
        )


# 27. Deterministic test fixture specified in prompt
# Carton 60cm x 40cm x 30cm, 10 cartons, 12 kg each, divisor 6000
def test_27_deterministic_prompt_fixture():
    inp = CargoLineInput(
        description="Standard Export Carton",
        length=60.0,
        width=40.0,
        height=30.0,
        dimension_unit="cm",
        gross_weight_per_pkg=12.0,
        weight_unit="kg",
        quantity=10,
    )
    res = calculate_cargo_line(inp, dimensional_divisor=6000.0)

    # Volume per carton = 0.60 * 0.40 * 0.30 = 0.072 CBM
    assert pytest.approx(res.cbm_per_pkg, rel=1e-6) == 0.072
    # Total CBM for 10 cartons = 0.72 CBM
    assert pytest.approx(res.total_cbm, rel=1e-6) == 0.72
    # Total gross weight = 120 kg
    assert pytest.approx(res.total_gross_weight_kg, rel=1e-6) == 120.0
    # Volumetric weight per carton at 6000 divisor: 60*40*30 / 6000 = 12 kg
    # Total volumetric weight = 120 kg
    assert pytest.approx(res.volumetric_weight_kg, rel=1e-6) == 120.0

    agg = calculate_cargo_aggregate([inp], dimensional_divisor=6000.0)
    assert pytest.approx(agg.chargeable_weight_kg, rel=1e-6) == 120.0


# 28. Usable volume ratio bounds
def test_28_usable_volume_ratio_bounds():
    with pytest.raises(ValueError, match="ratio must be between"):
        estimate_single_package_container_capacity(0.5, 0.5, 0.5, 10.0, usable_ratio=1.5)
    with pytest.raises(ValueError, match="ratio must be between"):
        estimate_single_package_container_capacity(0.5, 0.5, 0.5, 10.0, usable_ratio=0.05)


# 29. Compare all container sizes
def test_29_compare_all_containers():
    results = compare_all_containers_for_cargo(0.6, 0.4, 0.3, 12.0)
    assert len(results) == 3
    keys = [r.container_key for r in results]
    assert keys == ["20_standard", "40_standard", "40_high_cube"]
    # 40' High cube must have larger usable volume than 40' Standard
    hc = next(r for r in results if r.container_key == "40_high_cube")
    std40 = next(r for r in results if r.container_key == "40_standard")
    assert hc.nominal_volume_cbm > std40.nominal_volume_cbm


# 30. Empty cargo lines handling
def test_30_empty_cargo_lines():
    agg = calculate_cargo_aggregate([])
    assert agg.total_packages == 0
    assert agg.total_cbm == 0.0
    assert agg.total_gross_weight_kg == 0.0
    assert agg.chargeable_weight_kg == 0.0
    assert len(agg.lines) == 0
