"""TradeSathi AI — Shipping CBM, Cargo Volume & Weight Calculation Engine
Milestone 2F — Logistics Tools

Provides precision calculations for:
1. Dimension and weight unit normalization.
2. Package volume in CBM and Cubic Feet.
3. Multiple cargo lines aggregation.
4. Volumetric and chargeable weight calculation with configurable divisors.
5. Container capacity estimations (nominal, usable, volume-based, and simplified geometric orientation grid).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import permutations
from typing import Any, Literal

# Standard Physical Conversion Constants
CBM_TO_CUFT_FACTOR = 35.3146667
KG_TO_LB_FACTOR = 2.2046226218
M_TO_CM_FACTOR = 100.0
M_TO_MM_FACTOR = 1000.0
INCH_TO_M_FACTOR = 0.0254
FOOT_TO_M_FACTOR = 0.3048

# Default Dimensional Divisors (cm^3 / kg)
DEFAULT_AIR_FREIGHT_DIVISOR = 6000.0
DEFAULT_COURIER_EXPRESS_DIVISOR = 5000.0
DEFAULT_ROAD_FREIGHT_DIVISOR = 5000.0

# Approximate Standard Dry Shipping Container Internal Dimensions (meters)
DEFAULT_CONTAINER_SPECS = {
    "20_standard": {
        "name": "20' Standard Dry",
        "length_m": 5.90,
        "width_m": 2.35,
        "height_m": 2.39,
        "default_usable_ratio": 0.85,
        "max_payload_kg": 21700.0,  # approximate baseline
    },
    "40_standard": {
        "name": "40' Standard Dry",
        "length_m": 12.03,
        "width_m": 2.35,
        "height_m": 2.39,
        "default_usable_ratio": 0.85,
        "max_payload_kg": 26500.0,
    },
    "40_high_cube": {
        "name": "40' High Cube Dry",
        "length_m": 12.03,
        "width_m": 2.35,
        "height_m": 2.69,
        "default_usable_ratio": 0.85,
        "max_payload_kg": 26500.0,
    },
}


def normalize_dimension_to_meters(val: float, unit: str) -> float:
    """Convert length/width/height into meters.
    Supported units: 'm', 'cm', 'mm', 'in'/'inch'/'inches', 'ft'/'foot'/'feet'.
    """
    if val is None or math.isnan(val) or math.isinf(val) or val <= 0:
        raise ValueError(f"Dimension must be a positive finite number, got {val}")

    u = unit.strip().lower()
    if u in ("m", "meter", "meters"):
        return float(val)
    elif u in ("cm", "centimeter", "centimeters"):
        return float(val) / M_TO_CM_FACTOR
    elif u in ("mm", "millimeter", "millimeters"):
        return float(val) / M_TO_MM_FACTOR
    elif u in ("in", "inch", "inches"):
        return float(val) * INCH_TO_M_FACTOR
    elif u in ("ft", "foot", "feet"):
        return float(val) * FOOT_TO_M_FACTOR
    else:
        raise ValueError(f"Unsupported dimension unit '{unit}'. Use mm, cm, m, inches, or feet.")


def normalize_weight_to_kg(val: float, unit: str) -> float:
    """Convert gross weight into kilograms.
    Supported units: 'kg', 'lb'/'lbs'.
    """
    if val is None or math.isnan(val) or math.isinf(val) or val < 0:
        raise ValueError(f"Gross weight must be a non-negative finite number, got {val}")

    u = unit.strip().lower()
    if u in ("kg", "kilogram", "kilograms"):
        return float(val)
    elif u in ("lb", "lbs", "pound", "pounds"):
        return float(val) / KG_TO_LB_FACTOR
    else:
        raise ValueError(f"Unsupported weight unit '{unit}'. Use kg or lb.")


def convert_kg_to_lb(kg: float) -> float:
    """Convert kilograms to pounds using full conversion precision."""
    if kg < 0 or math.isnan(kg) or math.isinf(kg):
        raise ValueError(f"Weight must be non-negative finite number, got {kg}")
    return kg * KG_TO_LB_FACTOR


def convert_cbm_to_cuft(cbm: float) -> float:
    """Convert cubic meters to cubic feet."""
    if cbm < 0 or math.isnan(cbm) or math.isinf(cbm):
        raise ValueError(f"Volume must be non-negative finite number, got {cbm}")
    return cbm * CBM_TO_CUFT_FACTOR


@dataclass
class CargoLineInput:
    description: str
    length: float
    width: float
    height: float
    dimension_unit: str = "cm"
    gross_weight_per_pkg: float = 0.0
    weight_unit: str = "kg"
    quantity: int = 1
    sku: str | None = None
    package_type: str = "carton"  # carton, box, pallet, crate, drum, custom
    notes: str | None = None


@dataclass
class CargoLineResult:
    description: str
    sku: str | None
    package_type: str
    quantity: int
    # Original user inputs
    length_orig: float
    width_orig: float
    height_orig: float
    dimension_unit: str
    gross_weight_orig: float
    weight_unit: str
    # Normalized metric values
    length_m: float
    width_m: float
    height_m: float
    weight_kg: float
    # Computed metrics
    cbm_per_pkg: float
    total_cbm: float
    total_cuft: float
    total_gross_weight_kg: float
    total_gross_weight_lb: float
    volumetric_weight_kg: float
    notes: str | None = None


@dataclass
class CargoAggregateSummary:
    total_packages: int
    total_cbm: float
    total_cuft: float
    total_gross_weight_kg: float
    total_gross_weight_lb: float
    total_volumetric_weight_kg: float
    chargeable_weight_kg: float
    dimensional_divisor_used: float
    freight_mode: str
    average_cbm_per_pkg: float
    average_weight_kg_per_pkg: float
    smallest_cbm_pkg: float
    largest_cbm_pkg: float
    lines: list[CargoLineResult] = field(default_factory=list)


def calculate_cargo_line(
    item: CargoLineInput,
    dimensional_divisor: float = DEFAULT_AIR_FREIGHT_DIVISOR,
) -> CargoLineResult:
    """Calculate normalized volumes, weights, and volumetric weights for a single cargo line."""
    if not isinstance(item.quantity, int) or item.quantity <= 0:
        raise ValueError(f"Quantity must be a positive integer >= 1, got {item.quantity}")

    if dimensional_divisor <= 0 or math.isnan(dimensional_divisor) or math.isinf(dimensional_divisor):
        raise ValueError(f"Dimensional divisor must be a positive number, got {dimensional_divisor}")

    l_m = normalize_dimension_to_meters(item.length, item.dimension_unit)
    w_m = normalize_dimension_to_meters(item.width, item.dimension_unit)
    h_m = normalize_dimension_to_meters(item.height, item.dimension_unit)
    wt_kg = normalize_weight_to_kg(item.gross_weight_per_pkg, item.weight_unit)

    # Per-package CBM = L_m * W_m * H_m
    cbm_per_pkg = l_m * w_m * h_m
    total_cbm = cbm_per_pkg * item.quantity
    total_cuft = convert_cbm_to_cuft(total_cbm)

    total_gross_kg = wt_kg * item.quantity
    total_gross_lb = convert_kg_to_lb(total_gross_kg)

    # Volumetric weight (kg) = (L_cm * W_cm * H_cm) / divisor * quantity
    # Note: L_cm = L_m * 100
    vol_cm3_per_pkg = (l_m * 100.0) * (w_m * 100.0) * (h_m * 100.0)
    vol_weight_per_pkg = vol_cm3_per_pkg / dimensional_divisor
    total_vol_weight_kg = vol_weight_per_pkg * item.quantity

    return CargoLineResult(
        description=item.description.strip(),
        sku=item.sku.strip() if item.sku else None,
        package_type=item.package_type.strip().lower(),
        quantity=item.quantity,
        length_orig=item.length,
        width_orig=item.width,
        height_orig=item.height,
        dimension_unit=item.dimension_unit.strip().lower(),
        gross_weight_orig=item.gross_weight_per_pkg,
        weight_unit=item.weight_unit.strip().lower(),
        length_m=l_m,
        width_m=w_m,
        height_m=h_m,
        weight_kg=wt_kg,
        cbm_per_pkg=cbm_per_pkg,
        total_cbm=total_cbm,
        total_cuft=total_cuft,
        total_gross_weight_kg=total_gross_kg,
        total_gross_weight_lb=total_gross_lb,
        volumetric_weight_kg=total_vol_weight_kg,
        notes=item.notes,
    )


def calculate_cargo_aggregate(
    items: list[CargoLineInput],
    freight_mode: Literal["sea", "air", "road", "general"] | str = "general",
    dimensional_divisor: float = DEFAULT_AIR_FREIGHT_DIVISOR,
    per_package_chargeable_rounding: bool = False,
) -> CargoAggregateSummary:
    """Aggregate multiple cargo lines with total CBM, weights, and chargeable weight."""
    if not items:
        return CargoAggregateSummary(
            total_packages=0,
            total_cbm=0.0,
            total_cuft=0.0,
            total_gross_weight_kg=0.0,
            total_gross_weight_lb=0.0,
            total_volumetric_weight_kg=0.0,
            chargeable_weight_kg=0.0,
            dimensional_divisor_used=dimensional_divisor,
            freight_mode=freight_mode,
            average_cbm_per_pkg=0.0,
            average_weight_kg_per_pkg=0.0,
            smallest_cbm_pkg=0.0,
            largest_cbm_pkg=0.0,
            lines=[],
        )

    computed_lines = [calculate_cargo_line(it, dimensional_divisor) for it in items]

    total_pkgs = sum(l.quantity for l in computed_lines)
    total_cbm = sum(l.total_cbm for l in computed_lines)
    total_cuft = convert_cbm_to_cuft(total_cbm)
    total_gross_kg = sum(l.total_gross_weight_kg for l in computed_lines)
    total_gross_lb = convert_kg_to_lb(total_gross_kg)
    total_vol_kg = sum(l.volumetric_weight_kg for l in computed_lines)

    if per_package_chargeable_rounding:
        # Sum of per-package chargeable weights
        chargeable_kg = sum(
            max(l.total_gross_weight_kg, l.volumetric_weight_kg) for l in computed_lines
        )
    else:
        # Aggregate comparison
        chargeable_kg = max(total_gross_kg, total_vol_kg)

    cbm_per_pkg_list = [l.cbm_per_pkg for l in computed_lines]
    avg_cbm = total_cbm / total_pkgs if total_pkgs > 0 else 0.0
    avg_wt_kg = total_gross_kg / total_pkgs if total_pkgs > 0 else 0.0

    return CargoAggregateSummary(
        total_packages=total_pkgs,
        total_cbm=total_cbm,
        total_cuft=total_cuft,
        total_gross_weight_kg=total_gross_kg,
        total_gross_weight_lb=total_gross_lb,
        total_volumetric_weight_kg=total_vol_kg,
        chargeable_weight_kg=chargeable_kg,
        dimensional_divisor_used=dimensional_divisor,
        freight_mode=freight_mode,
        average_cbm_per_pkg=avg_cbm,
        average_weight_kg_per_pkg=avg_wt_kg,
        smallest_cbm_pkg=min(cbm_per_pkg_list) if cbm_per_pkg_list else 0.0,
        largest_cbm_pkg=max(cbm_per_pkg_list) if cbm_per_pkg_list else 0.0,
        lines=computed_lines,
    )


@dataclass
class ContainerCapacityEstimate:
    container_key: str
    container_name: str
    internal_length_m: float
    internal_width_m: float
    internal_height_m: float
    nominal_volume_cbm: float
    usable_ratio: float
    usable_volume_cbm: float
    cargo_cbm: float
    volume_utilization_pct: float
    remaining_usable_cbm: float
    estimated_units_by_volume: int
    estimated_units_by_grid: int
    best_orientation: tuple[float, float, float] | None  # (l_m, w_m, h_m)
    does_fit_geometrically: bool
    estimated_cargo_weight_at_grid_kg: float
    payload_capacity_kg: float | None
    payload_feasibility: Literal["Pass", "Exceeds Payload", "Unknown"]
    limitation_notes: str


def estimate_single_package_container_capacity(
    package_length_m: float,
    package_width_m: float,
    package_height_m: float,
    package_weight_kg: float,
    container_key: str = "20_standard",
    custom_dimensions: dict[str, float] | None = None,
    usable_ratio: float = 0.85,
    custom_payload_capacity_kg: float | None = None,
) -> ContainerCapacityEstimate:
    """Estimate container capacity for a single package dimension across permitted spatial orientations.
    Compares volume capacity and simple geometric grid packing.
    """
    if package_length_m <= 0 or package_width_m <= 0 or package_height_m <= 0:
        raise ValueError("Package dimensions must be positive finite meters.")

    specs = DEFAULT_CONTAINER_SPECS.get(container_key, DEFAULT_CONTAINER_SPECS["20_standard"])
    name = specs["name"]

    c_len = custom_dimensions.get("length_m", specs["length_m"]) if custom_dimensions else specs["length_m"]
    c_wid = custom_dimensions.get("width_m", specs["width_m"]) if custom_dimensions else specs["width_m"]
    c_hgt = custom_dimensions.get("height_m", specs["height_m"]) if custom_dimensions else specs["height_m"]

    if c_len <= 0 or c_wid <= 0 or c_hgt <= 0:
        raise ValueError("Container dimensions must be positive finite numbers.")

    if not (0.1 <= usable_ratio <= 1.0):
        raise ValueError("Usable volume ratio must be between 0.10 and 1.00 (10% to 100%).")

    nominal_cbm = c_len * c_wid * c_hgt
    usable_cbm = nominal_cbm * usable_ratio

    pkg_cbm = package_length_m * package_width_m * package_height_m
    units_by_vol = math.floor(usable_cbm / pkg_cbm) if pkg_cbm > 0 else 0

    # Test all 6 spatial orientations against container dimensions
    best_units_grid = 0
    best_orientation = None
    distinct_orientations = set(permutations([package_length_m, package_width_m, package_height_m]))

    for (ol, ow, oh) in distinct_orientations:
        if ol <= c_len and ow <= c_wid and oh <= c_hgt:
            count_l = math.floor(c_len / ol)
            count_w = math.floor(c_wid / ow)
            count_h = math.floor(c_hgt / oh)
            total_grid = count_l * count_w * count_h
            if total_grid > best_units_grid:
                best_units_grid = total_grid
                best_orientation = (ol, ow, oh)

    does_fit = best_units_grid > 0

    # Cargo weight at calculated geometric capacity
    est_weight_kg = best_units_grid * package_weight_kg

    # Payload feasibility check
    payload_cap = custom_payload_capacity_kg if custom_payload_capacity_kg is not None else specs.get("max_payload_kg")
    if payload_cap is None or payload_cap <= 0:
        feasibility: Literal["Pass", "Exceeds Payload", "Unknown"] = "Unknown"
    elif est_weight_kg > payload_cap:
        feasibility = "Exceeds Payload"
    else:
        feasibility = "Pass"

    # Volume utilization for the geometric units
    cargo_cbm_at_grid = best_units_grid * pkg_cbm
    utilization_pct = (cargo_cbm_at_grid / nominal_cbm * 100.0) if nominal_cbm > 0 else 0.0
    remaining_usable = max(0.0, usable_cbm - cargo_cbm_at_grid)

    disclaimer = (
        "Simplified geometric grid estimate. Actual physical stuffing depends on pallet overhang, "
        "container door opening clearances, weight distribution, cargo lashing, center of gravity, "
        "and package stacking collapse strength."
    )

    return ContainerCapacityEstimate(
        container_key=container_key,
        container_name=name,
        internal_length_m=c_len,
        internal_width_m=c_wid,
        internal_height_m=c_hgt,
        nominal_volume_cbm=nominal_cbm,
        usable_ratio=usable_ratio,
        usable_volume_cbm=usable_cbm,
        cargo_cbm=cargo_cbm_at_grid,
        volume_utilization_pct=utilization_pct,
        remaining_usable_cbm=remaining_usable,
        estimated_units_by_volume=units_by_vol,
        estimated_units_by_grid=best_units_grid,
        best_orientation=best_orientation,
        does_fit_geometrically=does_fit,
        estimated_cargo_weight_at_grid_kg=est_weight_kg,
        payload_capacity_kg=payload_cap,
        payload_feasibility=feasibility,
        limitation_notes=disclaimer,
    )


def compare_all_containers_for_cargo(
    package_length_m: float,
    package_width_m: float,
    package_height_m: float,
    package_weight_kg: float,
    usable_ratio: float = 0.85,
    custom_payload_map: dict[str, float] | None = None,
) -> list[ContainerCapacityEstimate]:
    """Run container capacity estimation across 20' Standard, 40' Standard, and 40' High Cube."""
    results = []
    payloads = custom_payload_map or {}
    for c_key in ("20_standard", "40_standard", "40_high_cube"):
        est = estimate_single_package_container_capacity(
            package_length_m=package_length_m,
            package_width_m=package_width_m,
            package_height_m=package_height_m,
            package_weight_kg=package_weight_kg,
            container_key=c_key,
            usable_ratio=usable_ratio,
            custom_payload_capacity_kg=payloads.get(c_key),
        )
        results.append(est)
    return results
