"""Integration tests for TradeSathi AI CBM Calculator and Cargo Logistics API Endpoints
Milestone 2F — Logistics API Verification
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db import create_shipment, init_db, set_db_path
from backend.app.main import app


@pytest.fixture
def client_with_temp_db():
    """Isolated temporary SQLite database for logistics test suite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db = Path(tf.name)

    set_db_path(temp_db)
    init_db(temp_db)

    with TestClient(app) as client:
        yield client

    if temp_db.exists():
        try:
            temp_db.unlink()
        except Exception:
            pass


def test_stateless_cbm_calculate_api(client_with_temp_db):
    """POST /api/logistics/cbm/calculate returns accurate volumes and chargeable weight."""
    payload = {
        "items": [
            {
                "description": "Standard Carton",
                "length": 60,
                "width": 40,
                "height": 30,
                "dimension_unit": "cm",
                "gross_weight_per_pkg": 12,
                "weight_unit": "kg",
                "quantity": 10,
                "package_type": "carton",
            }
        ],
        "freight_mode": "air",
        "dimensional_divisor": 6000.0,
    }

    resp = client_with_temp_db.post("/api/logistics/cbm/calculate", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_packages"] == 10
    assert pytest.approx(data["total_cbm"], rel=1e-5) == 0.72
    assert pytest.approx(data["total_gross_weight_kg"], rel=1e-5) == 120.0
    assert pytest.approx(data["total_volumetric_weight_kg"], rel=1e-5) == 120.0
    assert pytest.approx(data["chargeable_weight_kg"], rel=1e-5) == 120.0
    assert len(data["lines"]) == 1
    assert pytest.approx(data["lines"][0]["cbm_per_pkg"], rel=1e-5) == 0.072


def test_calculate_validation_errors(client_with_temp_db):
    """POST /api/logistics/cbm/calculate rejects zero/negative dimensions and quantities."""
    # Zero length
    resp = client_with_temp_db.post("/api/logistics/cbm/calculate", json={
        "items": [{
            "description": "Invalid Box",
            "length": 0,
            "width": 10,
            "height": 10,
            "quantity": 1,
        }]
    })
    assert resp.status_code == 422

    # Negative quantity
    resp2 = client_with_temp_db.post("/api/logistics/cbm/calculate", json={
        "items": [{
            "description": "Invalid Box",
            "length": 10,
            "width": 10,
            "height": 10,
            "quantity": -2,
        }]
    })
    assert resp2.status_code == 422


def test_container_estimate_api(client_with_temp_db):
    """POST /api/logistics/cbm/container-estimate evaluates standard container types."""
    payload = {
        "package_length": 60,
        "package_width": 40,
        "package_height": 30,
        "dimension_unit": "cm",
        "package_weight": 12.0,
        "weight_unit": "kg",
        "usable_volume_ratio": 0.85,
    }

    resp = client_with_temp_db.post("/api/logistics/cbm/container-estimate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    keys = [item["container_key"] for item in data]
    assert "20_standard" in keys
    assert "40_standard" in keys
    assert "40_high_cube" in keys

    c20 = next(i for i in data if i["container_key"] == "20_standard")
    assert c20["estimated_units_by_grid"] > 0
    assert c20["does_fit_geometrically"] is True
    assert c20["payload_feasibility"] in ("Pass", "Unknown", "Exceeds Payload")


def test_cargo_calculation_crud_lifecycle(client_with_temp_db):
    """Test full persistence lifecycle: Create, List, Get, Update, Delete."""
    payload = {
        "title": "Electronics Export Consignment",
        "freight_mode": "sea",
        "dimensional_divisor": 5000.0,
        "items": [
            {
                "description": "Smart LED Units",
                "sku": "SKU-LED-55",
                "length": 120,
                "width": 80,
                "height": 15,
                "dimension_unit": "cm",
                "gross_weight_per_pkg": 18.5,
                "weight_unit": "kg",
                "quantity": 20,
                "package_type": "box",
            }
        ],
        "notes": "Fragile display panels",
    }

    # 1. Create
    create_resp = client_with_temp_db.post("/api/logistics/cbm/calculations", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    calc_id = created["id"]
    assert created["title"] == "Electronics Export Consignment"
    assert created["total_packages"] == 20
    assert len(created["lines"]) == 1

    # 2. Get Single
    get_resp = client_with_temp_db.get(f"/api/logistics/cbm/calculations/{calc_id}")
    assert get_resp.status_code == 200
    single = get_resp.json()
    assert single["id"] == calc_id
    assert single["total_packages"] == 20

    # 3. List
    list_resp = client_with_temp_db.get("/api/logistics/cbm/calculations?search=Electronics")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] >= 1
    assert any(c["id"] == calc_id for c in listed["calculations"])

    # 4. Update
    payload["title"] = "Updated Electronics Export Consignment"
    payload["items"][0]["quantity"] = 30
    put_resp = client_with_temp_db.put(f"/api/logistics/cbm/calculations/{calc_id}", json=payload)
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["title"] == "Updated Electronics Export Consignment"
    assert updated["total_packages"] == 30

    # 5. Delete
    del_resp = client_with_temp_db.delete(f"/api/logistics/cbm/calculations/{calc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # 6. Verify 404 after delete
    get_after_del = client_with_temp_db.get(f"/api/logistics/cbm/calculations/{calc_id}")
    assert get_after_del.status_code == 404


def test_shipment_cargo_measurements_link_and_discrepancy(client_with_temp_db):
    """Test linking cargo measurements to a shipment and checking discrepancy response."""
    # Create test shipment
    shipment = create_shipment({
        "reference": "EXP-2026-CBM-001",
        "exporter": "Apex Trading Ltd",
        "buyer": "Global Imports GmbH",
        "product_description": "Industrial Pump Assemblies",
    })
    shp_id = shipment["id"]

    # Save a calculation linked to this shipment
    payload = {
        "title": "Pump Assembly Consignment",
        "shipment_id": shp_id,
        "freight_mode": "sea",
        "items": [
            {
                "description": "Pump Unit Crate",
                "length": 1.0,
                "width": 1.0,
                "height": 1.0,
                "dimension_unit": "m",
                "gross_weight_per_pkg": 250.0,
                "weight_unit": "kg",
                "quantity": 4,
            }
        ],
    }

    create_resp = client_with_temp_db.post("/api/logistics/cbm/calculations", json=payload)
    assert create_resp.status_code == 201

    # Query shipment cargo measurements endpoint
    meas_resp = client_with_temp_db.get(f"/api/shipments/{shp_id}/cargo-measurements")
    assert meas_resp.status_code == 200
    data = meas_resp.json()
    assert data["shipment_id"] == shp_id
    assert len(data["calculations"]) == 1
    assert data["calculations"][0]["total_gross_weight_kg"] == 1000.0
    assert data["calculations"][0]["total_cbm"] == 4.0


def test_not_found_endpoints(client_with_temp_db):
    """Non-existent calculation and shipment IDs return clean 404s."""
    resp1 = client_with_temp_db.get("/api/logistics/cbm/calculations/cbm-nonexistent")
    assert resp1.status_code == 404

    resp2 = client_with_temp_db.delete("/api/logistics/cbm/calculations/cbm-nonexistent")
    assert resp2.status_code == 404

    resp3 = client_with_temp_db.get("/api/shipments/shp-nonexistent/cargo-measurements")
    assert resp3.status_code == 404
