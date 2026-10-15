"""TradeSathi AI — ExportMate ERP Phase 1: Master Data Automated Tests
Covers Product Master, Supplier Master, Customer Master, RBAC, and ERP Audit Logging.
Runs completely isolated using the global test fixture in conftest.py.
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ===========================================================================
# 1. Product Master Tests
# ===========================================================================

def test_product_lifecycle_and_validation(client):
    """Test full CRUD lifecycle for Product Master with validation."""
    # 1. Create Product
    payload = {
        "sku": "SKU-BT-SHRIMP-001",
        "name": "Frozen Black Tiger Shrimp 16/20",
        "description": "Head-on shell-on black tiger shrimp, IQF frozen",
        "category": "Seafood",
        "uom": "KG",
        "conversion_factor": 1.0,
        "default_purchase_cost": 650.0,
        "default_selling_price": 950.0,
        "currency": "INR",
        "hsn_code": "03061720",
        "tax_rate_pct": 5.0,
        "country_of_origin": "IN",
        "net_weight_kg": 1.0,
        "gross_weight_kg": 1.1,
        "barcode": "8901234567890",
        "batch_tracking": True,
        "is_active": True,
    }
    res = client.post("/api/products", json=payload, headers={"X-User-Role": "admin"})
    assert res.status_code == 201
    prod = res.json()
    assert prod["sku"] == "SKU-BT-SHRIMP-001"
    assert prod["name"] == "Frozen Black Tiger Shrimp 16/20"
    assert prod["default_selling_price"] == 950.0
    prod_id = prod["id"]

    # 2. Duplicate SKU prevention (Case-insensitive)
    dup_res = client.post("/api/products", json={
        "sku": "sku-bt-shrimp-001",
        "name": "Duplicate SKU Item",
    }, headers={"X-User-Role": "admin"})
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"]

    # 3. Duplicate Barcode prevention
    dup_bc = client.post("/api/products", json={
        "sku": "SKU-DIFF-002",
        "name": "Different SKU Same Barcode",
        "barcode": "8901234567890",
    }, headers={"X-User-Role": "admin"})
    assert dup_bc.status_code == 409
    assert "barcode" in dup_bc.json()["detail"].lower()

    # 4. Read Product
    get_res = client.get(f"/api/products/{prod_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == prod_id

    # 5. List with Search and Category Filter
    list_res = client.get("/api/products?search=Shrimp&category=Seafood")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] == 1
    assert data["items"][0]["sku"] == "SKU-BT-SHRIMP-001"

    # 6. Update Product
    update_res = client.patch(
        f"/api/products/{prod_id}",
        json={"default_selling_price": 980.0, "notes": "Price revised for Q4 export"},
        headers={"X-User-Role": "admin"},
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["default_selling_price"] == 980.0
    assert updated["notes"] == "Price revised for Q4 export"

    # 7. Delete Product
    del_res = client.delete(f"/api/products/{prod_id}", headers={"X-User-Role": "admin"})
    assert del_res.status_code == 200
    assert del_res.json()["id"] == prod_id

    # 8. Verify 404 after deletion
    assert client.get(f"/api/products/{prod_id}").status_code == 404


# ===========================================================================
# 2. Supplier Master Tests
# ===========================================================================

def test_supplier_lifecycle_and_validation(client):
    """Test full CRUD lifecycle for Supplier Master."""
    # 1. Create Supplier
    payload = {
        "code": "SUP-APEX-001",
        "name": "Apex Seafoods Pvt Ltd",
        "legal_name": "Apex Seafoods India Private Limited",
        "tax_id": "37AAACA1234A1Z5",
        "country": "IN",
        "state": "Andhra Pradesh",
        "address": "Door No 3-1-2, Coastal Highway, Visakhapatnam",
        "contact_person": "K. V. Rao",
        "email": "procurement@apexseafoods.example.com",
        "phone": "+91 891 2555666",
        "currency": "INR",
        "payment_terms": "Net 45",
        "payment_terms_days": 45,
        "bank_name": "State Bank of India",
        "status": "active",
    }
    res = client.post("/api/suppliers", json=payload, headers={"X-User-Role": "procurement"})
    assert res.status_code == 201
    sup = res.json()
    assert sup["code"] == "SUP-APEX-001"
    assert sup["name"] == "Apex Seafoods Pvt Ltd"
    sup_id = sup["id"]

    # 2. Duplicate Code prevention
    dup_res = client.post("/api/suppliers", json={
        "code": "sup-apex-001",
        "name": "Duplicate Apex",
    }, headers={"X-User-Role": "procurement"})
    assert dup_res.status_code == 409

    # 3. List and Search
    list_res = client.get("/api/suppliers?search=Apex&country=IN")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1

    # 4. Update Supplier
    update_res = client.patch(
        f"/api/suppliers/{sup_id}",
        json={"payment_terms": "Net 30", "payment_terms_days": 30},
        headers={"X-User-Role": "procurement"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["payment_terms_days"] == 30

    # 5. Delete Supplier
    del_res = client.delete(f"/api/suppliers/{sup_id}", headers={"X-User-Role": "admin"})
    assert del_res.status_code == 200
    assert client.get(f"/api/suppliers/{sup_id}").status_code == 404


# ===========================================================================
# 3. Customer Master Tests
# ===========================================================================

def test_customer_lifecycle_and_validation(client):
    """Test full CRUD lifecycle for Customer Master (CRM)."""
    # 1. Create International Customer
    payload = {
        "code": "CUS-PACIFIC-001",
        "name": "Pacific Cold Storage LLC",
        "legal_name": "Pacific Cold Storage & Distribution LLC",
        "tax_id": "US-EIN-987654321",
        "customer_type": "international",
        "country": "USA",
        "destination_port": "Long Beach, CA",
        "billing_address": "400 Ocean Gate Blvd, Long Beach, CA 90802",
        "contact_person": "Michael Chang",
        "email": "mchang@pacificcold.example.com",
        "currency": "USD",
        "payment_terms": "LC at sight",
        "payment_terms_days": 30,
        "credit_limit": 250000.0,
        "incoterm_preference": "CIF",
        "status": "active",
    }
    res = client.post("/api/customers", json=payload, headers={"X-User-Role": "sales"})
    assert res.status_code == 201
    cus = res.json()
    assert cus["code"] == "CUS-PACIFIC-001"
    assert cus["customer_type"] == "international"
    cus_id = cus["id"]

    # 2. Duplicate Code prevention
    dup_res = client.post("/api/customers", json={
        "code": "cus-pacific-001",
        "name": "Duplicate Pacific",
        "country": "USA",
    }, headers={"X-User-Role": "sales"})
    assert dup_res.status_code == 409

    # 3. Filter by Customer Type and Country
    list_res = client.get("/api/customers?customer_type=international&country=USA")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1

    # 4. Update Customer Credit Limit
    update_res = client.patch(
        f"/api/customers/{cus_id}",
        json={"credit_limit": 300000.0},
        headers={"X-User-Role": "sales"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["credit_limit"] == 300000.0

    # 5. Delete Customer
    del_res = client.delete(f"/api/customers/{cus_id}", headers={"X-User-Role": "admin"})
    assert del_res.status_code == 200
    assert client.get(f"/api/customers/{cus_id}").status_code == 404


# ===========================================================================
# 4. Role-Based Access Control (RBAC) Tests
# ===========================================================================

def test_rbac_permissions(client):
    """Verify that roles enforce least-privilege boundaries."""
    # 1. Viewer role CANNOT create products, suppliers, or customers
    prod_payload = {"sku": "SKU-VIEWER-TEST", "name": "Unauthorized Item"}
    res = client.post("/api/products", json=prod_payload, headers={"X-User-Role": "viewer"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    sup_payload = {"code": "SUP-UNAUTH", "name": "Unauthorized Supplier"}
    res = client.post("/api/suppliers", json=sup_payload, headers={"X-User-Role": "viewer"})
    assert res.status_code == 403

    cus_payload = {"code": "CUS-UNAUTH", "name": "Unauthorized Customer", "country": "US"}
    res = client.post("/api/customers", json=cus_payload, headers={"X-User-Role": "viewer"})
    assert res.status_code == 403

    # 2. Procurement CAN create supplier, but CANNOT delete supplier (admin only)
    sup_ok = client.post("/api/suppliers", json={
        "code": "SUP-PROC-001",
        "name": "Procurement Supplier",
    }, headers={"X-User-Role": "procurement"})
    assert sup_ok.status_code == 201
    sup_id = sup_ok.json()["id"]

    del_denied = client.delete(f"/api/suppliers/{sup_id}", headers={"X-User-Role": "procurement"})
    assert del_denied.status_code == 403

    del_ok = client.delete(f"/api/suppliers/{sup_id}", headers={"X-User-Role": "admin"})
    assert del_ok.status_code == 200


# ===========================================================================
# 5. ERP Audit Trail & Append-Only Trigger Tests
# ===========================================================================

def test_erp_audit_trail_and_trigger(client):
    """Verify that master data actions generate audit logs and trigger blocks modifications."""
    # Create product to generate audit log
    prod = client.post(
        "/api/products",
        json={"sku": "SKU-AUDIT-TEST", "name": "Audit Test Product"},
        headers={"X-User-Role": "admin", "X-User-Name": "Operator Alice"},
    ).json()
    prod_id = prod["id"]

    # Update product
    client.patch(
        f"/api/products/{prod_id}",
        json={"category": "Hardware"},
        headers={"X-User-Role": "admin", "X-User-Name": "Operator Alice"},
    )

    # Check audit log API
    audit_res = client.get(f"/api/master-data/audit-logs?entity_id={prod_id}")
    assert audit_res.status_code == 200
    logs = audit_res.json()["items"]
    assert len(logs) == 2
    actions = [l["action"] for l in logs]
    assert "create" in actions
    assert "update" in actions
    assert all(l["performed_by"] == "Operator Alice" for l in logs)

    # Database-level trigger test: Attempt direct UPDATE on erp_audit_logs table
    with get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="Audit integrity violation"):
            conn.execute("UPDATE erp_audit_logs SET action = 'tampered' WHERE entity_id = ?", (prod_id,))
