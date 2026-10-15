import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "tradesathi.db"
LIVE_DB_PATH = DEFAULT_DB_PATH.resolve()
_env_db = os.getenv("TRADESATHI_DB_PATH")
DB_PATH = Path(_env_db).resolve() if _env_db else DEFAULT_DB_PATH
_active_db_path: Path = DB_PATH


def is_test_environment() -> bool:
    """Return True if running under pytest or explicit test mode."""
    return bool(os.getenv("PYTEST_CURRENT_TEST") or os.getenv("TRADESATHI_TEST_MODE") == "1")


def set_db_path(path: Path | str) -> None:
    """Override active database path, useful for isolated test suites."""
    global _active_db_path
    _active_db_path = Path(path)


def get_db_path() -> Path:
    return _active_db_path


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = Path(db_path) if db_path else _active_db_path
    if is_test_environment() and target_path.resolve() == LIVE_DB_PATH:
        raise RuntimeError(
            f"CRITICAL TEST ISOLATION FAILURE: Attempted connection to LIVE database ({LIVE_DB_PATH}) "
            "during automated test execution. All tests must execute against isolated temporary databases."
        )
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if str(target_path) != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize SQLite tables and apply safe backward-compatible migrations."""
    with get_connection(db_path) as conn:
        # Create shipments table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id TEXT PRIMARY KEY,
                reference TEXT NOT NULL UNIQUE,
                exporter TEXT,
                buyer TEXT,
                product_description TEXT,
                destination_country TEXT,
                destination_port TEXT,
                planned_shipment_date TEXT,
                incoterm TEXT,
                named_place TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_reference ON shipments(reference)")

        # Create analyses table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                model TEXT,
                status TEXT NOT NULL,
                headline TEXT NOT NULL,
                document_count INTEGER NOT NULL,
                filenames_json TEXT NOT NULL,
                discrepancy_count INTEGER NOT NULL,
                response_json TEXT NOT NULL,
                shipment_id TEXT
            )
        """)

        # Migration: Ensure shipment_id column exists on pre-existing analyses table
        cursor = conn.execute("PRAGMA table_info(analyses)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "shipment_id" not in columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN shipment_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_shipment_id ON analyses(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created_at_asc ON analyses(created_at ASC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status)")

        # Create documents table for Milestone 2C Document Register
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                shipment_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                clean_filename TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'unknown',
                uploaded_at TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                processing_status TEXT NOT NULL DEFAULT 'completed',
                review_status TEXT NOT NULL DEFAULT 'uploaded',
                notes TEXT,
                last_reviewed_by TEXT,
                last_reviewed_at TEXT,
                review_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_shipment_id ON documents(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash)")

        # Create finding_reviews table for Milestone 2E.4 Human Review Audit Trail
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finding_reviews (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                previous_state TEXT NOT NULL,
                new_state TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                notes TEXT,
                reason TEXT,
                supporting_evidence_json TEXT,
                corrected_value TEXT,
                corrected_unit TEXT,
                source TEXT,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_finding_reviews_analysis_finding ON finding_reviews(analysis_id, finding_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_finding_reviews_analysis_time ON finding_reviews(analysis_id, timestamp)")

        # Migration: Ensure finding_reviews audit metadata columns exist
        cursor_fr = conn.execute("PRAGMA table_info(finding_reviews)")
        fr_cols = [row["name"] for row in cursor_fr.fetchall()]
        if "is_operator_assertion" not in fr_cols:
            conn.execute("ALTER TABLE finding_reviews ADD COLUMN is_operator_assertion INTEGER DEFAULT 1")
        if "resolution_basis" not in fr_cols:
            conn.execute("ALTER TABLE finding_reviews ADD COLUMN resolution_basis TEXT DEFAULT 'operator_assertion'")
        if "is_authenticated" not in fr_cols:
            conn.execute("ALTER TABLE finding_reviews ADD COLUMN is_authenticated INTEGER DEFAULT 0")

        # Database engine-level append-only guard for review audit events
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_review_update
            BEFORE UPDATE ON finding_reviews
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: historical review events are append-only and cannot be modified.');
            END;
        """)

        # Milestone 2F: Cargo Measurements & CBM Planning Tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cargo_calculations (
                id TEXT PRIMARY KEY,
                calculation_reference TEXT NOT NULL UNIQUE,
                shipment_id TEXT,
                title TEXT NOT NULL DEFAULT 'Cargo Calculation',
                freight_mode TEXT NOT NULL DEFAULT 'general',
                dimensional_divisor REAL NOT NULL DEFAULT 6000.0,
                volumetric_rounding TEXT NOT NULL DEFAULT 'standard',
                total_packages INTEGER NOT NULL DEFAULT 0,
                total_cbm REAL NOT NULL DEFAULT 0.0,
                total_cuft REAL NOT NULL DEFAULT 0.0,
                total_gross_weight_kg REAL NOT NULL DEFAULT 0.0,
                total_gross_weight_lb REAL NOT NULL DEFAULT 0.0,
                total_volumetric_weight_kg REAL NOT NULL DEFAULT 0.0,
                chargeable_weight_kg REAL NOT NULL DEFAULT 0.0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cargo_calc_shipment ON cargo_calculations(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cargo_calc_created ON cargo_calculations(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cargo_calc_ref ON cargo_calculations(calculation_reference)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cargo_lines (
                id TEXT PRIMARY KEY,
                calculation_id TEXT NOT NULL,
                sku TEXT,
                description TEXT NOT NULL,
                package_type TEXT NOT NULL DEFAULT 'carton',
                length REAL NOT NULL,
                width REAL NOT NULL,
                height REAL NOT NULL,
                dimension_unit TEXT NOT NULL DEFAULT 'cm',
                gross_weight_per_pkg REAL NOT NULL DEFAULT 0.0,
                weight_unit TEXT NOT NULL DEFAULT 'kg',
                quantity INTEGER NOT NULL DEFAULT 1,
                length_m REAL NOT NULL,
                width_m REAL NOT NULL,
                height_m REAL NOT NULL,
                weight_kg REAL NOT NULL,
                cbm_per_pkg REAL NOT NULL,
                total_cbm REAL NOT NULL,
                total_cuft REAL NOT NULL,
                total_weight_kg REAL NOT NULL,
                total_weight_lb REAL NOT NULL,
                volumetric_weight_kg REAL NOT NULL,
                notes TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (calculation_id) REFERENCES cargo_calculations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cargo_lines_calc ON cargo_lines(calculation_id)")

        # Milestone Phase 1: Master Data (Products, Suppliers, Customers & ERP Audit)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL DEFAULT 'General',
                uom TEXT NOT NULL DEFAULT 'PCS',
                purchase_uom TEXT,
                conversion_factor REAL NOT NULL DEFAULT 1.0,
                default_purchase_cost REAL NOT NULL DEFAULT 0.0,
                default_selling_price REAL NOT NULL DEFAULT 0.0,
                currency TEXT NOT NULL DEFAULT 'INR',
                hsn_code TEXT,
                tax_rate_pct REAL NOT NULL DEFAULT 0.0,
                country_of_origin TEXT DEFAULT 'IN',
                net_weight_kg REAL NOT NULL DEFAULT 0.0,
                gross_weight_kg REAL NOT NULL DEFAULT 0.0,
                barcode TEXT UNIQUE,
                batch_tracking INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active)")

        # Phase 7: Additive columns on products for inventory reorder monitoring
        cursor_prod = conn.cursor()
        prod_cols = [c[1] for c in cursor_prod.execute("PRAGMA table_info(products)").fetchall()]
        if "reorder_level" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN reorder_level REAL NOT NULL DEFAULT 0.0;")
        if "reorder_quantity" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN reorder_quantity REAL NOT NULL DEFAULT 0.0;")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                legal_name TEXT,
                tax_id TEXT,
                country TEXT NOT NULL DEFAULT 'IN',
                state TEXT,
                address TEXT,
                contact_person TEXT,
                email TEXT,
                phone TEXT,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_terms TEXT DEFAULT 'Net 30',
                payment_terms_days INTEGER NOT NULL DEFAULT 30,
                bank_name TEXT,
                bank_account_no TEXT,
                bank_ifsc_swift TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_code ON suppliers(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_tax_id ON suppliers(tax_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_status ON suppliers(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                legal_name TEXT,
                tax_id TEXT,
                customer_type TEXT NOT NULL DEFAULT 'international',
                country TEXT NOT NULL,
                destination_port TEXT,
                billing_address TEXT,
                shipping_address TEXT,
                contact_person TEXT,
                email TEXT,
                phone TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_terms TEXT DEFAULT 'LC at sight',
                payment_terms_days INTEGER NOT NULL DEFAULT 30,
                credit_limit REAL NOT NULL DEFAULT 0.0,
                incoterm_preference TEXT DEFAULT 'FOB',
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_code ON customers(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_tax_id ON customers(tax_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_status ON customers(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS erp_audit_logs (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                performed_by TEXT NOT NULL DEFAULT 'Local Operator',
                changes_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON erp_audit_logs(entity_type, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_time ON erp_audit_logs(timestamp DESC)")

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_erp_audit_update
            BEFORE UPDATE ON erp_audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: ERP audit log entries are append-only and cannot be modified.');
            END;
        """)

        # Milestone Phase 2: Procurement, Goods Receipt & Inventory Ledger
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id TEXT PRIMARY KEY,
                po_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                supplier_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                expected_delivery_date TEXT,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_terms TEXT DEFAULT 'Net 30',
                subtotal REAL NOT NULL DEFAULT 0.0,
                tax_total REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft',
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_number ON purchase_orders(po_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_supplier_id ON purchase_orders(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_order_date ON purchase_orders(order_date)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id TEXT PRIMARY KEY,
                po_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                uom TEXT NOT NULL DEFAULT 'PCS',
                ordered_qty REAL NOT NULL CHECK(ordered_qty > 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                tax_rate_pct REAL NOT NULL DEFAULT 0.0 CHECK(tax_rate_pct >= 0),
                line_total REAL NOT NULL,
                received_qty REAL NOT NULL DEFAULT 0.0 CHECK(received_qty >= 0),
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_poi_po_id ON purchase_order_items(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_poi_product_id ON purchase_order_items(product_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goods_receipts (
                id TEXT PRIMARY KEY,
                receipt_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                idempotency_key TEXT NOT NULL UNIQUE,
                po_id TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                receipt_date TEXT NOT NULL,
                received_by TEXT NOT NULL DEFAULT 'Local Operator',
                status TEXT NOT NULL DEFAULT 'draft',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gr_receipt_number ON goods_receipts(receipt_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gr_po_id ON goods_receipts(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gr_supplier_id ON goods_receipts(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gr_status ON goods_receipts(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goods_receipt_items (
                id TEXT PRIMARY KEY,
                receipt_id TEXT NOT NULL,
                po_item_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                uom TEXT NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0.0,
                received_qty REAL NOT NULL CHECK(received_qty >= 0),
                accepted_qty REAL NOT NULL DEFAULT 0.0 CHECK(accepted_qty >= 0),
                rejected_qty REAL NOT NULL DEFAULT 0.0 CHECK(rejected_qty >= 0),
                quarantined_qty REAL NOT NULL DEFAULT 0.0 CHECK(quarantined_qty >= 0),
                inspection_notes TEXT,
                rejection_reason TEXT,
                inspection_status TEXT NOT NULL DEFAULT 'pending',
                inspected_by TEXT,
                inspected_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (receipt_id) REFERENCES goods_receipts(id) ON DELETE CASCADE,
                FOREIGN KEY (po_item_id) REFERENCES purchase_order_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gri_receipt_id ON goods_receipt_items(receipt_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gri_po_item_id ON goods_receipt_items(po_item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gri_product_id ON goods_receipt_items(product_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_movements (
                id TEXT PRIMARY KEY,
                movement_number TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                movement_type TEXT NOT NULL,
                reference_doc_type TEXT NOT NULL,
                reference_doc_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity REAL NOT NULL,
                stock_type TEXT NOT NULL DEFAULT 'available',
                unit_cost REAL NOT NULL DEFAULT 0.0,
                total_cost REAL NOT NULL DEFAULT 0.0,
                performed_by TEXT NOT NULL DEFAULT 'Local Operator',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_product_id ON inventory_movements(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_movement_type ON inventory_movements(movement_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_ref ON inventory_movements(reference_doc_type, reference_doc_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_created ON inventory_movements(created_at)")

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_inventory_movement_update
            BEFORE UPDATE ON inventory_movements
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: Inventory movements are append-only and immutable.');
            END;
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_inventory_movement_delete
            BEFORE DELETE ON inventory_movements
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: Inventory movements cannot be deleted.');
            END;
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_balances (
                product_id TEXT NOT NULL,
                stock_type TEXT NOT NULL DEFAULT 'available',
                sku TEXT NOT NULL,
                on_hand_qty REAL NOT NULL DEFAULT 0.0,
                total_value REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (product_id, stock_type),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bal_product ON inventory_balances(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bal_sku ON inventory_balances(sku)")

        # Milestone Phase 3: Warehouse, Storage Locations, Transfers, Adjustments & Reservations
        conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouses (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                address TEXT,
                city TEXT,
                country TEXT DEFAULT 'IN',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wh_code ON warehouses(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wh_active ON warehouses(is_active)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_locations (
                id TEXT PRIMARY KEY,
                warehouse_id TEXT NOT NULL,
                location_code TEXT NOT NULL COLLATE NOCASE,
                zone TEXT,
                rack TEXT,
                shelf TEXT,
                bin TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                UNIQUE (warehouse_id, location_code)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loc_wh_id ON warehouse_locations(warehouse_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loc_code ON warehouse_locations(warehouse_id, location_code)")

        # Additive columns on inventory_movements if not already present
        cursor = conn.cursor()
        inv_cols = [c[1] for c in cursor.execute("PRAGMA table_info(inventory_movements)").fetchall()]
        if "warehouse_id" not in inv_cols:
            conn.execute("ALTER TABLE inventory_movements ADD COLUMN warehouse_id TEXT;")
        if "location_id" not in inv_cols:
            conn.execute("ALTER TABLE inventory_movements ADD COLUMN location_id TEXT;")
        if "uom" not in inv_cols:
            conn.execute("ALTER TABLE inventory_movements ADD COLUMN uom TEXT DEFAULT 'PCS';")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS location_inventory_balances (
                product_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                stock_type TEXT NOT NULL DEFAULT 'available',
                sku TEXT NOT NULL,
                on_hand_qty REAL NOT NULL DEFAULT 0.0,
                total_value REAL NOT NULL DEFAULT 0.0,
                uom TEXT NOT NULL DEFAULT 'PCS',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (product_id, warehouse_id, location_id, stock_type),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loc_bal_prod ON location_inventory_balances(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loc_bal_wh ON location_inventory_balances(warehouse_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_transfers (
                id TEXT PRIMARY KEY,
                transfer_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                idempotency_key TEXT UNIQUE,
                source_warehouse_id TEXT NOT NULL,
                source_location_id TEXT,
                dest_warehouse_id TEXT NOT NULL,
                dest_location_id TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                approved_by TEXT,
                dispatched_by TEXT,
                received_by TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT,
                dispatched_at TEXT,
                received_at TEXT,
                FOREIGN KEY (source_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (source_location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT,
                FOREIGN KEY (dest_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (dest_location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trf_num ON stock_transfers(transfer_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trf_status ON stock_transfers(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trf_source ON stock_transfers(source_warehouse_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trf_dest ON stock_transfers(dest_warehouse_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_transfer_items (
                id TEXT PRIMARY KEY,
                transfer_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                requested_quantity REAL NOT NULL CHECK(requested_quantity > 0),
                dispatched_quantity REAL NOT NULL DEFAULT 0.0 CHECK(dispatched_quantity >= 0),
                received_quantity REAL NOT NULL DEFAULT 0.0 CHECK(received_quantity >= 0),
                damaged_quantity REAL NOT NULL DEFAULT 0.0 CHECK(damaged_quantity >= 0),
                shortage_quantity REAL NOT NULL DEFAULT 0.0 CHECK(shortage_quantity >= 0),
                uom TEXT NOT NULL DEFAULT 'PCS',
                discrepancy_reason TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (transfer_id) REFERENCES stock_transfers(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trfi_trf_id ON stock_transfer_items(transfer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trfi_prod_id ON stock_transfer_items(product_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_adjustments (
                id TEXT PRIMARY KEY,
                adjustment_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                idempotency_key TEXT UNIQUE,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                location_id TEXT,
                stock_type TEXT NOT NULL DEFAULT 'available',
                system_quantity REAL NOT NULL,
                counted_quantity REAL NOT NULL,
                difference_quantity REAL NOT NULL,
                uom TEXT NOT NULL DEFAULT 'PCS',
                reason_code TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                approved_by TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adj_num ON inventory_adjustments(adjustment_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adj_status ON inventory_adjustments(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adj_prod ON inventory_adjustments(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adj_wh ON inventory_adjustments(warehouse_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_reservations (
                id TEXT PRIMARY KEY,
                reservation_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                idempotency_key TEXT UNIQUE,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                location_id TEXT,
                quantity REAL NOT NULL CHECK(quantity > 0),
                uom TEXT NOT NULL DEFAULT 'PCS',
                reference_type TEXT NOT NULL DEFAULT 'manual',
                reference_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                reserved_by TEXT NOT NULL DEFAULT 'Local Operator',
                released_by TEXT,
                consumed_by TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_num ON stock_reservations(reservation_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_status ON stock_reservations(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_prod ON stock_reservations(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_res_wh ON stock_reservations(warehouse_id)")

        # Seed default central warehouse and receiving location if empty
        wh_count = conn.execute("SELECT count(*) FROM warehouses").fetchone()[0]
        if wh_count == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT OR IGNORE INTO warehouses (id, code, name, address, city, country, is_active, created_at, updated_at)
                VALUES ('wh-main', 'WH-MAIN', 'Main Central Warehouse', 'Plot 42, Nhava Sheva Logistics Park', 'Navi Mumbai', 'IN', 1, ?, ?)
                """,
                (now_iso, now_iso),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO warehouse_locations (id, warehouse_id, location_code, zone, rack, shelf, bin, is_active, created_at, updated_at)
                VALUES ('loc-main-gen', 'wh-main', 'GEN-01', 'General Storage', 'A', '1', '1', 1, ?, ?)
                """,
                (now_iso, now_iso),
            )

        # Milestone Phase 4: Customer Quotations, Sales Orders, Fulfilment & Returns
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_quotations (
                id TEXT PRIMARY KEY,
                quotation_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                customer_id TEXT NOT NULL,
                customer_code TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                quotation_date TEXT NOT NULL,
                valid_until TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_terms TEXT DEFAULT 'LC at sight',
                incoterm TEXT DEFAULT 'FOB',
                destination_port TEXT,
                subtotal REAL NOT NULL DEFAULT 0.0,
                discount_total REAL NOT NULL DEFAULT 0.0,
                tax_total REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft',
                converted_order_id TEXT,
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qt_num ON customer_quotations(quotation_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qt_cust ON customer_quotations(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qt_status ON customer_quotations(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_quotation_items (
                id TEXT PRIMARY KEY,
                quotation_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                uom TEXT NOT NULL DEFAULT 'PCS',
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                discount_pct REAL NOT NULL DEFAULT 0.0 CHECK(discount_pct >= 0 AND discount_pct <= 100),
                tax_rate_pct REAL NOT NULL DEFAULT 0.0 CHECK(tax_rate_pct >= 0),
                subtotal REAL NOT NULL,
                discount_amount REAL NOT NULL DEFAULT 0.0,
                tax_amount REAL NOT NULL DEFAULT 0.0,
                line_total REAL NOT NULL,
                notes TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (quotation_id) REFERENCES customer_quotations(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qti_qt ON customer_quotation_items(quotation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qti_prod ON customer_quotation_items(product_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_orders (
                id TEXT PRIMARY KEY,
                order_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                quotation_id TEXT,
                customer_id TEXT NOT NULL,
                customer_code TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                billing_address TEXT,
                shipping_address TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                tax_id TEXT,
                order_date TEXT NOT NULL,
                requested_delivery_date TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_terms TEXT DEFAULT 'LC at sight',
                incoterm TEXT DEFAULT 'FOB',
                destination_port TEXT,
                subtotal REAL NOT NULL DEFAULT 0.0,
                discount_total REAL NOT NULL DEFAULT 0.0,
                tax_total REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft',
                shipment_id TEXT,
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                confirmed_by TEXT,
                confirmed_at TEXT,
                cancelled_by TEXT,
                cancelled_at TEXT,
                cancellation_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
                FOREIGN KEY (quotation_id) REFERENCES customer_quotations(id) ON DELETE SET NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_so_num ON sales_orders(order_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_so_cust ON sales_orders(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_so_status ON sales_orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_so_shipment ON sales_orders(shipment_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_order_items (
                id TEXT PRIMARY KEY,
                sales_order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                uom TEXT NOT NULL DEFAULT 'PCS',
                ordered_quantity REAL NOT NULL CHECK(ordered_quantity > 0),
                allocated_quantity REAL NOT NULL DEFAULT 0.0 CHECK(allocated_quantity >= 0),
                picked_quantity REAL NOT NULL DEFAULT 0.0 CHECK(picked_quantity >= 0),
                dispatched_quantity REAL NOT NULL DEFAULT 0.0 CHECK(dispatched_quantity >= 0),
                delivered_quantity REAL NOT NULL DEFAULT 0.0 CHECK(delivered_quantity >= 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                discount_pct REAL NOT NULL DEFAULT 0.0 CHECK(discount_pct >= 0 AND discount_pct <= 100),
                tax_rate_pct REAL NOT NULL DEFAULT 0.0 CHECK(tax_rate_pct >= 0),
                subtotal REAL NOT NULL,
                discount_amount REAL NOT NULL DEFAULT 0.0,
                tax_amount REAL NOT NULL DEFAULT 0.0,
                line_total REAL NOT NULL,
                reservation_id TEXT,
                warehouse_id TEXT,
                location_id TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY (reservation_id) REFERENCES stock_reservations(id) ON DELETE SET NULL,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_soi_so ON sales_order_items(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_soi_prod ON sales_order_items(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_soi_res ON sales_order_items(reservation_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_pick_lists (
                id TEXT PRIMARY KEY,
                pick_list_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                sales_order_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                assigned_to TEXT,
                picked_by TEXT,
                packed_by TEXT,
                packed_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pick_num ON sales_pick_lists(pick_list_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pick_so ON sales_pick_lists(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pick_status ON sales_pick_lists(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_pick_items (
                id TEXT PRIMARY KEY,
                pick_list_id TEXT NOT NULL,
                sales_order_item_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                location_id TEXT,
                required_quantity REAL NOT NULL,
                picked_quantity REAL NOT NULL DEFAULT 0.0,
                short_quantity REAL NOT NULL DEFAULT 0.0,
                discrepancy_reason TEXT,
                picked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (pick_list_id) REFERENCES sales_pick_lists(id) ON DELETE CASCADE,
                FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES warehouse_locations(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pki_list ON sales_pick_items(pick_list_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pki_soi ON sales_pick_items(sales_order_item_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_dispatches (
                id TEXT PRIMARY KEY,
                dispatch_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                sales_order_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL,
                shipment_id TEXT,
                idempotency_key TEXT UNIQUE,
                payload_hash TEXT,
                dispatch_date TEXT NOT NULL,
                carrier TEXT,
                tracking_reference TEXT,
                vehicle_no TEXT,
                packages_count INTEGER NOT NULL DEFAULT 1,
                total_weight_kg REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'dispatched',
                dispatched_by TEXT NOT NULL DEFAULT 'Local Operator',
                delivered_at TEXT,
                delivered_by TEXT,
                delivery_recipient TEXT,
                delivery_notes TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disp_num ON sales_dispatches(dispatch_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disp_so ON sales_dispatches(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disp_status ON sales_dispatches(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_dispatch_items (
                id TEXT PRIMARY KEY,
                dispatch_id TEXT NOT NULL,
                sales_order_item_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                dispatched_quantity REAL NOT NULL CHECK(dispatched_quantity > 0),
                delivered_quantity REAL NOT NULL DEFAULT 0.0,
                discrepancy_quantity REAL NOT NULL DEFAULT 0.0,
                uom TEXT NOT NULL DEFAULT 'PCS',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE CASCADE,
                FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dispi_disp ON sales_dispatch_items(dispatch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dispi_soi ON sales_dispatch_items(sales_order_item_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_returns (
                id TEXT PRIMARY KEY,
                return_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                sales_order_id TEXT NOT NULL,
                dispatch_id TEXT,
                customer_id TEXT NOT NULL,
                return_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'received',
                reason TEXT NOT NULL,
                notes TEXT,
                idempotency_key TEXT UNIQUE,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE RESTRICT,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ret_num ON sales_returns(return_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ret_so ON sales_returns(sales_order_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_return_items (
                id TEXT PRIMARY KEY,
                return_id TEXT NOT NULL,
                sales_order_item_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                returned_quantity REAL NOT NULL CHECK(returned_quantity > 0),
                accepted_quantity REAL NOT NULL DEFAULT 0.0,
                quarantined_quantity REAL NOT NULL DEFAULT 0.0,
                rejected_quantity REAL NOT NULL DEFAULT 0.0,
                condition_notes TEXT,
                uom TEXT NOT NULL DEFAULT 'PCS',
                created_at TEXT NOT NULL,
                FOREIGN KEY (return_id) REFERENCES sales_returns(id) ON DELETE CASCADE,
                FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reti_ret ON sales_return_items(return_id)")

        # Migration: Ensure payload_hash and total_weight_kg columns exist on pre-existing sales_dispatches table (ARC-01, Phase 5)
        cursor = conn.execute("PRAGMA table_info(sales_dispatches)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "payload_hash" not in columns:
            conn.execute("ALTER TABLE sales_dispatches ADD COLUMN payload_hash TEXT")
        if "total_weight_kg" not in columns:
            conn.execute("ALTER TABLE sales_dispatches ADD COLUMN total_weight_kg REAL DEFAULT 0.0")

        # --- Authentication & User Identity (SEC-01) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'sales', 'warehouse', 'procurement', 'viewer')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0, 1)),
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_tokens_hash ON user_tokens(token_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_tokens_user ON user_tokens(user_id)")


        # --- Phase 5: Export Operations Additive Columns on shipments ---
        cursor_shp = conn.execute("PRAGMA table_info(shipments)")
        shp_cols = [row["name"] for row in cursor_shp.fetchall()]
        shp_new_cols = [
            ("customer_id", "TEXT"),
            ("consignee_name", "TEXT"),
            ("consignee_address", "TEXT"),
            ("exporter_name", "TEXT"),
            ("exporter_address", "TEXT"),
            ("port_of_loading", "TEXT"),
            ("port_of_discharge", "TEXT"),
            ("transport_mode", "TEXT DEFAULT 'ocean'"),
            ("carrier_name", "TEXT"),
            ("vessel_name", "TEXT"),
            ("voyage_flight_no", "TEXT"),
            ("booking_reference", "TEXT"),
            ("bill_of_lading_no", "TEXT"),
            ("airway_bill_no", "TEXT"),
            ("container_no", "TEXT"),
            ("seal_no", "TEXT"),
            ("package_count", "INTEGER"),
            ("gross_weight_kg", "REAL"),
            ("net_weight_kg", "REAL"),
            ("weight_uom", "TEXT DEFAULT 'KG'"),
            ("estimated_departure_date", "TEXT"),
            ("actual_departure_date", "TEXT"),
            ("estimated_arrival_date", "TEXT"),
            ("actual_arrival_date", "TEXT"),
            ("readiness_status", "TEXT DEFAULT 'not_evaluated'"),
        ]
        for col_name, col_type in shp_new_cols:
            if col_name not in shp_cols:
                conn.execute(f"ALTER TABLE shipments ADD COLUMN {col_name} {col_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_customer ON shipments(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_readiness ON shipments(readiness_status)")

        # --- Phase 5: Document Register Versioning Additive Columns on documents ---
        cursor_doc = conn.execute("PRAGMA table_info(documents)")
        doc_cols = [row["name"] for row in cursor_doc.fetchall()]
        doc_new_cols = [
            ("version", "INTEGER DEFAULT 1"),
            ("parent_document_id", "TEXT"),
            ("is_current_version", "INTEGER DEFAULT 1"),
            ("issue_date", "TEXT"),
            ("expiry_date", "TEXT"),
            ("sales_order_id", "TEXT"),
            ("dispatch_id", "TEXT"),
            ("source", "TEXT DEFAULT 'upload'"),
        ]
        for col_name, col_type in doc_new_cols:
            if col_name not in doc_cols:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_document_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_order ON documents(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_dispatch ON documents(dispatch_id)")

        # --- Phase 5: Export Shipment Dispatches Linkage Guard ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_shipment_dispatches (
                id TEXT PRIMARY KEY,
                shipment_id TEXT NOT NULL,
                dispatch_id TEXT NOT NULL UNIQUE,
                sales_order_id TEXT,
                linked_at TEXT NOT NULL,
                linked_by TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
                FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE RESTRICT,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE RESTRICT
            )
        """)
        esd_cols = [r[1] for r in conn.execute("PRAGMA table_info(export_shipment_dispatches)").fetchall()]
        if "notes" not in esd_cols:
            conn.execute("ALTER TABLE export_shipment_dispatches ADD COLUMN notes TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_esd_shipment ON export_shipment_dispatches(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_esd_dispatch ON export_shipment_dispatches(dispatch_id)")

        # --- Phase 5: Configurable Export Checklist Rules ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_checklist_rules (
                id TEXT PRIMARY KEY,
                rule_name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                description TEXT,
                destination_country TEXT,
                product_category TEXT,
                transport_mode TEXT,
                customer_id TEXT,
                requirement_level TEXT NOT NULL DEFAULT 'mandatory' CHECK(requirement_level IN ('mandatory', 'conditional', 'optional')),
                reason TEXT NOT NULL DEFAULT 'Configured export requirement',
                rule_source TEXT NOT NULL DEFAULT 'standard_sop',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ecr_country ON export_checklist_rules(destination_country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ecr_doc_type ON export_checklist_rules(document_type)")

        # --- Phase 5: Shipment Checklist Items ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_shipment_checklist_items (
                id TEXT PRIMARY KEY,
                shipment_id TEXT NOT NULL,
                document_type TEXT NOT NULL,
                title TEXT,
                requirement_level TEXT NOT NULL CHECK(requirement_level IN ('mandatory', 'conditional', 'optional')),
                rule_id TEXT,
                rule_source TEXT NOT NULL DEFAULT 'standard_sop',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'missing', 'submitted', 'received', 'under_review', 'approved', 'rejected', 'expired', 'superseded', 'needs_confirmation')),
                reason TEXT,
                document_id TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                review_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
                FOREIGN KEY (rule_id) REFERENCES export_checklist_rules(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_esci_shipment ON export_shipment_checklist_items(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_esci_status ON export_shipment_checklist_items(status)")

        # Seed default standard SOP checklist rules if table is empty
        cnt_rules = conn.execute("SELECT count(*) FROM export_checklist_rules").fetchone()[0]
        if cnt_rules == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            default_rules = [
                ("rule-ci", "Commercial Invoice", "commercial_invoice", "Standard commercial invoice required for value and line item verification", None, None, None, None, "mandatory", "Required for all export customs value verification", "standard_sop", 1, now_iso, now_iso),
                ("rule-pl", "Packing List", "packing_list", "Itemized package count, carton specs, gross/net weight", None, None, None, None, "mandatory", "Required for physical inspection and tare verification", "standard_sop", 1, now_iso, now_iso),
                ("rule-si", "Shipping Instructions", "shipping_instructions", "Transport routing, consignee notify parties, handling instructions", None, None, None, None, "mandatory", "Required for carrier freight manifest execution", "standard_sop", 1, now_iso, now_iso),
                ("rule-coo", "Certificate of Origin", "certificate_of_origin", "Country of origin proof for customs tariff preferential/standard treatment", None, None, None, None, "conditional", "Destination or FTA treaty certificate requirements", "customs_standard", 1, now_iso, now_iso),
                ("rule-bl", "Bill of Lading", "bill_of_lading", "Carrier negotiable/express cargo transport document for ocean transit", None, None, "sea", None, "mandatory", "Ocean cargo transport document", "carrier_rules", 1, now_iso, now_iso),
                ("rule-awb", "Air Waybill", "airway_bill", "Non-negotiable air transport consignment note", None, None, "air", None, "mandatory", "Air freight transit note", "carrier_rules", 1, now_iso, now_iso),
            ]
            conn.executemany(
                """
                INSERT INTO export_checklist_rules (
                    id, rule_name, document_type, description, destination_country,
                    product_category, transport_mode, customer_id, requirement_level, reason, rule_source, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                default_rules,
            )

        # --- Phase 6: Commercial Invoicing, Payments, Indian GST & Multi-Currency ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_invoices (
                id TEXT PRIMARY KEY,
                invoice_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                customer_id TEXT NOT NULL,
                customer_code TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                billing_address TEXT NOT NULL,
                shipping_address TEXT,
                customer_tax_id TEXT,
                supplier_tax_id TEXT NOT NULL DEFAULT '19AAACT1234A1Z5',
                supplier_state_code TEXT NOT NULL DEFAULT '19',
                place_of_supply TEXT NOT NULL DEFAULT '19-West Bengal',
                invoice_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                exchange_rate REAL NOT NULL DEFAULT 1.0,
                exchange_rate_date TEXT,
                payment_terms TEXT,
                payment_terms_days INTEGER NOT NULL DEFAULT 30,
                sales_order_id TEXT,
                dispatch_id TEXT,
                export_shipment_id TEXT,
                tax_scheme TEXT NOT NULL DEFAULT 'GST' CHECK(tax_scheme IN ('GST', 'EXPORT_ZERO_RATED', 'EXPORT_LUT', 'SEZ', 'EXEMPT')),
                lut_bond_number TEXT,
                subtotal REAL NOT NULL DEFAULT 0.0,
                discount_total REAL NOT NULL DEFAULT 0.0,
                cgst_total REAL NOT NULL DEFAULT 0.0,
                sgst_total REAL NOT NULL DEFAULT 0.0,
                igst_total REAL NOT NULL DEFAULT 0.0,
                tax_total REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                amount_paid REAL NOT NULL DEFAULT 0.0,
                amount_credited REAL NOT NULL DEFAULT 0.0,
                outstanding_balance REAL NOT NULL DEFAULT 0.0,
                base_grand_total REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'issued', 'partially_paid', 'paid', 'overdue', 'credited', 'cancelled')),
                is_posted INTEGER NOT NULL DEFAULT 0,
                issued_at TEXT,
                issued_by TEXT,
                cancelled_at TEXT,
                cancelled_by TEXT,
                cancellation_reason TEXT,
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE SET NULL,
                FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE SET NULL,
                FOREIGN KEY (export_shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_num ON customer_invoices(invoice_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_cust ON customer_invoices(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_status ON customer_invoices(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_so ON customer_invoices(sales_order_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_invoice_items (
                id TEXT PRIMARY KEY,
                invoice_id TEXT NOT NULL,
                sales_order_item_id TEXT,
                product_id TEXT,
                product_sku TEXT NOT NULL,
                description TEXT NOT NULL,
                hsn_code TEXT,
                uom TEXT NOT NULL DEFAULT 'PCS',
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                discount_pct REAL NOT NULL DEFAULT 0.0 CHECK(discount_pct >= 0 AND discount_pct <= 100),
                discount_amount REAL NOT NULL DEFAULT 0.0,
                taxable_amount REAL NOT NULL DEFAULT 0.0,
                tax_classification TEXT NOT NULL DEFAULT 'taxable' CHECK(tax_classification IN ('taxable', 'exempt', 'nil_rated', 'zero_rated_export', 'non_gst')),
                gst_rate_pct REAL NOT NULL DEFAULT 0.0,
                cgst_rate_pct REAL NOT NULL DEFAULT 0.0,
                cgst_amount REAL NOT NULL DEFAULT 0.0,
                sgst_rate_pct REAL NOT NULL DEFAULT 0.0,
                sgst_amount REAL NOT NULL DEFAULT 0.0,
                igst_rate_pct REAL NOT NULL DEFAULT 0.0,
                igst_amount REAL NOT NULL DEFAULT 0.0,
                line_total REAL NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE CASCADE,
                FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id) ON DELETE SET NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_item_inv ON customer_invoice_items(invoice_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_item_soi ON customer_invoice_items(sales_order_item_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_payments (
                id TEXT PRIMARY KEY,
                payment_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                customer_id TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                payment_date TEXT NOT NULL,
                payment_method TEXT NOT NULL CHECK(payment_method IN ('bank_transfer', 'wire_swift', 'letter_of_credit', 'cheque', 'upi', 'cash')),
                reference_number TEXT,
                currency TEXT NOT NULL DEFAULT 'INR',
                exchange_rate REAL NOT NULL DEFAULT 1.0,
                amount REAL NOT NULL CHECK(amount > 0),
                allocated_amount REAL NOT NULL DEFAULT 0.0,
                unallocated_amount REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted', 'cancelled')),
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_num ON customer_payments(payment_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_cust ON customer_payments(customer_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_payment_allocations (
                id TEXT PRIMARY KEY,
                payment_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                allocated_amount REAL NOT NULL CHECK(allocated_amount > 0),
                realized_gain_loss REAL NOT NULL DEFAULT 0.0,
                allocated_at TEXT NOT NULL,
                allocated_by TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (payment_id) REFERENCES customer_payments(id) ON DELETE CASCADE,
                FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cpa_pay ON customer_payment_allocations(payment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cpa_inv ON customer_payment_allocations(invoice_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_credit_notes (
                id TEXT PRIMARY KEY,
                credit_note_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
                invoice_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                credit_note_date TEXT NOT NULL,
                reason TEXT NOT NULL CHECK(reason IN ('goods_return', 'pricing_error', 'discount_adjustment', 'defective_goods', 'other')),
                currency TEXT NOT NULL DEFAULT 'INR',
                exchange_rate REAL NOT NULL DEFAULT 1.0,
                subtotal REAL NOT NULL DEFAULT 0.0,
                cgst_total REAL NOT NULL DEFAULT 0.0,
                sgst_total REAL NOT NULL DEFAULT 0.0,
                igst_total REAL NOT NULL DEFAULT 0.0,
                tax_total REAL NOT NULL DEFAULT 0.0,
                grand_total REAL NOT NULL DEFAULT 0.0,
                notes TEXT,
                created_by TEXT NOT NULL DEFAULT 'Local Operator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE RESTRICT,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crn_num ON customer_credit_notes(credit_note_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crn_inv ON customer_credit_notes(invoice_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_credit_note_items (
                id TEXT PRIMARY KEY,
                credit_note_id TEXT NOT NULL,
                invoice_item_id TEXT,
                product_sku TEXT NOT NULL,
                description TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                taxable_amount REAL NOT NULL,
                gst_rate_pct REAL NOT NULL DEFAULT 0.0,
                cgst_amount REAL NOT NULL DEFAULT 0.0,
                sgst_amount REAL NOT NULL DEFAULT 0.0,
                igst_amount REAL NOT NULL DEFAULT 0.0,
                line_total REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (credit_note_id) REFERENCES customer_credit_notes(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crni_crn ON customer_credit_note_items(credit_note_id)")

        # Phase 7: Reporting indexes for fast analytics and bounded queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_date ON customer_invoices(invoice_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_due ON customer_invoices(due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_date ON customer_payments(payment_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crn_date ON customer_credit_notes(credit_note_date)")

        # Phase 8: Enterprise Barcode & QR Code Identification System
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_barcodes (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL CHECK(entity_type IN (
                    'product', 'location', 'purchase_order', 'goods_receipt',
                    'sales_order', 'sales_dispatch', 'dispatch_package',
                    'export_shipment', 'document'
                )),
                entity_id TEXT NOT NULL,
                entity_reference TEXT NOT NULL COLLATE NOCASE,
                barcode_value TEXT NOT NULL UNIQUE COLLATE NOCASE,
                symbology TEXT NOT NULL DEFAULT 'QR_CODE' CHECK(symbology IN ('QR_CODE', 'CODE128', 'EAN13')),
                format_version TEXT NOT NULL DEFAULT 'v1',
                label_size TEXT NOT NULL DEFAULT '4x2',
                file_path TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_by TEXT NOT NULL DEFAULT 'system',
                created_at TEXT NOT NULL,
                deactivated_by TEXT,
                deactivated_at TEXT
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_barcodes_active_entity ON entity_barcodes(entity_type, entity_id, symbology) WHERE is_active = 1")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_barcodes_val ON entity_barcodes(barcode_value)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_barcodes_entity ON entity_barcodes(entity_type, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_barcodes_ref ON entity_barcodes(entity_reference)")

        # Additive barcode columns on products and warehouse_locations
        cursor = conn.cursor()
        prod_cols = [c[1] for c in cursor.execute("PRAGMA table_info(products)").fetchall()]
        if "barcode" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN barcode TEXT;")

        loc_cols = [c[1] for c in cursor.execute("PRAGMA table_info(warehouse_locations)").fetchall()]
        if "barcode" not in loc_cols:
            conn.execute("ALTER TABLE warehouse_locations ADD COLUMN barcode TEXT;")

        # --- Phase 9: Secure Supplier & Customer Collaboration Foundation ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_invitations (
                id TEXT PRIMARY KEY,
                invitation_token_hash TEXT NOT NULL UNIQUE,
                account_type TEXT NOT NULL CHECK(account_type IN ('supplier', 'customer')),
                organization_id TEXT NOT NULL,
                organization_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE,
                invited_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'expired', 'revoked')),
                expires_at TEXT NOT NULL,
                accepted_at TEXT,
                revoked_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_inv_token ON portal_invitations(invitation_token_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_inv_org ON portal_invitations(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_inv_status ON portal_invitations(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                account_type TEXT NOT NULL CHECK(account_type IN ('supplier', 'customer')),
                organization_id TEXT NOT NULL,
                organization_name TEXT NOT NULL,
                invitation_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (invitation_id) REFERENCES portal_invitations(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_users_username ON portal_users(LOWER(username))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_users_org ON portal_users(organization_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_users_type ON portal_users(account_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_users_active ON portal_users(is_active)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_user_tokens (
                token_id TEXT PRIMARY KEY,
                portal_user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0, 1)),
                created_at TEXT NOT NULL,
                FOREIGN KEY (portal_user_id) REFERENCES portal_users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_tokens_hash ON portal_user_tokens(token_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p_tokens_user ON portal_user_tokens(portal_user_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS po_acknowledgements (
                id TEXT PRIMARY KEY,
                po_id TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                portal_user_id TEXT NOT NULL,
                portal_username TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('accept', 'reject', 'request_clarification')),
                previous_ack_status TEXT,
                supplier_comments TEXT,
                proposed_delivery_date TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT,
                FOREIGN KEY (portal_user_id) REFERENCES portal_users(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_ack_po ON po_acknowledgements(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_ack_supplier ON po_acknowledgements(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_ack_idem ON po_acknowledgements(idempotency_key)")

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_po_ack_update
            BEFORE UPDATE ON po_acknowledgements
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: PO acknowledgements are append-only and cannot be modified.');
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_prevent_po_ack_delete
            BEFORE DELETE ON po_acknowledgements
            BEGIN
                SELECT RAISE(ABORT, 'Audit integrity violation: PO acknowledgements cannot be deleted.');
            END;
        """)

        # Additive columns on purchase_orders for supplier acknowledgement
        cursor_po = conn.execute("PRAGMA table_info(purchase_orders)")
        po_cols = [row["name"] for row in cursor_po.fetchall()]
        po_new_cols = [
            ("supplier_ack_status", "TEXT DEFAULT 'unacknowledged'"),
            ("supplier_ack_at", "TEXT"),
            ("supplier_ack_by", "TEXT"),
            ("supplier_ack_notes", "TEXT"),
            ("supplier_proposed_delivery_date", "TEXT"),
        ]
        for col_name, col_type in po_new_cols:
            if col_name not in po_cols:
                conn.execute(f"ALTER TABLE purchase_orders ADD COLUMN {col_name} {col_type};")

        # Additive columns on documents for customer/supplier sharing policy
        cursor_doc = conn.execute("PRAGMA table_info(documents)")
        doc_cols = [row["name"] for row in cursor_doc.fetchall()]
        doc_sharing_cols = [
            ("shared_with_customer", "INTEGER NOT NULL DEFAULT 0"),
            ("shared_with_supplier", "INTEGER NOT NULL DEFAULT 0"),
            ("shared_at", "TEXT"),
            ("shared_by", "TEXT"),
            ("sharing_notes", "TEXT"),
            ("po_id", "TEXT"),
            ("asn_id", "TEXT"),
            ("supplier_id", "TEXT"),
            ("customer_id", "TEXT"),
            ("uploaded_by", "TEXT"),
        ]
        for col_name, col_type in doc_sharing_cols:
            if col_name not in doc_cols:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type};")

        # --- Phase 9B: Advanced Supplier Collaboration Tables ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_delivery_commitments (
                id TEXT PRIMARY KEY,
                po_id TEXT NOT NULL REFERENCES purchase_orders(id),
                supplier_id TEXT NOT NULL REFERENCES suppliers(id),
                revision_number INTEGER NOT NULL DEFAULT 1,
                proposed_delivery_date TEXT NOT NULL,
                supplier_dispatch_ref TEXT,
                carrier_name TEXT,
                tracking_number TEXT,
                supplier_comments TEXT,
                status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed', 'accepted', 'rejected', 'superseded')),
                internal_review_notes TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                idempotency_key TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdc_po ON supplier_delivery_commitments(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdc_supplier ON supplier_delivery_commitments(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdc_status ON supplier_delivery_commitments(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdc_idem ON supplier_delivery_commitments(idempotency_key)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_delivery_commitment_lines (
                id TEXT PRIMARY KEY,
                commitment_id TEXT NOT NULL REFERENCES supplier_delivery_commitments(id) ON DELETE CASCADE,
                po_item_id TEXT NOT NULL REFERENCES purchase_order_items(id),
                product_id TEXT NOT NULL,
                committed_qty REAL NOT NULL CHECK(committed_qty > 0),
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdcl_commitment ON supplier_delivery_commitment_lines(commitment_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_asns (
                id TEXT PRIMARY KEY,
                asn_number TEXT NOT NULL UNIQUE,
                po_id TEXT NOT NULL REFERENCES purchase_orders(id),
                supplier_id TEXT NOT NULL REFERENCES suppliers(id),
                dispatch_reference TEXT NOT NULL,
                package_count INTEGER NOT NULL DEFAULT 1 CHECK(package_count >= 0),
                carrier_name TEXT,
                tracking_number TEXT,
                dispatch_date TEXT NOT NULL,
                expected_arrival_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted', 'acknowledged', 'received', 'cancelled')),
                notes TEXT,
                idempotency_key TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_supplier_asn_dispatch UNIQUE (supplier_id, dispatch_reference)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asn_po ON supplier_asns(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asn_supplier ON supplier_asns(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asn_status ON supplier_asns(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asn_idem ON supplier_asns(idempotency_key)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_asn_items (
                id TEXT PRIMARY KEY,
                asn_id TEXT NOT NULL REFERENCES supplier_asns(id) ON DELETE CASCADE,
                po_item_id TEXT NOT NULL REFERENCES purchase_order_items(id),
                product_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                uom TEXT NOT NULL,
                shipped_qty REAL NOT NULL CHECK(shipped_qty > 0),
                package_label TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asni_asn ON supplier_asn_items(asn_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_discrepancies (
                id TEXT PRIMARY KEY,
                discrepancy_number TEXT NOT NULL UNIQUE,
                supplier_id TEXT NOT NULL REFERENCES suppliers(id),
                po_id TEXT NOT NULL REFERENCES purchase_orders(id),
                asn_id TEXT REFERENCES supplier_asns(id),
                commitment_id TEXT REFERENCES supplier_delivery_commitments(id),
                category TEXT NOT NULL CHECK(category IN ('quantity_mismatch', 'short_shipment', 'damaged_goods', 'delayed_shipment', 'incorrect_product', 'missing_documentation', 'other')),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'under_review', 'awaiting_supplier', 'resolved', 'closed', 'rejected')),
                internal_notes TEXT,
                shared_resolution_notes TEXT,
                resolved_by TEXT,
                resolved_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdisc_supplier ON supplier_discrepancies(supplier_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdisc_po ON supplier_discrepancies(po_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdisc_status ON supplier_discrepancies(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_discrepancy_messages (
                id TEXT PRIMARY KEY,
                discrepancy_id TEXT NOT NULL REFERENCES supplier_discrepancies(id) ON DELETE CASCADE,
                sender_type TEXT NOT NULL CHECK(sender_type IN ('supplier', 'staff')),
                sender_id TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                message TEXT NOT NULL,
                attachments_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sdmsg_disc ON supplier_discrepancy_messages(discrepancy_id)")

        # --- Phase 9C: Customer Collaboration & Order Communication Tables ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_order_threads (
                id TEXT PRIMARY KEY,
                sales_order_id TEXT NOT NULL REFERENCES sales_orders(id),
                customer_id TEXT NOT NULL REFERENCES customers(id),
                subject TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'under_review', 'resolved', 'closed')),
                internal_notes TEXT,
                last_message_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cothr_so ON customer_order_threads(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cothr_cust ON customer_order_threads(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cothr_status ON customer_order_threads(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_order_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES customer_order_threads(id) ON DELETE CASCADE,
                sender_type TEXT NOT NULL CHECK(sender_type IN ('customer', 'staff')),
                sender_id TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                message TEXT NOT NULL,
                is_internal_note INTEGER NOT NULL DEFAULT 0 CHECK(is_internal_note IN (0, 1)),
                idempotency_key TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comsg_thread ON customer_order_messages(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comsg_idem ON customer_order_messages(idempotency_key)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_document_requests (
                id TEXT PRIMARY KEY,
                request_number TEXT NOT NULL UNIQUE,
                customer_id TEXT NOT NULL REFERENCES customers(id),
                sales_order_id TEXT NOT NULL REFERENCES sales_orders(id),
                shipment_id TEXT REFERENCES shipments(id),
                document_category TEXT NOT NULL CHECK(document_category IN (
                    'commercial_invoice', 'packing_list', 'shipping_bill', 'bill_of_lading',
                    'certificate_of_origin', 'quality_certificate', 'inspection_certificate', 'other'
                )),
                message TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'under_review', 'fulfilled', 'rejected')),
                fulfilled_document_id TEXT REFERENCES documents(id),
                staff_decision_notes TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                idempotency_key TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cdreq_cust ON customer_document_requests(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cdreq_so ON customer_document_requests(sales_order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cdreq_status ON customer_document_requests(status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS collaboration_notifications (
                id TEXT PRIMARY KEY,
                recipient_type TEXT NOT NULL CHECK(recipient_type IN ('customer', 'supplier', 'staff')),
                recipient_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN (
                    'customer_message', 'customer_thread_created', 'staff_reply', 'document_request_status',
                    'document_shared', 'document_revoked', 'shipment_update',
                    'po_acknowledged', 'commitment_submitted', 'commitment_reviewed',
                    'asn_submitted', 'asn_acknowledged', 'supplier_doc_submitted',
                    'supplier_doc_reviewed', 'discrepancy_created', 'discrepancy_resolved',
                    'document_request_created'
                )),
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                reference_type TEXT,
                reference_id TEXT,
                is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0, 1)),
                delivery_status TEXT NOT NULL DEFAULT 'delivered' CHECK(delivery_status IN ('pending', 'processing', 'delivered', 'retry_pending', 'failed', 'cancelled')),
                delivery_channel TEXT NOT NULL DEFAULT 'in_app' CHECK(delivery_channel IN ('in_app', 'email')),
                idempotency_key TEXT,
                recipient_email TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_attempt_at TEXT,
                next_retry_at TEXT,
                claimed_by TEXT,
                claimed_at TEXT,
                lease_expires_at TEXT,
                error_message TEXT,
                error_class TEXT CHECK(error_class IN ('transient', 'permanent', NULL)),
                provider_message_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnotif_recip ON collaboration_notifications(recipient_type, recipient_id, is_read)")

        # Additive migration for existing collaboration_notifications tables
        notif_cols = [c[1] for c in cursor.execute("PRAGMA table_info(collaboration_notifications)").fetchall()]
        if "delivery_status" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'delivered';")
        if "delivery_channel" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN delivery_channel TEXT NOT NULL DEFAULT 'in_app';")
        if "idempotency_key" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN idempotency_key TEXT;")
        if "recipient_email" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN recipient_email TEXT;")
        if "attempt_count" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;")
        if "max_attempts" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3;")
        if "last_attempt_at" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN last_attempt_at TEXT;")
        if "next_retry_at" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN next_retry_at TEXT;")
        if "claimed_by" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN claimed_by TEXT;")
        if "claimed_at" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN claimed_at TEXT;")
        if "lease_expires_at" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN lease_expires_at TEXT;")
        if "error_message" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN error_message TEXT;")
        if "error_class" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN error_class TEXT;")
        if "provider_message_id" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN provider_message_id TEXT;")
        if "updated_at" not in notif_cols:
            conn.execute("ALTER TABLE collaboration_notifications ADD COLUMN updated_at TEXT;")

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_cnotif_idem ON collaboration_notifications(idempotency_key) WHERE idempotency_key IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnotif_delivery ON collaboration_notifications(delivery_status, next_retry_at, lease_expires_at)")

        # Phase 9D: User Notification Preferences
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_user_notification_preferences (
                user_id TEXT PRIMARY KEY REFERENCES portal_users(id) ON DELETE CASCADE,
                email_notifications_enabled INTEGER NOT NULL DEFAULT 1 CHECK(email_notifications_enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Phase 10: Production Readiness Schema Migration Tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)

        phases = [
            ("phase-1_core", "Core shipments, analyses, documents, finding_reviews"),
            ("phase-2_cbm", "Cargo calculations, lines, container estimation"),
            ("phase-3_warehouse", "Warehouses, locations, transfers, adjustments, reservations"),
            ("phase-4_sales", "Quotations, sales orders, pick lists, dispatches"),
            ("phase-5_exports", "Export filings, shipping bills, customs documents"),
            ("phase-6_invoicing", "Commercial invoicing, payments, GST, multi-currency"),
            ("phase-7_reporting", "ERP audit logs, financial reports, dashboard exports"),
            ("phase-8_barcodes", "Entity barcodes, thermal labels, scanner workflows"),
            ("phase-9_collaboration", "Supplier & customer portals, messaging, notifications"),
            ("phase-10_production_readiness", "Production hardening, schema migration tracking, health probes"),
        ]
        now_migration = datetime.now(timezone.utc).isoformat()
        for version, desc in phases:
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (version, desc, now_migration),
            )

        conn.commit()


def get_applied_migrations(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return all applied schema migration records ordered by applied_at."""
    with get_connection(db_path) as conn:
        try:
            cursor = conn.execute("SELECT version, description, applied_at FROM schema_migrations ORDER BY applied_at ASC")
            return [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []



# ==========================================
# Shipment Persistence Functions
# ==========================================


def create_shipment(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    shipment_id = data.get("id")
    if not shipment_id:
        shipment_id = f"shp-{uuid.uuid4().hex[:10]}"

    exporter = data.get("exporter") or data.get("exporter_name")
    buyer = data.get("buyer") or data.get("consignee_name")
    dest_port = data.get("destination_port") or data.get("port_of_discharge")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shipments (
                id, reference, exporter, buyer, product_description,
                destination_country, destination_port, planned_shipment_date,
                incoterm, named_place, notes, status, created_at, updated_at,
                customer_id, consignee_name, consignee_address, exporter_name, exporter_address,
                port_of_loading, port_of_discharge, transport_mode, carrier_name,
                vessel_name, voyage_flight_no, booking_reference, bill_of_lading_no,
                airway_bill_no, container_no, seal_no, package_count,
                gross_weight_kg, net_weight_kg, weight_uom, estimated_departure_date,
                actual_departure_date, estimated_arrival_date, actual_arrival_date, readiness_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_id,
                data["reference"].strip(),
                exporter,
                buyer,
                data.get("product_description"),
                data.get("destination_country"),
                dest_port,
                data.get("planned_shipment_date"),
                data.get("incoterm"),
                data.get("named_place"),
                data.get("notes"),
                data.get("status", "draft"),
                now,
                now,
                data.get("customer_id"),
                data.get("consignee_name") or buyer,
                data.get("consignee_address"),
                data.get("exporter_name") or exporter,
                data.get("exporter_address"),
                data.get("port_of_loading"),
                data.get("port_of_discharge") or dest_port,
                data.get("transport_mode", "sea"),
                data.get("carrier_name"),
                data.get("vessel_name"),
                data.get("voyage_flight_no"),
                data.get("booking_reference"),
                data.get("bill_of_lading_no"),
                data.get("airway_bill_no"),
                data.get("container_no"),
                data.get("seal_no"),
                data.get("package_count"),
                data.get("gross_weight_kg"),
                data.get("net_weight_kg"),
                data.get("weight_uom", "KG"),
                data.get("estimated_departure_date"),
                data.get("actual_departure_date"),
                data.get("estimated_arrival_date"),
                data.get("actual_arrival_date"),
                data.get("readiness_status", "not_evaluated"),
            ),
        )
        conn.commit()

    return get_shipment_by_id(shipment_id)  # type: ignore[return-value]


def get_shipment_by_id(shipment_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT a.id) AS analysis_count,
                   (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
                   (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
            FROM shipments s
            LEFT JOIN analyses a ON a.shipment_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (shipment_id,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return _row_to_shipment_dict(row)


def get_shipment_by_reference(reference: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT a.id) AS analysis_count,
                   (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
                   (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
            FROM shipments s
            LEFT JOIN analyses a ON a.shipment_id = s.id
            WHERE LOWER(TRIM(s.reference)) = LOWER(TRIM(?))
            GROUP BY s.id
            """,
            (reference,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return _row_to_shipment_dict(row)


def list_shipments(
    search: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = """
        SELECT s.*,
               COUNT(DISTINCT a.id) AS analysis_count,
               (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
               (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
        FROM shipments s
        LEFT JOIN analyses a ON a.shipment_id = s.id
        WHERE 1=1
    """
    params: list[Any] = []

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        query += """ AND (
            LOWER(s.reference) LIKE ? OR
            LOWER(COALESCE(s.exporter, '')) LIKE ? OR
            LOWER(COALESCE(s.buyer, '')) LIKE ? OR
            LOWER(COALESCE(s.destination_port, '')) LIKE ? OR
            LOWER(COALESCE(s.product_description, '')) LIKE ?
        )"""
        params.extend([term, term, term, term, term])

    if status and status.strip():
        query += " AND s.status = ?"
        params.append(status.strip())

    query += """
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT ?
    """
    params.append(limit)

    with get_connection() as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

    return [_row_to_shipment_dict(row) for row in rows]


def update_shipment(shipment_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "reference",
        "exporter",
        "buyer",
        "product_description",
        "destination_country",
        "destination_port",
        "planned_shipment_date",
        "incoterm",
        "named_place",
        "notes",
        "status",
        "customer_id",
        "consignee_name",
        "consignee_address",
        "exporter_name",
        "exporter_address",
        "port_of_loading",
        "port_of_discharge",
        "transport_mode",
        "carrier_name",
        "vessel_name",
        "voyage_flight_no",
        "booking_reference",
        "bill_of_lading_no",
        "airway_bill_no",
        "container_no",
        "seal_no",
        "package_count",
        "gross_weight_kg",
        "net_weight_kg",
        "weight_uom",
        "estimated_departure_date",
        "actual_departure_date",
        "estimated_arrival_date",
        "actual_arrival_date",
        "readiness_status",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        return get_shipment_by_id(shipment_id)

    # Sync legacy aliases if updated
    if "exporter_name" in filtered and "exporter" not in filtered:
        filtered["exporter"] = filtered["exporter_name"]
    elif "exporter" in filtered and "exporter_name" not in filtered:
        filtered["exporter_name"] = filtered["exporter"]

    if "consignee_name" in filtered and "buyer" not in filtered:
        filtered["buyer"] = filtered["consignee_name"]
    elif "buyer" in filtered and "consignee_name" not in filtered:
        filtered["consignee_name"] = filtered["buyer"]

    if "port_of_discharge" in filtered and "destination_port" not in filtered:
        filtered["destination_port"] = filtered["port_of_discharge"]
    elif "destination_port" in filtered and "port_of_discharge" not in filtered:
        filtered["port_of_discharge"] = filtered["destination_port"]

    now = datetime.now(timezone.utc).isoformat()
    filtered["updated_at"] = now

    set_clauses = [f"{k} = ?" for k in filtered.keys()]
    values = list(filtered.values())
    values.append(shipment_id)

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE shipments SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None

    return get_shipment_by_id(shipment_id)


def _row_to_shipment_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "reference": data["reference"],
        "exporter": data.get("exporter"),
        "buyer": data.get("buyer"),
        "product_description": data.get("product_description"),
        "destination_country": data.get("destination_country"),
        "destination_port": data.get("destination_port"),
        "planned_shipment_date": data.get("planned_shipment_date"),
        "incoterm": data.get("incoterm"),
        "named_place": data.get("named_place"),
        "notes": data.get("notes"),
        "status": data.get("status", "draft"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "analysis_count": data.get("analysis_count", 0),
        "document_count": data.get("document_count", 0),
        "latest_analysis_status": data.get("latest_analysis_status"),
        # Phase 5 Export Operations additions
        "customer_id": data.get("customer_id"),
        "consignee_name": data.get("consignee_name") or data.get("buyer"),
        "consignee_address": data.get("consignee_address"),
        "exporter_name": data.get("exporter_name") or data.get("exporter"),
        "exporter_address": data.get("exporter_address"),
        "port_of_loading": data.get("port_of_loading"),
        "port_of_discharge": data.get("port_of_discharge") or data.get("destination_port"),
        "transport_mode": data.get("transport_mode") or "sea",
        "carrier_name": data.get("carrier_name"),
        "vessel_name": data.get("vessel_name"),
        "voyage_flight_no": data.get("voyage_flight_no"),
        "booking_reference": data.get("booking_reference"),
        "bill_of_lading_no": data.get("bill_of_lading_no"),
        "airway_bill_no": data.get("airway_bill_no"),
        "container_no": data.get("container_no"),
        "seal_no": data.get("seal_no"),
        "package_count": data.get("package_count"),
        "gross_weight_kg": data.get("gross_weight_kg"),
        "net_weight_kg": data.get("net_weight_kg"),
        "weight_uom": data.get("weight_uom", "KG"),
        "estimated_departure_date": data.get("estimated_departure_date"),
        "actual_departure_date": data.get("actual_departure_date"),
        "estimated_arrival_date": data.get("estimated_arrival_date"),
        "actual_arrival_date": data.get("actual_arrival_date"),
        "readiness_status": data.get("readiness_status", "not_evaluated"),
    }


def delete_shipment(shipment_id: str) -> dict[str, Any] | None:
    """Safely delete a shipment while preserving historical analysis audits.
    Unlinks analyses (sets shipment_id to NULL) so audit history is never silently corrupted.
    Deletes documents registered to this shipment.
    """
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        return None

    with get_connection() as conn:
        conn.execute("UPDATE analyses SET shipment_id = NULL WHERE shipment_id = ?", (shipment_id,))
        conn.execute("DELETE FROM documents WHERE shipment_id = ?", (shipment_id,))
        conn.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
        conn.commit()

    return shipment


# ==========================================
# Document Persistence Functions (Milestone 2C)
# ==========================================


def _row_to_document_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "shipment_id": data["shipment_id"],
        "original_filename": data["original_filename"],
        "clean_filename": data["clean_filename"],
        "document_type": data.get("document_type", "unknown"),
        "uploaded_at": data["uploaded_at"],
        "storage_key": data["storage_key"],
        "file_size": data["file_size"],
        "file_hash": data["file_hash"],
        "processing_status": data.get("processing_status", "completed"),
        "review_status": data.get("review_status", "uploaded"),
        "notes": data.get("notes"),
        "last_reviewed_by": data.get("last_reviewed_by"),
        "last_reviewed_at": data.get("last_reviewed_at"),
        "review_notes": data.get("review_notes"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        # Phase 5 additions
        "version": data.get("version", 1),
        "parent_document_id": data.get("parent_document_id"),
        "is_current_version": bool(data.get("is_current_version", 1)),
        "issue_date": data.get("issue_date"),
        "expiry_date": data.get("expiry_date"),
        "sales_order_id": data.get("sales_order_id"),
        "dispatch_id": data.get("dispatch_id"),
        "source": data.get("source", "upload"),
        # Phase 9 collaboration document sharing policy
        "shared_with_customer": bool(data.get("shared_with_customer", 0)),
        "shared_with_supplier": bool(data.get("shared_with_supplier", 0)),
        "shared_at": data.get("shared_at"),
        "shared_by": data.get("shared_by"),
        "sharing_notes": data.get("sharing_notes"),
        # Phase 9B additions
        "po_id": data.get("po_id"),
        "asn_id": data.get("asn_id"),
        "supplier_id": data.get("supplier_id"),
        "customer_id": data.get("customer_id"),
        "uploaded_by": data.get("uploaded_by"),
    }


def create_document_record(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    doc_id = data.get("id") or f"doc-{uuid.uuid4().hex[:10]}"
    parent_id = data.get("parent_document_id")

    with get_connection() as conn:
        version = int(data.get("version", 1))
        if parent_id:
            # Check parent doc and get next version
            cur = conn.execute(
                "SELECT COALESCE(MAX(version), 1) + 1 FROM documents WHERE id = ? OR parent_document_id = ?",
                (parent_id, parent_id),
            )
            v_row = cur.fetchone()
            if v_row and v_row[0]:
                version = v_row[0]
            # Supersede previous versions
            conn.execute(
                "UPDATE documents SET is_current_version = 0, review_status = 'superseded', updated_at = ? WHERE id = ? OR parent_document_id = ?",
                (now, parent_id, parent_id),
            )

        conn.execute(
            """
            INSERT INTO documents (
                id, shipment_id, original_filename, clean_filename,
                document_type, uploaded_at, storage_key, file_size, file_hash,
                processing_status, review_status, notes, last_reviewed_by,
                last_reviewed_at, review_notes, created_at, updated_at,
                version, parent_document_id, is_current_version, issue_date,
                expiry_date, sales_order_id, dispatch_id, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                data["shipment_id"],
                data["original_filename"],
                data.get("clean_filename", data["original_filename"]),
                data.get("document_type", "unknown"),
                data.get("uploaded_at", now),
                data["storage_key"],
                int(data.get("file_size", 0)),
                data["file_hash"],
                data.get("processing_status", "completed"),
                data.get("review_status", "uploaded"),
                data.get("notes"),
                data.get("last_reviewed_by"),
                data.get("last_reviewed_at"),
                data.get("review_notes"),
                now,
                now,
                version,
                parent_id,
                1 if data.get("is_current_version", True) else 0,
                data.get("issue_date"),
                data.get("expiry_date"),
                data.get("sales_order_id"),
                data.get("dispatch_id"),
                data.get("source", "upload"),
            ),
        )
        conn.commit()

    return get_document_by_id(doc_id)  # type: ignore[return-value]


def get_document_by_id(doc_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
    if not row:
        return None
    return _row_to_document_dict(row)


def list_documents_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM documents WHERE shipment_id = ? ORDER BY uploaded_at ASC",
            (shipment_id,),
        )
        rows = cursor.fetchall()
    return [_row_to_document_dict(r) for r in rows]


def get_duplicate_document(
    shipment_id: str,
    file_hash: str | None = None,
    filename: str | None = None,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        if file_hash:
            cursor = conn.execute(
                "SELECT * FROM documents WHERE shipment_id = ? AND file_hash = ? LIMIT 1",
                (shipment_id, file_hash),
            )
            row = cursor.fetchone()
            if row:
                return _row_to_document_dict(row)
        if filename:
            clean_name = filename.strip().lower()
            cursor = conn.execute(
                "SELECT * FROM documents WHERE shipment_id = ? AND LOWER(original_filename) = ? LIMIT 1",
                (shipment_id, clean_name),
            )
            row = cursor.fetchone()
            if row:
                return _row_to_document_dict(row)
    return None


def update_document_record(doc_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "document_type",
        "processing_status",
        "review_status",
        "notes",
        "last_reviewed_by",
        "last_reviewed_at",
        "review_notes",
        "is_current_version",
        "parent_document_id",
        "version",
        "issue_date",
        "expiry_date",
        "sales_order_id",
        "dispatch_id",
        "source",
        "shared_with_customer",
        "shared_with_supplier",
        "shared_at",
        "shared_by",
        "sharing_notes",
        "po_id",
        "asn_id",
        "supplier_id",
        "customer_id",
        "uploaded_by",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        return get_document_by_id(doc_id)

    now = datetime.now(timezone.utc).isoformat()
    filtered["updated_at"] = now

    set_clauses = [f"{k} = ?" for k in filtered.keys()]
    values = list(filtered.values())
    values.append(doc_id)

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE documents SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None

    return get_document_by_id(doc_id)


def delete_document_record(doc_id: str) -> dict[str, Any] | None:
    doc = get_document_by_id(doc_id)
    if not doc:
        return None
    with get_connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    return doc


# ==========================================
# Analysis Persistence Functions
# ==========================================


def save_analysis(
    analysis_id: str,
    mode: str,
    model: str | None,
    status: str,
    headline: str,
    filenames: list[str],
    discrepancy_count: int,
    response_data: dict[str, Any],
    shipment_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO analyses (
                id, created_at, mode, model, status, headline,
                document_count, filenames_json, discrepancy_count, response_json,
                shipment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                now,
                mode,
                model,
                status,
                headline,
                len(filenames),
                json.dumps(filenames),
                discrepancy_count,
                json.dumps(response_data),
                shipment_id,
            ),
        )

        # If linked to a shipment, update the shipment's status and updated_at
        if shipment_id:
            conn.execute(
                """
                UPDATE shipments
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, shipment_id),
            )

        conn.commit()


def list_analyses(
    limit: int | None = None,
    search: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    audit_type: str | None = None,
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    return_meta: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], int]:
    """Retrieve audit analyses with full search, filtering, and pagination support.

    Searches across audit ID, headline, filenames, shipment ref, exporter, buyer,
    and extracted document response JSON.
    """
    base_query = """
        FROM analyses a
        LEFT JOIN shipments s ON a.shipment_id = s.id
        WHERE 1=1
    """
    params: list[Any] = []

    # 1. Search term filter
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        base_query += """ AND (
            LOWER(a.id) LIKE ? OR
            LOWER(a.headline) LIKE ? OR
            LOWER(a.filenames_json) LIKE ? OR
            LOWER(COALESCE(s.reference, '')) LIKE ? OR
            LOWER(COALESCE(s.exporter, '')) LIKE ? OR
            LOWER(COALESCE(s.buyer, '')) LIKE ? OR
            LOWER(a.response_json) LIKE ?
        )"""
        params.extend([term, term, term, term, term, term, term])

    # 2. Status filter
    if status and status.strip() and status.strip().lower() != "all":
        base_query += " AND LOWER(a.status) = ?"
        params.append(status.strip().lower())

    # 3. Date range filter
    if date_from and date_from.strip():
        df = date_from.strip()
        if len(df) == 10:
            df = f"{df}T00:00:00"
        base_query += " AND a.created_at >= ?"
        params.append(df)

    if date_to and date_to.strip():
        dt = date_to.strip()
        if len(dt) == 10:
            dt = f"{dt}T23:59:59.999999"
        base_query += " AND a.created_at <= ?"
        params.append(dt)

    # 4. Audit type filter (linked vs standalone)
    if audit_type and audit_type.strip().lower() == "linked":
        base_query += " AND a.shipment_id IS NOT NULL"
    elif audit_type and audit_type.strip().lower() == "standalone":
        base_query += " AND a.shipment_id IS NULL"

    count_query = f"SELECT COUNT(*) {base_query}"

    with get_connection() as conn:
        cursor_count = conn.execute(count_query, params)
        total = cursor_count.fetchone()[0]

        order = "ASC" if str(sort_order).strip().lower() in ("asc", "oldest") else "DESC"
        data_query = f"""
            SELECT a.id, a.created_at, a.mode, a.model, a.status, a.headline,
                   a.document_count, a.filenames_json, a.discrepancy_count,
                   a.shipment_id, a.response_json,
                   s.reference AS shipment_reference,
                   s.exporter AS shipment_exporter,
                   s.buyer AS shipment_buyer
            {base_query}
            ORDER BY a.created_at {order}
        """

        data_params = list(params)
        if (
            limit is not None
            and search is None
            and status is None
            and date_from is None
            and date_to is None
            and audit_type is None
            and not return_meta
        ):
            # Backward-compatible simple limit query
            data_query += " LIMIT ?"
            data_params.append(limit)
        else:
            eff_page = max(1, page)
            eff_size = max(1, min(100, page_size if limit is None else limit))
            offset = (eff_page - 1) * eff_size
            data_query += " LIMIT ? OFFSET ?"
            data_params.extend([eff_size, offset])

        cursor = conn.execute(data_query, data_params)
        rows = cursor.fetchall()

    results = []
    for row in rows:
        filenames = []
        try:
            filenames = json.loads(row["filenames_json"])
        except Exception:
            pass

        invoice_numbers: set[str] = set()
        exporters: set[str] = set()
        buyers: set[str] = set()
        doc_shipment_ref = row["shipment_reference"]

        if row["shipment_exporter"]:
            exporters.add(str(row["shipment_exporter"]).strip())
        if row["shipment_buyer"]:
            buyers.add(str(row["shipment_buyer"]).strip())

        try:
            resp_data = json.loads(row["response_json"])
            for doc in resp_data.get("documents", []):
                if doc.get("invoice_number"):
                    invoice_numbers.add(str(doc["invoice_number"]).strip())
                if doc.get("exporter"):
                    exporters.add(str(doc["exporter"]).strip())
                if doc.get("buyer"):
                    buyers.add(str(doc["buyer"]).strip())
                if not doc_shipment_ref and doc.get("shipment_reference"):
                    doc_shipment_ref = str(doc["shipment_reference"]).strip()
        except Exception:
            pass

        results.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "model": row["model"],
            "status": row["status"],
            "headline": row["headline"],
            "document_count": row["document_count"],
            "filenames": filenames,
            "discrepancy_count": row["discrepancy_count"],
            "shipment_id": row["shipment_id"],
            "shipment_reference": doc_shipment_ref,
            "invoice_numbers": sorted(list(invoice_numbers)),
            "exporters": sorted(list(exporters)),
            "buyers": sorted(list(buyers)),
            "is_linked": bool(row["shipment_id"]),
        })

    if return_meta:
        return results, total
    return results


def list_analyses_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, created_at, mode, model, status, headline,
                   document_count, filenames_json, discrepancy_count, response_json, shipment_id
            FROM analyses
            WHERE shipment_id = ?
            ORDER BY created_at DESC
            """,
            (shipment_id,),
        )
        rows = cursor.fetchall()

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "model": row["model"],
            "status": row["status"],
            "headline": row["headline"],
            "document_count": row["document_count"],
            "filenames": json.loads(row["filenames_json"]),
            "discrepancy_count": row["discrepancy_count"],
            "response_data": json.loads(row["response_json"]),
            "shipment_id": row["shipment_id"],
        })
    return results


def get_latest_analysis_for_shipment(shipment_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, created_at, mode, model, status, headline,
                   document_count, filenames_json, discrepancy_count, response_json, shipment_id
            FROM analyses
            WHERE shipment_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (shipment_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    return {
        "id": data["id"],
        "created_at": data["created_at"],
        "mode": data["mode"],
        "model": data["model"],
        "status": data["status"],
        "headline": data["headline"],
        "document_count": data["document_count"],
        "filenames": json.loads(data["filenames_json"]),
        "discrepancy_count": data["discrepancy_count"],
        "response_data": json.loads(data["response_json"]),
        "shipment_id": data["shipment_id"],
    }


def _row_to_finding_review_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    ev_json = data.get("supporting_evidence_json")
    ev_list = []
    if ev_json:
        try:
            ev_list = json.loads(ev_json)
        except Exception:
            ev_list = [ev_json]
    return {
        "id": data["id"],
        "analysis_id": data["analysis_id"],
        "finding_id": data["finding_id"],
        "previous_state": data["previous_state"],
        "new_state": data["new_state"],
        "reviewer": data["reviewer"],
        "timestamp": data["timestamp"],
        "notes": data.get("notes") or "",
        "reason": data.get("reason") or "",
        "supporting_evidence": ev_list,
        "corrected_value": data.get("corrected_value"),
        "corrected_unit": data.get("corrected_unit"),
        "source": data.get("source"),
        "is_operator_assertion": bool(data.get("is_operator_assertion", 1)),
        "resolution_basis": data.get("resolution_basis") or "operator_assertion",
        "is_authenticated": bool(data.get("is_authenticated", 0)),
    }


def record_finding_review(event_data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    rev_id = event_data.get("id") or f"rev-{uuid.uuid4().hex[:10]}"
    timestamp = event_data.get("timestamp") or now
    ev_json = json.dumps(event_data.get("supporting_evidence") or [])

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO finding_reviews (
                id, analysis_id, finding_id, previous_state, new_state,
                reviewer, timestamp, notes, reason, supporting_evidence_json,
                corrected_value, corrected_unit, source,
                is_operator_assertion, resolution_basis, is_authenticated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rev_id,
                event_data["analysis_id"],
                event_data["finding_id"],
                event_data["previous_state"],
                event_data["new_state"],
                event_data.get("reviewer", "Local Operator"),
                timestamp,
                event_data.get("notes", ""),
                event_data.get("reason", ""),
                ev_json,
                str(event_data["corrected_value"]) if event_data.get("corrected_value") is not None else None,
                event_data.get("corrected_unit"),
                event_data.get("source"),
                1 if event_data.get("is_operator_assertion", True) else 0,
                event_data.get("resolution_basis", "operator_assertion"),
                1 if event_data.get("is_authenticated", False) else 0,
            ),
        )
        conn.commit()

    return {
        "id": rev_id,
        "analysis_id": event_data["analysis_id"],
        "finding_id": event_data["finding_id"],
        "previous_state": event_data["previous_state"],
        "new_state": event_data["new_state"],
        "reviewer": event_data.get("reviewer", "Local Operator"),
        "timestamp": timestamp,
        "notes": event_data.get("notes", ""),
        "reason": event_data.get("reason", ""),
        "supporting_evidence": event_data.get("supporting_evidence") or [],
        "corrected_value": event_data.get("corrected_value"),
        "corrected_unit": event_data.get("corrected_unit"),
        "source": event_data.get("source"),
        "is_operator_assertion": bool(event_data.get("is_operator_assertion", True)),
        "resolution_basis": event_data.get("resolution_basis", "operator_assertion"),
        "is_authenticated": bool(event_data.get("is_authenticated", False)),
    }


def get_finding_reviews_for_analysis(analysis_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM finding_reviews WHERE analysis_id = ? ORDER BY timestamp ASC",
            (analysis_id,),
        )
        rows = cursor.fetchall()
    return [_row_to_finding_review_dict(r) for r in rows]


def get_finding_reviews(analysis_id: str, finding_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM finding_reviews WHERE analysis_id = ? AND finding_id = ? ORDER BY timestamp ASC",
            (analysis_id, finding_id),
        )
        rows = cursor.fetchall()
    return [_row_to_finding_review_dict(r) for r in rows]


def update_analysis_response_json(analysis_id: str, response_data: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE analyses SET response_json = ? WHERE id = ?",
            (json.dumps(response_data), analysis_id),
        )
        conn.commit()


def get_analysis_by_id(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT a.response_json, a.shipment_id,
                   s.reference AS shipment_reference,
                   s.exporter AS shipment_exporter,
                   s.buyer AS shipment_buyer
            FROM analyses a
            LEFT JOIN shipments s ON a.shipment_id = s.id
            WHERE a.id = ?
            """,
            (analysis_id,),
        )
        row = cursor.fetchone()
    if row:
        raw_json = row["response_json"]
        try:
            data = json.loads(raw_json)
        except Exception as exc:
            return {
                "id": analysis_id,
                "error": "malformed_payload",
                "message": f"Historical analysis payload is malformed or corrupted ({type(exc).__name__}).",
                "shipment_id": row["shipment_id"],
            }
        data["shipment_id"] = row["shipment_id"]
        if row["shipment_reference"]:
            data["shipment_reference"] = row["shipment_reference"]

        # Decorate discrepancies with stable IDs, review status, and review history
        discrepancies = data.get("discrepancies", [])
        reviews = get_finding_reviews_for_analysis(analysis_id)
        reviews_by_finding: dict[str, list[dict[str, Any]]] = {}
        for rev in reviews:
            reviews_by_finding.setdefault(rev["finding_id"], []).append(rev)

        for idx, d in enumerate(discrepancies):
            if not d.get("id"):
                clean_field = re.sub(r"[^a-zA-Z0-9_]", "_", d.get("field", "finding"))
                d["id"] = f"fnd-{clean_field}-{idx+1}"

            f_id = d["id"]
            if f_id in reviews_by_finding:
                f_revs = reviews_by_finding[f_id]
                d["review_history"] = f_revs
                latest = f_revs[-1]
                d["review_status"] = latest["new_state"]
                if latest["new_state"] == "resolved":
                    d["resolution"] = {
                        "resolved_at": latest["timestamp"],
                        "resolved_by": latest["reviewer"],
                        "reason": latest.get("reason", ""),
                        "supporting_evidence": latest.get("supporting_evidence", []),
                        "corrected_value": latest.get("corrected_value"),
                        "corrected_unit": latest.get("corrected_unit"),
                        "source": latest.get("source"),
                        "is_operator_assertion": bool(latest.get("is_operator_assertion", True)),
                        "resolution_basis": latest.get("resolution_basis", "operator_assertion"),
                        "is_authenticated": bool(latest.get("is_authenticated", False)),
                    }
                elif latest["new_state"] == "reopened":
                    d["resolution"] = None
            else:
                if not d.get("review_status"):
                    d["review_status"] = "pending_review"
                if "review_history" not in d:
                    d["review_history"] = []

        data["discrepancies"] = discrepancies
        return data
    return None


def delete_analysis_by_id(analysis_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM finding_reviews WHERE analysis_id = ?", (analysis_id,))
        cursor = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        return cursor.rowcount > 0


# ==========================================
# Cargo Calculation Persistence Functions
# ==========================================


def create_cargo_calculation(data: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    calc_id = data.get("id") or f"cbm-{uuid.uuid4().hex[:10]}"
    ref = data.get("calculation_reference") or f"CALC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO cargo_calculations (
                id, calculation_reference, shipment_id, title, freight_mode,
                dimensional_divisor, volumetric_rounding, total_packages,
                total_cbm, total_cuft, total_gross_weight_kg, total_gross_weight_lb,
                total_volumetric_weight_kg, chargeable_weight_kg, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                calc_id,
                ref,
                data.get("shipment_id"),
                data.get("title", "Cargo Calculation"),
                data.get("freight_mode", "general"),
                data.get("dimensional_divisor", 6000.0),
                data.get("volumetric_rounding", "standard"),
                data.get("total_packages", 0),
                data.get("total_cbm", 0.0),
                data.get("total_cuft", 0.0),
                data.get("total_gross_weight_kg", 0.0),
                data.get("total_gross_weight_lb", 0.0),
                data.get("total_volumetric_weight_kg", 0.0),
                data.get("chargeable_weight_kg", 0.0),
                data.get("notes"),
                now,
                now,
            ),
        )

        for idx, line in enumerate(lines):
            line_id = line.get("id") or f"cbl-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO cargo_lines (
                    id, calculation_id, sku, description, package_type,
                    length, width, height, dimension_unit,
                    gross_weight_per_pkg, weight_unit, quantity,
                    length_m, width_m, height_m, weight_kg,
                    cbm_per_pkg, total_cbm, total_cuft,
                    total_weight_kg, total_weight_lb, volumetric_weight_kg,
                    notes, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    line_id,
                    calc_id,
                    line.get("sku"),
                    line.get("description", "Cargo Line"),
                    line.get("package_type", "carton"),
                    line.get("length_orig", line.get("length", 0.0)),
                    line.get("width_orig", line.get("width", 0.0)),
                    line.get("height_orig", line.get("height", 0.0)),
                    line.get("dimension_unit", "cm"),
                    line.get("gross_weight_orig", line.get("gross_weight_per_pkg", 0.0)),
                    line.get("weight_unit", "kg"),
                    line.get("quantity", 1),
                    line.get("length_m", 0.0),
                    line.get("width_m", 0.0),
                    line.get("height_m", 0.0),
                    line.get("weight_kg", 0.0),
                    line.get("cbm_per_pkg", 0.0),
                    line.get("total_cbm", 0.0),
                    line.get("total_cuft", 0.0),
                    line.get("total_gross_weight_kg", line.get("total_weight_kg", 0.0)),
                    line.get("total_gross_weight_lb", line.get("total_weight_lb", 0.0)),
                    line.get("volumetric_weight_kg", 0.0),
                    line.get("notes"),
                    idx,
                    now,
                    now,
                ),
            )
        conn.commit()

    return get_cargo_calculation_by_id(calc_id) or {}


def _row_to_cargo_line_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    d["length_orig"] = d.get("length_orig") if d.get("length_orig") is not None else float(d.get("length", 0.0))
    d["width_orig"] = d.get("width_orig") if d.get("width_orig") is not None else float(d.get("width", 0.0))
    d["height_orig"] = d.get("height_orig") if d.get("height_orig") is not None else float(d.get("height", 0.0))
    d["gross_weight_orig"] = d.get("gross_weight_orig") if d.get("gross_weight_orig") is not None else float(d.get("gross_weight_per_pkg", 0.0))
    d["total_gross_weight_kg"] = d.get("total_gross_weight_kg") if d.get("total_gross_weight_kg") is not None else float(d.get("total_weight_kg", 0.0))
    d["total_gross_weight_lb"] = d.get("total_gross_weight_lb") if d.get("total_gross_weight_lb") is not None else float(d.get("total_weight_lb", 0.0))
    return d


def get_cargo_calculation_by_id(calc_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM cargo_calculations WHERE id = ? OR calculation_reference = ?", (calc_id, calc_id))
        row = cursor.fetchone()
        if not row:
            return None
        calc = dict(row)

        lines_cursor = conn.execute("SELECT * FROM cargo_lines WHERE calculation_id = ? ORDER BY sort_order ASC, created_at ASC", (calc["id"],))
        calc["lines"] = [_row_to_cargo_line_dict(r) for r in lines_cursor.fetchall()]
        return calc


def list_cargo_calculations(
    shipment_id: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    offset = max(0, (page - 1) * page_size)
    where_clauses = []
    params: list[Any] = []

    if shipment_id:
        where_clauses.append("shipment_id = ?")
        params.append(shipment_id)
    if search:
        s = f"%{search.strip()}%"
        where_clauses.append("(calculation_reference LIKE ? OR title LIKE ? OR notes LIKE ?)")
        params.extend([s, s, s])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_connection() as conn:
        count_cursor = conn.execute(f"SELECT COUNT(*) AS total FROM cargo_calculations {where_sql}", params)
        total = int(count_cursor.fetchone()["total"])

        cursor = conn.execute(
            f"SELECT * FROM cargo_calculations {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cursor.fetchall()]

        for r in rows:
            lines_c = conn.execute("SELECT * FROM cargo_lines WHERE calculation_id = ? ORDER BY sort_order ASC", (r["id"],))
            r["lines"] = [_row_to_cargo_line_dict(lr) for lr in lines_c.fetchall()]

        return rows, total


def update_cargo_calculation(
    calc_id: str,
    data: dict[str, Any],
    lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()
    existing = get_cargo_calculation_by_id(calc_id)
    if not existing:
        return None

    actual_id = existing["id"]

    with get_connection() as conn:
        fields = []
        params = []
        updatable = [
            "title", "shipment_id", "freight_mode", "dimensional_divisor",
            "volumetric_rounding", "total_packages", "total_cbm", "total_cuft",
            "total_gross_weight_kg", "total_gross_weight_lb",
            "total_volumetric_weight_kg", "chargeable_weight_kg", "notes",
        ]
        for k in updatable:
            if k in data:
                fields.append(f"{k} = ?")
                params.append(data[k])

        if fields:
            fields.append("updated_at = ?")
            params.append(now)
            params.append(actual_id)
            conn.execute(f"UPDATE cargo_calculations SET {', '.join(fields)} WHERE id = ?", params)

        if lines is not None:
            conn.execute("DELETE FROM cargo_lines WHERE calculation_id = ?", (actual_id,))
            for idx, line in enumerate(lines):
                line_id = line.get("id") or f"cbl-{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO cargo_lines (
                        id, calculation_id, sku, description, package_type,
                        length, width, height, dimension_unit,
                        gross_weight_per_pkg, weight_unit, quantity,
                        length_m, width_m, height_m, weight_kg,
                        cbm_per_pkg, total_cbm, total_cuft,
                        total_weight_kg, total_weight_lb, volumetric_weight_kg,
                        notes, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        line_id,
                        actual_id,
                        line.get("sku"),
                        line.get("description", "Cargo Line"),
                        line.get("package_type", "carton"),
                        line.get("length_orig", line.get("length", 0.0)),
                        line.get("width_orig", line.get("width", 0.0)),
                        line.get("height_orig", line.get("height", 0.0)),
                        line.get("dimension_unit", "cm"),
                        line.get("gross_weight_orig", line.get("gross_weight_per_pkg", 0.0)),
                        line.get("weight_unit", "kg"),
                        line.get("quantity", 1),
                        line.get("length_m", 0.0),
                        line.get("width_m", 0.0),
                        line.get("height_m", 0.0),
                        line.get("weight_kg", 0.0),
                        line.get("cbm_per_pkg", 0.0),
                        line.get("total_cbm", 0.0),
                        line.get("total_cuft", 0.0),
                        line.get("total_gross_weight_kg", line.get("total_weight_kg", 0.0)),
                        line.get("total_gross_weight_lb", line.get("total_weight_lb", 0.0)),
                        line.get("volumetric_weight_kg", 0.0),
                        line.get("notes"),
                        idx,
                        now,
                        now,
                    ),
                )

        conn.commit()

    return get_cargo_calculation_by_id(actual_id)


def delete_cargo_calculation(calc_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM cargo_lines WHERE calculation_id = ? OR calculation_id IN (SELECT id FROM cargo_calculations WHERE calculation_reference = ?)", (calc_id, calc_id))
        cursor = conn.execute("DELETE FROM cargo_calculations WHERE id = ? OR calculation_reference = ?", (calc_id, calc_id))
        conn.commit()
        return cursor.rowcount > 0


def get_cargo_calculations_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM cargo_calculations WHERE shipment_id = ? ORDER BY created_at DESC", (shipment_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            lines_c = conn.execute("SELECT * FROM cargo_lines WHERE calculation_id = ? ORDER BY sort_order ASC", (r["id"],))
            r["lines"] = [_row_to_cargo_line_dict(lr) for lr in lines_c.fetchall()]
        return rows


# ==========================================
# Phase 5: Export Operations Persistence
# ==========================================


def get_document_versions(doc_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        doc = get_document_by_id(doc_id)
        if not doc:
            return []
        root_id = doc.get("parent_document_id") or doc["id"]
        cursor = conn.execute(
            """
            SELECT * FROM documents
            WHERE id = ? OR parent_document_id = ?
            ORDER BY version ASC, created_at ASC
            """,
            (root_id, root_id),
        )
        rows = cursor.fetchall()
        return [_row_to_document_dict(r) for r in rows]


def link_dispatch_to_export_shipment(
    shipment_id: str,
    dispatch_id: str,
    linked_by: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Links a sales dispatch to an export shipment.
    Guarantees:
    - Atomically executed in BEGIN IMMEDIATE transaction.
    - Fails if dispatch_id is already linked to ANY export shipment (UNIQUE constraint on dispatch_id).
    - Updates sales_dispatches.shipment_id.
    """
    now = datetime.now(timezone.utc).isoformat()
    link_id = f"esd-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,))
            if not cur.fetchone():
                raise ValueError(f"Shipment {shipment_id} not found")

            cur = conn.execute(
                "SELECT id, dispatch_number, sales_order_id, packages_count, COALESCE(total_weight_kg, 0.0) AS total_weight_kg, status FROM sales_dispatches WHERE id = ?",
                (dispatch_id,),
            )
            dispatch = cur.fetchone()
            if not dispatch:
                raise ValueError(f"Dispatch {dispatch_id} not found")

            cur = conn.execute("SELECT shipment_id FROM export_shipment_dispatches WHERE dispatch_id = ?", (dispatch_id,))
            existing = cur.fetchone()
            if existing:
                raise ValueError(f"Dispatch {dispatch_id} is already linked to shipment {existing['shipment_id']}")

            conn.execute(
                """
                INSERT INTO export_shipment_dispatches (id, shipment_id, dispatch_id, sales_order_id, linked_at, linked_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (link_id, shipment_id, dispatch_id, dispatch["sales_order_id"], now, linked_by, notes),
            )

            conn.execute(
                "UPDATE sales_dispatches SET shipment_id = ?, updated_at = ? WHERE id = ?",
                (shipment_id, now, dispatch_id),
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "id": link_id,
        "shipment_id": shipment_id,
        "dispatch_id": dispatch_id,
        "linked_at": now,
        "linked_by": linked_by,
        "notes": notes,
        "dispatch_number": dispatch["dispatch_number"],
        "order_id": dispatch["sales_order_id"],
        "total_packages": dispatch["packages_count"] or 1,
        "total_gross_weight": float(dispatch["total_weight_kg"] or 0.0),
        "total_net_weight": float(dispatch["total_weight_kg"] or 0.0),
        "status": dispatch["status"],
    }


def unlink_dispatch_from_export_shipment(shipment_id: str, dispatch_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                "DELETE FROM export_shipment_dispatches WHERE shipment_id = ? AND dispatch_id = ?",
                (shipment_id, dispatch_id),
            )
            deleted = cur.rowcount > 0
            if deleted:
                conn.execute(
                    "UPDATE sales_dispatches SET shipment_id = NULL, updated_at = ? WHERE id = ? AND shipment_id = ?",
                    (now, dispatch_id, shipment_id),
                )
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise


def get_linked_dispatches_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT esd.id AS link_id,
                   esd.shipment_id,
                   esd.dispatch_id,
                   esd.linked_at,
                   esd.linked_by,
                   esd.notes AS link_notes,
                   sd.dispatch_number,
                   sd.sales_order_id AS order_id,
                   sd.warehouse_id,
                   sd.dispatch_date,
                   sd.carrier AS carrier_name,
                   sd.tracking_reference AS tracking_number,
                   sd.status AS dispatch_status,
                   COALESCE(sd.packages_count, 1) AS total_packages,
                   COALESCE(sd.total_weight_kg, 0.0) AS total_gross_weight,
                   COALESCE(sd.total_weight_kg, 0.0) AS total_net_weight,
                   so.order_number,
                   so.customer_id,
                   c.name AS customer_name
            FROM export_shipment_dispatches esd
            JOIN sales_dispatches sd ON sd.id = esd.dispatch_id
            JOIN sales_orders so ON so.id = sd.sales_order_id
            LEFT JOIN customers c ON c.id = so.customer_id
            WHERE esd.shipment_id = ?
            ORDER BY esd.linked_at ASC
            """,
            (shipment_id,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def list_export_checklist_rules(active_only: bool = True) -> list[dict[str, Any]]:
    with get_connection() as conn:
        query = "SELECT * FROM export_checklist_rules"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY rule_name ASC"
        cursor = conn.execute(query)
        return [dict(r) for r in cursor.fetchall()]


def create_export_checklist_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule_id = rule.get("id") or f"ecr-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO export_checklist_rules (
                id, rule_name, document_type, destination_country,
                product_category, transport_mode, customer_id,
                requirement_level, reason, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                rule["rule_name"],
                rule["document_type"],
                rule.get("destination_country"),
                rule.get("product_category"),
                rule.get("transport_mode"),
                rule.get("customer_id"),
                rule.get("requirement_level", "mandatory"),
                rule.get("reason", "Standard export requirement"),
                1 if rule.get("is_active", True) else 0,
                now,
                now,
            ),
        )
        conn.commit()
        cursor = conn.execute("SELECT * FROM export_checklist_rules WHERE id = ?", (rule_id,))
        return dict(cursor.fetchone())


def get_export_checklist_items(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT ci.*,
                   d.original_filename AS document_filename,
                   d.file_hash AS document_file_hash,
                   d.version AS document_version,
                   d.is_current_version AS document_is_current
            FROM export_shipment_checklist_items ci
            LEFT JOIN documents d ON d.id = ci.document_id
            WHERE ci.shipment_id = ?
            ORDER BY ci.requirement_level DESC, ci.document_type ASC
            """,
            (shipment_id,),
        )
        return [dict(r) for r in cursor.fetchall()]


def upsert_export_checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = item.get("id") or f"eci-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id FROM export_shipment_checklist_items WHERE shipment_id = ? AND document_type = ?",
            (item["shipment_id"], item["document_type"]),
        )
        existing = cursor.fetchone()
        if existing:
            actual_id = existing["id"]
            conn.execute(
                """
                UPDATE export_shipment_checklist_items
                SET rule_id = COALESCE(?, rule_id),
                    requirement_level = COALESCE(?, requirement_level),
                    status = COALESCE(?, status),
                    reason = COALESCE(?, reason),
                    document_id = COALESCE(?, document_id),
                    reviewed_by = COALESCE(?, reviewed_by),
                    reviewed_at = COALESCE(?, reviewed_at),
                    review_notes = COALESCE(?, review_notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    item.get("rule_id"),
                    item.get("requirement_level"),
                    item.get("status"),
                    item.get("reason"),
                    item.get("document_id"),
                    item.get("reviewed_by"),
                    item.get("reviewed_at"),
                    item.get("review_notes"),
                    now,
                    actual_id,
                ),
            )
            item_id = actual_id
        else:
            conn.execute(
                """
                INSERT INTO export_shipment_checklist_items (
                    id, shipment_id, rule_id, document_type, requirement_level,
                    status, reason, document_id, reviewed_by, reviewed_at,
                    review_notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    item["shipment_id"],
                    item.get("rule_id"),
                    item["document_type"],
                    item.get("requirement_level", "mandatory"),
                    item.get("status", "pending"),
                    item.get("reason", "Required export document"),
                    item.get("document_id"),
                    item.get("reviewed_by"),
                    item.get("reviewed_at"),
                    item.get("review_notes"),
                    now,
                    now,
                ),
            )
        conn.commit()
        cur = conn.execute("SELECT * FROM export_shipment_checklist_items WHERE id = ?", (item_id,))
        return dict(cur.fetchone())


def update_export_checklist_item(item_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "document_id", "reviewed_by", "reviewed_at", "review_notes", "requirement_level", "reason"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        with get_connection() as conn:
            cur = conn.execute("SELECT * FROM export_shipment_checklist_items WHERE id = ?", (item_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    now = datetime.now(timezone.utc).isoformat()
    filtered["updated_at"] = now
    clauses = [f"{k} = ?" for k in filtered.keys()]
    values = list(filtered.values()) + [item_id]

    with get_connection() as conn:
        conn.execute(f"UPDATE export_shipment_checklist_items SET {', '.join(clauses)} WHERE id = ?", values)
        conn.commit()
        cur = conn.execute("SELECT * FROM export_shipment_checklist_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ==========================================
# Phase 6: Invoicing, Payments & GST Persistence
# ==========================================


def get_next_invoice_number() -> str:
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT count(*) FROM customer_invoices WHERE invoice_number LIKE ?",
            (f"INV-{year}-%",),
        )
        count = cur.fetchone()[0]
        return f"INV-{year}-{count + 1:04d}"


def get_next_payment_number() -> str:
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT count(*) FROM customer_payments WHERE payment_number LIKE ?",
            (f"PAY-{year}-%",),
        )
        count = cur.fetchone()[0]
        return f"PAY-{year}-{count + 1:04d}"


def get_next_credit_note_number() -> str:
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT count(*) FROM customer_credit_notes WHERE credit_note_number LIKE ?",
            (f"CRN-{year}-%",),
        )
        count = cur.fetchone()[0]
        return f"CRN-{year}-{count + 1:04d}"


def create_customer_invoice_record(data: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    invoice_id = data.get("id") or f"inv-{uuid.uuid4().hex[:10]}"
    invoice_number = data.get("invoice_number") or get_next_invoice_number()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Cumulative invoiceable quantity check against sales order
            if data.get("sales_order_id"):
                so_id = data["sales_order_id"]
                for item in items:
                    so_item_id = item.get("sales_order_item_id")
                    if so_item_id:
                        cur = conn.execute(
                            "SELECT ordered_quantity FROM sales_order_items WHERE id = ? AND sales_order_id = ?",
                            (so_item_id, so_id),
                        )
                        so_row = cur.fetchone()
                        if so_row:
                            ordered_qty = so_row["ordered_quantity"]
                            cur_inv = conn.execute(
                                """
                                SELECT COALESCE(SUM(cii.quantity), 0.0) AS already_invoiced
                                FROM customer_invoice_items cii
                                JOIN customer_invoices ci ON ci.id = cii.invoice_id
                                WHERE cii.sales_order_item_id = ? AND ci.status != 'cancelled'
                                """,
                                (so_item_id,),
                            )
                            already_invoiced = cur_inv.fetchone()["already_invoiced"]
                            new_qty = float(item["quantity"])
                            if round(already_invoiced + new_qty, 4) > round(ordered_qty, 4):
                                raise ValueError(
                                    f"Cumulative invoiced quantity ({already_invoiced + new_qty}) exceeds "
                                    f"ordered quantity ({ordered_qty}) for item {item.get('product_sku')}"
                                )

            # Compute totals
            subtotal = round(sum(float(it.get("taxable_amount", 0.0)) for it in items), 2)
            discount_total = round(sum(float(it.get("discount_amount", 0.0)) for it in items), 2)
            cgst_total = round(sum(float(it.get("cgst_amount", 0.0)) for it in items), 2)
            sgst_total = round(sum(float(it.get("sgst_amount", 0.0)) for it in items), 2)
            igst_total = round(sum(float(it.get("igst_amount", 0.0)) for it in items), 2)
            tax_total = round(cgst_total + sgst_total + igst_total, 2)
            grand_total = round(subtotal + tax_total, 2)
            rate = float(data.get("exchange_rate") or 1.0)
            base_grand_total = round(grand_total * rate, 2)
            outstanding_balance = grand_total

            conn.execute(
                """
                INSERT INTO customer_invoices (
                    id, invoice_number, customer_id, customer_code, customer_name,
                    billing_address, shipping_address, customer_tax_id, supplier_tax_id,
                    supplier_state_code, place_of_supply, invoice_date, due_date,
                    currency, exchange_rate, exchange_rate_date, payment_terms, payment_terms_days,
                    sales_order_id, dispatch_id, export_shipment_id, tax_scheme, lut_bond_number,
                    subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                    grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                    status, is_posted, notes, created_by, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, 0.0, 0.0, ?, ?,
                    ?, 0, ?, ?, ?, ?
                )
                """,
                (
                    invoice_id,
                    invoice_number,
                    data["customer_id"],
                    data.get("customer_code", ""),
                    data["customer_name"],
                    data["billing_address"],
                    data.get("shipping_address"),
                    data.get("customer_tax_id"),
                    data.get("supplier_tax_id", "19AAACT1234A1Z5"),
                    data.get("supplier_state_code", "19"),
                    data.get("place_of_supply", "19-West Bengal"),
                    data["invoice_date"],
                    data["due_date"],
                    data.get("currency", "INR"),
                    rate,
                    data.get("exchange_rate_date", data["invoice_date"]),
                    data.get("payment_terms", "Net 30"),
                    int(data.get("payment_terms_days") or 30),
                    data.get("sales_order_id"),
                    data.get("dispatch_id"),
                    data.get("export_shipment_id"),
                    data.get("tax_scheme", "GST"),
                    data.get("lut_bond_number"),
                    subtotal,
                    discount_total,
                    cgst_total,
                    sgst_total,
                    igst_total,
                    tax_total,
                    grand_total,
                    outstanding_balance,
                    base_grand_total,
                    data.get("status", "draft"),
                    data.get("notes"),
                    data.get("created_by", "Local Operator"),
                    now,
                    now,
                ),
            )

            # Insert line items
            for idx, item in enumerate(items):
                item_id = item.get("id") or f"inv-item-{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO customer_invoice_items (
                        id, invoice_id, sales_order_item_id, product_id, product_sku,
                        description, hsn_code, uom, quantity, unit_price,
                        discount_pct, discount_amount, taxable_amount, tax_classification,
                        gst_rate_pct, cgst_rate_pct, cgst_amount, sgst_rate_pct, sgst_amount,
                        igst_rate_pct, igst_amount, line_total, sort_order, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        item_id,
                        invoice_id,
                        item.get("sales_order_item_id"),
                        item.get("product_id"),
                        item["product_sku"],
                        item["description"],
                        item.get("hsn_code"),
                        item.get("uom", "PCS"),
                        float(item["quantity"]),
                        float(item["unit_price"]),
                        float(item.get("discount_pct", 0.0)),
                        float(item.get("discount_amount", 0.0)),
                        float(item["taxable_amount"]),
                        item.get("tax_classification", "taxable"),
                        float(item.get("gst_rate_pct", 0.0)),
                        float(item.get("cgst_rate_pct", 0.0)),
                        float(item.get("cgst_amount", 0.0)),
                        float(item.get("sgst_rate_pct", 0.0)),
                        float(item.get("sgst_amount", 0.0)),
                        float(item.get("igst_rate_pct", 0.0)),
                        float(item.get("igst_amount", 0.0)),
                        float(item["line_total"]),
                        idx,
                        now,
                    ),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return get_customer_invoice_record(invoice_id)


def get_customer_invoice_record(invoice_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM customer_invoices WHERE id = ?", (invoice_id,))
        invoice = cur.fetchone()
        if not invoice:
            return None

        inv_dict = dict(invoice)
        cur_items = conn.execute(
            "SELECT * FROM customer_invoice_items WHERE invoice_id = ? ORDER BY sort_order ASC",
            (invoice_id,),
        )
        inv_dict["items"] = [dict(it) for it in cur_items.fetchall()]

        cur_alloc = conn.execute(
            """
            SELECT cpa.*, cp.payment_number, cp.payment_date, cp.payment_method, cp.reference_number
            FROM customer_payment_allocations cpa
            JOIN customer_payments cp ON cp.id = cpa.payment_id
            WHERE cpa.invoice_id = ?
            ORDER BY cpa.allocated_at ASC
            """,
            (invoice_id,),
        )
        inv_dict["allocations"] = [dict(a) for a in cur_alloc.fetchall()]

        cur_crn = conn.execute(
            "SELECT * FROM customer_credit_notes WHERE invoice_id = ? ORDER BY created_at ASC",
            (invoice_id,),
        )
        inv_dict["credit_notes"] = [dict(c) for c in cur_crn.fetchall()]

        return inv_dict


def get_customer_invoice_by_number_record(invoice_number: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT id FROM customer_invoices WHERE invoice_number = ?", (invoice_number,))
        row = cur.fetchone()
        if not row:
            return None
        return get_customer_invoice_record(row["id"])


def list_customer_invoices_record(
    customer_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM customer_invoices WHERE 1=1"
    params: list[Any] = []

    if customer_id:
        query += " AND customer_id = ?"
        params.append(customer_id)
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (invoice_number LIKE ? OR customer_name LIKE ? OR place_of_supply LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def update_customer_invoice_status_record(
    invoice_id: str,
    target_status: str,
    actor: str,
    reason: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("SELECT * FROM customer_invoices WHERE id = ?", (invoice_id,))
            inv = cur.fetchone()
            if not inv:
                raise ValueError(f"Invoice {invoice_id} not found")

            current_status = inv["status"]
            valid_transitions = {
                "draft": ["approved", "issued", "cancelled"],
                "approved": ["issued", "cancelled"],
                "issued": ["partially_paid", "paid", "cancelled", "overdue", "credited"],
                "partially_paid": ["paid", "credited"],
                "paid": ["credited"],
                "overdue": ["partially_paid", "paid", "credited", "cancelled"],
                "credited": [],
                "cancelled": [],
            }

            if target_status not in valid_transitions.get(current_status, []):
                raise ValueError(f"Cannot transition invoice from '{current_status}' to '{target_status}'")

            if target_status == "cancelled":
                if inv["amount_paid"] > 0:
                    raise ValueError("Cannot cancel an invoice with recorded payments. Use Credit Note instead.")
                conn.execute(
                    """
                    UPDATE customer_invoices
                    SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?,
                        cancellation_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, actor, reason or "Cancelled by user", now, invoice_id),
                )
            elif target_status in ("issued", "approved"):
                is_posted = 1 if target_status == "issued" else inv["is_posted"]
                conn.execute(
                    """
                    UPDATE customer_invoices
                    SET status = ?, is_posted = ?, issued_at = COALESCE(issued_at, ?),
                        issued_by = COALESCE(issued_by, ?), updated_at = ?
                    WHERE id = ?
                    """,
                    (target_status, is_posted, now, actor, now, invoice_id),
                )
            else:
                conn.execute(
                    "UPDATE customer_invoices SET status = ?, updated_at = ? WHERE id = ?",
                    (target_status, now, invoice_id),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return get_customer_invoice_record(invoice_id)


def create_customer_payment_record(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    payment_id = data.get("id") or f"pay-{uuid.uuid4().hex[:10]}"
    payment_number = data.get("payment_number") or get_next_payment_number()
    amount = float(data["amount"])

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO customer_payments (
                id, payment_number, customer_id, customer_name, payment_date,
                payment_method, reference_number, currency, exchange_rate,
                amount, allocated_amount, unallocated_amount, status, notes,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, 'posted', ?, ?, ?, ?)
            """,
            (
                payment_id,
                payment_number,
                data["customer_id"],
                data["customer_name"],
                data["payment_date"],
                data["payment_method"],
                data.get("reference_number"),
                data.get("currency", "INR"),
                float(data.get("exchange_rate") or 1.0),
                amount,
                amount,
                data.get("notes"),
                data.get("created_by", "Local Operator"),
                now,
                now,
            ),
        )
        conn.commit()

    return get_customer_payment_record(payment_id)


def get_customer_payment_record(payment_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM customer_payments WHERE id = ?", (payment_id,))
        p = cur.fetchone()
        if not p:
            return None
        p_dict = dict(p)
        cur_alloc = conn.execute(
            """
            SELECT cpa.*, ci.invoice_number, ci.currency AS invoice_currency, ci.grand_total, ci.outstanding_balance
            FROM customer_payment_allocations cpa
            JOIN customer_invoices ci ON ci.id = cpa.invoice_id
            WHERE cpa.payment_id = ?
            ORDER BY cpa.allocated_at ASC
            """,
            (payment_id,),
        )
        p_dict["allocations"] = [dict(a) for a in cur_alloc.fetchall()]
        return p_dict


def list_customer_payments_record(customer_id: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    query = "SELECT * FROM customer_payments WHERE 1=1"
    params: list[Any] = []
    if customer_id:
        query += " AND customer_id = ?"
        params.append(customer_id)
    query += " ORDER BY payment_date DESC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def allocate_customer_payment_record(
    payment_id: str,
    invoice_id: str,
    amount: float,
    actor: str,
    notes: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    alloc_id = f"cpa-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur_p = conn.execute("SELECT * FROM customer_payments WHERE id = ?", (payment_id,))
            payment = cur_p.fetchone()
            if not payment:
                raise ValueError(f"Payment {payment_id} not found")

            if payment["status"] != "posted":
                raise ValueError("Payment is not in posted status")

            unallocated = round(float(payment["unallocated_amount"]), 2)
            alloc_amt = round(float(amount), 2)
            if alloc_amt <= 0:
                raise ValueError("Allocation amount must be greater than zero")
            if alloc_amt > unallocated:
                raise ValueError(f"Cannot allocate {alloc_amt}; unallocated balance is only {unallocated}")

            cur_i = conn.execute("SELECT * FROM customer_invoices WHERE id = ?", (invoice_id,))
            invoice = cur_i.fetchone()
            if not invoice:
                raise ValueError(f"Invoice {invoice_id} not found")

            if invoice["status"] not in ("approved", "issued", "partially_paid", "overdue"):
                raise ValueError(f"Cannot allocate payment to invoice in '{invoice['status']}' status")

            outstanding = round(float(invoice["outstanding_balance"]), 2)
            if alloc_amt > outstanding:
                raise ValueError(f"Cannot allocate {alloc_amt}; invoice outstanding balance is only {outstanding}")

            # Compute realized FX gain/loss if multi-currency
            realized_fx = 0.0
            inv_rate = float(invoice["exchange_rate"] or 1.0)
            pay_rate = float(payment["exchange_rate"] or 1.0)
            if invoice["currency"] != "INR" and invoice["currency"] == payment["currency"]:
                realized_fx = round(alloc_amt * (pay_rate - inv_rate), 2)

            # Insert allocation
            conn.execute(
                """
                INSERT INTO customer_payment_allocations (
                    id, payment_id, invoice_id, allocated_amount, realized_gain_loss,
                    allocated_at, allocated_by, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (alloc_id, payment_id, invoice_id, alloc_amt, realized_fx, now, actor, notes),
            )

            # Update Payment balances
            new_unallocated = round(unallocated - alloc_amt, 2)
            new_p_allocated = round(float(payment["allocated_amount"]) + alloc_amt, 2)
            conn.execute(
                """
                UPDATE customer_payments
                SET unallocated_amount = ?, allocated_amount = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_unallocated, new_p_allocated, now, payment_id),
            )

            # Update Invoice balances & status
            new_inv_paid = round(float(invoice["amount_paid"]) + alloc_amt, 2)
            new_outstanding = round(outstanding - alloc_amt, 2)
            new_status = "paid" if new_outstanding <= 0.001 else "partially_paid"
            conn.execute(
                """
                UPDATE customer_invoices
                SET amount_paid = ?, outstanding_balance = ?, status = ?, is_posted = 1, updated_at = ?
                WHERE id = ?
                """,
                (new_inv_paid, new_outstanding, new_status, now, invoice_id),
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return get_customer_payment_record(payment_id)


def create_customer_credit_note_record(data: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    crn_id = data.get("id") or f"crn-{uuid.uuid4().hex[:10]}"
    crn_number = data.get("credit_note_number") or get_next_credit_note_number()
    invoice_id = data["invoice_id"]

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur_i = conn.execute("SELECT * FROM customer_invoices WHERE id = ?", (invoice_id,))
            invoice = cur_i.fetchone()
            if not invoice:
                raise ValueError(f"Invoice {invoice_id} not found")

            if invoice["status"] in ("draft", "cancelled"):
                raise ValueError(f"Cannot issue credit note against invoice in '{invoice['status']}' status")

            subtotal = round(sum(float(it.get("taxable_amount", 0.0)) for it in items), 2)
            cgst_total = round(sum(float(it.get("cgst_amount", 0.0)) for it in items), 2)
            sgst_total = round(sum(float(it.get("sgst_amount", 0.0)) for it in items), 2)
            igst_total = round(sum(float(it.get("igst_amount", 0.0)) for it in items), 2)
            tax_total = round(cgst_total + sgst_total + igst_total, 2)
            grand_total = round(subtotal + tax_total, 2)

            outstanding = round(float(invoice["outstanding_balance"]), 2)
            if grand_total > float(invoice["grand_total"]):
                raise ValueError("Credit note grand total cannot exceed original invoice grand total")

            conn.execute(
                """
                INSERT INTO customer_credit_notes (
                    id, credit_note_number, invoice_id, customer_id, customer_name,
                    credit_note_date, reason, currency, exchange_rate,
                    subtotal, cgst_total, sgst_total, igst_total, tax_total, grand_total,
                    notes, created_by, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    crn_id,
                    crn_number,
                    invoice_id,
                    invoice["customer_id"],
                    invoice["customer_name"],
                    data.get("credit_note_date", now[:10]),
                    data["reason"],
                    invoice["currency"],
                    float(invoice["exchange_rate"] or 1.0),
                    subtotal,
                    cgst_total,
                    sgst_total,
                    igst_total,
                    tax_total,
                    grand_total,
                    data.get("notes"),
                    data.get("created_by", "Local Operator"),
                    now,
                    now,
                ),
            )

            for it in items:
                it_id = f"crni-{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO customer_credit_note_items (
                        id, credit_note_id, invoice_item_id, product_sku, description,
                        quantity, unit_price, taxable_amount, gst_rate_pct,
                        cgst_amount, sgst_amount, igst_amount, line_total, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it_id,
                        crn_id,
                        it.get("invoice_item_id"),
                        it["product_sku"],
                        it["description"],
                        float(it["quantity"]),
                        float(it["unit_price"]),
                        float(it["taxable_amount"]),
                        float(it.get("gst_rate_pct", 0.0)),
                        float(it.get("cgst_amount", 0.0)),
                        float(it.get("sgst_amount", 0.0)),
                        float(it.get("igst_amount", 0.0)),
                        float(it["line_total"]),
                        now,
                    ),
                )

            # Deduct from invoice balance
            new_amount_credited = round(float(invoice["amount_credited"]) + grand_total, 2)
            new_outstanding = max(0.0, round(outstanding - grand_total, 2))
            new_status = "credited" if new_outstanding <= 0.001 and float(invoice["amount_paid"]) == 0 else invoice["status"]
            if new_outstanding <= 0.001 and float(invoice["amount_paid"]) > 0:
                new_status = "paid"

            conn.execute(
                """
                UPDATE customer_invoices
                SET amount_credited = ?, outstanding_balance = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_amount_credited, new_outstanding, new_status, now, invoice_id),
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return get_customer_credit_note_record(crn_id)


def get_customer_credit_note_record(crn_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM customer_credit_notes WHERE id = ?", (crn_id,))
        c = cur.fetchone()
        if not c:
            return None
        c_dict = dict(c)
        cur_it = conn.execute("SELECT * FROM customer_credit_note_items WHERE credit_note_id = ?", (crn_id,))
        c_dict["items"] = [dict(it) for it in cur_it.fetchall()]
        return c_dict


def list_customer_credit_notes_record(invoice_id: str | None = None, customer_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM customer_credit_notes WHERE 1=1"
    params: list[Any] = []
    if invoice_id:
        query += " AND invoice_id = ?"
        params.append(invoice_id)
    if customer_id:
        query += " AND customer_id = ?"
        params.append(customer_id)
    query += " ORDER BY credit_note_date DESC, created_at DESC"

    with get_connection() as conn:
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_receivables_aging_data(as_of_date: str | None = None) -> dict[str, Any]:
    if as_of_date:
        try:
            today = datetime.fromisoformat(as_of_date).date() if "T" in as_of_date else datetime.strptime(as_of_date, "%Y-%m-%d").date()
        except Exception:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, invoice_number, customer_id, customer_name, invoice_date, due_date,
                   currency, exchange_rate, grand_total, amount_paid, amount_credited, outstanding_balance
            FROM customer_invoices
            WHERE status IN ('issued', 'partially_paid', 'overdue') AND outstanding_balance > 0
            ORDER BY due_date ASC
            """
        )
        invoices = [dict(r) for r in cur.fetchall()]

    buckets = {"current": 0.0, "days_1_30": 0.0, "days_31_60": 0.0, "days_61_90": 0.0, "days_90_plus": 0.0}
    by_customer: dict[str, dict[str, Any]] = {}
    total_receivable_inr = 0.0

    for inv in invoices:
        due_d = datetime.fromisoformat(inv["due_date"].replace("Z", "+00:00")).date() if "T" in inv["due_date"] else datetime.strptime(inv["due_date"], "%Y-%m-%d").date()
        overdue_days = (today - due_d).days
        bal = float(inv["outstanding_balance"])
        rate = float(inv["exchange_rate"] or 1.0)
        bal_inr = round(bal * rate, 2)
        total_receivable_inr += bal_inr

        cust_id = inv["customer_id"]
        if cust_id not in by_customer:
            by_customer[cust_id] = {
                "customer_id": cust_id,
                "customer_name": inv["customer_name"],
                "total_outstanding_inr": 0.0,
                "current": 0.0,
                "days_1_30": 0.0,
                "days_31_60": 0.0,
                "days_61_90": 0.0,
                "days_90_plus": 0.0,
                "invoices_count": 0,
            }

        cust_rec = by_customer[cust_id]
        cust_rec["total_outstanding_inr"] = round(cust_rec["total_outstanding_inr"] + bal_inr, 2)
        cust_rec["invoices_count"] += 1

        if overdue_days <= 0:
            buckets["current"] = round(buckets["current"] + bal_inr, 2)
            cust_rec["current"] = round(cust_rec["current"] + bal_inr, 2)
        elif 1 <= overdue_days <= 30:
            buckets["days_1_30"] = round(buckets["days_1_30"] + bal_inr, 2)
            cust_rec["days_1_30"] = round(cust_rec["days_1_30"] + bal_inr, 2)
        elif 31 <= overdue_days <= 60:
            buckets["days_31_60"] = round(buckets["days_31_60"] + bal_inr, 2)
            cust_rec["days_31_60"] = round(cust_rec["days_31_60"] + bal_inr, 2)
        elif 61 <= overdue_days <= 90:
            buckets["days_61_90"] = round(buckets["days_61_90"] + bal_inr, 2)
            cust_rec["days_61_90"] = round(cust_rec["days_61_90"] + bal_inr, 2)
        else:
            buckets["days_90_plus"] = round(buckets["days_90_plus"] + bal_inr, 2)
            cust_rec["days_90_plus"] = round(cust_rec["days_90_plus"] + bal_inr, 2)

    return {
        "as_of_date": today.isoformat(),
        "total_receivables_inr": round(total_receivable_inr, 2),
        "buckets": buckets,
        "customers": list(by_customer.values()),
        "invoices_analyzed": len(invoices),
    }


def get_gst_outward_supplies_data(from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    query = """
        SELECT ci.*
        FROM customer_invoices ci
        WHERE ci.status IN ('issued', 'partially_paid', 'paid', 'credited', 'overdue')
    """
    params: list[Any] = []
    if from_date:
        query += " AND ci.invoice_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND ci.invoice_date <= ?"
        params.append(to_date)

    with get_connection() as conn:
        cur = conn.execute(query, params)
        invoices = [dict(r) for r in cur.fetchall()]

    b2b_intra = {"taxable_value": 0.0, "cgst": 0.0, "sgst": 0.0, "invoice_count": 0}
    b2b_inter = {"taxable_value": 0.0, "igst": 0.0, "invoice_count": 0}
    export_lut = {"taxable_value": 0.0, "invoice_count": 0}
    export_taxable = {"taxable_value": 0.0, "igst": 0.0, "invoice_count": 0}
    exempt_nil = {"taxable_value": 0.0, "invoice_count": 0}

    for inv in invoices:
        rate = float(inv["exchange_rate"] or 1.0)
        subtotal_inr = round(float(inv["subtotal"]) * rate, 2)
        cgst_inr = round(float(inv["cgst_total"]) * rate, 2)
        sgst_inr = round(float(inv["sgst_total"]) * rate, 2)
        igst_inr = round(float(inv["igst_total"]) * rate, 2)

        scheme = inv["tax_scheme"]
        pos = inv.get("place_of_supply", "")

        if scheme == "EXPORT_LUT":
            export_lut["taxable_value"] = round(export_lut["taxable_value"] + subtotal_inr, 2)
            export_lut["invoice_count"] += 1
        elif scheme == "EXPORT_ZERO_RATED":
            export_taxable["taxable_value"] = round(export_taxable["taxable_value"] + subtotal_inr, 2)
            export_taxable["igst"] = round(export_taxable["igst"] + igst_inr, 2)
            export_taxable["invoice_count"] += 1
        elif scheme == "EXEMPT":
            exempt_nil["taxable_value"] = round(exempt_nil["taxable_value"] + subtotal_inr, 2)
            exempt_nil["invoice_count"] += 1
        elif pos.startswith("19") or pos.lower().startswith("19-west bengal"):
            b2b_intra["taxable_value"] = round(b2b_intra["taxable_value"] + subtotal_inr, 2)
            b2b_intra["cgst"] = round(b2b_intra["cgst"] + cgst_inr, 2)
            b2b_intra["sgst"] = round(b2b_intra["sgst"] + sgst_inr, 2)
            b2b_intra["invoice_count"] += 1
        else:
            b2b_inter["taxable_value"] = round(b2b_inter["taxable_value"] + subtotal_inr, 2)
            b2b_inter["igst"] = round(b2b_inter["igst"] + igst_inr, 2)
            b2b_inter["invoice_count"] += 1

    total_tax_liability = round(b2b_intra["cgst"] + b2b_intra["sgst"] + b2b_inter["igst"] + export_taxable["igst"], 2)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_invoices": len(invoices),
        "total_tax_liability_inr": total_tax_liability,
        "b2b_intra_state": b2b_intra,
        "b2b_inter_state": b2b_inter,
        "export_supplies_under_lut": export_lut,
        "export_supplies_with_tax": export_taxable,
        "exempt_supplies": exempt_nil,
        "statutory_notice": (
            "TradeSathi AI GST Outward Supplies Report — Internal summary for reconciliation and preparation. "
            "Does not constitute statutory GSTR-1 filing without authorized verification."
        ),
    }


# ==========================================
# Phase 8: Entity Barcodes Persistence
# ==========================================

def get_or_create_entity_barcode_record(
    entity_type: str,
    entity_id: str,
    entity_reference: str,
    symbology: str = "QR_CODE",
    label_size: str = "4x2",
    created_by: str = "system",
    file_path: str | None = None,
) -> dict[str, Any]:
    """
    Get existing active barcode or register new deterministic barcode record for an entity.
    Guarantees idempotency and prevents duplicate barcode creation.
    """
    entity_type_norm = entity_type.strip().lower()
    symbology_norm = symbology.strip().upper()
    now = datetime.now(timezone.utc).isoformat()

    # Deterministic standard barcode value format: TS:v1:{TYPE}:{REF}
    type_code_map = {
        "product": "PROD",
        "location": "LOC",
        "purchase_order": "PO",
        "goods_receipt": "GR",
        "sales_order": "SO",
        "sales_dispatch": "DSP",
        "dispatch_package": "PKG",
        "export_shipment": "EXP",
        "document": "DOC",
    }
    type_code = type_code_map.get(entity_type_norm, entity_type_norm.upper()[:4])
    default_barcode_value = f"TS:v1:{type_code}:{entity_reference.strip()}"

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # 1. Check if active record already exists for this entity & symbology
            cur = conn.execute(
                """
                SELECT * FROM entity_barcodes
                WHERE entity_type = ? AND entity_id = ? AND symbology = ? AND is_active = 1
                """,
                (entity_type_norm, entity_id, symbology_norm),
            )
            existing = cur.fetchone()
            if existing:
                conn.commit()
                return dict(existing)

            # 2. Check if default barcode_value is already registered
            cur_val = conn.execute(
                "SELECT * FROM entity_barcodes WHERE barcode_value = ?",
                (default_barcode_value,),
            )
            val_existing = cur_val.fetchone()
            if val_existing:
                barcode_val = f"{default_barcode_value}:{uuid.uuid4().hex[:6]}"
            else:
                barcode_val = default_barcode_value

            barcode_id = f"bc-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO entity_barcodes (
                    id, entity_type, entity_id, entity_reference, barcode_value,
                    symbology, format_version, label_size, file_path, is_active,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'v1', ?, ?, 1, ?, ?)
                """,
                (
                    barcode_id,
                    entity_type_norm,
                    entity_id,
                    entity_reference.strip(),
                    barcode_val,
                    symbology_norm,
                    label_size,
                    file_path,
                    created_by,
                    now,
                ),
            )
            conn.commit()
            return {
                "id": barcode_id,
                "entity_type": entity_type_norm,
                "entity_id": entity_id,
                "entity_reference": entity_reference.strip(),
                "barcode_value": barcode_val,
                "symbology": symbology_norm,
                "format_version": "v1",
                "label_size": label_size,
                "file_path": file_path,
                "is_active": 1,
                "created_by": created_by,
                "created_at": now,
            }
        except Exception:
            conn.rollback()
            raise


def get_barcode_record_by_value(barcode_value: str) -> dict[str, Any] | None:
    """Fetch registered barcode record by barcode/QR code value."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM entity_barcodes WHERE barcode_value = ?",
            (barcode_value.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_barcode_record_by_id(barcode_id: str) -> dict[str, Any] | None:
    """Fetch registered barcode record by ID."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM entity_barcodes WHERE id = ?",
            (barcode_id.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_entity_barcodes_record(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List registered barcodes with filtering and pagination."""
    query = "SELECT * FROM entity_barcodes WHERE is_active = 1"
    params: list[Any] = []
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type.strip().lower())
    if entity_id:
        query += " AND entity_id = ?"
        params.append(entity_id.strip())
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, limit), max(0, offset)])

    with get_connection() as conn:
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def deactivate_entity_barcode_record(barcode_id: str, deactivated_by: str) -> bool:
    """Safely deactivate a barcode record."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE entity_barcodes
            SET is_active = 0, deactivated_by = ?, deactivated_at = ?
            WHERE id = ? AND is_active = 1
            """,
            (deactivated_by, now, barcode_id),
        )
        conn.commit()
        return cur.rowcount > 0




